"""Rutas de la vista de calendario (/apps/calendario y /api/apps/calendario/...)."""

import pytest
from fastapi.testclient import TestClient

from backend import apps_calendario, gmail, google_calendario, integraciones, rutas_apps_calendario
from backend.main import app


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setenv("JARVIS_CLAVE_SECRETA", "clave-de-pruebas-larga")
    monkeypatch.setenv("GOOGLE_JARVIS_CLIENT_ID", "id")
    monkeypatch.setenv("GOOGLE_JARVIS_CLIENT_SECRET", "secreto")
    rutas_apps_calendario._cache_calendarios.clear()
    c = TestClient(app)
    c.post("/acceso", data={"clave": "la-del-admin"}, follow_redirects=False)
    return c


def con_permisos(monkeypatch, *permisos):
    integraciones.guardar_gmail("admin", "yo@gmail.com", "refresh-1", "100")
    monkeypatch.setattr(gmail, "token_de_acceso", lambda r: "tok")
    monkeypatch.setattr(gmail, "permisos", lambda r: set(permisos))


@pytest.fixture
def conectado(cliente, monkeypatch):
    con_permisos(monkeypatch, gmail.LEER, gmail.CALENDARIO, gmail.CALENDARIOS)
    monkeypatch.setattr(apps_calendario, "calendarios", lambda t: [
        {"id": "yo@gmail.com", "nombre": "yo", "principal": True, "puede_editar": True},
        {"id": "feriados", "nombre": "Feriados", "principal": False, "puede_editar": False}])
    return cliente


def test_la_pagina(cliente):
    r = cliente.get("/apps/calendario")
    assert r.status_code == 200 and "calendario.js" in r.text


def test_sin_gmail(cliente):
    assert cliente.get("/api/apps/calendario/estado").json() == {"conectado": False}
    r = cliente.get("/api/apps/calendario/calendarios")
    assert r.status_code == 409 and r.json()["conectar"] is True


def test_sin_permiso_de_calendario(cliente, monkeypatch):
    con_permisos(monkeypatch, gmail.LEER)
    assert cliente.get("/api/apps/calendario/estado").json() == {"conectado": False, "reconectar": True}
    assert cliente.get("/api/apps/calendario/calendarios").status_code == 409


def test_estado(conectado):
    assert conectado.get("/api/apps/calendario/estado").json() == {"conectado": True, "cuenta": "yo@gmail.com", "lista": True}


def test_calendarios(conectado):
    ids = [c["id"] for c in conectado.get("/api/apps/calendario/calendarios").json()["calendarios"]]
    assert ids == ["yo@gmail.com", "feriados"]


def test_sin_la_lista_solo_el_principal(cliente, monkeypatch):
    con_permisos(monkeypatch, gmail.CALENDARIO)
    (unico,) = cliente.get("/api/apps/calendario/calendarios").json()["calendarios"]
    assert unico["id"] == "primary" and unico["principal"] and unico["puede_editar"]


def test_eventos_del_rango(conectado, monkeypatch):
    pedidos = []
    monkeypatch.setattr(apps_calendario, "eventos_de", lambda t, cals, d, h: pedidos.append((cals, d, h)) or [{"id": "e1"}])
    r = conectado.get("/api/apps/calendario/eventos", params={
        "desde": "2026-11-22T00:00:00-04:00", "hasta": "2026-11-29T00:00:00-04:00", "calendarios": "yo@gmail.com,feriados,ajeno"})
    assert r.json() == {"eventos": [{"id": "e1"}]}
    assert pedidos == [([("yo@gmail.com", True), ("feriados", False)], "2026-11-22T00:00:00-04:00", "2026-11-29T00:00:00-04:00")]


def test_rango_demasiado_largo_o_malo(conectado):
    largo = conectado.get("/api/apps/calendario/eventos", params={"desde": "2026-01-01T00:00:00Z", "hasta": "2026-06-01T00:00:00Z"})
    malo = conectado.get("/api/apps/calendario/eventos", params={"desde": "ayer", "hasta": "hoy"})
    assert largo.status_code == 400 and malo.status_code == 400


def test_crear_cambiar_borrar_responder(conectado, monkeypatch):
    hechos = []
    monkeypatch.setattr(apps_calendario, "crear", lambda t, c, d: hechos.append(("crear", c, d["titulo"])) or {"id": "e9"})
    monkeypatch.setattr(apps_calendario, "cambiar", lambda t, c, i, d, todos=False: hechos.append(("cambiar", i, todos, sorted(d))) or {"id": i})
    monkeypatch.setattr(apps_calendario, "borrar", lambda t, c, i, todos=False: hechos.append(("borrar", i, todos)))
    monkeypatch.setattr(apps_calendario, "responder", lambda t, c, i, r: hechos.append(("responder", i, r)) or {"id": i})
    assert conectado.post("/api/apps/calendario/eventos", json={
        "calendario": "yo@gmail.com", "titulo": "Visita", "inicio": "2026-11-24T09:00:00-04:00",
        "fin": "2026-11-24T10:00:00-04:00"}).json() == {"id": "e9"}
    conectado.patch("/api/apps/calendario/eventos/yo@gmail.com/e9?todos=1", json={"titulo": "Visita 2"})
    conectado.delete("/api/apps/calendario/eventos/yo@gmail.com/e9")
    conectado.post("/api/apps/calendario/eventos/yo@gmail.com/e9/respuesta", json={"respuesta": "si"})
    assert hechos == [("crear", "yo@gmail.com", "Visita"), ("cambiar", "e9", True, ["titulo"]),
                      ("borrar", "e9", False), ("responder", "e9", "si")]


def test_no_escribe_en_un_calendario_de_solo_lectura(conectado):
    r = conectado.post("/api/apps/calendario/eventos", json={"calendario": "feriados", "titulo": "x",
                                                             "inicio": "2026-11-24", "fin": "2026-11-25", "todo_el_dia": True})
    assert r.status_code == 403


def test_errores_de_google(conectado, monkeypatch):
    def falla(t, c, d):
        raise google_calendario.ErrorGoogleCalendario("El evento ya no existe", 404)

    monkeypatch.setattr(apps_calendario, "crear", falla)
    r = conectado.post("/api/apps/calendario/eventos", json={"calendario": "yo@gmail.com", "titulo": "x",
                                                             "inicio": "2026-11-24T09:00:00Z", "fin": "2026-11-24T10:00:00Z"})
    assert r.status_code == 502 and "ya no existe" in r.json()["error"]


def test_respuesta_mala(conectado, monkeypatch):
    monkeypatch.setattr(apps_calendario, "responder", lambda t, c, i, r: (_ for _ in ()).throw(ValueError("mala")))
    assert conectado.post("/api/apps/calendario/eventos/yo@gmail.com/e1/respuesta", json={"respuesta": "x"}).status_code == 400
