import sqlite3

import pytest

from backend import basedatos


def test_las_tablas_del_asistente_existen():
    with basedatos.conexion() as con:
        tablas = {fila["name"] for fila in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )}
    assert {"asistentes", "asistente_videos"} <= tablas


def test_un_video_solo_puede_ser_de_los_tres_estados():
    with basedatos.conexion() as con:
        con.execute("INSERT INTO organizaciones (id, nombre, creada) VALUES ('o1', 'Org', 'x')")
        with pytest.raises(sqlite3.IntegrityError):
            con.execute(
                "INSERT INTO asistente_videos (organizacion_id, estado, actualizado) "
                "VALUES ('o1', 'bailando', 'x')"
            )


from backend import acceso, asistente  # noqa: E402


def _org(id_="o1", nombre="JH"):
    with basedatos.conexion() as con:
        con.execute("INSERT OR IGNORE INTO organizaciones (id, nombre, creada) VALUES (?, ?, 'x')",
                    (id_, nombre))


def _usuario(org=None):
    return acceso.Usuario("u-1", "Ana", "usuario", organizacion_id=org)


def test_sin_configurar_se_usa_la_variable(monkeypatch):
    monkeypatch.setenv("JARVIS_NOMBRE", "Nebo")
    _org()
    assert asistente.nombre(_usuario("o1")) == "Nebo"


def test_sin_variable_ni_configuracion_es_jarvis(monkeypatch):
    monkeypatch.delenv("JARVIS_NOMBRE", raising=False)
    assert asistente.nombre(_usuario(None)) == "Jarvis"


def test_el_nombre_de_la_organizacion_gana(monkeypatch):
    monkeypatch.setenv("JARVIS_NOMBRE", "Nebo")
    _org()
    asistente.guardar_nombre("o1", "  Sofía ")
    assert asistente.nombre(_usuario("o1")) == "Sofía"
    # Otra organizacion, o alguien sin organizacion, sigue con la variable.
    _org("o2", "Otra")
    assert asistente.nombre(_usuario("o2")) == "Nebo"
    assert asistente.nombre(_usuario(None)) == "Nebo"


def test_un_nombre_vacio_vuelve_a_la_variable(monkeypatch):
    monkeypatch.setenv("JARVIS_NOMBRE", "Nebo")
    _org()
    asistente.guardar_nombre("o1", "Sofía")
    asistente.guardar_nombre("o1", "   ")
    assert asistente.nombre(_usuario("o1")) == "Nebo"


def test_el_nombre_no_puede_ser_larguisimo():
    _org()
    with pytest.raises(asistente.ErrorDeAsistente):
        asistente.guardar_nombre("o1", "x" * 41)


def test_configuracion_de_una_organizacion_sin_nada():
    _org()
    datos = asistente.configuracion("o1")
    assert datos == {
        "organizacion_id": "o1", "nombre": None, "foto": None,
        "videos": {e: {"archivo": None, "trabajo_estado": None, "error": None}
                   for e in asistente.ESTADOS},
    }


def test_las_instrucciones_usan_el_nombre_de_la_organizacion(monkeypatch):
    from backend import cerebro

    monkeypatch.setenv("JARVIS_NOMBRE", "Nebo")
    _org()
    asistente.guardar_nombre("o1", "Sofía")
    assert cerebro.instrucciones(_usuario("o1")).startswith("Eres Sofía, el asistente personal de Ana.")
    assert cerebro.instrucciones(_usuario(None)).startswith("Eres Nebo, el asistente personal de Ana.")
