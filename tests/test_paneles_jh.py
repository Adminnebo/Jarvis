"""Jarvis dentro de los paneles de JH: sesion de Supabase por encabezado, CORS,
widget, contexto del panel y la herramienta consultar_panel."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import acceso, cerebro, herramientas, paneles_jh, supabase_sesion
from backend.main import app

PORTAL = "https://portaljh.neboaiconsulting.com"


@pytest.fixture
def con_panel(monkeypatch):
    """Un token de panel valido ('tok-ana') para Ana, usuaria con jarvis.usar."""
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setenv("JARVIS_CLAVE_SECRETA", "clave-de-pruebas-larga")
    ana = acceso.Usuario("sb-ana", "Ana", "usuario")
    monkeypatch.setattr(supabase_sesion, "entrar", lambda t: ana if t == "ana.jwt.firma" else None)
    monkeypatch.setattr(supabase_sesion, "revalidar", lambda u: u)
    paneles_jh._activos.clear()
    return TestClient(app)


def test_entra_con_el_token_del_panel(con_panel):
    r = con_panel.get("/api/estado", headers={"Authorization": "Bearer ana.jwt.firma"})
    assert r.status_code == 200 and r.json()["usuario"] == "Ana"
    assert con_panel.get("/api/estado", headers={"Authorization": "Bearer otro.jwt.firma"}).status_code == 401


def test_cors_solo_para_el_portal(con_panel):
    ok = con_panel.options("/api/chat", headers={"Origin": PORTAL, "Access-Control-Request-Method": "POST",
                                                 "Access-Control-Request-Headers": "authorization,content-type"})
    assert ok.status_code == 200 and ok.headers["access-control-allow-origin"] == PORTAL
    ajeno = con_panel.options("/api/chat", headers={"Origin": "https://malo.com", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in ajeno.headers


def test_el_widget_se_sirve_sin_sesion(con_panel):
    r = con_panel.get("/jarvis-widget.js")
    assert r.status_code == 200 and "JarvisWidget" in r.text


def test_el_chat_desde_un_panel_lleva_su_catalogo(con_panel, monkeypatch):
    vistos = []

    def responder(mensajes, usuario, extra, dispositivo):
        vistos.append((usuario.id, extra, dispositivo))
        yield {"tipo": "texto", "dato": "ok"}

    monkeypatch.setattr(cerebro, "responder", responder)
    con_panel.post("/api/chat", headers={"Authorization": "Bearer ana.jwt.firma"},
                   json={"mensaje": "¿quién debe más?", "panel": "cobranzas", "contexto": "Cliente 1234 abierto"})
    ((usuario_id, extra, dispositivo),) = vistos
    assert usuario_id == "sb-ana" and dispositivo == "panel-cobranzas"
    assert "Cobranzas" in extra and "consultar_panel" in extra and "cartera" in extra and "Cliente 1234" in extra
    assert paneles_jh.activo("sb-ana") == {"panel": "cobranzas", "token": "ana.jwt.firma"}


def test_un_panel_desconocido_no_se_activa(con_panel, monkeypatch):
    monkeypatch.setattr(cerebro, "responder", lambda m, u, e, d: iter([]))
    con_panel.post("/api/chat", headers={"Authorization": "Bearer ana.jwt.firma"}, json={"mensaje": "x", "panel": "otro"})
    assert paneles_jh.activo("sb-ana") is None


# --- la herramienta ---

@pytest.fixture
def portal(monkeypatch):
    pedidos = []
    respuestas = {}

    def manejar(pedido: httpx.Request):
        pedidos.append(pedido)
        status, cuerpo = respuestas.get(pedido.url.path, (404, {"error": "no existe"}))
        return httpx.Response(status, json=cuerpo)

    monkeypatch.setattr(paneles_jh, "_http", lambda: httpx.Client(transport=httpx.MockTransport(manejar)))
    paneles_jh._activos.clear()
    return pedidos, respuestas


def test_consulta_con_el_token_de_la_persona(portal):
    pedidos, respuestas = portal
    respuestas["/cobranzas/api/jarvis/clientes/1234"] = (200, {"cliente": {"nombre": "Ferretería X", "deuda": 5000}})
    paneles_jh.activar("u1", "cobranzas", "tok")
    texto = paneles_jh.consultar("u1", "cliente", json.dumps({"codigo": "1234"}))
    assert "Ferretería X" in texto and "dato" in texto.lower()
    assert str(pedidos[0].url) == f"{PORTAL}/cobranzas/api/jarvis/clientes/1234"
    assert pedidos[0].headers["authorization"] == "Bearer tok"


def test_parametros_de_busqueda_y_solo_los_permitidos(portal):
    pedidos, respuestas = portal
    respuestas["/api/jarvis/conversaciones"] = (200, {"conversaciones": []})
    paneles_jh.activar("u1", "conversaciones", "tok")
    paneles_jh.consultar("u1", "conversaciones", json.dumps({"q": "pedro", "sin_responder": True, "otra": "x"}))
    params = pedidos[0].url.params
    assert params["q"] == "pedro" and params["sin_responder"] == "1" and "otra" not in params


def test_permiso_negado_por_el_panel(portal):
    _, respuestas = portal
    respuestas["/cobranzas/api/jarvis/promesas"] = (403, {"error": "Sin permiso"})
    paneles_jh.activar("u1", "cobranzas", "tok")
    assert "permiso" in paneles_jh.consultar("u1", "promesas", "{}").lower()


def test_consulta_de_otro_panel_o_sin_panel(portal):
    paneles_jh.activar("u1", "cobranzas", "tok")
    assert "no existe" in paneles_jh.consultar("u1", "embudo", "{}").lower()
    assert "panel" in paneles_jh.consultar("u2", "cartera", "{}").lower()


def test_un_codigo_no_puede_cambiar_la_ruta(portal):
    pedidos, respuestas = portal
    paneles_jh.activar("u1", "cobranzas", "tok")
    paneles_jh.consultar("u1", "cliente", json.dumps({"codigo": "../../admin"}))
    assert pedidos and "/admin" not in pedidos[0].url.path.replace("%2F", "/").split("/clientes/")[0]
    assert pedidos[0].url.path.startswith("/cobranzas/api/jarvis/clientes/")


def test_respuesta_larga_se_recorta(portal):
    _, respuestas = portal
    respuestas["/reactivacion/api/jarvis/resumen"] = (200, {"x": "a" * 50000})
    paneles_jh.activar("u1", "reactivacion", "tok")
    assert len(paneles_jh.consultar("u1", "resumen", "{}")) < 10000


def test_la_herramienta_esta(monkeypatch):
    nombres = {e["name"] for e in herramientas.esquemas()}
    assert "consultar_panel" in nombres
