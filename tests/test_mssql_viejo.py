"""SQL Server 2008 R2 sin parches solo acepta TDS 7.0.

Con la version por defecto de FreeTDS la conexion abre (el puerto responde) pero
el login falla con "DB-Lib error message 20002 ... TDS server connection failed".
Paso con el ERP de JH (gemelo-kpi.jhelectroalambres.com:5033).
"""

import sys
import types

import pytest

from backend import fuentes


class _ErrorOperacional(Exception):
    pass


class _Cursor:
    def __init__(self):
        self.sql = None

    def execute(self, sql):
        self.sql = sql

    def fetchmany(self, n):
        return [{"base": "sim"}]

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Conexion:
    def cursor(self, as_dict=False):
        return _Cursor()

    def close(self):
        pass


@pytest.fixture
def pymssql_falso(monkeypatch):
    llamadas = []
    servidor_viejo = {"activo": True}

    def connect(**kw):
        llamadas.append(kw)
        if servidor_viejo["activo"] and kw.get("tds_version") != "7.0":
            raise _ErrorOperacional(
                "(20002, b'DB-Lib error message 20002, severity 9:\\n"
                "TDS server connection failed (gemelo-kpi.jhelectroalambres.com)\\n')")
        return _Conexion()

    modulo = types.SimpleNamespace(connect=connect, OperationalError=_ErrorOperacional)
    monkeypatch.setitem(sys.modules, "pymssql", modulo)
    fuentes._tds_viejo.clear()
    return llamadas, servidor_viejo


CONFIG = {"host": "gemelo-kpi.jhelectroalambres.com", "puerto": "5033", "base": "sim",
          "usuario": "u", "password": "p"}


def test_un_sql_server_2008_conecta_con_tds_7_0(pymssql_falso):
    llamadas, _ = pymssql_falso
    filas = fuentes.consultar_mssql(CONFIG, "select db_name() as base", 10)
    assert filas == [{"base": "sim"}]
    assert [k.get("tds_version") for k in llamadas] == [None, "7.0"]


def test_la_segunda_vez_va_directo_con_7_0(pymssql_falso):
    llamadas, _ = pymssql_falso
    fuentes.consultar_mssql(CONFIG, "select 1", 10)
    llamadas.clear()
    fuentes.consultar_mssql(CONFIG, "select 1", 10)
    assert [k.get("tds_version") for k in llamadas] == ["7.0"]


def test_un_servidor_moderno_no_se_toca(pymssql_falso):
    llamadas, viejo = pymssql_falso
    viejo["activo"] = False
    fuentes.consultar_mssql(CONFIG, "select 1", 10)
    assert [k.get("tds_version") for k in llamadas] == [None]


def test_otro_error_no_se_disfraza(pymssql_falso, monkeypatch):
    def connect(**kw):
        raise _ErrorOperacional("(18456, b'Login failed for user')")
    monkeypatch.setattr(sys.modules["pymssql"], "connect", connect)
    with pytest.raises(_ErrorOperacional, match="18456"):
        fuentes.consultar_mssql(CONFIG, "select 1", 10)


def test_en_sql_server_tambien_se_ven_las_vistas():
    # El usuario del ERP de JH solo tiene SELECT sobre vistas (List_*IA): sin
    # ellas Jarvis veia la base vacia.
    sql = fuentes.SQL_TABLAS["mssql"].lower()
    assert "'view'" in sql and "'base table'" in sql
