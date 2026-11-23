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


class _Transcripciones:
    def __init__(self, vistos, falla=False):
        self.vistos, self.falla = vistos, falla

    def create(self, **kw):
        if self.falla:
            raise RuntimeError("cuota")
        self.vistos.append(kw)
        uso = type("U", (), {"model_dump": lambda s: {"input_tokens": 50, "output_tokens": 6}})()
        return type("R", (), {"text": " Hola Jarvis ", "usage": uso})()


def _cliente_falso(vistos, falla=False):
    audio = type("A", (), {"transcriptions": _Transcripciones(vistos, falla)})()
    return type("C", (), {"audio": audio})()


def test_dictado_pasa_el_audio_a_texto(con_panel, monkeypatch):
    from backend import consumo
    vistos, anotados = [], []
    monkeypatch.setattr(cerebro, "cliente", lambda: _cliente_falso(vistos))
    monkeypatch.setattr(consumo, "registrar", lambda *a, **k: anotados.append((a, k)))
    r = con_panel.post("/api/dictado", headers={"Authorization": "Bearer ana.jwt.firma"},
                       files={"audio": ("dictado.webm", b"\x1a\x45audio", "audio/webm")})
    assert r.status_code == 200 and r.json() == {"texto": "Hola Jarvis"}
    assert vistos[0]["language"] == "es" and vistos[0]["file"][1] == b"\x1a\x45audio"
    assert anotados[0][0][0] == "transcripcion" and anotados[0][1]["dispositivo"] == "panel"


def test_dictado_pide_sesion_y_avisa_si_falla(con_panel, monkeypatch):
    sin = con_panel.post("/api/dictado", files={"audio": ("d.webm", b"x", "audio/webm")})
    assert sin.status_code == 401
    monkeypatch.setattr(cerebro, "cliente", lambda: _cliente_falso([], falla=True))
    r = con_panel.post("/api/dictado", headers={"Authorization": "Bearer ana.jwt.firma"},
                       files={"audio": ("d.webm", b"x", "audio/webm")})
    assert r.status_code == 502 and "transcribir" in r.json()["error"]


def test_voz_en_vivo_lleva_las_instrucciones_del_panel(con_panel, monkeypatch):
    vistos = {}

    def negociar(oferta, usuario, extra=""):
        vistos.update(oferta=oferta, usuario=usuario.nombre, extra=extra)
        return "v=0 respuesta"

    monkeypatch.setattr(cerebro, "negociar_webrtc", negociar)
    r = con_panel.post("/api/voz/sdp?panel=cobranzas&contexto=cliente%201234%20abierto",
                       content="v=0 oferta", headers={"Authorization": "Bearer ana.jwt.firma",
                                                      "X-Jarvis-Panel": "cobranzas"})
    assert r.status_code == 200 and r.text == "v=0 respuesta"
    assert vistos["usuario"] == "Ana" and "consultar_panel" in vistos["extra"]
    assert "cliente 1234 abierto" in vistos["extra"]
    assert paneles_jh.activo("sb-ana")["panel"] == "cobranzas"


def test_voz_sin_panel_no_agrega_nada_y_sin_sesion_no_entra(con_panel, monkeypatch):
    vistos = {}
    monkeypatch.setattr(cerebro, "negociar_webrtc", lambda o, u, extra="": vistos.setdefault("extra", extra) or "v=0")
    con_panel.post("/api/voz/sdp?panel=inventado", content="v=0", headers={"Authorization": "Bearer ana.jwt.firma"})
    assert vistos["extra"] == ""
    assert con_panel.post("/api/voz/sdp?panel=cobranzas", content="v=0").status_code == 401


def test_las_herramientas_de_la_voz_llegan_al_panel(con_panel, monkeypatch):
    """En la voz las herramientas llegan sueltas a /api/herramienta: la cabecera del panel
    activa el panel con el token vigente y el gasto se anota a ese panel."""
    vistos = []

    def ejecutar(nombre, argumentos, usuario_id, quien=None, dispositivo="navegador"):
        vistos.append((nombre, dispositivo, (paneles_jh.activo(usuario_id) or {}).get("token")))
        return "ok", []

    monkeypatch.setattr(herramientas, "ejecutar_completo", ejecutar)
    r = con_panel.post("/api/herramienta", json={"nombre": "consultar_panel", "argumentos": "{}"},
                       headers={"Authorization": "Bearer ana.jwt.firma", "X-Jarvis-Panel": "conversaciones"})
    assert r.status_code == 200
    assert vistos == [("consultar_panel", "panel-conversaciones", "ana.jwt.firma")]


def test_cors_y_voz_js_para_el_widget(con_panel):
    r = con_panel.options("/api/voz/sdp", headers={"Origin": PORTAL, "Access-Control-Request-Method": "POST",
                                                    "Access-Control-Request-Headers": "authorization,x-jarvis-panel"})
    assert r.status_code == 200 and "x-jarvis-panel" in r.headers["access-control-allow-headers"].lower()
    js = con_panel.get("/voz.js", headers={"Origin": PORTAL})
    assert js.status_code == 200 and "crearSesionDeVoz" in js.text
    assert js.headers.get("access-control-allow-origin") == PORTAL
