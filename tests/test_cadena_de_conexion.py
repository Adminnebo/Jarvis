"""SUPABASE_DB_URL tal como la escribe una persona en el panel del proveedor.

Railway y los demas guardan el valor literal: si se pega con comillas o con
un espacio adelante, eso llega a psycopg, que no lo reconoce como URL y falla
con 'missing "=" after ... in connection info string'.

La usan solo las consultas directas a Postgres (esquema.consultar). El acceso
desde los paneles no: lee el perfil por la API de Supabase.
"""

import pytest

from backend import esquema

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
