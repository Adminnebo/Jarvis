import pytest

from backend import supabase_sesion


@pytest.fixture
def configurado(monkeypatch):
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-de-prueba")
    monkeypatch.setenv("SUPABASE_PROJECT_REF", "abcdefghijklmnopqrst")
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://x:y@z:5432/postgres")


def test_sin_variables_el_puente_esta_apagado():
    assert supabase_sesion.configurado() is False


def test_con_las_tres_variables_esta_encendido(configurado):
    assert supabase_sesion.configurado() is True


def test_falta_la_cadena_de_postgres(configurado, monkeypatch):
    # Sin conexion directa, leer el perfil iria por MCP y costaria mas de un
    # segundo en cada revalidacion.
    monkeypatch.delenv("SUPABASE_DB_URL")
    assert supabase_sesion.configurado() is False


def test_la_url_del_proyecto_sale_de_la_referencia(configurado):
    assert supabase_sesion.url_proyecto() == "https://abcdefghijklmnopqrst.supabase.co"


def test_un_uuid_invalido_no_llega_a_la_base(configurado):
    # El uuid se interpola en el SQL, asi que tiene que estar comprobado antes.
    with pytest.raises(ValueError):
        supabase_sesion.perfil("'; drop table profiles; --")


def perfil_de(role="agent", permissions=None, platforms=None, nombre="Ana Perez"):
    return {
        "id": "11111111-2222-3333-4444-555555555555",
        "email": "ana@empresa.com",
        "full_name": nombre,
        "role": role,
        "permissions": permissions,
        "platforms": platforms,
    }


def test_con_jarvis_usar_entra_como_usuario():
    usuario = supabase_sesion.usuario_de_perfil(perfil_de(permissions=["jarvis.usar"]))
    assert usuario.rol == "usuario"
    assert usuario.nombre == "Ana Perez"
    assert usuario.id == "sb-11111111-2222-3333-4444-555555555555"


def test_con_jarvis_admin_entra_como_admin():
    usuario = supabase_sesion.usuario_de_perfil(perfil_de(permissions=["jarvis.admin"]))
    assert usuario.rol == "admin"


@pytest.mark.parametrize("role", ["super_admin", "admin"])
def test_los_administradores_de_la_plataforma_son_admin(role):
    assert supabase_sesion.usuario_de_perfil(perfil_de(role=role)).rol == "admin"


def test_sin_permiso_de_jarvis_no_entra():
    assert supabase_sesion.usuario_de_perfil(perfil_de(permissions=["inbox.send"])) is None


def test_un_perfil_viejo_sin_permisos_no_entra():
    # permissions en NULL y platforms de las tres viejas: el catalogo ya no
    # concede jarvis por respaldo, y aqui tampoco.
    sin_migrar = perfil_de(
        permissions=None, platforms=["inbox", "cotizaciones", "cobranzas"]
    )
    assert supabase_sesion.usuario_de_perfil(sin_migrar) is None


def test_sin_nombre_se_usa_la_parte_del_correo():
    anonimo = perfil_de(permissions=["jarvis.usar"], nombre=None)
    assert supabase_sesion.usuario_de_perfil(anonimo).nombre == "ana"


def test_un_perfil_inexistente_no_entra():
    assert supabase_sesion.usuario_de_perfil(None) is None
