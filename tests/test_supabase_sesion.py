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
