import json

import pytest

from backend import fuentes


@pytest.fixture
def motor(monkeypatch):
    """Un motor de mentira que anota lo que recibe."""
    vistos = []

    def falso(config, sql, limite, id_fuente=None, parametros=None):
        vistos.append({"sql": sql, "parametros": parametros, "limite": limite})
        return [{"n": 1}]

    monkeypatch.setitem(fuentes.MOTORES, "mssql", falso)
    monkeypatch.setattr(fuentes, "obtener", lambda _id: {
        "id": "erp", "nombre": "ERP", "tipo": "mssql", "activa": True, "solo_lectura": True, "config": {}})
    return vistos


def test_consultar_pasa_los_parametros_al_motor(motor):
    fuentes.consultar("erp", "select count(*) n from v where f >= %(desde)s", 10, parametros={"desde": "2026-10-26"})
    assert motor[0]["parametros"] == {"desde": "2026-10-26"}


def test_sin_parametros_sigue_como_antes(motor):
    fuentes.consultar("erp", "select 1", 10)
    assert motor[0]["parametros"] is None
