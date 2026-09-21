"""Cuando SUPABASE_DB_URL no es una URL de Postgres, decir como empieza.

Sin esto, el unico sintoma era 'missing "=" after <SUPABASE_DB_URL>', que dice
que la cadena esta mal pero no por que, y la cadena no se puede mostrar
porque lleva la contrasena.
"""

import pytest

from backend import esquema, supabase_sesion

CLAVE = "clave-secreta"


@pytest.mark.parametrize("escrita", [
    f"postgresql://postgres.abc:{CLAVE}@host:6543/postgres",
    f"postgres://postgres.abc:{CLAVE}@host:6543/postgres",
    f'"postgresql://postgres.abc:{CLAVE}@host:6543/postgres"',
    "",
])
def test_una_cadena_buena_no_tiene_problema(monkeypatch, escrita):
    monkeypatch.setenv("SUPABASE_DB_URL", escrita)
    assert esquema.problema_de_la_cadena() is None


@pytest.mark.parametrize("escrita, se_ve", [
    # Comillas tipograficas: las ponen WhatsApp, Notas y los procesadores.
    (f"“postgresql://postgres.abc:{CLAVE}@host/postgres”", "\\u201cpostgresql"),
    # Un caracter invisible adelante, tipico de copiar desde el celular.
    (f"​postgresql://postgres.abc:{CLAVE}@host/postgres", "\\u200bpostgresql"),
    (f"﻿postgresql://postgres.abc:{CLAVE}@host/postgres", "\\ufeffpostgresql"),
    # Acentos graves de markdown.
    (f"`postgresql://postgres.abc:{CLAVE}@host/postgres`", "`postgresql"),
    # El esquema de otra libreria.
    (f"postgresql+psycopg://postgres.abc:{CLAVE}@host/postgres", "postgresql+psycopg"),
    # La URL del proyecto en vez de la de la base.
    ("https://abcdefghijklmnopqrst.supabase.co", "https"),
    (f"POSTGRESQL://postgres.abc:{CLAVE}@host/postgres", "POSTGRESQL"),
])
def test_se_ve_como_empieza_sin_la_contrasena(monkeypatch, escrita, se_ve):
    monkeypatch.setenv("SUPABASE_DB_URL", escrita)
    problema = esquema.problema_de_la_cadena()
    assert se_ve in problema
    assert CLAVE not in problema


@pytest.mark.parametrize("escrita", [
    # Solo la contrasena, pegada en la variable equivocada.
    CLAVE,
    # Una contrasena con ':' no puede asomar su primera parte.
    "abc:def-la-contrasena",
])
def test_si_no_parece_un_esquema_no_se_muestra_nada_de_la_cadena(monkeypatch, escrita):
    monkeypatch.setenv("SUPABASE_DB_URL", escrita)
    problema = esquema.problema_de_la_cadena()
    assert problema == "no empieza con postgresql://"


def test_el_diagnostico_lo_dice_sin_ir_a_supabase(monkeypatch):
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon")
    monkeypatch.setenv("SUPABASE_PROJECT_REF", "abcdefghijklmnopqrst")
    monkeypatch.setenv("SUPABASE_DB_URL", f"“postgresql://p.abc:{CLAVE}@host/postgres”")

    def no_deberia(_):
        raise AssertionError("con la cadena mal no hace falta validar el token")

    monkeypatch.setattr(supabase_sesion, "id_de_token", no_deberia)

    motivo = supabase_sesion.diagnostico("un-token")
    assert motivo.startswith("cadena-invalida:")
    assert "\\u201cpostgresql" in motivo
    assert CLAVE not in motivo


def test_el_mensaje_para_la_persona_dice_como_empieza():
    from backend.main import mensaje_de_rechazo

    mensaje = mensaje_de_rechazo("cadena-invalida:empieza con '\\u201cpostgresql'")
    assert "SUPABASE_DB_URL" in mensaje
    assert "\\u201cpostgresql" in mensaje
