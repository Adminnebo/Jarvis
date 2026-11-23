"""Mover y cancelar eventos de Google Calendar por voz, en dos pasos como todo lo demas:
la herramienta prepara y describe el cambio; confirmar_cambio_evento lo hace solo
despues del "si". Usa apps_calendario.py con el token del Gmail de la persona."""

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime

from . import apps_calendario, gmail, integraciones
from .google_calendario import ErrorGoogleCalendario, _api

VIGENCIA = 600


class ErrorAccion(Exception):
    """Algo que Jarvis le puede decir a la persona tal cual."""


@dataclass
class Pendiente:
    tipo: str          # "mover" o "cancelar"
    calendario: str
    evento_id: str
    titulo: str
    datos: dict
    creado: float = field(default_factory=time.time)


_pendientes: dict[str, Pendiente] = {}
_candado = threading.Lock()


def _token(usuario_id: str) -> str:
    conexion = integraciones.conexion(usuario_id)
    if not conexion or conexion["estado"] != "conectado" or not conexion["token"]:
        raise ErrorAccion("No tienes Google conectado. Conéctalo en Integraciones.")
    try:
        token = gmail.token_de_acceso(conexion["token"])
        if gmail.CALENDARIO not in gmail.permisos(conexion["token"]):
            raise ErrorAccion("Jarvis no tiene permiso sobre tu calendario de Google: reconecta y marca la casilla del calendario.")
    except gmail.ErrorGmail as error:
        raise ErrorAccion(f"No pude entrar a tu Google: {error}") from error
    return token


def _evento(token: str, calendario: str, evento_id: str) -> dict:
    try:
        e = _api("GET", f"/calendars/{apps_calendario._c(calendario)}/events/{apps_calendario._c(evento_id)}", token)
    except ErrorGoogleCalendario as error:
        raise ErrorAccion(f"No encontré ese evento: {error}") from error
    return apps_calendario._normalizar(e, calendario, True, {})


def _cuando(texto: str) -> str:
    try:
        return datetime.fromisoformat(texto.replace("Z", "+00:00")).strftime("%d/%m %H:%M")
    except ValueError:
        return texto


def _guardar(usuario_id: str, pendiente: Pendiente) -> None:
    with _candado:
        _pendientes[usuario_id] = pendiente


def mover(usuario_id: str, evento_id: str, inicio: str, calendario: str = "primary", fin: str = "") -> str:
    """Prepara mover un evento. Sin `fin` conserva la duracion."""
    token = _token(usuario_id)
    try:
        nuevo_inicio = datetime.fromisoformat(inicio.replace("Z", "+00:00"))
        if nuevo_inicio.tzinfo is None:
            raise ValueError
    except ValueError as error:
        raise ErrorAccion("La hora nueva tiene que venir completa, con zona: 2026-11-25T10:00:00-04:00.") from error
    e = _evento(token, calendario, evento_id)
    if not e["puede_editar"]:
        raise ErrorAccion("Ese evento no lo puedes mover: lo organiza otra persona.")
    if e["todo_el_dia"]:
        raise ErrorAccion("Es un evento de todo el día: muévelo desde el calendario.")
    if fin:
        nuevo_fin = datetime.fromisoformat(fin.replace("Z", "+00:00"))
    else:
        duracion = datetime.fromisoformat(e["fin"]) - datetime.fromisoformat(e["inicio"])
        nuevo_fin = nuevo_inicio + duracion
    if nuevo_fin <= nuevo_inicio:
        raise ErrorAccion("El final tiene que ser después del comienzo.")
    datos = {"inicio": nuevo_inicio.isoformat(), "fin": nuevo_fin.isoformat()}
    _guardar(usuario_id, Pendiente("mover", calendario, evento_id, e["titulo"], datos))
    serie = " Es un evento que se repite: solo se movería esta vez." if e["recurrente"] else ""
    return (f"Listo para mover «{e['titulo']}» de {_cuando(e['inicio'])} a {_cuando(datos['inicio'])}-"
            f"{nuevo_fin:%H:%M}.{serie} Los invitados recibirán el aviso. Pregúntale a la persona y llama a "
            "confirmar_cambio_evento SOLO si dice que sí.")


def cancelar(usuario_id: str, evento_id: str, calendario: str = "primary") -> str:
    token = _token(usuario_id)
    e = _evento(token, calendario, evento_id)
    if not e["puede_editar"]:
        raise ErrorAccion("Ese evento no lo puedes cancelar: lo organiza otra persona. Puedes rechazar la invitación.")
    _guardar(usuario_id, Pendiente("cancelar", calendario, evento_id, e["titulo"], {}))
    serie = " Es un evento que se repite: solo se cancelaría esta vez." if e["recurrente"] else ""
    return (f"Listo para cancelar «{e['titulo']}» del {_cuando(e['inicio'])}.{serie} Los invitados recibirán el aviso. "
            "Pregúntale a la persona y llama a confirmar_cambio_evento SOLO si dice que sí.")


def confirmar(usuario_id: str) -> str:
    with _candado:
        pendiente = _pendientes.pop(usuario_id, None)   # un "si" repetido no hace nada dos veces
    if pendiente is None or time.time() - pendiente.creado > VIGENCIA:
        raise ErrorAccion("No hay ningún cambio de calendario pendiente (o pasaron más de 10 minutos).")
    token = _token(usuario_id)
    try:
        if pendiente.tipo == "mover":
            apps_calendario.cambiar(token, pendiente.calendario, pendiente.evento_id, pendiente.datos)
            return f"Listo: «{pendiente.titulo}» quedó el {_cuando(pendiente.datos['inicio'])}."
        apps_calendario.borrar(token, pendiente.calendario, pendiente.evento_id)
        return f"Listo: cancelé «{pendiente.titulo}»."
    except ErrorGoogleCalendario as error:
        raise ErrorAccion(f"Google no lo aceptó: {error}") from error
