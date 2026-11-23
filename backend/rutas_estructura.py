"""La estructura comun de Jarvis (/): el resumen de contadores de la barra.

Cada minuto la barra pide cuantos chats y correos hay sin leer y cual es el
proximo evento de hoy. Todo es opcional: si una integracion falta o falla, ese
contador viene en None y la barra no lo muestra."""

import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request

from . import apps_calendario, evolution_wa, gmail, integraciones

VIDA = 45

router = APIRouter()
_cache: dict[str, tuple[float, dict]] = {}


def _whatsapp(usuario_id: str) -> int | None:
    from . import whatsapp_chats

    instancia = whatsapp_chats._instancia(usuario_id)
    if not instancia:
        return None
    return sum(int(c.get("no_leidos") or 0) for c in evolution_wa.chats(instancia, 200))


def _google(usuario_id: str) -> tuple[int | None, dict | None]:
    conexion = integraciones.conexion(usuario_id)
    if not conexion or conexion["estado"] != "conectado" or not conexion["token"]:
        return None, None
    token = gmail.token_de_acceso(conexion["token"])
    correo = gmail.no_leidos_de(token, "INBOX")
    proximo = None
    if gmail.CALENDARIO in gmail.permisos(conexion["token"]):
        ahora = datetime.now(timezone.utc)
        for e in apps_calendario.eventos(token, "primary", ahora.isoformat(), (ahora + timedelta(hours=18)).isoformat()):
            if e["todo_el_dia"]:
                continue
            if datetime.fromisoformat(e["inicio"].replace("Z", "+00:00")) >= ahora:
                proximo = {"titulo": e["titulo"], "inicio": e["inicio"]}
                break
    return correo, proximo


@router.get("/api/apps/resumen")
def resumen(peticion: Request):
    usuario_id = peticion.state.usuario.id
    guardado = _cache.get(usuario_id)
    if guardado and time.time() - guardado[0] < VIDA:
        return guardado[1]
    datos = {"whatsapp": None, "correo": None, "calendario": None}
    try:
        datos["whatsapp"] = _whatsapp(usuario_id)
    except Exception:  # noqa: BLE001 - un contador caido no tumba la barra
        pass
    try:
        datos["correo"], datos["calendario"] = _google(usuario_id)
    except Exception:  # noqa: BLE001
        pass
    _cache[usuario_id] = (time.time(), datos)
    return datos
