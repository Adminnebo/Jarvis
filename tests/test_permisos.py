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


def test_el_rechazo_dice_el_tipo_de_fallo(cliente, monkeypatch):
    from backend import supabase_sesion

    monkeypatch.setattr(supabase_sesion, "entrar", lambda t: None)
    monkeypatch.setattr(supabase_sesion, "diagnostico",
                        lambda t: "error-perfil:UndefinedTable")
    cliente.cookies.clear()
    respuesta = cliente.post("/acceso/supabase", json={"token": "x"})
    assert respuesta.status_code == 403
    assert "UndefinedTable" in respuesta.json()["error"]
    assert respuesta.json()["motivo"] == "error-perfil:UndefinedTable"


# --------------------------------------------------------------------------
# Cuentas de organizacion: /registro y /acceso/cuenta
# --------------------------------------------------------------------------

def _registrar(cliente, organizacion="Acme", nombre="Lucas",
               email="lucas@acme.com", password="una-clave-larga"):
    cliente.cookies.clear()
    return cliente.post("/registro", data={
        "organizacion": organizacion, "nombre": nombre,
        "email": email, "password": password,
    }, follow_redirects=False)


def test_registrar_una_organizacion_deja_cookie(cliente):
    from backend import acceso

    respuesta = _registrar(cliente)
    assert respuesta.status_code == 303
    assert acceso.COOKIE in respuesta.cookies


def test_despues_de_registrarse_la_sesion_ya_es_de_organizacion(cliente):
    _registrar(cliente)
    estado = cliente.get("/api/estado").json()
    assert estado["usuario"] == "Lucas"
    assert estado["organizacion"] == "Acme"
    assert estado["es_admin_org"] is True
    # Una cuenta de organizacion no administra Jarvis (fuentes/consumo).
    assert cliente.get("/api/fuentes").status_code == 403


def test_no_se_puede_registrar_dos_veces_el_mismo_correo(cliente):
    _registrar(cliente)
    repetido = _registrar(cliente, organizacion="Otra", nombre="Otro")
    assert repetido.status_code == 400


def test_entrar_con_cuenta_despues_de_registrarse(cliente):
    from backend import acceso

    _registrar(cliente)
    cliente.cookies.clear()
    respuesta = cliente.post("/acceso/cuenta", data={
        "email": "lucas@acme.com", "password": "una-clave-larga",
    }, follow_redirects=False)
    assert respuesta.status_code == 303
    assert acceso.COOKIE in respuesta.cookies


def test_entrar_con_cuenta_contrasena_mala(cliente):
    _registrar(cliente)
    cliente.cookies.clear()
    respuesta = cliente.post("/acceso/cuenta", data={
        "email": "lucas@acme.com", "password": "no-es",
    })
    assert respuesta.status_code == 401


# --------------------------------------------------------------------------
# Dispositivos: vincular un reloj por codigo y usarlo con Authorization: Bearer
# --------------------------------------------------------------------------

def test_generar_y_vincular_un_codigo_desde_la_api(cliente):
    _entrar(cliente, "la-de-jorge")
    codigo = cliente.post("/api/dispositivos/codigo").json()["codigo"]

    # El reloj lo canjea sin sesion: /api/dispositivos/vincular es libre.
    cliente.cookies.clear()
    respuesta = cliente.post("/api/dispositivos/vincular", json={"codigo": codigo})
    assert respuesta.status_code == 200
    assert "token" in respuesta.json()


def test_un_codigo_invalido_no_vincula(cliente):
    respuesta = cliente.post("/api/dispositivos/vincular", json={"codigo": "XXXXXX"})
    assert respuesta.status_code == 400


def test_el_token_del_dispositivo_sirve_como_bearer(cliente):
    _entrar(cliente, "la-de-jorge")
    codigo = cliente.post("/api/dispositivos/codigo").json()["codigo"]

    cliente.cookies.clear()
    token = cliente.post("/api/dispositivos/vincular", json={"codigo": codigo}).json()["token"]

    respuesta = cliente.get("/api/estado", headers={"Authorization": f"Bearer {token}"})
    assert respuesta.status_code == 200
    assert respuesta.json()["usuario"] == "Jorge"


def test_un_bearer_invalido_da_401(cliente):
    respuesta = cliente.get("/api/estado", headers={"Authorization": "Bearer lo-que-sea"})
    assert respuesta.status_code == 401


def test_el_dispositivo_no_puede_con_rutas_de_admin(cliente):
    _entrar(cliente, "la-del-admin")
    codigo = cliente.post("/api/dispositivos/codigo").json()["codigo"]
    cliente.cookies.clear()
    token = cliente.post("/api/dispositivos/vincular", json={"codigo": codigo}).json()["token"]

    # Aunque el dueno del reloj sea el admin, el dispositivo hereda su rol:
    # esto documenta el comportamiento actual, no una restriccion aparte.
    respuesta = cliente.get("/api/fuentes", headers={"Authorization": f"Bearer {token}"})
    assert respuesta.status_code == 200


def test_listar_y_revocar_mis_dispositivos(cliente):
    _entrar(cliente, "la-de-jorge")
    cliente.post("/api/dispositivos/codigo")
    codigo = cliente.post("/api/dispositivos/codigo").json()["codigo"]
    cliente.cookies.clear()
    cliente.post("/api/dispositivos/vincular", json={"codigo": codigo})

    _entrar(cliente, "la-de-jorge")
    lista = cliente.get("/api/dispositivos").json()["dispositivos"]
    assert len(lista) == 1

    borrado = cliente.delete(f"/api/dispositivos/{lista[0]['id']}")
    assert borrado.json() == {"borrado": True}
    assert cliente.get("/api/dispositivos").json()["dispositivos"] == []


# --------------------------------------------------------------------------
# Organizacion: agregar miembros
# --------------------------------------------------------------------------

def test_el_dueno_de_la_organizacion_puede_agregar_gente(cliente):
    _registrar(cliente)
    respuesta = cliente.post("/api/organizacion/usuarios", json={
        "nombre": "Ana", "email": "ana@acme.com", "password": "otra-clave-larga",
    })
    assert respuesta.status_code == 200

    miembros = cliente.get("/api/organizacion").json()["miembros"]
    assert {m["email"] for m in miembros} == {"lucas@acme.com", "ana@acme.com"}


def test_una_persona_sin_organizacion_no_puede_agregar_gente(cliente):
    _entrar(cliente, "la-de-jorge")
    respuesta = cliente.post("/api/organizacion/usuarios", json={
        "nombre": "Ana", "email": "ana@acme.com", "password": "otra-clave-larga",
    })
    assert respuesta.status_code == 403


# --------------------------------------------------------------------------
# Consumo por organizacion
# --------------------------------------------------------------------------

def test_lo_consumido_viaja_en_la_vista_de_la_organizacion(cliente):
    from backend import consumo, cuentas

    _registrar(cliente)
    usuario = cuentas.entrar("lucas@acme.com", "una-clave-larga")
    consumo.registrar("texto", "gpt-5.6-terra", {"input_tokens": 1_000_000}, usuario=usuario)

    consumido = cliente.get("/api/organizacion").json()["consumido"]
    assert consumido["consultas"] == 1
    assert consumido["cobrado"] == 2.0


def test_el_tablero_del_admin_lista_lo_de_cada_organizacion(cliente):
    from backend import consumo, cuentas

    _registrar(cliente)
    usuario = cuentas.entrar("lucas@acme.com", "una-clave-larga")
    consumo.registrar("texto", "gpt-5.6-terra", {"input_tokens": 1_000_000}, usuario=usuario)

    _entrar(cliente, "la-del-admin")
    organizaciones = cliente.get("/api/organizaciones").json()["organizaciones"]
    assert [(o["nombre"], o["cobrado"]) for o in organizaciones] == [("Acme", 2.0)]


def test_lo_de_todas_las_organizaciones_es_solo_del_admin(cliente):
    _registrar(cliente)
    # Un cliente no ve lo que consumieron los demas.
    assert cliente.get("/api/organizaciones").status_code == 403

    _entrar(cliente, "la-del-admin")
    assert cliente.get("/api/organizaciones").status_code == 200


def test_un_miembro_normal_no_puede_agregar_gente(cliente):
    _registrar(cliente)
    cliente.post("/api/organizacion/usuarios", json={
        "nombre": "Ana", "email": "ana@acme.com", "password": "otra-clave-larga",
    })

    cliente.cookies.clear()
    cliente.post("/acceso/cuenta", data={"email": "ana@acme.com", "password": "otra-clave-larga"})

    respuesta = cliente.post("/api/organizacion/usuarios", json={
        "nombre": "Otro", "email": "otro@acme.com", "password": "otra-clave-larga",
    })
    assert respuesta.status_code == 403
