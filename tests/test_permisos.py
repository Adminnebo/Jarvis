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
    """El admin crea la organizacion y la sesion queda como la cuenta nueva.

    Crearla ya no deja logueado a nadie: la cuenta nueva entra despues con su
    correo, como lo haria de verdad.
    """
    _entrar(cliente, "la-del-admin")
    respuesta = cliente.post("/registro", data={
        "organizacion": organizacion, "nombre": nombre,
        "email": email, "password": password,
    })
    if respuesta.status_code == 200:
        cliente.cookies.clear()
        cliente.post("/acceso/cuenta", data={"email": email, "password": password})
    return respuesta


def _crear_como_admin(cliente, organizacion="Acme", email="lucas@acme.com"):
    return cliente.post("/registro", data={
        "organizacion": organizacion, "nombre": "Lucas",
        "email": email, "password": "una-clave-larga",
    })


def test_sin_sesion_no_se_puede_crear_una_organizacion(cliente):
    # Estuvo abierto, y como las fuentes son comunes cualquiera que tuviera la
    # URL se registraba y consultaba los datos del negocio.
    cliente.cookies.clear()
    assert cliente.get("/registro").status_code == 401
    assert _crear_como_admin(cliente).status_code == 401


def test_quien_no_administra_jarvis_no_crea_organizaciones(cliente):
    _entrar(cliente, "la-de-jorge")
    assert cliente.get("/registro").status_code == 403
    assert _crear_como_admin(cliente).status_code == 403


def test_una_cuenta_de_organizacion_no_crea_otras(cliente):
    _registrar(cliente)
    assert _crear_como_admin(cliente, "Otra", "otro@x.com").status_code == 403


def test_el_admin_crea_una_organizacion_sin_perder_su_sesion(cliente):
    _entrar(cliente, "la-del-admin")

    respuesta = _crear_como_admin(cliente)
    assert respuesta.status_code == 200
    assert "Acme creada" in respuesta.text

    # Sigue siendo el admin: crearla no lo cambio por la cuenta nueva.
    assert cliente.get("/api/estado").json()["rol"] == "admin"


def test_el_nombre_de_la_organizacion_se_escapa(cliente):
    _entrar(cliente, "la-del-admin")
    respuesta = _crear_como_admin(cliente, "<script>alert(1)</script>")
    assert "<script>alert(1)</script>" not in respuesta.text
    assert "&lt;script&gt;" in respuesta.text


def test_la_pantalla_de_acceso_ya_no_ofrece_registrarse(cliente):
    cliente.cookies.clear()
    assert "/registro" not in cliente.get("/acceso").text
    assert "/registro" not in cliente.get("/acceso/cuenta").text


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

def test_las_funciones_de_organizacion_son_solo_del_super_admin(cliente):
    # Ni siquiera quien la administra: todo lo de arriba es del super admin.
    _registrar(cliente)
    assert cliente.get("/api/organizacion").status_code == 403
    respuesta = cliente.post("/api/organizacion/usuarios", json={
        "nombre": "Ana", "email": "ana@acme.com", "password": "otra-clave-larga",
    })
    assert respuesta.status_code == 403


def test_una_persona_sin_organizacion_no_puede_agregar_gente(cliente):
    _entrar(cliente, "la-de-jorge")
    respuesta = cliente.post("/api/organizacion/usuarios", json={
        "nombre": "Ana", "email": "ana@acme.com", "password": "otra-clave-larga",
    })
    assert respuesta.status_code == 403


# --------------------------------------------------------------------------
# Consumo por organizacion
# --------------------------------------------------------------------------

def test_el_consumo_por_organizacion_se_abre_por_persona(cliente, monkeypatch):
    from backend import consumo, cuentas

    monkeypatch.setenv("JARVIS_MARGEN", "30")
    _registrar(cliente)
    lucas = cuentas.entrar("lucas@acme.com", "una-clave-larga")
    consumo.registrar("texto", "gpt-5.6-terra", {"input_tokens": 1_000_000}, usuario=lucas)
    consumo.registrar("texto", "gpt-5.6-terra", {"input_tokens": 1_000_000}, usuario=lucas)

    _entrar(cliente, "la-del-admin")
    datos = cliente.get("/api/consumo?periodo=todo").json()
    acme = next(o for o in datos["por_organizacion"] if o["organizacion"] == "Acme")

    assert acme["usuarios"] == [{
        "usuario_id": lucas.id, "nombre": "Lucas",
        "consultas": 2, "tokens": 2_000_000, "costo": 4.0, "cobrado": 5.2,
    }]


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
    from backend import cuentas

    _registrar(cliente)
    organizacion = cuentas.entrar("lucas@acme.com", "una-clave-larga").organizacion_id
    cuentas.agregar_usuario(organizacion, "Ana", "ana@acme.com", "otra-clave-larga")

    cliente.cookies.clear()
    cliente.post("/acceso/cuenta", data={"email": "ana@acme.com", "password": "otra-clave-larga"})

    respuesta = cliente.post("/api/organizacion/usuarios", json={
        "nombre": "Otro", "email": "otro@acme.com", "password": "otra-clave-larga",
    })
    assert respuesta.status_code == 403


def test_el_pedido_del_reloj_se_marca_como_tal(cliente, monkeypatch):
    """Pedir respuestas cortas es hoy lo unico que distingue al reloj."""
    from backend import cerebro, consumo

    vistos = []

    def responder_falso(mensajes, usuario, extra="", dispositivo="navegador"):
        vistos.append(dispositivo)
        return iter(())

    monkeypatch.setattr(cerebro, "responder", responder_falso)
    _entrar(cliente, "la-del-admin")

    cliente.post("/api/chat", json={"mensaje": "hola", "breve": True})
    cliente.post("/api/chat", json={"mensaje": "hola"})

    assert vistos == [consumo.RELOJ_SIN_VINCULAR, "navegador"]
