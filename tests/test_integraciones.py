import pytest

from backend import basedatos, gmail, integraciones, secretos


def _tablas():
    with basedatos.conexion() as con:
        return {f["name"] for f in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_existen_las_tablas_de_integraciones():
    assert {"integraciones", "reglas_aviso", "avisos", "correos_vistos",
            "zernio_cuentas", "zernio_eventos", "whatsapp_pendientes"} <= _tablas()


def test_guardar_y_leer_la_conexion_con_el_token_cifrado():
    assert integraciones.guardar_gmail("u1", "ana@gmail.com", "refresh-1", "100") is None
    with basedatos.conexion() as con:
        crudo = con.execute("SELECT token FROM integraciones").fetchone()["token"]
    assert "refresh-1" not in crudo
    c = integraciones.conexion("u1")
    assert c["cuenta"] == "ana@gmail.com" and c["token"] == "refresh-1"
    assert c["cursor"] == "100" and c["estado"] == "conectado"


def test_reconectar_devuelve_el_token_anterior():
    integraciones.guardar_gmail("u1", "ana@gmail.com", "viejo", "1")
    assert integraciones.guardar_gmail("u1", "ana@gmail.com", "nuevo", "2") == "viejo"
    assert integraciones.conexion("u1")["token"] == "nuevo"


def test_conectados_solo_trae_los_conectados():
    integraciones.guardar_gmail("u1", "a@gmail.com", "r1", "1")
    integraciones.guardar_gmail("u2", "b@gmail.com", "r2", "1")
    integraciones.marcar_desconectado("u2", "Google retiro el acceso")
    assert [c["usuario_id"] for c in integraciones.conectados()] == ["u1"]
    assert integraciones.conexion("u2")["error"] == "Google retiro el acceso"


def test_desconectar_borra_el_token_y_lo_devuelve():
    integraciones.guardar_gmail("u1", "a@gmail.com", "r1", "1")
    assert integraciones.desconectar("u1") == "r1"
    c = integraciones.conexion("u1")
    assert c["estado"] == "desconectado" and c["token"] is None
    assert integraciones.desconectar("u1") is None


def test_mover_cursor():
    integraciones.guardar_gmail("u1", "a@gmail.com", "r1", "1")
    integraciones.mover_cursor("u1", "55")
    assert integraciones.conexion("u1")["cursor"] == "55"


def test_reglas_por_defecto_y_guardadas():
    assert integraciones.reglas("u1") == {"reglas": "", "whatsapp": None, "activo": True}
    integraciones.guardar_reglas("u1", "clientes y pagos", "809 555 1234", True)
    assert integraciones.reglas("u1") == {"reglas": "clientes y pagos", "whatsapp": "18095551234", "activo": True}
    integraciones.guardar_reglas("u1", "x", "", False)
    assert integraciones.reglas("u1")["whatsapp"] is None


def test_un_whatsapp_malo_es_valueerror():
    with pytest.raises(ValueError):
        integraciones.guardar_reglas("u1", "x", "123", True)


def test_catalogo_muestra_gmail_con_su_estado(monkeypatch):
    monkeypatch.setenv("GOOGLE_JARVIS_CLIENT_ID", "x")
    monkeypatch.setenv("GOOGLE_JARVIS_CLIENT_SECRET", "y")
    integraciones.guardar_gmail("u1", "a@gmail.com", "r1", "1")
    app = integraciones.catalogo("u1")[0]
    assert app["app"] == "gmail" and app["disponible"] and app["estado"] == "conectado"
    assert app["cuenta"] == "a@gmail.com" and "token" not in app


def test_conectar_gmail_guarda_y_revoca_el_anterior(monkeypatch):
    revocados = []
    integraciones.guardar_gmail("u1", "a@gmail.com", "viejo", "1")
    monkeypatch.setattr(gmail, "canjear_codigo", lambda c: {"access_token": "a", "refresh_token": "nuevo"})
    monkeypatch.setattr(gmail, "perfil", lambda t: {"email": "ana@gmail.com", "historyId": "500"})
    monkeypatch.setattr(gmail, "revocar", revocados.append)
    assert integraciones.conectar_gmail("u1", "codigo") == "ana@gmail.com"
    assert integraciones.conexion("u1")["cursor"] == "500"
    assert revocados == ["viejo"]


from backend import zernio


def test_catalogo_trae_whatsapp(monkeypatch):
    monkeypatch.setenv("ZERNIO_API_KEY", "z")
    apps = {a["app"]: a for a in integraciones.catalogo("u1")}
    assert apps["whatsapp"]["disponible"] and apps["whatsapp"]["estado"] == "sin_conectar"


def test_iniciar_whatsapp_crea_el_perfil_una_sola_vez(monkeypatch):
    llamadas = []
    monkeypatch.setattr(zernio, "perfil_de", lambda u, n: llamadas.append((u, n)) or "p1")
    assert integraciones.iniciar_whatsapp("u1", "Ana") == "p1"
    assert integraciones.iniciar_whatsapp("u1", "Ana") == "p1"
    assert llamadas == [("u1", "Ana")]


def test_guardar_y_desconectar_whatsapp(monkeypatch):
    monkeypatch.setattr(zernio, "perfil_de", lambda u, n: "p1")
    integraciones.iniciar_whatsapp("u1", "Ana")
    integraciones.guardar_whatsapp("u1", "acc-1", "+1 809 555 1234")
    assert integraciones.usuario_de_cuenta("acc-1") == "u1"
    c = integraciones.conexion("u1", "whatsapp")
    assert c["estado"] == "conectado" and c["cuenta"] == "+1 809 555 1234"
    assert [x["usuario_id"] for x in integraciones.conectados("whatsapp")] == ["u1"]
    assert integraciones.desconectar_whatsapp("u1") == "acc-1"
    assert integraciones.usuario_de_cuenta("acc-1") is None
    assert integraciones.conexion("u1", "whatsapp")["estado"] == "desconectado"
    assert integraciones.cuenta_zernio("u1")["perfil_id"] == "p1"   # el perfil se conserva
    assert integraciones.desconectar_whatsapp("u1") is None


def test_la_misma_cuenta_en_otra_persona_se_mueve(monkeypatch):
    monkeypatch.setattr(zernio, "perfil_de", lambda u, n: f"p-{u}")
    for u in ("u1", "u2"):
        integraciones.iniciar_whatsapp(u, u)
    integraciones.guardar_whatsapp("u1", "acc-1", "x")
    integraciones.guardar_whatsapp("u2", "acc-1", "x")
    assert integraciones.usuario_de_cuenta("acc-1") == "u2"
