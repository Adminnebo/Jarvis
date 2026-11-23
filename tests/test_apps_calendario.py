"""apps_calendario.py: Google Calendar para la vista /apps/calendario."""

import json

import httpx
import pytest

from backend import apps_calendario, gmail, google_calendario


@pytest.fixture
def api(monkeypatch):
    """Google Calendar falso: `respuestas` es {(METODO, ruta): (status, json)}; anota cada pedido."""
    pedidos, respuestas = [], {}

    def manejar(pedido: httpx.Request):
        pedidos.append(pedido)
        ruta = pedido.url.path.removeprefix("/calendar/v3")
        status, cuerpo = respuestas.get((pedido.method, ruta), (404, {"error": {"message": "no existe"}}))
        return httpx.Response(status, json=cuerpo)

    cliente = httpx.Client(transport=httpx.MockTransport(manejar))
    monkeypatch.setattr(google_calendario, "_http", lambda: cliente)
    apps_calendario._paleta.clear()
    return pedidos, respuestas


def test_pide_la_lista_de_calendarios():
    assert gmail.CALENDARIOS in gmail.PERMISOS


def test_calendarios(api):
    _, respuestas = api
    respuestas[("GET", "/users/me/calendarList")] = (200, {"items": [
        {"id": "yo@gmail.com", "summary": "yo@gmail.com", "primary": True, "backgroundColor": "#9fe1e7",
         "foregroundColor": "#000000", "accessRole": "owner"},
        {"id": "es.do#holiday", "summary": "Festivos en RD", "summaryOverride": "Feriados", "backgroundColor": "#16a765",
         "accessRole": "reader"}]})
    principal, feriados = apps_calendario.calendarios("t")
    assert principal == {"id": "yo@gmail.com", "nombre": "yo@gmail.com", "color": "#9fe1e7", "texto": "#000000",
                         "principal": True, "puede_editar": True}
    assert feriados["nombre"] == "Feriados" and not feriados["puede_editar"] and not feriados["principal"]


def evento(**extra):
    base = {"id": "e1", "summary": "Visita a la obra", "status": "confirmed",
            "start": {"dateTime": "2026-11-24T09:00:00-04:00"}, "end": {"dateTime": "2026-11-24T10:00:00-04:00"},
            "location": "Bávaro", "description": "Llevar planos", "htmlLink": "https://cal/e1",
            "organizer": {"email": "yo@gmail.com", "self": True},
            "attendees": [{"email": "yo@gmail.com", "self": True, "responseStatus": "accepted", "organizer": True},
                          {"email": "carlos@rc.com", "displayName": "Carlos", "responseStatus": "tentative"}],
            "hangoutLink": "https://meet.google.com/abc", "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 15}]}}
    base.update(extra)
    return base


def test_eventos_normalizados(api):
    pedidos, respuestas = api
    respuestas[("GET", "/calendars/yo@gmail.com/events")] = (200, {"items": [
        evento(), evento(id="e2", summary="Cumpleaños", start={"date": "2026-11-25"}, end={"date": "2026-11-26"},
                         attendees=None, hangoutLink=None, organizer={"email": "otro@x.com"}, colorId="11"),
        evento(id="e3", status="cancelled")]})
    respuestas[("GET", "/colors")] = (200, {"event": {"11": {"background": "#dc2127"}}})
    uno, dos = apps_calendario.eventos("t", "yo@gmail.com", "2026-11-23T00:00:00-04:00", "2026-11-30T00:00:00-04:00",
                                       puede_editar=True)
    assert uno == {"id": "e1", "calendario": "yo@gmail.com", "titulo": "Visita a la obra",
                   "inicio": "2026-11-24T09:00:00-04:00", "fin": "2026-11-24T10:00:00-04:00", "todo_el_dia": False,
                   "ubicacion": "Bávaro", "descripcion": "Llevar planos", "color": None, "meet": "https://meet.google.com/abc",
                   "invitados": [{"correo": "yo@gmail.com", "nombre": None, "estado": "si", "yo": True, "organizador": True},
                                 {"correo": "carlos@rc.com", "nombre": "Carlos", "estado": "quizas", "yo": False, "organizador": False}],
                   "mi_respuesta": "si", "organizador": "yo@gmail.com", "soy_organizador": True, "recurrente": None,
                   "puede_editar": True, "aviso_min": 15, "enlace": "https://cal/e1"}
    assert dos["todo_el_dia"] and dos["inicio"] == "2026-11-25" and dos["fin"] == "2026-11-26"
    assert dos["color"] == "#dc2127" and not dos["soy_organizador"] and not dos["puede_editar"]
    params = next(p for p in pedidos if p.url.path.endswith("/events")).url.params
    assert params["singleEvents"] == "true" and params["timeMin"].startswith("2026-11-23")


def test_eventos_de_varios_calendarios_en_paralelo(monkeypatch):
    def eventos(token, cal, desde, hasta, puede_editar=True):
        if cal == "malo":
            raise google_calendario.ErrorGoogleCalendario("sin acceso", 404)
        return [{"id": cal + "-1", "inicio": "2026-11-24T09:00:00-04:00"}]

    monkeypatch.setattr(apps_calendario, "eventos", eventos)
    lista = apps_calendario.eventos_de("t", [("a", True), ("malo", True), ("b", False)], "d", "h")
    assert sorted(e["id"] for e in lista) == ["a-1", "b-1"]


def test_crear_con_meet_invitados_y_aviso(api):
    pedidos, respuestas = api
    respuestas[("POST", "/calendars/yo@gmail.com/events")] = (200, evento())
    creado = apps_calendario.crear("t", "yo@gmail.com", {
        "titulo": "Visita", "inicio": "2026-11-24T09:00:00-04:00", "fin": "2026-11-24T10:00:00-04:00",
        "invitados": ["carlos@rc.com"], "meet": True, "ubicacion": "Bávaro", "descripcion": "x", "aviso_min": 15})
    assert creado["id"] == "e1"
    cuerpo = json.loads(pedidos[0].content)
    assert cuerpo["summary"] == "Visita" and cuerpo["start"] == {"dateTime": "2026-11-24T09:00:00-04:00"}
    assert cuerpo["attendees"] == [{"email": "carlos@rc.com"}] and cuerpo["location"] == "Bávaro"
    assert cuerpo["conferenceData"]["createRequest"]["conferenceSolutionKey"] == {"type": "hangoutsMeet"}
    assert cuerpo["reminders"] == {"useDefault": False, "overrides": [{"method": "popup", "minutes": 15}]}
    assert pedidos[0].url.params["sendUpdates"] == "all" and pedidos[0].url.params["conferenceDataVersion"] == "1"


def test_crear_de_todo_el_dia(api):
    pedidos, respuestas = api
    respuestas[("POST", "/calendars/c/events")] = (200, evento())
    apps_calendario.crear("t", "c", {"titulo": "Feria", "inicio": "2026-11-25", "fin": "2026-11-26", "todo_el_dia": True})
    cuerpo = json.loads(pedidos[0].content)
    assert cuerpo["start"] == {"date": "2026-11-25"} and cuerpo["end"] == {"date": "2026-11-26"}
    assert "conferenceData" not in cuerpo and "reminders" not in cuerpo


def test_cambiar_solo_lo_que_viene(api):
    pedidos, respuestas = api
    respuestas[("PATCH", "/calendars/c/events/e1")] = (200, evento())
    apps_calendario.cambiar("t", "c", "e1", {"inicio": "2026-11-24T11:00:00-04:00", "fin": "2026-11-24T12:00:00-04:00"})
    assert json.loads(pedidos[0].content) == {"start": {"dateTime": "2026-11-24T11:00:00-04:00"},
                                              "end": {"dateTime": "2026-11-24T12:00:00-04:00"}}
    assert pedidos[0].url.params["sendUpdates"] == "all"


def test_cambiar_todos_corre_la_madre(api):
    pedidos, respuestas = api
    respuestas[("GET", "/calendars/c/events/e1_20261124")] = (200, evento(
        id="e1_20261124", recurringEventId="e1", start={"dateTime": "2026-11-24T09:00:00-04:00"}))
    respuestas[("GET", "/calendars/c/events/e1")] = (200, evento(
        id="e1", start={"dateTime": "2026-11-03T09:00:00-04:00"}, end={"dateTime": "2026-11-03T10:00:00-04:00"},
        recurrence=["RRULE:FREQ=WEEKLY"]))
    respuestas[("PATCH", "/calendars/c/events/e1")] = (200, evento(id="e1"))
    apps_calendario.cambiar("t", "c", "e1_20261124", {"titulo": "Visita semanal", "inicio": "2026-11-24T10:30:00-04:00",
                                                      "fin": "2026-11-24T11:30:00-04:00"}, todos=True)
    parche = [p for p in pedidos if p.method == "PATCH"][-1]
    cuerpo = json.loads(parche.content)
    assert parche.url.path.endswith("/events/e1")
    assert cuerpo["summary"] == "Visita semanal"
    assert cuerpo["start"] == {"dateTime": "2026-11-03T10:30:00-04:00"} and cuerpo["end"] == {"dateTime": "2026-11-03T11:30:00-04:00"}


def test_borrar_uno_o_todos(api):
    pedidos, respuestas = api
    respuestas[("DELETE", "/calendars/c/events/e1_1")] = (204, {})
    respuestas[("GET", "/calendars/c/events/e1_1")] = (200, evento(id="e1_1", recurringEventId="e1"))
    respuestas[("DELETE", "/calendars/c/events/e1")] = (204, {})
    apps_calendario.borrar("t", "c", "e1_1")
    apps_calendario.borrar("t", "c", "e1_1", todos=True)
    borrados = [p.url.path.rsplit("/", 1)[-1] for p in pedidos if p.method == "DELETE"]
    assert borrados == ["e1_1", "e1"] and all(p.url.params["sendUpdates"] == "all" for p in pedidos if p.method == "DELETE")


def test_responder_invitacion(api):
    pedidos, respuestas = api
    respuestas[("GET", "/calendars/c/events/e1")] = (200, evento(attendees=[
        {"email": "carlos@rc.com", "organizer": True, "responseStatus": "accepted"},
        {"email": "yo@gmail.com", "self": True, "responseStatus": "needsAction"}]))
    respuestas[("PATCH", "/calendars/c/events/e1")] = (200, evento())
    apps_calendario.responder("t", "c", "e1", "no")
    asistentes = json.loads([p for p in pedidos if p.method == "PATCH"][-1].content)["attendees"]
    assert asistentes[1] == {"email": "yo@gmail.com", "self": True, "responseStatus": "declined"}
    assert asistentes[0]["responseStatus"] == "accepted"
    with pytest.raises(ValueError):
        apps_calendario.responder("t", "c", "e1", "talvez")
