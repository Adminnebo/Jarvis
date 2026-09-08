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
