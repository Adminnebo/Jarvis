"""Rutas de la bandeja de correo (/apps/correo y /api/apps/correo/...)."""

import email
import json
from email import policy

import pytest
from fastapi.testclient import TestClient

from backend import apps_correo, gmail, integraciones, rutas_apps_correo
from backend.main import app


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setenv("JARVIS_CLAVE_SECRETA", "clave-de-pruebas-larga")
    monkeypatch.setenv("GOOGLE_JARVIS_CLIENT_ID", "id")
    monkeypatch.setenv("GOOGLE_JARVIS_CLIENT_SECRET", "secreto")
    c = TestClient(app)
    c.post("/acceso", data={"clave": "la-del-admin"}, follow_redirects=False)
    return c


@pytest.fixture
def conectado(cliente, monkeypatch):
    integraciones.guardar_gmail("admin", "yo@gmail.com", "refresh-1", "100")
    monkeypatch.setattr(gmail, "token_de_acceso", lambda r: "tok")
    monkeypatch.setattr(gmail, "puede_modificar", lambda r: True)
    return cliente


def test_la_pagina(cliente):
    r = cliente.get("/apps/correo")
    assert r.status_code == 200 and "correo.js" in r.text


def test_sin_gmail_es_409(cliente):
    r = cliente.get("/api/apps/correo/etiquetas")
    assert r.status_code == 409 and r.json()["conectar"] is True


def test_estado(conectado, monkeypatch):
    monkeypatch.setattr(gmail, "perfil", lambda t: {"email": "yo@gmail.com", "historyId": "555"})
    assert conectado.get("/api/apps/correo/estado").json() == {
        "conectado": True, "cuenta": "yo@gmail.com", "modificar": True, "historyId": "555"}


def test_estado_sin_conectar(cliente):
    assert cliente.get("/api/apps/correo/estado").json()["conectado"] is False


def test_acceso_revocado_desconecta(conectado, monkeypatch):
    def revocado(r):
        raise gmail.ErrorGmail("Google retiro el acceso", revocado=True)

    monkeypatch.setattr(gmail, "token_de_acceso", revocado)
    r = conectado.get("/api/apps/correo/etiquetas")
    assert r.status_code == 409 and r.json()["conectar"] is True
    assert integraciones.conexion("admin")["estado"] == "desconectado"


def test_etiquetas(conectado, monkeypatch):
    monkeypatch.setattr(gmail, "etiquetas", lambda t: [{"id": "INBOX", "no_leidos": 3}])
    assert conectado.get("/api/apps/correo/etiquetas").json() == {"etiquetas": [{"id": "INBOX", "no_leidos": 3}]}


def test_hilos(conectado, monkeypatch):
    pedidos = []
    monkeypatch.setattr(gmail, "hilos", lambda t, e, q, p: pedidos.append((e, q, p)) or (["h1"], "p2"))
    monkeypatch.setattr(apps_correo, "hilos_para_lista", lambda t, ids, propio: [{"id": i, "propio": propio} for i in ids])
    r = conectado.get("/api/apps/correo/hilos?etiqueta=INBOX&q=category:primary&pagina=p1").json()
    assert r == {"hilos": [{"id": "h1", "propio": "yo@gmail.com"}], "siguiente": "p2"}
    assert pedidos == [("INBOX", "category:primary", "p1")]


def test_abrir_hilo_lo_marca_leido(conectado, monkeypatch):
    monkeypatch.setattr(gmail, "hilo_completo", lambda t, i, solo_cabeceras=False:
                        {"id": i, "messages": [{"id": "m1", "labelIds": ["UNREAD", "INBOX"]}]})
    monkeypatch.setattr(apps_correo, "mensaje_para_ver", lambda t, m: {"id": m["id"], "no_leido": "UNREAD" in m["labelIds"]})
    marcados = []
    monkeypatch.setattr(gmail, "modificar_hilos", lambda t, ids, agregar=(), quitar=(): marcados.append((ids, list(quitar))))
    r = conectado.get("/api/apps/correo/hilos/h1").json()
    assert r["id"] == "h1" and r["mensajes"] == [{"id": "m1", "no_leido": True}]
    assert marcados == [(["h1"], ["UNREAD"])]


def test_adjunto(conectado, monkeypatch):
    monkeypatch.setattr(gmail, "adjunto", lambda t, m, a: b"%PDF")
    r = conectado.get("/api/apps/correo/adjunto/m1/a1?nombre=factura.pdf&tipo=application/pdf")
    assert r.content == b"%PDF" and r.headers["content-type"] == "application/pdf"
    assert "factura.pdf" in r.headers["content-disposition"]


@pytest.mark.parametrize("accion, esperado", [
    ("archivar", ("modificar", [], ["INBOX"])),
    ("eliminar", ("papelera",)),
    ("restaurar", ("restaurar",)),
])
def test_acciones(conectado, monkeypatch, accion, esperado):
    hechos = []
    monkeypatch.setattr(gmail, "modificar_hilos", lambda t, ids, agregar=(), quitar=(): hechos.append(("modificar", list(agregar), list(quitar))))
    monkeypatch.setattr(gmail, "papelera", lambda t, ids: hechos.append(("papelera",)))
    monkeypatch.setattr(gmail, "restaurar", lambda t, ids: hechos.append(("restaurar",)))
    r = conectado.post("/api/apps/correo/acciones", json={"ids": ["h1"], "accion": accion})
    assert r.json() == {"ok": True} and hechos == [esperado]


def test_accion_mala_es_400(conectado):
    assert conectado.post("/api/apps/correo/acciones", json={"ids": ["h1"], "accion": "volar"}).status_code == 400


def test_sin_permiso_de_modificar_es_403(conectado, monkeypatch):
    monkeypatch.setattr(gmail, "puede_modificar", lambda r: False)
    r = conectado.post("/api/apps/correo/acciones", json={"ids": ["h1"], "accion": "archivar"})
    assert r.status_code == 403 and r.json()["reconectar"] is True
    assert conectado.put("/api/apps/correo/borrador", data={"html": "x"}).status_code == 403


def _correo_de(crudo: bytes):
    return email.message_from_bytes(crudo, policy=policy.default)


def test_guardar_borrador(conectado, monkeypatch):
    guardados = []
    monkeypatch.setattr(gmail, "guardar_borrador", lambda t, crudo, borrador_id, hilo_id:
                        guardados.append((_correo_de(crudo), borrador_id, hilo_id)) or {"id": "d1", "message": {"id": "m9"}})
    r = conectado.put("/api/apps/correo/borrador", data={"para": "pedro@jh.com", "asunto": "Hola", "html": "<p>hola</p>",
                                                        "hilo": "h1", "borrador_id": "d0"},
                      files=[("adjuntos", ("a.txt", b"hola", "text/plain"))])
    assert r.json() == {"id": "d1", "mensaje": "m9"}
    correo, borrador_id, hilo = guardados[0]
    assert correo["To"] == "pedro@jh.com" and correo["From"] == "yo@gmail.com" and borrador_id == "d0" and hilo == "h1"
    assert [a.get_filename() for a in correo.iter_attachments()] == ["a.txt"]


def test_enviar_respuesta_con_adjunto_original(conectado, monkeypatch):
    enviados = []
    monkeypatch.setattr(gmail, "adjunto", lambda t, m, a: b"%PDF-orig")
    monkeypatch.setattr(gmail, "enviar_mime", lambda t, crudo, hilo_id=None: enviados.append((_correo_de(crudo), hilo_id)) or {"id": "m5"})
    r = conectado.post("/api/apps/correo/enviar", data={
        "para": "pedro@jh.com", "asunto": "Re: Factura", "html": "<p>va</p>", "hilo": "h1",
        "responder_message_id": "<abc@jh.com>", "responder_referencias": "",
        "adjuntos_originales": json.dumps([{"mensaje": "m1", "id": "a1", "nombre": "f.pdf", "tipo": "application/pdf"}])})
    assert r.json() == {"ok": True, "id": "m5"}
    correo, hilo = enviados[0]
    assert hilo == "h1" and correo["In-Reply-To"] == "<abc@jh.com>"
    (adjunto,) = list(correo.iter_attachments())
    assert adjunto.get_filename() == "f.pdf" and adjunto.get_content() == b"%PDF-orig"


def test_enviar_un_borrador_lo_actualiza_y_lo_manda(conectado, monkeypatch):
    hechos = []
    monkeypatch.setattr(gmail, "guardar_borrador", lambda t, crudo, b, h: hechos.append(("guardar", b)) or {"id": b})
    monkeypatch.setattr(gmail, "enviar_borrador", lambda t, b: hechos.append(("enviar", b)) or {"id": "m7"})
    r = conectado.post("/api/apps/correo/enviar", data={"para": "a@b.com", "html": "x", "borrador_id": "d1"})
    assert r.json() == {"ok": True, "id": "m7"} and hechos == [("guardar", "d1"), ("enviar", "d1")]


def test_enviar_sin_destinatario_es_400(conectado):
    assert conectado.post("/api/apps/correo/enviar", data={"html": "x"}).status_code == 400


def test_adjuntos_demasiado_grandes(conectado, monkeypatch):
    monkeypatch.setattr(rutas_apps_correo, "MAX_ADJUNTOS", 5)
    r = conectado.post("/api/apps/correo/enviar", data={"para": "a@b.com", "html": "x"},
                       files=[("adjuntos", ("a.bin", b"123456", "application/octet-stream"))])
    assert r.status_code == 413


def test_descartar_borrador(conectado, monkeypatch):
    borrados = []
    monkeypatch.setattr(gmail, "borrar_borrador", lambda t, b: borrados.append(b))
    assert conectado.delete("/api/apps/correo/borrador/d1").json() == {"ok": True} and borrados == ["d1"]


def test_cambios(conectado, monkeypatch):
    monkeypatch.setattr(gmail, "cambios", lambda t, desde: {"historyId": "600", "hilos": ["h1"]})
    assert conectado.get("/api/apps/correo/cambios?desde=500").json() == {"historyId": "600", "hay": True}

    def viejo(t, desde):
        raise gmail.ErrorGmail("muy viejo", status=404)

    monkeypatch.setattr(gmail, "cambios", viejo)
    monkeypatch.setattr(gmail, "perfil", lambda t: {"email": "yo@gmail.com", "historyId": "700"})
    assert conectado.get("/api/apps/correo/cambios?desde=1").json() == {"historyId": "700", "hay": True}


def test_borrador_de_un_mensaje(conectado, monkeypatch):
    monkeypatch.setattr(gmail, "borrador_de_mensaje", lambda t, m: "d7" if m == "m1" else None)
    assert conectado.get("/api/apps/correo/borrador-de/m1").json() == {"id": "d7"}
    assert conectado.get("/api/apps/correo/borrador-de/m2").status_code == 404
