"""Grabar reuniones de Meet con el bot: quién pide, qué se le manda, qué vuelve.

El aviso previo (calendario._avisar) llama a proponer(). Con "Grabar siempre"
se pide solo; si no, el aviso trae Grabar / No grabar. Lo que el bot sube llega
por rutas_reuniones.py y lo procesa reuniones_trabajo.py.
Ver docs/superpowers/specs/2026-11-24-bot-grabacion-meet-design.md.
"""

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from . import bot_meet, rutas
from . import reuniones_datos as rd

PATRON = re.compile(r"(?:https://)?meet\.google\.com/([a-z]{3}-[a-z]{4}-[a-z]{3})")
BASE = "https://asistente.neboaiconsulting.com"
PIDE_BOT = ("propuesta", "cancelada", "sin_bot")


def link_meet(evento: dict) -> str | None:
    lugares = [((evento.get("conferencing") or {}).get("url") or ""),
               evento.get("location") or "", evento.get("description") or ""]
    for texto in lugares:
        m = PATRON.search(texto)
        if m:
            return f"https://meet.google.com/{m.group(1)}"
    return None


def proponer(usuario_id: str, evento: dict) -> dict | None:
    """La reunión de ese evento (creada si hace falta), o None si no aplica."""
    url = link_meet(evento)
    if not url or not bot_meet.configurado():
        return None
    codigo = url.rsplit("/", 1)[1]
    return rd.crear_o_obtener(f"{codigo}@{evento['start'][:16]}", url, evento.get("title") or "Reunión",
                              evento["start"], evento["end"])


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def token_valido(reunion_id: str, token: str) -> bool:
    r = rd.obtener(reunion_id)
    return bool(r and r["token_hash"] and token and hmac.compare_digest(r["token_hash"], _hash(token)))


def pedir(usuario_id: str, reunion_id: str) -> str:
    r = rd.obtener(reunion_id)
    if r is None:
        return "No encontré esa reunión."
    rd.interesar(reunion_id, usuario_id, True)
    if r["estado"] not in PIDE_BOT:
        return f"Listo, «{r['titulo']}» ya se va a grabar."
    token = secrets.token_urlsafe(32)
    try:
        bot_meet.agendar(reunion_id, r["meet_url"], r["inicio"], r["fin"], token)
    except bot_meet.SinBotLibre:
        rd.actualizar(reunion_id, estado="sin_bot")
        return f"No hay bot libre para grabar «{r['titulo']}»: ya hay dos reuniones grabándose a esa hora."
    except bot_meet.ErrorBot as error:
        print(f"  AVISO: no pude agendar el bot para {reunion_id}: {error}")
        return f"No pude mandar el bot a «{r['titulo']}». Inténtalo de nuevo en un momento."
    rd.actualizar(reunion_id, estado="agendada", token_hash=_hash(token), motivo=None)
    return f"Listo, voy a grabar «{r['titulo']}»."


def no_grabar(usuario_id: str, reunion_id: str) -> str:
    r = rd.obtener(reunion_id)
    if r is None:
        return "No encontré esa reunión."
    rd.interesar(reunion_id, usuario_id, False)
    if not rd.interesados(reunion_id) and r["estado"] == "agendada":
        try:
            bot_meet.cancelar(reunion_id)
        except bot_meet.ErrorBot as error:
            print(f"  AVISO: no pude cancelar el bot de {reunion_id}: {error}")
        rd.actualizar(reunion_id, estado="cancelada")
    return f"Listo, no grabo «{r['titulo']}»."


# --------------------------------------------------------------------------
# Enlace firmado de WhatsApp (Grabar / No grabar sin sesión)
# --------------------------------------------------------------------------

def _clave() -> bytes:
    from . import secretos
    return secretos.clave()


def _firma(usuario_id: str, reunion_id: str, accion: str) -> str:
    return hmac.new(_clave(), f"{usuario_id}|{reunion_id}|{accion}".encode(), hashlib.sha256).hexdigest()[:32]


def enlace(usuario_id: str, reunion_id: str, accion: str) -> str:
    q = {"u": usuario_id, "r": reunion_id, "a": accion, "f": _firma(usuario_id, reunion_id, accion)}
    return f"{BASE}/reuniones/accion?{urlencode(q)}"


def verificar_enlace(usuario_id: str, reunion_id: str, accion: str, firma: str) -> bool:
    if accion not in ("grabar", "no_grabar"):
        return False
    return hmac.compare_digest(_firma(usuario_id, reunion_id, accion), firma or "")
