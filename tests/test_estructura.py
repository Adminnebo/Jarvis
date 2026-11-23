"""La estructura comun (/), el asistente (/asistente), el contexto del chat, el resumen
de contadores y las herramientas para mover y cancelar eventos."""

import json

import pytest
from fastapi.testclient import TestClient

from backend import (acciones_calendario, apps_calendario, cerebro, evolution_wa, gmail, herramientas,
                     integraciones, rutas_estructura)
from backend.main import app


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setenv("JARVIS_CLAVE_SECRETA", "clave-de-pruebas-larga")
    rutas_estructura._cache.clear()
    c = TestClient(app)
    c.post("/acceso", data={"clave": "la-del-admin"}, follow_redirects=False)
    return c


def test_la_raiz_es_la_estructura_y_el_asistente_se_muda(cliente):
    assert "estructura.js" in cliente.get("/").text
    assert "app.js" in cliente.get("/asistente").text


def test_el_contexto_llega_como_instruccion_del_turno(cliente, monkeypatch):
    vistos = []

    def responder(mensajes, usuario, extra, dispositivo):
        vistos.append((mensajes[-1]["content"], extra))
        yield {"tipo": "texto", "dato": "ok"}

    monkeypatch.setattr(cerebro, "responder", responder)
    cliente.post("/api/chat", json={"mensaje": "respóndele que mañana paso",
                                    "contexto": "Correo: hilo id h1, asunto «Factura», de Pedro"})
    ((mensaje, extra),) = vistos
    assert mensaje == "respóndele que mañana paso"            # el contexto no entra al historial
    assert "hilo id h1" in extra and "esto" in extra.lower()
    vistos.clear()
    cliente.post("/api/chat", json={"mensaje": "hola", "contexto": "x" * 5000})
    assert len(vistos[0][1]) < 1200                            # recortado


def test_sin_contexto_no_cambia_nada(cliente, monkeypatch):
    vistos = []
    monkeypatch.setattr(cerebro, "responder", lambda m, u, extra, d: iter(vistos.append(extra) or []))
    cliente.post("/api/chat", json={"mensaje": "hola"})
    assert vistos == [""]


# --- resumen de contadores ---

def test_resumen_sin_nada_conectado(cliente):
    assert cliente.get("/api/apps/resumen").json() == {"whatsapp": None, "correo": None, "calendario": None}


def test_resumen_con_todo(cliente, monkeypatch):
    monkeypatch.setenv("EVOLUTION_URL", "https://evo")
    monkeypatch.setenv("EVOLUTION_API_KEY", "k")
    integraciones.preparar_evolution("admin")
    integraciones.conectar_evolution("admin", "18095551234")
    integraciones.guardar_gmail("admin", "yo@gmail.com", "r", "1")
    monkeypatch.setattr(evolution_wa, "chats", lambda inst, limite=50: [{"no_leidos": 2}, {"no_leidos": 0}, {"no_leidos": 3}])
    monkeypatch.setattr(gmail, "token_de_acceso", lambda r: "t")
    monkeypatch.setattr(gmail, "permisos", lambda r: {gmail.LEER, gmail.CALENDARIO})
    monkeypatch.setattr(gmail, "no_leidos_de", lambda t, e: 7)
    monkeypatch.setattr(apps_calendario, "eventos", lambda t, c, d, h, puede_editar=True: [
        {"titulo": "Pasado", "inicio": "2000-01-01T09:00:00+00:00", "todo_el_dia": False},
        {"titulo": "Visita", "inicio": "2999-01-01T15:00:00+00:00", "todo_el_dia": False}])
    r = cliente.get("/api/apps/resumen").json()
    assert r["whatsapp"] == 5 and r["correo"] == 7
    assert r["calendario"] == {"titulo": "Visita", "inicio": "2999-01-01T15:00:00+00:00"}


def test_resumen_aguanta_fallos(cliente, monkeypatch):
    integraciones.guardar_gmail("admin", "yo@gmail.com", "r", "1")

    def falla(r):
        raise gmail.ErrorGmail("caido")

    monkeypatch.setattr(gmail, "token_de_acceso", falla)
    assert cliente.get("/api/apps/resumen").json() == {"whatsapp": None, "correo": None, "calendario": None}


# --- mover y cancelar eventos ---

@pytest.fixture
def con_calendario(monkeypatch):
    integraciones.guardar_gmail("u1", "yo@gmail.com", "r", "1")
    monkeypatch.setattr(gmail, "token_de_acceso", lambda r: "t")
    monkeypatch.setattr(gmail, "permisos", lambda r: {gmail.LEER, gmail.CALENDARIO})
    acciones_calendario._pendientes.clear()
    hechos = []
    monkeypatch.setattr(acciones_calendario, "_evento", lambda t, cal, id_: {
        "id": id_, "titulo": "Reunión con Pedro", "inicio": "2026-11-24T15:00:00-04:00",
        "fin": "2026-11-24T16:00:00-04:00", "todo_el_dia": False, "recurrente": None, "puede_editar": True})
    monkeypatch.setattr(apps_calendario, "cambiar", lambda t, c, i, d, todos=False: hechos.append(("cambiar", c, i, d)) or {})
    monkeypatch.setattr(apps_calendario, "borrar", lambda t, c, i, todos=False: hechos.append(("borrar", c, i)))
    return hechos


def test_mover_conserva_la_duracion_y_pide_confirmar(con_calendario):
    texto = acciones_calendario.mover("u1", "e1", "2026-11-25T10:00:00-04:00")
    assert "Reunión con Pedro" in texto and "confirmar_cambio_evento" in texto
    assert con_calendario == []
    assert "Listo" in acciones_calendario.confirmar("u1")
    assert con_calendario == [("cambiar", "primary", "e1", {"inicio": "2026-11-25T10:00:00-04:00",
                                                            "fin": "2026-11-25T11:00:00-04:00"})]
    with pytest.raises(acciones_calendario.ErrorAccion):
        acciones_calendario.confirmar("u1")                    # un "si" repetido no hace nada dos veces


def test_cancelar(con_calendario):
    assert "cancelar" in acciones_calendario.cancelar("u1", "e1", "trabajo").lower()
    acciones_calendario.confirmar("u1")
    assert con_calendario == [("borrar", "trabajo", "e1")]


def test_hora_mala(con_calendario):
    with pytest.raises(acciones_calendario.ErrorAccion):
        acciones_calendario.mover("u1", "e1", "mañana")


def test_sin_calendario(monkeypatch):
    with pytest.raises(acciones_calendario.ErrorAccion):
        acciones_calendario.cancelar("nadie", "e1")


def test_las_herramientas_estan(monkeypatch):
    monkeypatch.setenv("GOOGLE_JARVIS_CLIENT_ID", "x")
    monkeypatch.setenv("GOOGLE_JARVIS_CLIENT_SECRET", "y")
    nombres = {e["name"] for e in herramientas.esquemas()}
    assert {"mover_evento", "cancelar_evento", "confirmar_cambio_evento"} <= nombres
    texto = herramientas.ejecutar("cancelar_evento", json.dumps({"id": "e1"}), "nadie")
    assert "Google" in texto or "calendario" in texto.lower()
