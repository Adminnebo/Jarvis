"""SUPABASE_DB_URL tal como la escribe una persona en el panel del proveedor.

Railway y los demas guardan el valor literal: si se pega con comillas o con
un espacio adelante, eso llega a psycopg, que no lo reconoce como URL y falla
con 'missing "=" after ... in connection info string'. Asi fallaba el acceso
desde el panel de conversaciones.
"""

import pytest

from backend import esquema, supabase_sesion

LIMPIA = "postgresql://usuario:clave-secreta@db.ejemplo.com:6543/postgres"


@pytest.mark.parametrize("escrita", [
    LIMPIA,
    " " + LIMPIA,
    "\n" + LIMPIA,
    LIMPIA + "\n",
    '"' + LIMPIA + '"',
    "'" + LIMPIA + "'",
    '  "' + LIMPIA + '"  ',
])
def test_la_cadena_llega_limpia(monkeypatch, escrita):
    monkeypatch.setenv("SUPABASE_DB_URL", escrita)
    assert esquema.cadena_de_conexion() == LIMPIA


def test_una_comilla_suelta_no_se_toca(monkeypatch):
    # Solo se quitan si envuelven la cadena entera: una sola no es un envoltorio.
    monkeypatch.setenv("SUPABASE_DB_URL", '"' + LIMPIA)
    assert esquema.cadena_de_conexion() == '"' + LIMPIA


def test_sin_variable_no_hay_cadena(monkeypatch):
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    assert esquema.cadena_de_conexion() == ""


def test_unas_comillas_vacias_no_cuentan_como_configurada(monkeypatch):
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon")
    monkeypatch.setenv("SUPABASE_PROJECT_REF", "abcdefghijklmnopqrst")
    monkeypatch.setenv("SUPABASE_DB_URL", '""')
    assert supabase_sesion.configurado() is False


@pytest.mark.parametrize("escrita", ['"' + LIMPIA + '"', " " + LIMPIA])
def test_a_psycopg_le_llega_la_cadena_limpia(monkeypatch, escrita):
    import psycopg

    recibida = []

    def conectar_falso(cadena, **opciones):
        recibida.append(cadena)
        raise psycopg.OperationalError("sin red en las pruebas")

    monkeypatch.setenv("SUPABASE_DB_URL", escrita)
    monkeypatch.setattr(psycopg, "connect", conectar_falso)

    with pytest.raises(psycopg.OperationalError):
        esquema.consultar_directo("select 1")

    assert recibida == [LIMPIA]


def test_la_contrasena_no_sale_en_el_diagnostico_aunque_venga_entre_comillas(
    monkeypatch, capsys,
):
    """El error de conexion trae la cadena limpia: es la que se tiene que tapar.

    ProgrammingError porque es el unico cuyo detalle llega hasta la persona;
    los demas solo van al log, que tambien se revisa.
    """
    import psycopg

    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon")
    monkeypatch.setenv("SUPABASE_PROJECT_REF", "abcdefghijklmnopqrst")
    monkeypatch.setenv("SUPABASE_DB_URL", '"' + LIMPIA + '"')
    monkeypatch.setattr(supabase_sesion, "id_de_token",
                        lambda token: "11111111-2222-3333-4444-555555555555")

    def falla_con_la_cadena(uuid):
        raise psycopg.ProgrammingError(f"no se pudo conectar con {LIMPIA}")

    monkeypatch.setattr(supabase_sesion, "perfil_cacheado", falla_con_la_cadena)

    motivo = supabase_sesion.diagnostico("un-token")
    log = capsys.readouterr().out

    assert motivo.startswith("error-perfil:ProgrammingError")
    assert "clave-secreta" not in motivo
    assert "clave-secreta" not in log
    assert "<SUPABASE_DB_URL>" in motivo
