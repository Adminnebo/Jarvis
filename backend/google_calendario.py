"""Google Calendar de cada persona, con el mismo token de su Gmail (app "Asistente Virtual").

El permiso del calendario es una casilla opcional al conectar Gmail (ver
gmail.CALENDARIO e integraciones.calendario_google). Este modulo solo habla con
Google y devuelve los eventos con la misma forma que los de Zernio (Outlook),
asi calendario.py los trata igual. Ver
docs/superpowers/specs/2026-11-18-integraciones-outlook-calendario-design.md.
"""

import uuid

import httpx

URL = "https://www.googleapis.com/calendar/v3"
ESTADOS = {"accepted": "accepted", "declined": "declined", "tentative": "tentative", "needsAction": "pending"}

_cliente = httpx.Client(timeout=30)


class ErrorGoogleCalendario(Exception):
    """`revocado`: hay que reconectar Gmail. `sin_permiso`: no marco la casilla del calendario."""

    def __init__(self, mensaje: str, status: int = 0, revocado: bool = False, sin_permiso: bool = False):
        super().__init__(mensaje)
        self.status = status
        self.revocado = revocado
        self.sin_permiso = sin_permiso


def _http() -> httpx.Client:
    return _cliente   # las pruebas lo reemplazan por uno con MockTransport


def _api(metodo: str, ruta: str, token: str, **kwargs) -> dict:
    try:
        r = _http().request(metodo, URL + ruta, headers={"authorization": f"Bearer {token}"}, **kwargs)
    except httpx.HTTPError as error:
        raise ErrorGoogleCalendario(f"No se pudo hablar con Google Calendar: {error}") from error
    if r.status_code < 400:
        return r.json() if r.content else {}
    try:
        error = r.json().get("error") or {}
    except ValueError:
        error = {}
    mensaje = error.get("message") or f"Google Calendar respondio {r.status_code}"
    razones = {e.get("reason") for e in error.get("errors") or []}
    if r.status_code == 401:
        raise ErrorGoogleCalendario(mensaje, 401, revocado=True)
    if r.status_code == 403 and ("insufficientPermissions" in razones or "insufficient" in mensaje.lower()):
        raise ErrorGoogleCalendario(mensaje, 403, sin_permiso=True)
    raise ErrorGoogleCalendario(mensaje, r.status_code)


def _normalizar(e: dict) -> dict:
    todo_el_dia = "date" in (e.get("start") or {})
    clave = "date" if todo_el_dia else "dateTime"
    video = next((p.get("uri") for p in (e.get("conferenceData") or {}).get("entryPoints") or []
                  if p.get("entryPointType") == "video"), None) or e.get("hangoutLink")
    return {
        "id": e.get("id", ""), "title": e.get("summary") or "", "status": e.get("status") or "confirmed",
        "allDay": todo_el_dia, "start": (e.get("start") or {}).get(clave, ""),
        "end": (e.get("end") or {}).get(clave, ""),
        "participants": [{"email": a.get("email"), "name": a.get("displayName"), "self": bool(a.get("self")),
                          "status": ESTADOS.get(a.get("responseStatus"), "pending"),
                          **({"resource": True} if a.get("resource") else {})}
                         for a in e.get("attendees") or []],
        "conferencing": {"url": video} if video else None,
    }


def eventos(token: str, desde: str, hasta: str, zona: str, maximo: int = 200) -> list[dict]:
    """Eventos del calendario principal entre `desde` y `hasta` (ISO), ordenados por inicio."""
    salida, pagina = [], None
    for _ in range(5):
        params = {"timeMin": desde, "timeMax": hasta, "timeZone": zona, "singleEvents": "true",
                  "orderBy": "startTime", "maxResults": "100"}
        if pagina:
            params["pageToken"] = pagina
        datos = _api("GET", "/calendars/primary/events", token, params=params)
        salida.extend(_normalizar(e) for e in datos.get("items") or [])
        pagina = datos.get("nextPageToken")
        if not pagina or len(salida) >= maximo:
            break
    return salida[:maximo]


def ocupado(token: str, desde: str, hasta: str) -> list[tuple[str, str]]:
    """Bloques ocupados del calendario principal (ISO, en UTC)."""
    datos = _api("POST", "/freeBusy", token, json={"timeMin": desde, "timeMax": hasta, "items": [{"id": "primary"}]})
    bloques = ((datos.get("calendars") or {}).get("primary") or {}).get("busy") or []
    return [(b["start"], b["end"]) for b in bloques]


def crear_evento(token: str, titulo: str, inicio: str, fin: str, zona: str,
                 invitados: list[str], notas: str = "") -> dict:
    """Crea la reunion con Meet y manda las invitaciones."""
    cuerpo = {
        "summary": titulo, "start": {"dateTime": inicio, "timeZone": zona},
        "end": {"dateTime": fin, "timeZone": zona},
        "attendees": [{"email": d} for d in invitados],
        "conferenceData": {"createRequest": {"requestId": uuid.uuid4().hex,
                                             "conferenceSolutionKey": {"type": "hangoutsMeet"}}},
    }
    if notas:
        cuerpo["description"] = notas
    datos = _api("POST", "/calendars/primary/events", token, json=cuerpo,
                 params={"conferenceDataVersion": "1", "sendUpdates": "all"})
    return _normalizar(datos)
