"""El Google Calendar de cada persona dentro de Jarvis (/apps/calendario).

Lista de calendarios, eventos de un rango, crear, cambiar (uno o toda la serie),
borrar y responder invitaciones. Usa el cliente de google_calendario.py (mismo
token del Gmail). Ver docs/superpowers/specs/2026-11-23-apps-calendario-design.md.
"""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from urllib.parse import quote

from .google_calendario import ErrorGoogleCalendario, _api

EN_PARALELO = 8
RESPUESTAS = {"si": "accepted", "no": "declined", "quizas": "tentative"}
_ESTADO = {"accepted": "si", "declined": "no", "tentative": "quizas", "needsAction": "pendiente"}

_paleta: dict[str, str] = {}
_candado = threading.Lock()


def _c(calendario: str) -> str:
    return quote(calendario, safe="@")


# --------------------------------------------------------------------------
# Leer
# --------------------------------------------------------------------------

def calendarios(token: str) -> list[dict]:
    """Los calendarios de la persona (su lista de Google), el principal primero."""
    salida = []
    for c in _api("GET", "/users/me/calendarList", token).get("items") or []:
        salida.append({
            "id": c["id"], "nombre": c.get("summaryOverride") or c.get("summary") or c["id"],
            "color": c.get("backgroundColor") or "#7986cb", "texto": c.get("foregroundColor") or "#000000",
            "principal": bool(c.get("primary")), "puede_editar": c.get("accessRole") in ("owner", "writer"),
        })
    return sorted(salida, key=lambda c: (not c["principal"], c["nombre"].lower()))


def _colores(token: str) -> dict[str, str]:
    with _candado:
        if _paleta:
            return dict(_paleta)
    try:
        datos = _api("GET", "/colors", token).get("event") or {}
    except ErrorGoogleCalendario:
        return {}
    with _candado:
        _paleta.update({k: v.get("background") for k, v in datos.items() if v.get("background")})
        return dict(_paleta)


def _normalizar(e: dict, calendario: str, puede_editar: bool, paleta: dict[str, str]) -> dict:
    todo_el_dia = "date" in (e.get("start") or {})
    clave = "date" if todo_el_dia else "dateTime"
    invitados = []
    mi_respuesta = None
    for a in e.get("attendees") or []:
        if a.get("resource"):
            continue
        estado = _ESTADO.get(a.get("responseStatus"), "pendiente")
        invitados.append({"correo": a.get("email"), "nombre": a.get("displayName"), "estado": estado,
                          "yo": bool(a.get("self")), "organizador": bool(a.get("organizer"))})
        if a.get("self"):
            mi_respuesta = estado
    organizador = e.get("organizer") or {}
    soy_organizador = bool(organizador.get("self")) or not organizador.get("email")
    video = next((p.get("uri") for p in (e.get("conferenceData") or {}).get("entryPoints") or []
                  if p.get("entryPointType") == "video"), None) or e.get("hangoutLink")
    avisos = (e.get("reminders") or {}).get("overrides") or []
    return {
        "id": e.get("id"), "calendario": calendario, "titulo": e.get("summary") or "(Sin título)",
        "inicio": (e.get("start") or {}).get(clave, ""), "fin": (e.get("end") or {}).get(clave, ""),
        "todo_el_dia": todo_el_dia, "ubicacion": e.get("location") or "", "descripcion": e.get("description") or "",
        "color": paleta.get(str(e.get("colorId"))) if e.get("colorId") else None,
        "meet": video, "invitados": invitados, "mi_respuesta": mi_respuesta,
        "organizador": organizador.get("email"), "soy_organizador": soy_organizador,
        "recurrente": e.get("recurringEventId"),
        "puede_editar": bool(puede_editar and (soy_organizador or e.get("guestsCanModify"))),
        "aviso_min": min((a.get("minutes", 0) for a in avisos), default=None),
        "enlace": e.get("htmlLink"),
    }


def eventos(token: str, calendario: str, desde: str, hasta: str, puede_editar: bool = True) -> list[dict]:
    """Eventos de un calendario entre dos momentos ISO (las repeticiones ya desplegadas)."""
    paleta = _colores(token)
    salida, pagina = [], None
    for _ in range(10):
        params = {"timeMin": desde, "timeMax": hasta, "singleEvents": "true", "orderBy": "startTime", "maxResults": "250"}
        if pagina:
            params["pageToken"] = pagina
        datos = _api("GET", f"/calendars/{_c(calendario)}/events", token, params=params)
        salida.extend(_normalizar(e, calendario, puede_editar, paleta)
                      for e in datos.get("items") or [] if e.get("status") != "cancelled")
        pagina = datos.get("nextPageToken")
        if not pagina:
            break
    return salida


def eventos_de(token: str, calendarios_: list[tuple[str, bool]], desde: str, hasta: str) -> list[dict]:
    """Eventos de varios calendarios ((id, puede_editar)) en paralelo. Uno que falla se salta."""
    def uno(par):
        calendario, puede = par
        try:
            return eventos(token, calendario, desde, hasta, puede_editar=puede)
        except ErrorGoogleCalendario as error:
            if error.revocado or error.sin_permiso:
                raise
            return []

    with ThreadPoolExecutor(max_workers=EN_PARALELO) as grupo:
        return [e for lista in grupo.map(uno, calendarios_) for e in lista]


# --------------------------------------------------------------------------
# Escribir
# --------------------------------------------------------------------------

def _momento(valor: str, todo_el_dia: bool) -> dict:
    return {"date": valor[:10]} if todo_el_dia else {"dateTime": valor}


def _cuerpo(datos: dict, nuevo: bool) -> dict:
    """Los campos de Google para lo que vino (al crear, todos; al cambiar, solo los presentes)."""
    cuerpo: dict = {}
    todo_el_dia = bool(datos.get("todo_el_dia"))
    if "titulo" in datos:
        cuerpo["summary"] = datos["titulo"] or "(Sin título)"
    if "inicio" in datos:
        cuerpo["start"] = _momento(datos["inicio"], todo_el_dia)
    if "fin" in datos:
        cuerpo["end"] = _momento(datos["fin"], todo_el_dia)
    if "ubicacion" in datos:
        cuerpo["location"] = datos["ubicacion"] or ""
    if "descripcion" in datos:
        cuerpo["description"] = datos["descripcion"] or ""
    if "invitados" in datos:
        cuerpo["attendees"] = [{"email": c.strip()} for c in datos["invitados"] if str(c).strip()]
    if datos.get("meet"):
        cuerpo["conferenceData"] = {"createRequest": {"requestId": uuid.uuid4().hex,
                                                      "conferenceSolutionKey": {"type": "hangoutsMeet"}}}
    if datos.get("aviso_min") is not None and (nuevo or "aviso_min" in datos):
        cuerpo["reminders"] = {"useDefault": False, "overrides": [{"method": "popup", "minutes": int(datos["aviso_min"])}]}
    return cuerpo


_ENVIAR = {"sendUpdates": "all", "conferenceDataVersion": "1"}


def crear(token: str, calendario: str, datos: dict) -> dict:
    e = _api("POST", f"/calendars/{_c(calendario)}/events", token, json=_cuerpo(datos, nuevo=True), params=_ENVIAR)
    return _normalizar(e, calendario, True, _colores(token))


def _instante(valor: dict) -> datetime | date:
    if "dateTime" in valor:
        return datetime.fromisoformat(valor["dateTime"].replace("Z", "+00:00"))
    return date.fromisoformat(valor["date"])


def _correr(valor: dict, delta) -> dict:
    """Mueve un start/end de Google `delta` (mismo tipo: hora o dia completo)."""
    if "dateTime" in valor:
        return {**valor, "dateTime": (_instante(valor) + delta).isoformat()}
    return {**valor, "date": (_instante(valor) + delta).isoformat()}


def cambiar(token: str, calendario: str, evento_id: str, datos: dict, todos: bool = False) -> dict:
    """Cambia un evento. Con `todos` y una repeticion, cambia la serie: los textos tal cual y,
    si cambio la hora, la madre se corre lo mismo que se corrio esta repeticion."""
    cuerpo = _cuerpo(datos, nuevo=False)
    destino = evento_id
    if todos:
        instancia = _api("GET", f"/calendars/{_c(calendario)}/events/{_c(evento_id)}", token)
        madre_id = instancia.get("recurringEventId")
        if madre_id:
            destino = madre_id
            madre = _api("GET", f"/calendars/{_c(calendario)}/events/{_c(madre_id)}", token)
            for clave in ("start", "end"):
                if clave in cuerpo:
                    delta = _instante(cuerpo[clave]) - _instante(instancia[clave])
                    cuerpo[clave] = _correr(madre[clave], delta)
    e = _api("PATCH", f"/calendars/{_c(calendario)}/events/{_c(destino)}", token, json=cuerpo, params=_ENVIAR)
    return _normalizar(e, calendario, True, _colores(token))


def borrar(token: str, calendario: str, evento_id: str, todos: bool = False) -> None:
    destino = evento_id
    if todos:
        destino = _api("GET", f"/calendars/{_c(calendario)}/events/{_c(evento_id)}", token).get("recurringEventId") or evento_id
    _api("DELETE", f"/calendars/{_c(calendario)}/events/{_c(destino)}", token, params={"sendUpdates": "all"})


def responder(token: str, calendario: str, evento_id: str, respuesta: str) -> dict:
    """Si/no/quizas a una invitacion (cambia solo la respuesta propia)."""
    if respuesta not in RESPUESTAS:
        raise ValueError("La respuesta tiene que ser si, no o quizas.")
    e = _api("GET", f"/calendars/{_c(calendario)}/events/{_c(evento_id)}", token)
    asistentes = [{**a, "responseStatus": RESPUESTAS[respuesta]} if a.get("self") else a for a in e.get("attendees") or []]
    e = _api("PATCH", f"/calendars/{_c(calendario)}/events/{_c(evento_id)}", token,
             json={"attendees": asistentes}, params={"sendUpdates": "all"})
    return _normalizar(e, calendario, True, _colores(token))
