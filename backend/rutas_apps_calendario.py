"""Rutas de la vista de calendario (/apps/calendario). Con la sesion de la persona y
siempre sobre SU Google Calendar (el token de su Gmail). Ver apps_calendario.py."""

import time
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from . import apps_calendario, gmail, integraciones
from .google_calendario import ErrorGoogleCalendario

WEB = Path(__file__).resolve().parent.parent / "web"
MAX_DIAS = 62
VIDA_LISTA = 300

router = APIRouter()
_cache_calendarios: dict[str, tuple[float, list[dict]]] = {}


def _error(status: int, mensaje: str, **extra) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": mensaje, **extra})


class _Fallo(Exception):
    def __init__(self, respuesta: JSONResponse):
        self.respuesta = respuesta


def _acceso(peticion: Request) -> tuple[str, dict, set[str]]:
    """(token, conexion de Gmail, permisos) de quien pide, o _Fallo."""
    usuario_id = peticion.state.usuario.id
    conexion = integraciones.conexion(usuario_id)
    if not conexion or conexion["estado"] != "conectado" or not conexion["token"]:
        raise _Fallo(_error(409, "Conecta tu Google para ver tu calendario.", conectar=True))
    try:
        token = gmail.token_de_acceso(conexion["token"])
        permisos = gmail.permisos(conexion["token"])
    except gmail.ErrorGmail as error:
        if error.revocado:
            integraciones.marcar_desconectado(usuario_id, str(error))
        raise _Fallo(_error(409, "Google retiro el acceso: vuelve a conectar.", conectar=True)) from error
    if gmail.CALENDARIO not in permisos:
        raise _Fallo(_error(409, "Reconecta tu Google y marca la casilla del calendario.", conectar=True, reconectar=True))
    return token, conexion, permisos


def _manejar(funcion):
    import functools

    @functools.wraps(funcion)
    def envuelta(*args, **kwargs):
        try:
            return funcion(*args, **kwargs)
        except _Fallo as fallo:
            return fallo.respuesta
        except ErrorGoogleCalendario as error:
            if error.revocado or error.sin_permiso:
                return _error(409, "Reconecta tu Google para usar el calendario.", conectar=True, reconectar=True)
            return _error(502, str(error))
    return envuelta


def _calendarios(peticion: Request, token: str, conexion: dict, permisos: set[str]) -> list[dict]:
    if gmail.CALENDARIOS not in permisos:
        return [{"id": "primary", "nombre": conexion["cuenta"], "color": "#039be5", "texto": "#000000",
                 "principal": True, "puede_editar": True}]
    clave = peticion.state.usuario.id
    guardada = _cache_calendarios.get(clave)
    if guardada and time.time() - guardada[0] < VIDA_LISTA:
        return guardada[1]
    lista = apps_calendario.calendarios(token)
    _cache_calendarios[clave] = (time.time(), lista)
    return lista


def _escribible(peticion: Request, token: str, conexion: dict, permisos: set[str], calendario: str) -> None:
    propio = next((c for c in _calendarios(peticion, token, conexion, permisos) if c["id"] == calendario), None)
    if not propio or not propio["puede_editar"]:
        raise _Fallo(_error(403, "No puedes cambiar eventos de ese calendario."))


@router.get("/apps/calendario")
def pagina():
    return FileResponse(WEB / "apps-calendario.html")


@router.get("/api/apps/calendario/estado")
@_manejar
def estado(peticion: Request):
    conexion = integraciones.conexion(peticion.state.usuario.id)
    if not conexion or conexion["estado"] != "conectado":
        return {"conectado": False}
    try:
        _, conexion, permisos = _acceso(peticion)
    except _Fallo:
        return {"conectado": False, "reconectar": True}
    return {"conectado": True, "cuenta": conexion["cuenta"], "lista": gmail.CALENDARIOS in permisos}


@router.get("/api/apps/calendario/calendarios")
@_manejar
def calendarios(peticion: Request):
    token, conexion, permisos = _acceso(peticion)
    return {"calendarios": _calendarios(peticion, token, conexion, permisos)}


def _fecha(texto: str) -> datetime:
    return datetime.fromisoformat(texto.replace("Z", "+00:00"))


@router.get("/api/apps/calendario/eventos")
@_manejar
def eventos(peticion: Request, desde: str, hasta: str, calendarios: str = ""):
    try:
        if (_fecha(hasta) - _fecha(desde)).days > MAX_DIAS:
            return _error(400, "El rango es demasiado largo.")
    except ValueError:
        return _error(400, "Fechas no validas.")
    token, conexion, permisos = _acceso(peticion)
    propios = {c["id"]: c["puede_editar"] for c in _calendarios(peticion, token, conexion, permisos)}
    pedidos = [c for c in calendarios.split(",") if c] or list(propios)
    elegidos = [(c, propios[c]) for c in pedidos if c in propios]   # solo calendarios de la persona
    return {"eventos": apps_calendario.eventos_de(token, elegidos, desde, hasta)}


class Evento(BaseModel):
    calendario: str = "primary"
    titulo: str | None = None
    inicio: str | None = None
    fin: str | None = None
    todo_el_dia: bool | None = None
    invitados: list[str] | None = None
    meet: bool | None = None
    ubicacion: str | None = None
    descripcion: str | None = None
    aviso_min: int | None = None


@router.post("/api/apps/calendario/eventos")
@_manejar
def crear(peticion: Request, datos: Evento):
    token, conexion, permisos = _acceso(peticion)
    _escribible(peticion, token, conexion, permisos, datos.calendario)
    if not datos.inicio or not datos.fin:
        return _error(400, "Falta cuándo es.")
    campos = datos.model_dump(exclude_none=True, exclude={"calendario"})
    campos.setdefault("titulo", "")
    return apps_calendario.crear(token, datos.calendario, campos)


@router.patch("/api/apps/calendario/eventos/{calendario}/{evento_id}")
@_manejar
def cambiar(calendario: str, evento_id: str, peticion: Request, datos: Evento, todos: int = 0):
    token, conexion, permisos = _acceso(peticion)
    _escribible(peticion, token, conexion, permisos, calendario)
    return apps_calendario.cambiar(token, calendario, evento_id, datos.model_dump(exclude_none=True, exclude={"calendario"}),
                                   todos=bool(todos))


@router.delete("/api/apps/calendario/eventos/{calendario}/{evento_id}")
@_manejar
def borrar(calendario: str, evento_id: str, peticion: Request, todos: int = 0):
    token, conexion, permisos = _acceso(peticion)
    _escribible(peticion, token, conexion, permisos, calendario)
    apps_calendario.borrar(token, calendario, evento_id, todos=bool(todos))
    return {"ok": True}


class Respuesta(BaseModel):
    respuesta: str


@router.post("/api/apps/calendario/eventos/{calendario}/{evento_id}/respuesta")
@_manejar
def responder(calendario: str, evento_id: str, peticion: Request, datos: Respuesta):
    token, _, _ = _acceso(peticion)
    try:
        return apps_calendario.responder(token, calendario, evento_id, datos.respuesta)
    except ValueError as error:
        return _error(400, str(error))
