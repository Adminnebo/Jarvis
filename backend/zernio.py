"""Cliente de la API de Zernio para el WhatsApp de cada persona (coexistencia).

La cuenta de Zernio es de Nebo y la comparten otros paneles (JDL, Supletodo):
este modulo NUNCA adopta un perfil por su nombre ni toca webhooks ajenos. El
perfil de cada persona se reconoce por externalId = "jarvis:<usuario_id>" y el
webhook por su nombre "Jarvis <host>". Solo habla con Zernio: no sabe de
avisos ni de la base. Ver docs/superpowers/specs/2026-11-09-integraciones-whatsapp-design.md.
"""

import hashlib
import hmac
import os
from urllib.parse import urlparse

import httpx

BASE = "https://zernio.com/api/v1"
EVENTOS = ["message.received", "message.sent", "account.disconnected"]

_cliente = httpx.Client(timeout=30)


class ErrorZernio(Exception):
    def __init__(self, mensaje: str, status: int = 0, codigo: str | None = None, detalle: dict | None = None):
        super().__init__(mensaje)
        self.status = status
        self.codigo = codigo
        self.detalle = detalle or {}


def _http() -> httpx.Client:
    return _cliente   # las pruebas lo reemplazan por uno con MockTransport


def _clave() -> str:
    return os.getenv("ZERNIO_API_KEY", "").strip()


def secreto_webhook() -> str:
    return os.getenv("ZERNIO_WEBHOOK_SECRET", "").strip()


def _base() -> str:
    return os.getenv("ZERNIO_API_URL", BASE).strip().rstrip("/")


def configurado() -> bool:
    return bool(_clave())


def _llamar(metodo: str, ruta: str, *, params: dict | None = None, cuerpo: dict | None = None,
            cabeceras: dict | None = None) -> dict:
    if not configurado():
        raise ErrorZernio("Zernio no esta configurado (falta ZERNIO_API_KEY).")
    try:
        r = _http().request(
            metodo, _base() + ruta,
            params={k: v for k, v in (params or {}).items() if v not in (None, "")},
            json=cuerpo,
            headers={"Authorization": f"Bearer {_clave()}", **(cabeceras or {})},
        )
    except httpx.HTTPError as error:
        raise ErrorZernio(f"No se pudo hablar con Zernio: {error}") from error
    try:
        datos = r.json() if r.content else {}
    except ValueError:
        datos = {}
    if not isinstance(datos, dict):
        datos = {"data": datos}
    if r.status_code >= 400:
        error = datos.get("error")
        mensaje = (error.get("message") if isinstance(error, dict) else error) or datos.get("message") \
            or f"Zernio respondio {r.status_code}"
        codigo = datos.get("code") or (error.get("code") if isinstance(error, dict) else None) or datos.get("reason")
        raise ErrorZernio(str(mensaje), r.status_code, codigo, datos)
    return datos


# --------------------------------------------------------------------------
# Perfiles y conexion
# --------------------------------------------------------------------------

def perfil_de(usuario_id: str, nombre: str) -> str:
    """El perfil de Zernio de esta persona; lo crea si no existe."""
    externo = f"jarvis:{usuario_id}"
    for perfil in _llamar("GET", "/profiles", params={"externalId": externo}).get("profiles") or []:
        if perfil.get("externalId") == externo:
            return perfil["_id"]
    cuerpo = {"name": f"Jarvis · {nombre}"[:80], "externalId": externo,
              "description": "WhatsApp conectado a Jarvis (asistente.neboaiconsulting.com)"}
    try:
        return _llamar("POST", "/profiles", cuerpo=cuerpo)["profile"]["_id"]
    except ErrorZernio as error:
        if error.status != 409:
            raise
        if error.codigo == "profile_external_id_conflict":
            existente = (error.detalle.get("details") or {}).get("existingProfileId")
            if existente:
                return existente
            raise
        # Otro perfil de la cuenta compartida ya usa ese nombre: se desambigua con el id.
        cuerpo["name"] = f"Jarvis · {nombre} · {usuario_id[:8]}"[:80]
        return _llamar("POST", "/profiles", cuerpo=cuerpo)["profile"]["_id"]


def url_conexion(perfil_id: str, retorno: str) -> str:
    datos = _llamar("GET", "/connect/whatsapp", params={
        "profileId": perfil_id, "redirect_url": retorno, "onboarding": "business_app",
        "signup": "hosted", "language": "es"})
    if not datos.get("authUrl"):
        raise ErrorZernio("Zernio no devolvio la direccion para conectar.")
    return datos["authUrl"]


def desconectar_cuenta(cuenta_id: str) -> None:
    _llamar("DELETE", f"/accounts/{cuenta_id}")


# --------------------------------------------------------------------------
# Inbox
# --------------------------------------------------------------------------

def conversaciones(cuenta_id: str, limite: int = 50) -> tuple[list[dict], str | None]:
    """(chats mas recientes primero, error de la cuenta si Zernio no pudo leerla)."""
    datos = _llamar("GET", "/inbox/conversations", params={
        "accountId": cuenta_id, "platform": "whatsapp", "limit": str(limite), "sortOrder": "desc"})
    fallo = next((str(f.get("error") or f.get("code") or "error")
                  for f in (datos.get("meta") or {}).get("failedAccounts") or []
                  if f.get("accountId") == cuenta_id), None)
    return list(datos.get("data") or []), fallo


def conversacion(conversacion_id: str, cuenta_id: str) -> dict:
    datos = _llamar("GET", f"/inbox/conversations/{conversacion_id}", params={"accountId": cuenta_id})
    return datos.get("data") or datos.get("conversation") or datos


def mensajes(conversacion_id: str, cuenta_id: str, limite: int = 30) -> list[dict]:
    """Los ultimos `limite` mensajes, del mas viejo al mas nuevo."""
    datos = _llamar("GET", f"/inbox/conversations/{conversacion_id}/messages", params={
        "accountId": cuenta_id, "limit": str(limite), "sortOrder": "desc"})
    return list(reversed(datos.get("messages") or []))


def enviar(conversacion_id: str, cuenta_id: str, texto: str, clave: str) -> str:
    """Envia texto a un chat existente. `clave` evita mandarlo dos veces si se reintenta."""
    datos = _llamar("POST", f"/inbox/conversations/{conversacion_id}/messages",
                    cuerpo={"accountId": cuenta_id, "message": texto},
                    cabeceras={"Idempotency-Key": clave})
    return str((datos.get("data") or {}).get("messageId") or "")


# --------------------------------------------------------------------------
# Webhook
# --------------------------------------------------------------------------

def firma_valida(cuerpo: bytes, firma: str) -> bool:
    secreto = secreto_webhook()
    if not secreto or not firma:
        return False
    esperada = hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperada, firma.strip().lower())


def nombre_webhook(url: str) -> str:
    return f"Jarvis {urlparse(url).hostname or url}"


def asegurar_webhook(url: str) -> str:
    """Crea o actualiza el webhook de Jarvis. Nunca toca uno con otro nombre."""
    if not secreto_webhook():
        raise ErrorZernio("Falta ZERNIO_WEBHOOK_SECRET.")
    nombre = nombre_webhook(url)
    nuestros = [w for w in _llamar("GET", "/webhooks/settings").get("webhooks") or []
                if w.get("name") == nombre]
    actual = next((w for w in nuestros if w.get("url") == url), None) or (nuestros[0] if nuestros else None)
    cuerpo = {"name": nombre, "url": url, "secret": secreto_webhook(), "events": EVENTOS, "isActive": True}
    if actual:
        _llamar("PUT", "/webhooks/settings", cuerpo={"_id": actual["_id"], **cuerpo})
        return actual["_id"]
    return str((_llamar("POST", "/webhooks/settings", cuerpo=cuerpo).get("webhook") or {}).get("_id") or "")
