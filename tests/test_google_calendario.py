import json

import httpx
import pytest

from backend import google_calendario as gc


@pytest.fixture
def api(monkeypatch):
    pedidos, respuestas = [], {}

    def manejar(pedido: httpx.Request):
        pedidos.append(pedido)
        status, cuerpo = respuestas.get((pedido.method, pedido.url.path), (404, {"error": {"message": "no"}}))
        return httpx.Response(status, json=cuerpo)

    monkeypatch.setattr(gc, "_http", lambda: httpx.Client(transport=httpx.MockTransport(manejar)))
    return pedidos, respuestas


EVENTO = {
    "id": "g1", "summary": "Revision", "status": "confirmed",
    "start": {"dateTime": "2026-11-20T15:00:00-04:00"}, "end": {"dateTime": "2026-11-20T15:30:00-04:00"},
    "attendees": [{"email": "ana@gmail.com", "self": True, "responseStatus": "accepted"},
                  {"email": "p@x.com", "displayName": "Pedro", "responseStatus": "needsAction"}],
    "conferenceData": {"entryPoints": [{"entryPointType": "video", "uri": "https://meet.google.com/abc"}]},
}


def test_eventos_normaliza_como_zernio(api):
    pedidos, respuestas = api
    respuestas[("GET", "/calendar/v3/calendars/primary/events")] = (200, {"items": [
        EVENTO, {"id": "g2", "summary": "Feriado", "start": {"date": "2026-11-21"}, "end": {"date": "2026-11-22"}}]})
    uno, dos = gc.eventos("tok", "2026-11-20T00:00:00-04:00", "2026-11-22T00:00:00-04:00", "America/Santo_Domingo")
    assert uno == {"id": "g1", "title": "Revision", "status": "confirmed", "allDay": False,
                   "start": "2026-11-20T15:00:00-04:00", "end": "2026-11-20T15:30:00-04:00",
                   "participants": [{"email": "ana@gmail.com", "name": None, "self": True, "status": "accepted"},
                                    {"email": "p@x.com", "name": "Pedro", "self": False, "status": "pending"}],
                   "conferencing": {"url": "https://meet.google.com/abc"}}
    assert dos["allDay"] and dos["start"] == "2026-11-21" and dos["conferencing"] is None
    p = pedidos[0]
    assert p.headers["authorization"] == "Bearer tok"
    assert p.url.params["singleEvents"] == "true" and p.url.params["timeZone"] == "America/Santo_Domingo"


def test_ocupado_lee_freebusy(api):
    pedidos, respuestas = api
    respuestas[("POST", "/calendar/v3/freeBusy")] = (200, {"calendars": {"primary": {"busy": [
        {"start": "2026-11-20T13:00:00Z", "end": "2026-11-20T14:00:00Z"}]}}})
    assert gc.ocupado("tok", "a", "b") == [("2026-11-20T13:00:00Z", "2026-11-20T14:00:00Z")]
    assert json.loads(pedidos[0].content) == {"timeMin": "a", "timeMax": "b", "items": [{"id": "primary"}]}


def test_crear_evento_con_meet_e_invitaciones(api):
    pedidos, respuestas = api
    respuestas[("POST", "/calendar/v3/calendars/primary/events")] = (200, EVENTO)
    evento = gc.crear_evento("tok", "Revision", "2026-11-20T15:00:00-04:00", "2026-11-20T15:30:00-04:00",
                             "America/Santo_Domingo", ["p@x.com"], "Traer contrato")
    assert evento["conferencing"]["url"] == "https://meet.google.com/abc"
    p = pedidos[0]
    assert p.url.params["conferenceDataVersion"] == "1" and p.url.params["sendUpdates"] == "all"
    cuerpo = json.loads(p.content)
    assert cuerpo["summary"] == "Revision" and cuerpo["attendees"] == [{"email": "p@x.com"}]
    assert cuerpo["start"] == {"dateTime": "2026-11-20T15:00:00-04:00", "timeZone": "America/Santo_Domingo"}
    assert cuerpo["conferenceData"]["createRequest"]["conferenceSolutionKey"] == {"type": "hangoutsMeet"}
    assert cuerpo["description"] == "Traer contrato"


def test_errores(api):
    _, respuestas = api
    respuestas[("POST", "/calendar/v3/freeBusy")] = (403, {"error": {"message": "Insufficient Permission",
                                                                     "errors": [{"reason": "insufficientPermissions"}]}})
    with pytest.raises(gc.ErrorGoogleCalendario) as error:
        gc.ocupado("tok", "a", "b")
    assert error.value.sin_permiso and not error.value.revocado
    respuestas[("POST", "/calendar/v3/freeBusy")] = (401, {"error": {"message": "Invalid Credentials"}})
    with pytest.raises(gc.ErrorGoogleCalendario) as error:
        gc.ocupado("tok", "a", "b")
    assert error.value.revocado
