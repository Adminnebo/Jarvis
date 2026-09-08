from backend import acceso


def test_sin_variables_hay_un_solo_admin_por_defecto():
    lista = acceso.usuarios()
    assert len(lista) == 1
    assert lista[0].id == "admin"
    assert lista[0].rol == "admin"


def test_el_admin_toma_su_nombre_de_jarvis_usuario(monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "secreta")
    monkeypatch.setenv("JARVIS_USUARIO", "Lucas")
    lista = acceso.usuarios()
    assert [u.nombre for u in lista] == ["Lucas"]


def test_cada_variable_con_prefijo_es_una_persona(monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "secreta")
    monkeypatch.setenv("JARVIS_PASSWORD_JORGE", "otra")
    lista = acceso.usuarios()
    assert [(u.id, u.nombre, u.rol) for u in lista] == [
        ("admin", "Admin", "admin"),
        ("jorge", "Jorge", "usuario"),
    ]


def test_se_descartan_sufijos_y_contrasenas_vacias(monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "secreta")
    monkeypatch.setenv("JARVIS_PASSWORD_", "huerfana")
    monkeypatch.setenv("JARVIS_PASSWORD_ANA", "   ")
    assert [u.id for u in acceso.usuarios()] == ["admin"]


def test_la_contrasena_dice_quien_entra(monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setenv("JARVIS_PASSWORD_JORGE", "la-de-jorge")
    assert acceso.quien_entra("la-del-admin").id == "admin"
    assert acceso.quien_entra("la-de-jorge").id == "jorge"


def test_una_contrasena_incorrecta_no_entra(monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    assert acceso.quien_entra("cualquier-cosa") is None
    assert acceso.quien_entra("") is None


def test_sin_proteccion_no_entra_nadie_por_contrasena():
    # Sin JARVIS_PASSWORD no hay login: la identidad la da por_defecto().
    assert acceso.quien_entra("lo-que-sea") is None
    assert acceso.por_defecto().rol == "admin"


import time


def test_un_token_valido_devuelve_a_su_dueno(monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setenv("JARVIS_PASSWORD_JORGE", "la-de-jorge")
    token = acceso.crear_token(acceso.quien_entra("la-de-jorge"))
    assert acceso.usuario_de_token(token).id == "jorge"


def test_un_token_manipulado_se_rechaza(monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setenv("JARVIS_PASSWORD_JORGE", "la-de-jorge")
    token = acceso.crear_token(acceso.quien_entra("la-de-jorge"))
    # Cambiarse a si mismo por el admin es justo lo que hay que impedir.
    assert acceso.usuario_de_token(token.replace("jorge", "admin", 1)) is None
    assert acceso.usuario_de_token("basura") is None
    assert acceso.usuario_de_token(None) is None


def test_un_token_vencido_se_rechaza(monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setattr(acceso, "DURACION", -10)
    token = acceso.crear_token(acceso.quien_entra("la-del-admin"))
    assert acceso.usuario_de_token(token) is None


def test_el_token_de_alguien_que_ya_no_esta_se_rechaza(monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setenv("JARVIS_CLAVE_SECRETA", "una-clave-larga-y-estable")
    monkeypatch.setenv("JARVIS_PASSWORD_JORGE", "la-de-jorge")
    token = acceso.crear_token(acceso.quien_entra("la-de-jorge"))

    # Le quitamos su variable: asi se echa a alguien.
    monkeypatch.delenv("JARVIS_PASSWORD_JORGE")
    assert acceso.usuario_de_token(token) is None


def test_avisa_si_dos_personas_comparten_contrasena(monkeypatch, capsys):
    monkeypatch.setenv("JARVIS_PASSWORD", "repetida")
    monkeypatch.setenv("JARVIS_PASSWORD_JORGE", "repetida")

    acceso.avisar_de_contrasenas_repetidas()

    salida = capsys.readouterr().out
    assert "repiten" in salida
    # Gana el primero: el admin.
    assert acceso.quien_entra("repetida").id == "admin"


def test_no_avisa_si_todas_son_distintas(monkeypatch, capsys):
    monkeypatch.setenv("JARVIS_PASSWORD", "una")
    monkeypatch.setenv("JARVIS_PASSWORD_JORGE", "otra")

    acceso.avisar_de_contrasenas_repetidas()

    assert capsys.readouterr().out == ""


import pytest


@pytest.mark.parametrize("ruta, metodo", [
    ("/api/fuentes", "GET"),
    ("/api/fuentes", "POST"),
    ("/api/fuentes/tipos", "GET"),
    ("/api/fuentes/abc123/consultar", "POST"),
    ("/api/fuentes/abc123", "DELETE"),
    ("/api/esquema/refrescar", "POST"),
    ("/api/consumo", "GET"),
    ("/api/consumo", "DELETE"),
])
def test_rutas_solo_para_admin(ruta, metodo):
    assert acceso.exige_admin(ruta, metodo) is True


@pytest.mark.parametrize("ruta, metodo", [
    ("/api/chat", "POST"),
    ("/api/estado", "GET"),
    ("/api/memoria", "GET"),
    ("/api/herramienta", "POST"),
    ("/api/voz/sesion", "GET"),
    # Lo escribe el navegador durante la voz: bloquearlo dejaria sin registrar
    # el gasto de quien no es admin.
    ("/api/consumo/voz", "POST"),
    ("/", "GET"),
])
def test_rutas_abiertas_a_todos(ruta, metodo):
    assert acceso.exige_admin(ruta, metodo) is False
