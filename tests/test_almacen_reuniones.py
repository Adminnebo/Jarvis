import json

import httpx

from backend import almacen_reuniones as al


def preparar(monkeypatch, responder):
    monkeypatch.setenv("SUPABASE_PROJECT_REF", "ref")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "llave")
    pedidos = []

    def manejar(req):
        pedidos.append(req)
        return responder(req)
    monkeypatch.setattr(al, "_http", lambda: httpx.Client(transport=httpx.MockTransport(manejar)))
    return pedidos


def test_subir(monkeypatch):
    pedidos = preparar(monkeypatch, lambda r: httpx.Response(200, json={"Key": "x"}))
    al.subir("r1", 2, b"OGG")
    r = pedidos[0]
    assert r.method == "POST" and r.url.path == "/storage/v1/object/reuniones/r1/00002.ogg"
    assert r.headers["authorization"] == "Bearer llave" and r.headers["x-upsert"] == "true"
    assert r.content == b"OGG"


def test_url_firmada(monkeypatch):
    preparar(monkeypatch, lambda r: httpx.Response(200, json={"signedURL": "/object/sign/reuniones/r1/00001.ogg?token=t"}))
    assert al.url_firmada("r1", 1) == "https://ref.supabase.co/storage/v1/object/sign/reuniones/r1/00001.ogg?token=t"


def test_borrar_todo_el_audio(monkeypatch):
    pedidos = preparar(monkeypatch, lambda r: httpx.Response(200, json=[]))
    al.borrar("r1", [1, 2])
    assert pedidos[0].method == "DELETE" and pedidos[0].url.path == "/storage/v1/object/reuniones"
    assert json.loads(pedidos[0].content) == {"prefixes": ["r1/00001.ogg", "r1/00002.ogg"]}


def test_subir_webm(monkeypatch):
    pedidos = preparar(monkeypatch, lambda r: httpx.Response(200, json={"Key": "x"}))
    al.subir("r1", 3, b"WEBM", "webm")
    assert pedidos[0].url.path == "/storage/v1/object/reuniones/r1/00003.webm"
    assert pedidos[0].headers["content-type"] == "audio/webm"


def test_borrar_con_formatos(monkeypatch):
    pedidos = preparar(monkeypatch, lambda r: httpx.Response(200, json=[]))
    al.borrar("r1", [1, 2], {2: "mp4"})
    assert json.loads(pedidos[0].content) == {"prefixes": ["r1/00001.ogg", "r1/00002.mp4"]}
