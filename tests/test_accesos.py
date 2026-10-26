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


from backend import accesos  # noqa: E402

VENTAS = {
    "id": "ventas_por_periodo",
    "pregunta": "¿Cuántas ventas se hicieron hoy?",
    "descripcion": "Cantidad y monto de ventas entre dos fechas.",
    "sql": "select count(*) as ventas from List_OrdenVentasIA where Fecha >= %(desde)s and Fecha < %(hasta)s",
    "parametros": {
        "desde": {"tipo": "fecha", "descripcion": "Desde (incluida)", "por_defecto": "2026-10-26"},
        "hasta": {"tipo": "fecha", "descripcion": "Hasta (excluida)", "por_defecto": "2026-10-27"},
    },
}


def test_guardar_y_listar(motor):
    accesos.guardar("erp", VENTAS)
    [a] = accesos.listar("erp")
    assert a["id"] == "ventas_por_periodo" and a["parametros"]["desde"]["tipo"] == "fecha"
    assert a["activo"] is True and a["ultimo_error"] is None


def test_el_sql_tiene_que_ser_de_solo_lectura(motor):
    with pytest.raises(accesos.ErrorDeAcceso, match="solo lectura"):
        accesos.guardar("erp", {**VENTAS, "sql": "delete from List_ClientesIA"})


def test_los_placeholders_tienen_que_coincidir(motor):
    with pytest.raises(accesos.ErrorDeAcceso, match="hasta"):
        accesos.guardar("erp", {**VENTAS, "sql": "select 1 where f >= %(desde)s"})


def test_el_nombre_es_corto_y_sin_espacios(motor):
    with pytest.raises(accesos.ErrorDeAcceso):
        accesos.guardar("erp", {**VENTAS, "id": "ventas de hoy!"})


def test_tipos_de_variable(motor):
    p = {"tipo": "entero", "descripcion": "Cuantos", "por_defecto": 5, "minimo": 1, "maximo": 50}
    assert accesos.valor(p, "7") == 7
    with pytest.raises(accesos.ErrorDeAcceso):
        accesos.valor(p, 500)
    assert accesos.valor({"tipo": "fecha"}, "2026-10-26") == "2026-10-26"
    with pytest.raises(accesos.ErrorDeAcceso):
        accesos.valor({"tipo": "fecha"}, "26/10/2026")
    with pytest.raises(accesos.ErrorDeAcceso):
        accesos.valor({"tipo": "texto"}, "x" * 101)


def test_borrar_y_desactivar(motor):
    accesos.guardar("erp", VENTAS)
    accesos.activar("ventas_por_periodo", False)
    assert accesos.listar("erp")[0]["activo"] is False
    assert accesos.borrar("ventas_por_periodo") is True
    assert accesos.listar("erp") == []


def test_borrar_la_fuente_borra_sus_accesos(motor):
    accesos.guardar("erp", VENTAS)
    accesos.borrar_de_fuente("erp")
    assert accesos.listar("erp") == []
