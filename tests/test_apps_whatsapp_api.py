"""Rutas de la vista de WhatsApp (/apps/whatsapp y /api/apps/whatsapp/...)."""

import asyncio
import base64
import json

import pytest
from fastapi.testclient import TestClient

from backend import apps_whatsapp, evolution_wa, integraciones, rutas_apps_whatsapp
from backend.main import app

JID = "18097778888@s.whatsapp.net"


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setenv("JARVIS_CLAVE_SECRETA", "clave-de-pruebas-larga")
    monkeypatch.setenv("EVOLUTION_URL", "https://evo")
    monkeypatch.setenv("EVOLUTION_API_KEY", "k")
    monkeypatch.setattr(evolution_wa, "asegurar_eventos", lambda inst, url: None)
    c = TestClient(app)
    c.post("/acceso", data={"clave": "la-del-admin"}, follow_redirects=False)
    return c


@pytest.fixture
def conectado(cliente):
    integraciones.preparar_evolution("admin")
    integraciones.conectar_evolution("admin", "18095551234")
    return cliente


def test_la_pagina(cliente):
    r = cliente.get("/apps/whatsapp")
    assert r.status_code == 200 and "whatsapp.js" in r.text


def test_sin_sesion_no_entra(cliente):
    r = TestClient(app).get("/api/apps/whatsapp/chats", follow_redirects=False)
    assert r.status_code in (401, 302, 303, 307) and "chats" not in r.text


def test_sin_whatsapp_vinculado_es_409(cliente):
    r = cliente.get("/api/apps/whatsapp/chats")
    assert r.status_code == 409 and r.json()["vincular"] is True


def test_estado(conectado):
    assert conectado.get("/api/apps/whatsapp/estado").json() == {"conectado": True, "cuenta": "+1 809-555-1234"}


def test_chats(conectado, monkeypatch):
    monkeypatch.setattr(evolution_wa, "chats", lambda inst, limite=50: [{"id": JID, "nombre": "Pedro"}])
    assert conectado.get("/api/apps/whatsapp/chats").json() == {"chats": [{"id": JID, "nombre": "Pedro"}]}


def test_mensajes_con_pagina(conectado, monkeypatch):
    pedidos = []
    monkeypatch.setattr(evolution_wa, "mensajes", lambda inst, jid, limite=30, pagina=1:
                        pedidos.append((inst, jid, pagina)) or [{"id": "m1"}])
    r = conectado.get(f"/api/apps/whatsapp/chats/{JID}/mensajes?pagina=2")
    assert r.json() == {"mensajes": [{"id": "m1"}], "jid": JID} and pedidos == [("jarvis-admin", JID, 2)]
    nuevo = conectado.get("/api/apps/whatsapp/chats/8097778888/mensajes").json()
    assert nuevo["jid"] == JID


def test_grupo_es_400(conectado):
    assert conectado.get("/api/apps/whatsapp/chats/1203@g.us/mensajes").status_code == 400


def test_numero_nuevo_se_vuelve_jid(conectado, monkeypatch):
    enviados = []
    monkeypatch.setattr(evolution_wa, "enviar", lambda inst, jid, texto, cita=None:
                        enviados.append((jid, texto, cita)) or "nuevo")
    r = conectado.post("/api/apps/whatsapp/chats/8097778888/mensajes", json={"texto": "hola"})
    assert r.json() == {"id": "nuevo", "jid": JID} and enviados == [(JID, "hola", None)]


def test_enviar_texto_con_cita_y_vacio(conectado, monkeypatch):
    enviados = []
    monkeypatch.setattr(evolution_wa, "enviar", lambda inst, jid, texto, cita=None: enviados.append(cita) or "x")
    conectado.post(f"/api/apps/whatsapp/chats/{JID}/mensajes", json={"texto": "si", "cita": {"id": "m0", "texto": "va?"}})
    assert enviados == [{"id": "m0", "texto": "va?"}]
    assert conectado.post(f"/api/apps/whatsapp/chats/{JID}/mensajes", json={"texto": "  "}).status_code == 400


def test_si_evolution_falla_es_502(conectado, monkeypatch):
    def falla(*a, **k):
        raise evolution_wa.ErrorEvolution("caido", 500)

    monkeypatch.setattr(evolution_wa, "enviar", falla)
    r = conectado.post(f"/api/apps/whatsapp/chats/{JID}/mensajes", json={"texto": "hola"})
    assert r.status_code == 502 and "caido" in r.json()["error"]


def test_enviar_archivo(conectado, monkeypatch):
    enviados = []
    monkeypatch.setattr(evolution_wa, "enviar_archivo", lambda inst, jid, mime, nombre, b64, pie="", cita=None:
                        enviados.append((mime, nombre, base64.b64decode(b64), pie, cita)) or "f1")
    r = conectado.post(f"/api/apps/whatsapp/chats/{JID}/archivo",
                       files={"archivo": ("factura.pdf", b"%PDF-1", "application/pdf")},
                       data={"pie": "la factura", "cita": json.dumps({"id": "m0", "texto": "x"})})
    assert r.json()["id"] == "f1"
    assert enviados == [("application/pdf", "factura.pdf", b"%PDF-1", "la factura", {"id": "m0", "texto": "x"})]


def test_archivo_muy_grande(conectado, monkeypatch):
    monkeypatch.setattr(rutas_apps_whatsapp, "MAX_ARCHIVO", 10)
    r = conectado.post(f"/api/apps/whatsapp/chats/{JID}/archivo",
                       files={"archivo": ("a.bin", b"x" * 11, "application/octet-stream")})
    assert r.status_code == 413


def test_enviar_nota(conectado, monkeypatch):
    enviadas = []
    monkeypatch.setattr(evolution_wa, "enviar_nota", lambda inst, jid, b64, cita=None:
                        enviadas.append(base64.b64decode(b64)) or "n1")
    r = conectado.post(f"/api/apps/whatsapp/chats/{JID}/nota", files={"audio": ("nota.webm", b"OPUS", "audio/webm")})
    assert r.json()["id"] == "n1" and enviadas == [b"OPUS"]


def test_marcar_leido(conectado, monkeypatch):
    marcados = []
    monkeypatch.setattr(evolution_wa, "marcar_leido", lambda inst, jid, ids: marcados.append((jid, ids)))
    assert conectado.post(f"/api/apps/whatsapp/chats/{JID}/leido", json={"ids": ["a", "b"]}).json() == {"ok": True}
    assert marcados == [(JID, ["a", "b"])]


def test_archivo_de_un_mensaje(conectado, monkeypatch):
    monkeypatch.setattr(evolution_wa, "archivo", lambda inst, id_: {
        "mime": "image/jpeg", "nombre": "foto.jpg", "base64": base64.b64encode(b"JPEG").decode()})
    r = conectado.get("/api/apps/whatsapp/archivo/m1")
    assert r.status_code == 200 and r.content == b"JPEG" and r.headers["content-type"] == "image/jpeg"
    assert "private" in r.headers["cache-control"]


def test_foto(conectado, monkeypatch):
    monkeypatch.setattr(apps_whatsapp, "foto", lambda inst, jid: "https://pps/x.jpg" if jid == JID else None)
    r = conectado.get(f"/api/apps/whatsapp/foto/{JID}", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "https://pps/x.jpg"
    assert conectado.get("/api/apps/whatsapp/foto/otro@s.whatsapp.net").status_code == 404


def test_flujo_de_eventos():
    class Peticion:
        def __init__(self):
            self.vueltas = 0

        async def is_disconnected(self):
            self.vueltas += 1
            return self.vueltas > 2

    async def prueba():
        flujo = rutas_apps_whatsapp.flujo("u1", Peticion(), latido=0.05)
        assert (await flujo.__anext__()).startswith("retry:")
        apps_whatsapp.publicar("u1", {"tipo": "mensaje", "mensaje": {"id": "m1"}})
        assert json.loads((await flujo.__anext__()).removeprefix("data: ")) == {"tipo": "mensaje", "mensaje": {"id": "m1"}}
        assert (await flujo.__anext__()).startswith(":")   # latido
        with pytest.raises(StopAsyncIteration):
            await flujo.__anext__()
        assert not apps_whatsapp._suscritos.get("u1")

    asyncio.run(prueba())
