import time

from backend import acceso, cuentas, dispositivos


def test_un_codigo_recien_generado_vincula():
    codigo_info = dispositivos.generar_codigo("jorge")
    assert len(codigo_info["codigo"]) == 6

    resultado = dispositivos.vincular(codigo_info["codigo"], "Mi reloj")
    assert resultado is not None

    usuario_id, token = resultado
    assert usuario_id == "jorge"
    assert token


def test_el_codigo_es_de_un_solo_uso():
    codigo_info = dispositivos.generar_codigo("jorge")
    assert dispositivos.vincular(codigo_info["codigo"]) is not None
    assert dispositivos.vincular(codigo_info["codigo"]) is None


def test_un_codigo_que_no_existe_no_vincula():
    assert dispositivos.vincular("XXXXXX") is None
    assert dispositivos.vincular("") is None


def test_un_codigo_vencido_no_vincula(monkeypatch):
    monkeypatch.setattr(dispositivos, "VIGENCIA_CODIGO", __import__("datetime").timedelta(seconds=0))
    codigo_info = dispositivos.generar_codigo("jorge")
    time.sleep(0.01)
    assert dispositivos.vincular(codigo_info["codigo"]) is None


def test_generar_un_codigo_nuevo_invalida_el_anterior():
    primero = dispositivos.generar_codigo("jorge")["codigo"]
    dispositivos.generar_codigo("jorge")
    assert dispositivos.vincular(primero) is None


def test_el_token_del_dispositivo_resuelve_al_dueno_por_variable(monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setenv("JARVIS_PASSWORD_JORGE", "la-de-jorge")

    codigo = dispositivos.generar_codigo("jorge")["codigo"]
    _, token = dispositivos.vincular(codigo)

    usuario = dispositivos.usuario_de_token(token)
    assert usuario is not None
    assert usuario.id == "jorge"
    assert usuario.nombre == "Jorge"


def test_el_token_del_dispositivo_resuelve_al_dueno_de_una_organizacion():
    org = cuentas.crear_organizacion("Acme", "Lucas", "lucas@acme.com", "una-clave-larga")

    codigo = dispositivos.generar_codigo(org.id)["codigo"]
    _, token = dispositivos.vincular(codigo)

    usuario = dispositivos.usuario_de_token(token)
    assert usuario is not None
    assert usuario.id == org.id
    assert usuario.organizacion_id == org.organizacion_id


def test_un_token_invalido_no_resuelve_a_nadie():
    assert dispositivos.usuario_de_token("lo-que-sea") is None
    assert dispositivos.usuario_de_token("") is None


def test_si_borran_la_cuenta_el_dispositivo_se_queda_sin_dueno(monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setenv("JARVIS_PASSWORD_JORGE", "la-de-jorge")

    codigo = dispositivos.generar_codigo("jorge")["codigo"]
    _, token = dispositivos.vincular(codigo)
    assert dispositivos.usuario_de_token(token) is not None

    monkeypatch.delenv("JARVIS_PASSWORD_JORGE")
    assert dispositivos.usuario_de_token(token) is None


def test_listar_y_revocar_dispositivos():
    codigo = dispositivos.generar_codigo("jorge")["codigo"]
    dispositivos.vincular(codigo, "Mi reloj")

    lista = dispositivos.dispositivos_de("jorge")
    assert len(lista) == 1
    assert lista[0]["nombre"] == "Mi reloj"

    assert dispositivos.revocar("jorge", lista[0]["id"]) is True
    assert dispositivos.dispositivos_de("jorge") == []


def test_no_se_puede_revocar_el_dispositivo_de_otro():
    codigo = dispositivos.generar_codigo("jorge")["codigo"]
    dispositivos.vincular(codigo)
    id_dispositivo = dispositivos.dispositivos_de("jorge")[0]["id"]

    assert dispositivos.revocar("admin", id_dispositivo) is False
    assert len(dispositivos.dispositivos_de("jorge")) == 1


def test_una_cuenta_normal_vincula_su_reloj_y_solo_ve_los_suyos(monkeypatch):
    """El reloj ya no es solo del super admin: cualquiera lo vincula desde Ajustes > Reloj."""
    from fastapi.testclient import TestClient

    from backend import acceso, supabase_sesion
    from backend.main import app

    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setenv("JARVIS_CLAVE_SECRETA", "clave-de-pruebas-larga")
    ana = acceso.Usuario("sb-ana-reloj", "Ana", "usuario")
    monkeypatch.setattr(supabase_sesion, "entrar", lambda t: ana if t == "ana.jwt.firma" else None)
    monkeypatch.setattr(supabase_sesion, "revalidar", lambda u: u)
    monkeypatch.setattr(dispositivos, "_usuario_para", lambda uid: ana if uid == ana.id else None)
    cliente = TestClient(app)
    ana_h = {"Authorization": "Bearer ana.jwt.firma"}

    dispositivos.generar_codigo("otro-usuario")
    dispositivos.vincular(dispositivos.generar_codigo("otro-usuario")["codigo"], "Reloj ajeno")

    r = cliente.post("/api/dispositivos/codigo", headers=ana_h)
    assert r.status_code == 200
    vinculo = dispositivos.vincular(r.json()["codigo"], "Reloj de Ana")
    assert vinculo is not None
    lista = cliente.get("/api/dispositivos", headers=ana_h).json()["dispositivos"]
    assert [d["nombre"] for d in lista] == ["Reloj de Ana"]
