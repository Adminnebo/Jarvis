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
    (app_,) = admin.get("/api/integraciones").json()["apps"]
    assert app_["app"] == "gmail" and app_["estado"] == "sin_conectar"


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
