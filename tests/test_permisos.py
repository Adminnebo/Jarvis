import pytest
from fastapi.testclient import TestClient

# Se importa arriba del todo a proposito: backend.main llama a
# load_dotenv(override=True) al importarse (main.py:23). Si esa importacion
# ocurriera dentro de la prueba, el .env real de la maquina pisaria las
# contrasenas de prueba y los resultados dependerian de quien las corre.
from backend.main import app


@pytest.fixture
def cliente(entorno_limpio, monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setenv("JARVIS_PASSWORD_JORGE", "la-de-jorge")
    monkeypatch.setenv("JARVIS_CLAVE_SECRETA", "clave-de-pruebas-larga")
    return TestClient(app)


def _entrar(cliente, contrasena):
    """Deja la sesion abierta como esa persona.

    TestClient guarda las cookies entre peticiones, asi que despues de esto
    basta con llamar a cliente.get(...) sin pasar nada mas.
    """
    cliente.cookies.clear()
    respuesta = cliente.post(
        "/acceso", data={"clave": contrasena}, follow_redirects=False
    )
    assert respuesta.status_code == 303


def test_sin_cookie_la_api_responde_401(cliente):
    assert cliente.get("/api/estado").status_code == 401


def test_una_contrasena_mala_no_entra(cliente):
    respuesta = cliente.post(
        "/acceso", data={"clave": "no-es"}, follow_redirects=False
    )
    assert respuesta.status_code == 401


def test_el_admin_puede_con_las_fuentes(cliente):
    _entrar(cliente, "la-del-admin")
    assert cliente.get("/api/fuentes").status_code == 200


def test_un_usuario_normal_no_puede_con_las_fuentes(cliente):
    _entrar(cliente, "la-de-jorge")
    assert cliente.get("/api/fuentes").status_code == 403
    assert cliente.get("/api/consumo").status_code == 403


def test_un_usuario_normal_si_puede_conversar_y_anotar_voz(cliente):
    _entrar(cliente, "la-de-jorge")
    assert cliente.get("/api/estado").status_code == 200
    assert cliente.get("/api/memoria").status_code == 200
    assert cliente.post("/api/consumo/voz", json={"uso": {}}).status_code == 200


def test_cada_uno_ve_su_propio_estado(cliente):
    _entrar(cliente, "la-de-jorge")
    de_jorge = cliente.get("/api/estado").json()

    _entrar(cliente, "la-del-admin")
    del_admin = cliente.get("/api/estado").json()

    assert de_jorge["usuario"] == "Jorge"
    assert de_jorge["rol"] == "usuario"
    assert del_admin["rol"] == "admin"
