"""Outlook (Microsoft 365 / Outlook.com) de cada persona por Zernio: el correo y sus avisos.

La cuenta de Microsoft vive en el mismo perfil de Zernio que el WhatsApp de la
persona. Correo: buscar, leer, responder y enviar (lo llama correo.py; los ids
que salen de aqui son de hilo y llevan "o:" delante). Avisos: el webhook solo
anota a la persona "por revisar"; el hilo de fondo lista los hilos nuevos desde
el cursor y los clasifica con las reglas de siempre. El calendario esta en
calendario.py.
Ver docs/superpowers/specs/2026-11-18-integraciones-outlook-calendario-design.md.
"""

import html
import os
import re
import threading
import time
from datetime import datetime, timezone

from . import avisos, integraciones, zernio

RETORNO = "https://asistente.neboaiconsulting.com/integraciones/outlook/callback"
BARRIDO = 1800         # respaldo del webhook, por persona
MAX_POR_VUELTA = 20
PERDIDO = {"account_scope_missing", "admin_consent_required", "mailbox_not_available"}


class ErrorOutlook(Exception):
    """Algo que Jarvis le puede decir a la persona tal cual."""


def retorno() -> str:
    return os.getenv("ZERNIO_OUTLOOK_RETORNO", RETORNO).strip()


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _cuando(texto: str | None) -> datetime:
    return datetime.fromisoformat((texto or "1970-01-01T00:00:00+00:00").replace("Z", "+00:00"))


# --------------------------------------------------------------------------
# Cuenta y errores
# --------------------------------------------------------------------------

def cuenta(usuario_id: str) -> str:
    cuenta_id = integraciones.cuenta_outlook(usuario_id)
    if not cuenta_id:
        raise ErrorOutlook("No tienes Outlook conectado. Conectalo en Integraciones (menu de arriba) "
                           "y vuelve a pedirmelo.")
    return cuenta_id


def direccion(usuario_id: str) -> str:
    return (integraciones.conexion(usuario_id, "outlook") or {}).get("cuenta") or ""


def desconectado(usuario_id: str, motivo: str) -> None:
    """Una sola vez: si ya estaba desconectado no se repite el aviso."""
    actual = integraciones.conexion(usuario_id, "outlook")
    if not actual or actual["estado"] != "conectado":
        return
    integraciones.marcar_desconectado(usuario_id, motivo, app="outlook")
    regla = integraciones.reglas(usuario_id)
    avisos.crear(usuario_id, f"desconexion-ol-{int(time.time())}", None, "Outlook", "Reconecta tu Outlook",
                 "Jarvis perdio el acceso a tu Outlook. Vuelve a conectarlo en Integraciones.",
                 con_whatsapp=bool(regla["whatsapp"]), tipo="sistema", app="outlook")


def explicar(usuario_id: str, error: zernio.ErrorZernio) -> ErrorOutlook:
    """Traduce el error de Zernio y, si la cuenta perdio el permiso, la marca desconectada."""
    if error.status == 412 or (error.codigo or "") in PERDIDO:
        desconectado(usuario_id, str(error))
        return ErrorOutlook("Tu Outlook se desconecto o le falta un permiso: reconectalo en Integraciones.")
    if error.status == 429:
        return ErrorOutlook("Outlook no responde por ahora (limite de uso). Intentalo en un momento.")
    return ErrorOutlook(f"Outlook respondio con un error: {error}")


# --------------------------------------------------------------------------
# Correo (lo usa correo.py)
# --------------------------------------------------------------------------

def _persona(p: dict | None) -> str:
    if not p:
        return ""
    nombre, correo = (p.get("name") or "").strip(), p.get("email") or ""
    return f"{nombre} <{correo}>" if nombre else correo


def _fecha(texto: str | None) -> str:
    return (texto or "")[:16].replace("T", " ")


def _texto(m: dict) -> str:
    limpio = (m.get("clean") or {}).get("text")
    if limpio:
        return limpio.strip()
    if m.get("text"):
        return m["text"].strip()
    sin_etiquetas = re.sub(r"<[^>]+>", " ", m.get("html") or "")
    return re.sub(r"\s+", " ", html.unescape(sin_etiquetas)).strip()


def _de_otro(m: dict, propia: str) -> bool:
    return ((m.get("from") or {}).get("email") or "").lower() != propia


def buscar(usuario_id: str, consulta: str, cuantos: int) -> list[dict]:
    cuenta_id = cuenta(usuario_id)
    propia = direccion(usuario_id).lower()
    try:
        lista = zernio.hilos(cuenta_id, buscar=consulta, limite=cuantos)
    except zernio.ErrorZernio as error:
        raise explicar(usuario_id, error) from error
    salida = []
    for h in lista:
        otros = [p for p in h.get("participants") or [] if (p.get("email") or "").lower() != propia]
        salida.append({"id": f"o:{h.get('id')}",
                       "fecha": _fecha(h.get("latestMessageReceivedAt") or h.get("earliestMessageAt")),
                       "de": _persona(otros[0]) if otros else propia,
                       "asunto": h.get("subject") or "", "fragmento": h.get("snippet") or ""})
    return salida


def _hilo(usuario_id: str, hilo_id: str) -> dict:
    cuenta_id = cuenta(usuario_id)
    try:
        return zernio.hilo(hilo_id, cuenta_id)
    except zernio.ErrorZernio as error:
        raise explicar(usuario_id, error) from error


def leer(usuario_id: str, hilo_id: str) -> list[dict]:
    datos = _hilo(usuario_id, hilo_id)
    return [{"id": m.get("id", ""), "de": _persona(m.get("from")),
             "para": ", ".join(_persona(p) for p in m.get("to") or []),
             "fecha": _fecha(m.get("date")), "asunto": m.get("subject") or datos.get("subject") or "",
             "texto": _texto(m)} for m in datos.get("messages") or []]


def a_quien_responder(usuario_id: str, hilo_id: str) -> dict:
    """El ultimo mensaje del hilo que no mando la persona: {mensaje_id, para, asunto}."""
    propia = direccion(usuario_id).lower()
    datos = _hilo(usuario_id, hilo_id)
    mensajes = datos.get("messages") or []
    ajenos = [m for m in mensajes if _de_otro(m, propia)]
    if ajenos:
        ultimo = ajenos[-1]
        destino = ((ultimo.get("replyTo") or [None])[0] or ultimo.get("from") or {}).get("email", "")
    elif mensajes:
        ultimo = mensajes[-1]
        destino = ((ultimo.get("to") or [{}])[0]).get("email", "")
    else:
        raise ErrorOutlook("Ese hilo de Outlook esta vacio.")
    base = ultimo.get("subject") or datos.get("subject") or ""
    return {"mensaje_id": ultimo.get("id", ""), "para": destino,
            "asunto": base if base.lower().startswith("re:") else f"Re: {base}"}


def enviar(usuario_id: str, para: list[str], asunto: str, texto: str, clave: str,
           responder_a: str | None = None) -> None:
    cuenta_id = cuenta(usuario_id)
    try:
        zernio.enviar_correo(cuenta_id, para, asunto, texto, clave, responder_a)
    except zernio.ErrorZernio as error:
        raise explicar(usuario_id, error) from error
