"""Gmail de cada persona, con la app OAuth propia "Asistente Virtual".

La app de Google no esta verificada (proyecto aparte de "Nebo Gmail"): al
conectar sale la advertencia y se entra por Avanzado. Pide leer y enviar. Este
modulo solo habla con Google: no sabe de avisos, de reglas ni de la base.
Ver docs/superpowers/specs/2026-11-09-integraciones-gmail-design.md.
"""

import base64
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import threading
import time
from email.message import EmailMessage
from urllib.parse import urlencode

import httpx

from . import acceso

URL_AUTORIZAR = "https://accounts.google.com/o/oauth2/v2/auth"
URL_TOKEN = "https://oauth2.googleapis.com/token"
URL_REVOCAR = "https://oauth2.googleapis.com/revoke"
URL_GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
LEER = "https://www.googleapis.com/auth/gmail.readonly"
ENVIAR = "https://www.googleapis.com/auth/gmail.send"
PERMISOS = ("openid", "email", LEER, ENVIAR)
RETORNO = "https://asistente.neboaiconsulting.com/integraciones/gmail/callback"
VIGENCIA_ESTADO = 600

_candado = threading.Lock()
_usados: dict[str, float] = {}                    # nonce -> caduca
_cache_tokens: dict[str, tuple[str, float]] = {}  # sha256(refresh) -> (access, caduca)
_cliente = httpx.Client(timeout=30)


class ErrorGmail(Exception):
    """Algo que se le puede decir a la persona. `revocado`: hay que reconectar."""

    def __init__(self, mensaje: str, revocado: bool = False, status: int = 0):
        super().__init__(mensaje)
        self.revocado = revocado
        self.status = status


def _http() -> httpx.Client:
    return _cliente   # las pruebas lo reemplazan por uno con MockTransport


def _id() -> str:
    return os.getenv("GOOGLE_JARVIS_CLIENT_ID", "").strip()


def _secreto() -> str:
    return os.getenv("GOOGLE_JARVIS_CLIENT_SECRET", "").strip()


def configurado() -> bool:
    return bool(_id() and _secreto())


def retorno() -> str:
    return os.getenv("GOOGLE_JARVIS_RETORNO", RETORNO).strip()


def _b64(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).decode("ascii").rstrip("=")


def _de_b64(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


# --------------------------------------------------------------------------
# Estado del OAuth: quien conecta, firmado, de un solo uso y por 10 minutos
# --------------------------------------------------------------------------

def _firmar(cuerpo: str) -> str:
    clave = hmac.new(acceso.clave_de_sesion(), b"gmail-estado", hashlib.sha256).digest()
    return _b64(hmac.new(clave, cuerpo.encode("ascii"), hashlib.sha256).digest())


def crear_estado(usuario_id: str) -> str:
    datos = {"u": usuario_id, "c": int(time.time()) + VIGENCIA_ESTADO, "n": secrets.token_urlsafe(9)}
    cuerpo = _b64(json.dumps(datos).encode("utf-8"))
    return f"{cuerpo}.{_firmar(cuerpo)}"


def leer_estado(estado: str) -> str | None:
    """El usuario que pidio conectar, o None si es falso, vencido o ya usado."""
    try:
        cuerpo, firma = (estado or "").rsplit(".", 1)
        if not hmac.compare_digest(firma, _firmar(cuerpo)):
            return None
        datos = json.loads(_de_b64(cuerpo))
    except (ValueError, json.JSONDecodeError):
        return None
    ahora = time.time()
    if datos.get("c", 0) < ahora:
        return None
    with _candado:
        for nonce, caduca in list(_usados.items()):
            if caduca < ahora:
                del _usados[nonce]
        if datos["n"] in _usados:
            return None
        _usados[datos["n"]] = datos["c"]
    return datos["u"]


def url_de_autorizacion(usuario_id: str) -> str:
    return URL_AUTORIZAR + "?" + urlencode({
        "client_id": _id(), "redirect_uri": retorno(), "response_type": "code",
        "scope": " ".join(PERMISOS), "access_type": "offline", "prompt": "consent",
        "include_granted_scopes": "false", "state": crear_estado(usuario_id),
    })


# --------------------------------------------------------------------------
# Tokens
# --------------------------------------------------------------------------

def _guardar_en_cache(refresh: str, acceso_: str, expira_en: int) -> None:
    with _candado:
        _cache_tokens[hashlib.sha256(refresh.encode()).hexdigest()] = (
            acceso_, time.time() + int(expira_en or 3600) - 60)


def canjear_codigo(codigo: str) -> dict:
    """El codigo de la vuelta de Google -> {access_token, refresh_token, ...}."""
    r = _http().post(URL_TOKEN, data={
        "code": codigo, "client_id": _id(), "client_secret": _secreto(),
        "redirect_uri": retorno(), "grant_type": "authorization_code",
    })
    if r.status_code >= 400:
        raise ErrorGmail(f"Google no acepto la conexion (HTTP {r.status_code}). Intenta de nuevo.")
    datos = r.json()
    concedidos = set(str(datos.get("scope", "")).split())
    if not {LEER, ENVIAR} <= concedidos:
        raise ErrorGmail("Hay que marcar las dos casillas (leer y enviar correos). Vuelve a conectar.")
    if not datos.get("refresh_token"):
        raise ErrorGmail("Google no dio un permiso permanente. Quita el acceso en "
                         "myaccount.google.com/permissions y vuelve a conectar.")
    _guardar_en_cache(datos["refresh_token"], datos["access_token"], datos.get("expires_in"))
    return datos


def token_de_acceso(refresh: str) -> str:
    clave = hashlib.sha256(refresh.encode()).hexdigest()
    with _candado:
        guardado = _cache_tokens.get(clave)
    if guardado and guardado[1] > time.time():
        return guardado[0]
    r = _http().post(URL_TOKEN, data={
        "refresh_token": refresh, "client_id": _id(), "client_secret": _secreto(),
        "grant_type": "refresh_token",
    })
    if r.status_code == 400 and "invalid_grant" in r.text:
        raise ErrorGmail("Google retiro el acceso a este Gmail.", revocado=True, status=400)
    if r.status_code >= 400:
        raise ErrorGmail(f"Google no renovo el acceso (HTTP {r.status_code}).", status=r.status_code)
    datos = r.json()
    _guardar_en_cache(refresh, datos["access_token"], datos.get("expires_in"))
    return datos["access_token"]


def revocar(refresh: str) -> None:
    with _candado:
        _cache_tokens.pop(hashlib.sha256(refresh.encode()).hexdigest(), None)
    try:
        _http().post(URL_REVOCAR, data={"token": refresh})
    except httpx.HTTPError:
        pass   # si Google no responde, igual lo olvidamos de nuestro lado


# --------------------------------------------------------------------------
# API de Gmail
# --------------------------------------------------------------------------

def _api(metodo: str, ruta: str, token: str, **kwargs) -> dict:
    r = _http().request(metodo, URL_GMAIL + ruta,
                        headers={"authorization": f"Bearer {token}"}, **kwargs)
    if r.status_code == 401:
        raise ErrorGmail("Google no acepto el acceso a Gmail.", revocado=True, status=401)
    if r.status_code >= 400:
        try:
            detalle = (r.json().get("error") or {}).get("message", "")
        except ValueError:
            detalle = r.text[:200]
        raise ErrorGmail(f"Gmail respondio {r.status_code}: {detalle}", status=r.status_code)
    return r.json() if r.content else {}


def perfil(token: str) -> dict:
    datos = _api("GET", "/profile", token)
    return {"email": datos["emailAddress"], "historyId": str(datos["historyId"])}


def historial(token: str, desde: str) -> tuple[list[str], str]:
    """Ids de los correos que entraron al INBOX desde `desde`, y el historyId nuevo.

    Un `desde` demasiado viejo da ErrorGmail con status 404.
    """
    ids: list[str] = []
    pagina = None
    while True:
        parametros = {"startHistoryId": desde, "historyTypes": "messageAdded",
                      "labelId": "INBOX", "maxResults": 100}
        if pagina:
            parametros["pageToken"] = pagina
        datos = _api("GET", "/history", token, params=parametros)
        for cambio in datos.get("history", []):
            for agregado in cambio.get("messagesAdded", []):
                identificador = agregado["message"]["id"]
                if identificador not in ids:
                    ids.append(identificador)
        pagina = datos.get("nextPageToken")
        if not pagina:
            return ids, str(datos.get("historyId", desde))


def mensaje(token: str, identificador: str) -> dict:
    return _api("GET", f"/messages/{identificador}", token, params={"format": "full"})


def _sin_html(texto: str) -> str:
    texto = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", texto)
    texto = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", texto)
    texto = html.unescape(re.sub(r"<[^>]+>", " ", texto))
    texto = re.sub(r"[ \t\r\f\v]+", " ", texto)
    return re.sub(r"\n\s*\n+", "\n\n", texto).strip()


def texto_plano(parte: dict) -> str:
    """El cuerpo legible: text/plain si lo hay; si no, el HTML sin etiquetas."""
    planos: list[str] = []
    htmls: list[str] = []

    def recorrer(p: dict) -> None:
        datos = (p.get("body") or {}).get("data")
        if datos and not p.get("filename"):
            contenido = _de_b64(datos).decode("utf-8", "replace")
            if p.get("mimeType") == "text/plain":
                planos.append(contenido)
            elif p.get("mimeType") == "text/html":
                htmls.append(contenido)
        for hija in p.get("parts") or []:
            recorrer(hija)

    recorrer(parte)
    if planos:
        return "\n".join(planos).strip()
    return _sin_html("\n".join(htmls))


def resumen_de(m: dict) -> dict:
    cabeceras = {c["name"].lower(): c["value"] for c in (m.get("payload") or {}).get("headers", [])}
    return {
        "id": m.get("id", ""), "hilo": m.get("threadId", ""),
        "de": cabeceras.get("from", ""), "para": cabeceras.get("to", ""),
        "asunto": cabeceras.get("subject", ""), "fecha": cabeceras.get("date", ""),
        "message_id": cabeceras.get("message-id", ""), "referencias": cabeceras.get("references", ""),
        "etiquetas": m.get("labelIds", []), "fragmento": html.unescape(m.get("snippet", "")),
        "texto": texto_plano(m.get("payload") or {}),
    }


def buscar(token: str, consulta: str, cuantos: int = 10) -> list[dict]:
    datos = _api("GET", "/messages", token, params={"q": consulta, "maxResults": max(1, min(cuantos, 25))})
    return [
        resumen_de(_api("GET", f"/messages/{m['id']}", token, params={
            "format": "metadata", "metadataHeaders": ["From", "To", "Subject", "Date"]}))
        for m in datos.get("messages", [])
    ]


def hilo(token: str, identificador: str) -> list[dict]:
    datos = _api("GET", f"/threads/{identificador}", token, params={"format": "full"})
    return [resumen_de(m) for m in datos.get("messages", [])]


def enviar(token: str, de: str, para: str, asunto: str, cuerpo: str,
           responder: dict | None = None) -> str:
    """Manda un correo de texto. Con `responder` ({hilo, message_id, referencias}) va en ese hilo."""
    correo = EmailMessage()
    correo["From"] = de
    correo["To"] = para
    correo["Subject"] = asunto
    datos: dict = {}
    if responder:
        if responder.get("message_id"):
            correo["In-Reply-To"] = responder["message_id"]
            correo["References"] = f"{responder.get('referencias', '')} {responder['message_id']}".strip()
        if responder.get("hilo"):
            datos["threadId"] = responder["hilo"]
    correo.set_content(cuerpo)
    datos["raw"] = _b64(correo.as_bytes())
    return _api("POST", "/messages/send", token, json=datos).get("id", "")
