

from backend import basedatos


def _tablas():
    with basedatos.conexion() as con:
        return {f["name"] for f in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_existen_las_tablas_de_integraciones():
    assert {"integraciones", "reglas_aviso", "avisos", "correos_vistos"} <= _tablas()
