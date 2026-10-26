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
