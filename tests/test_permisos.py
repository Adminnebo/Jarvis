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


def test_la_pagina_de_entrada_es_libre(cliente):
    # Se pide sin sesion: es justo la que la crea.
    assert cliente.get("/entrar").status_code == 200


def test_entrar_con_un_token_bueno_deja_cookie(cliente, monkeypatch):
    from backend import acceso, supabase_sesion

    monkeypatch.setattr(supabase_sesion, "entrar",
                        lambda t: acceso.Usuario("sb-abc", "Ana", "usuario"))
    cliente.cookies.clear()
    respuesta = cliente.post("/acceso/supabase", json={"token": "loquesea"})
    assert respuesta.status_code == 200
    assert acceso.COOKIE in respuesta.cookies


def test_entrar_sin_permiso_da_403(cliente, monkeypatch):
    from backend import supabase_sesion

    monkeypatch.setattr(supabase_sesion, "entrar", lambda t: None)
    cliente.cookies.clear()
    assert cliente.post("/acceso/supabase", json={"token": "x"}).status_code == 403


def test_la_sesion_del_panel_sirve_para_la_api(cliente, monkeypatch):
    from backend import acceso, supabase_sesion

    ana = acceso.Usuario("sb-abc", "Ana", "usuario")
    monkeypatch.setattr(supabase_sesion, "entrar", lambda t: ana)
    monkeypatch.setattr(supabase_sesion, "revalidar", lambda u: ana)

    cliente.cookies.clear()
    cliente.post("/acceso/supabase", json={"token": "loquesea"})

    estado = cliente.get("/api/estado").json()
    assert estado["usuario"] == "Ana"
    assert estado["rol"] == "usuario"
    # Sin jarvis.admin no toca la configuracion.
    assert cliente.get("/api/fuentes").status_code == 403


def test_si_le_quitan_el_permiso_queda_fuera(cliente, monkeypatch):
    from backend import acceso, supabase_sesion

    ana = acceso.Usuario("sb-abc", "Ana", "usuario")
    monkeypatch.setattr(supabase_sesion, "entrar", lambda t: ana)
    monkeypatch.setattr(supabase_sesion, "revalidar", lambda u: ana)
    cliente.cookies.clear()
    cliente.post("/acceso/supabase", json={"token": "loquesea"})
    assert cliente.get("/api/estado").status_code == 200

    # El super admin le quita la casilla.
    monkeypatch.setattr(supabase_sesion, "revalidar", lambda u: None)
    assert cliente.get("/api/estado").status_code == 401


def test_los_de_contrasena_no_pasan_por_supabase(cliente, monkeypatch):
    from backend import supabase_sesion

    def no_deberia(_):
        raise AssertionError("no se revalida a quien entro por contrasena")

    _entrar(cliente, "la-del-admin")
    monkeypatch.setattr(supabase_sesion, "perfil_cacheado", no_deberia)
    assert cliente.get("/api/estado").status_code == 200
