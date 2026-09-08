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


def test_entrar_con_un_token_bueno(configurado, monkeypatch):
    monkeypatch.setattr(supabase_sesion, "id_de_token",
                        lambda t: "11111111-2222-3333-4444-555555555555")
    monkeypatch.setattr(supabase_sesion, "perfil_cacheado",
                        lambda u: perfil_de(permissions=["jarvis.usar"]))
    assert supabase_sesion.entrar("un-token").rol == "usuario"


def test_entrar_con_un_token_invalido(configurado, monkeypatch):
    monkeypatch.setattr(supabase_sesion, "id_de_token", lambda t: None)
    assert supabase_sesion.entrar("un-token") is None


def test_si_supabase_falla_no_entra_nadie(configurado, monkeypatch):
    def revienta(_):
        raise RuntimeError("Supabase no responde")

    monkeypatch.setattr(supabase_sesion, "id_de_token", revienta)
    # Nunca modo abierto: un fallo deja fuera, no deja pasar.
    assert supabase_sesion.entrar("un-token") is None


def test_con_el_puente_apagado_no_entra_nadie():
    assert supabase_sesion.entrar("un-token") is None


def test_revalidar_devuelve_none_si_le_quitaron_el_permiso(configurado, monkeypatch):
    previo = supabase_sesion.usuario_de_perfil(perfil_de(permissions=["jarvis.usar"]))
    monkeypatch.setattr(supabase_sesion, "perfil_cacheado",
                        lambda u: perfil_de(permissions=["inbox.send"]))
    assert supabase_sesion.revalidar(previo) is None


def test_revalidar_actualiza_el_rol(configurado, monkeypatch):
    previo = supabase_sesion.usuario_de_perfil(perfil_de(permissions=["jarvis.usar"]))
    monkeypatch.setattr(supabase_sesion, "perfil_cacheado",
                        lambda u: perfil_de(permissions=["jarvis.admin"]))
    assert supabase_sesion.revalidar(previo).rol == "admin"


def test_revalidar_ignora_a_los_de_contrasena(configurado):
    from backend import acceso

    de_variable = acceso.Usuario("admin", "Lucas", "admin")
    # No lleva el prefijo: no se toca la base por el.
    assert supabase_sesion.revalidar(de_variable) is de_variable


def test_el_perfil_se_cachea_un_minuto(configurado, monkeypatch):
    llamadas = []

    def contar(uuid):
        llamadas.append(uuid)
        return perfil_de(permissions=["jarvis.usar"])

    supabase_sesion.limpiar_cache()
    monkeypatch.setattr(supabase_sesion, "perfil", contar)

    uuid = "11111111-2222-3333-4444-555555555555"
    supabase_sesion.perfil_cacheado(uuid)
    supabase_sesion.perfil_cacheado(uuid)
    supabase_sesion.perfil_cacheado(uuid)

    # Tres consultas seguidas, una sola ida a la base.
    assert len(llamadas) == 1
