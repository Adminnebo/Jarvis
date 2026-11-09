# tests/test_integraciones_api.py
import pytest
from fastapi.testclient import TestClient

from backend import avisos, gmail, integraciones
from backend.main import app


@pytest.fixture
def admin(monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setenv("JARVIS_CLAVE_SECRETA", "clave-de-pruebas-larga")
    monkeypatch.setenv("GOOGLE_JARVIS_CLIENT_ID", "id")
    monkeypatch.setenv("GOOGLE_JARVIS_CLIENT_SECRET", "secreto")
    cliente = TestClient(app)
    cliente.post("/acceso", data={"clave": "la-del-admin"}, follow_redirects=False)
    return cliente


def test_catalogo(admin):
    apps = {a["app"]: a for a in admin.get("/api/integraciones").json()["apps"]}
    assert apps["gmail"]["estado"] == "sin_conectar" and "whatsapp" in apps


def test_conectar_redirige_a_google_con_el_estado_del_usuario(admin):
    r = admin.get("/integraciones/gmail/conectar", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"].startswith("https://accounts.google.com/")


def test_callback_sin_sesion_pero_con_estado_conecta(admin, monkeypatch):
    estado = gmail.crear_estado("admin")
    monkeypatch.setattr(integraciones, "conectar_gmail", lambda u, c: "ana@gmail.com" if u == "admin" else None)
    r = TestClient(app).get(f"/integraciones/gmail/callback?code=abc&state={estado}", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "/?integraciones=gmail"


def test_callback_con_estado_falso_es_400():
    r = TestClient(app).get("/integraciones/gmail/callback?code=abc&state=falso", follow_redirects=False)
    assert r.status_code == 400


def test_callback_con_error_de_google_lo_explica(admin):
    estado = gmail.crear_estado("admin")
    r = TestClient(app).get(f"/integraciones/gmail/callback?error=access_denied&state={estado}")
    assert r.status_code == 400 and "no se conecto" in r.text.lower()


def test_reglas_ida_y_vuelta_y_numero_malo(admin):
    r = admin.put("/api/integraciones/gmail/reglas", json={"reglas": "pagos", "whatsapp": "8095551234", "activo": True})
    assert r.json()["whatsapp"] == "18095551234"
    assert admin.get("/api/integraciones/gmail/reglas").json()["reglas"] == "pagos"
    assert admin.put("/api/integraciones/gmail/reglas", json={"reglas": "", "whatsapp": "12", "activo": True}).status_code == 400


def test_desconectar_revoca(admin, monkeypatch):
    revocados = []
    monkeypatch.setattr(gmail, "revocar", revocados.append)
    integraciones.guardar_gmail("admin", "ana@gmail.com", "r1", "1")
    assert admin.delete("/api/integraciones/gmail").json() == {"ok": True}
    assert revocados == ["r1"]


def test_avisos_solo_los_propios(admin):
    avisos.crear("admin", "m1", "h1", "Carlos", "A", "pide precio", con_whatsapp=False)
    avisos.crear("otro", "m2", "h2", "X", "B", "secreto", con_whatsapp=False)
    assert admin.get("/api/avisos/contador").json() == {"no_vistos": 1}
    (aviso,) = admin.get("/api/avisos?solo_no_vistos=1").json()["avisos"]
    assert aviso["resumen"] == "pide precio"
    otro = avisos.listar("otro")[0]["id"]
    assert admin.post(f"/api/avisos/{otro}/visto").status_code == 404
    assert admin.post(f"/api/avisos/{aviso['id']}/visto").json() == {"ok": True}


import hashlib
import hmac
import json

from backend import whatsapp_chats, zernio


@pytest.fixture
def con_zernio(admin, monkeypatch):
    monkeypatch.setenv("ZERNIO_API_KEY", "z")
    monkeypatch.setenv("ZERNIO_WEBHOOK_SECRET", "secreto-w")
    monkeypatch.setattr(zernio, "asegurar_webhook", lambda url: "w1")
    monkeypatch.setattr(zernio, "perfil_de", lambda u, n: "p1")
    monkeypatch.setattr(zernio, "url_conexion", lambda perfil, retorno: f"https://meta/x?perfil={perfil}&r={retorno}")
    return admin


def test_conectar_whatsapp_lleva_a_zernio(con_zernio):
    r = con_zernio.get("/integraciones/whatsapp/conectar", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert r.headers["location"].startswith("https://meta/x?perfil=p1")
    assert "estado=" in r.headers["location"]


def test_conectar_whatsapp_sin_zernio_es_503(admin, monkeypatch):
    monkeypatch.delenv("ZERNIO_API_KEY", raising=False)
    assert admin.get("/integraciones/whatsapp/conectar", follow_redirects=False).status_code == 503


def test_callback_whatsapp_guarda_la_cuenta(con_zernio):
    integraciones.iniciar_whatsapp("admin", "Admin")
    estado = gmail.crear_estado("admin")
    r = TestClient(app).get(
        f"/integraciones/whatsapp/callback?estado={estado}&connected=whatsapp&profileId=p1"
        "&accountId=acc-1&username=%2B18095551234", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "/?integraciones=whatsapp"
    assert integraciones.usuario_de_cuenta("acc-1") == "admin"


def test_callback_whatsapp_con_otro_perfil_no_guarda(con_zernio):
    integraciones.iniciar_whatsapp("admin", "Admin")
    estado = gmail.crear_estado("admin")
    r = TestClient(app).get(f"/integraciones/whatsapp/callback?estado={estado}&connected=whatsapp"
                            "&profileId=p-ajeno&accountId=acc-1")
    assert r.status_code == 400 and integraciones.usuario_de_cuenta("acc-1") is None


def test_callback_whatsapp_con_error_lo_explica(con_zernio):
    estado = gmail.crear_estado("admin")
    r = TestClient(app).get(f"/integraciones/whatsapp/callback?estado={estado}"
                            "&error=whatsapp_number_already_connected&platform=whatsapp")
    assert r.status_code == 400 and "ya esta conectado" in r.text


def test_desconectar_whatsapp(con_zernio, monkeypatch):
    integraciones.iniciar_whatsapp("admin", "Admin")
    integraciones.guardar_whatsapp("admin", "acc-1", "x")
    borradas = []
    monkeypatch.setattr(zernio, "desconectar_cuenta", borradas.append)
    assert con_zernio.delete("/api/integraciones/whatsapp").json() == {"ok": True}
    assert borradas == ["acc-1"]


def _firmado(cuerpo: dict):
    datos = json.dumps(cuerpo).encode()
    return datos, {"x-zernio-signature": hmac.new(b"secreto-w", datos, hashlib.sha256).hexdigest(),
                   "content-type": "application/json"}


def test_webhook_firmado_se_procesa_una_vez(con_zernio, monkeypatch):
    recibidos = []
    monkeypatch.setattr(whatsapp_chats, "recibir", lambda ev: recibidos.append(ev["id"]) or "ok")
    datos, cabeceras = _firmado({"id": "ev-1", "event": "message.received"})
    sin_sesion = TestClient(app)
    assert sin_sesion.post("/integraciones/whatsapp/webhook", content=datos, headers=cabeceras).status_code == 200
    r = sin_sesion.post("/integraciones/whatsapp/webhook", content=datos, headers=cabeceras)
    assert r.json().get("repetido") and recibidos == ["ev-1"]


def test_webhook_sin_firma_es_401(con_zernio):
    r = TestClient(app).post("/integraciones/whatsapp/webhook", content=b'{"id":"x"}',
                             headers={"x-zernio-signature": "mala"})
    assert r.status_code == 401


def test_webhook_que_falla_se_puede_reintentar(con_zernio, monkeypatch):
    def falla(ev):
        raise RuntimeError("base caida")

    monkeypatch.setattr(whatsapp_chats, "recibir", falla)
    datos, cabeceras = _firmado({"id": "ev-2", "event": "message.received"})
    assert TestClient(app).post("/integraciones/whatsapp/webhook", content=datos, headers=cabeceras).status_code == 500
    assert not whatsapp_chats.ya_procesado("ev-2")   # la marca se borro


def test_reglas_por_la_ruta_nueva(admin):
    r = admin.put("/api/avisos/reglas", json={"reglas": "pagos", "whatsapp": "", "activo": True})
    assert r.json()["reglas"] == "pagos"
    assert admin.get("/api/avisos/reglas").json()["reglas"] == "pagos"
