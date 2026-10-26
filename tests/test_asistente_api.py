import pytest
from fastapi.testclient import TestClient

from backend import asistente, cuentas
from backend.main import app

JPG = b"\xff\xd8\xff\xe0" + b"0" * 100


@pytest.fixture
def admin(monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setenv("JARVIS_CLAVE_SECRETA", "clave-de-pruebas-larga")
    monkeypatch.setenv("JARVIS_NOMBRE", "Nebo")
    cliente = TestClient(app)
    cliente.post("/acceso", data={"clave": "la-del-admin"}, follow_redirects=False)
    return cliente


def _org_con_persona():
    usuario = cuentas.crear_organizacion("JH", "Ana", "ana@jh.com", "una-clave-larga")
    return usuario.organizacion_id


def test_el_admin_cambia_el_nombre(admin):
    org = _org_con_persona()
    r = admin.put(f"/api/asistente/{org}", json={"nombre": "Sofía"})
    assert r.status_code == 200
    assert admin.get(f"/api/asistente/{org}").json()["nombre"] == "Sofía"


def test_una_organizacion_que_no_existe_da_404(admin):
    assert admin.get("/api/asistente/no-existe").status_code == 404


def test_el_admin_sube_la_foto(admin):
    org = _org_con_persona()
    r = admin.post(f"/api/asistente/{org}/foto", files={"foto": ("cara.jpg", JPG, "image/jpeg")})
    assert r.status_code == 200 and r.json()["foto"].startswith("foto-")


def test_una_foto_mala_es_400(admin):
    org = _org_con_persona()
    r = admin.post(f"/api/asistente/{org}/foto", files={"foto": ("x.gif", b"GIF89a", "image/gif")})
    assert r.status_code == 400 and "JPG" in r.json()["error"]


def test_quien_no_es_admin_no_entra(monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setenv("JARVIS_CLAVE_SECRETA", "clave-de-pruebas-larga")
    org = _org_con_persona()
    cliente = TestClient(app)
    cliente.post("/acceso/cuenta", data={"email": "ana@jh.com", "password": "una-clave-larga"},
                 follow_redirects=False)
    assert cliente.get(f"/api/asistente/{org}").status_code == 403
    assert cliente.put(f"/api/asistente/{org}", json={"nombre": "X"}).status_code == 403


def test_el_estado_trae_el_asistente_de_la_organizacion(monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setenv("JARVIS_CLAVE_SECRETA", "clave-de-pruebas-larga")
    monkeypatch.setenv("JARVIS_NOMBRE", "Nebo")
    org = _org_con_persona()
    asistente.guardar_nombre(org, "Sofía")
    archivo = asistente.guardar_foto(org, JPG)
    cliente = TestClient(app)
    cliente.post("/acceso/cuenta", data={"email": "ana@jh.com", "password": "una-clave-larga"},
                 follow_redirects=False)
    estado = cliente.get("/api/estado").json()
    assert estado["nombre"] == "Sofía"
    assert estado["asistente"]["foto"] == f"/avatares/{org}/{archivo}"
    assert estado["asistente"]["videos"] == {"reposo": None, "escuchando": None, "hablando": None}
    # Su foto la puede ver; la de otra organizacion no.
    assert cliente.get(f"/avatares/{org}/{archivo}").content == JPG
    otra = cuentas.crear_organizacion("Otra", "Beto", "beto@otra.com", "otra-clave-larga").organizacion_id
    otro_archivo = asistente.guardar_foto(otra, JPG)
    assert cliente.get(f"/avatares/{otra}/{otro_archivo}").status_code == 404


def test_avatares_no_deja_salir_de_la_carpeta(admin):
    org = _org_con_persona()
    assert admin.get(f"/avatares/{org}/..%2F..%2Fjarvis.db").status_code == 404


def test_generar_sin_clave_de_higgsfield_es_400(admin, monkeypatch):
    monkeypatch.delenv("HIGGSFIELD_API_KEY_ID", raising=False)
    org = _org_con_persona()
    admin.post(f"/api/asistente/{org}/foto", files={"foto": ("cara.jpg", JPG, "image/jpeg")})
    r = admin.post(f"/api/asistente/{org}/generar", json={"estados": ["reposo"]})
    assert r.status_code == 400 and "Higgsfield" in r.json()["error"]
