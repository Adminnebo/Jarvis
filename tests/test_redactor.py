import json

import pytest

from backend import accesos, fuentes, redactor

ESQUEMA = {"fuente": "ERP", "tipo": "mssql", "tablas": [
    {"tabla": "List_OrdenVentasIA", "columnas": "Numero int, Fecha datetime, Vendedor varchar, Total money"},
]}


class _Modelo:
    """Reemplaza a cerebro.cliente(): devuelve lo que se le diga y anota lo que recibio."""

    def __init__(self, salida):
        self.salida, self.pedidos = salida, []
        self.responses = self

    def create(self, **kw):
        self.pedidos.append(kw)
        return type("R", (), {"output_text": json.dumps(self.salida), "usage": None})()


@pytest.fixture
def base(monkeypatch):
    monkeypatch.setattr(fuentes, "obtener", lambda _id: {
        "id": "erp", "nombre": "ERP", "tipo": "mssql", "activa": True, "solo_lectura": True,
        "config": {}, "tablas": {}})
    monkeypatch.setattr(fuentes, "esquema_de", lambda _id, refrescar=False: ESQUEMA)
    filas = []
    monkeypatch.setitem(fuentes.MOTORES, "mssql",
                        lambda c, sql, lim, idf=None, parametros=None: filas.append((sql, parametros)) or [{"ventas": 12}])
    return filas


def test_proponer_diccionario_lee_filas_de_ejemplo_y_no_guarda(base, monkeypatch):
    modelo = _Modelo({"leyenda": "ordenes de venta", "columnas": {"Total": "monto con ITBIS"}, "reglas": ""})
    monkeypatch.setattr(redactor, "_cliente", lambda: modelo)
    borrador = redactor.proponer_diccionario("erp", "List_OrdenVentasIA")
    assert borrador == {"leyenda": "ordenes de venta", "columnas": {"Total": "monto con ITBIS"}, "reglas": ""}
    assert base[0][0].lower().startswith("select top 5 *")
    assert "List_OrdenVentasIA" in modelo.pedidos[0]["input"]


def test_proponer_acceso_lo_valida_y_lo_corre_sin_guardar(base, monkeypatch):
    modelo = _Modelo({
        "id": "ventas_por_periodo", "descripcion": "Ventas entre dos fechas.",
        "sql": "select count(*) as ventas from List_OrdenVentasIA where Fecha >= %(desde)s and Fecha < %(hasta)s",
        "parametros": {"desde": {"tipo": "fecha", "descripcion": "desde", "por_defecto": "2026-10-26"},
                       "hasta": {"tipo": "fecha", "descripcion": "hasta", "por_defecto": "2026-10-27"}}})
    monkeypatch.setattr(redactor, "_cliente", lambda: modelo)
    r = redactor.proponer_acceso("erp", "¿Cuántas ventas hoy?")
    assert r["propuesta"]["id"] == "ventas_por_periodo"
    assert r["resultado"] == [{"ventas": 12}] and r["error"] is None
    assert base[-1][1] == {"desde": "2026-10-26", "hasta": "2026-10-27"}
    assert accesos.listar("erp") == []


def test_una_propuesta_invalida_devuelve_el_motivo(base, monkeypatch):
    modelo = _Modelo({"id": "borra", "descripcion": "x", "sql": "delete from t", "parametros": {}})
    monkeypatch.setattr(redactor, "_cliente", lambda: modelo)
    r = redactor.proponer_acceso("erp", "borra todo")
    assert r["resultado"] is None and "solo lectura" in r["error"]


def test_la_correccion_viaja_al_modelo(base, monkeypatch):
    modelo = _Modelo({"id": "x_y", "descripcion": "d", "sql": "select 1 as n", "parametros": {}})
    monkeypatch.setattr(redactor, "_cliente", lambda: modelo)
    redactor.proponer_acceso("erp", "p", correccion="solo las no anuladas", anterior={"sql": "select 2"})
    assert "solo las no anuladas" in modelo.pedidos[0]["input"] and "select 2" in modelo.pedidos[0]["input"]


def test_el_pedido_menciona_json(base, monkeypatch):
    # La API exige la palabra JSON en el mensaje (no basta en las instrucciones)
    # para responder con text.format json_object.
    modelo = _Modelo({"leyenda": "", "columnas": {}, "reglas": ""})
    monkeypatch.setattr(redactor, "_cliente", lambda: modelo)
    redactor.proponer_diccionario("erp", "List_OrdenVentasIA")
    assert "json" in modelo.pedidos[0]["input"].lower()


def test_reglas_en_lista_quedan_como_texto(base, monkeypatch):
    modelo = _Modelo({"leyenda": "x", "columnas": {}, "reglas": ["Un cliente activo es activo = 1.", "Suspendido = 1 no compra."]})
    monkeypatch.setattr(redactor, "_cliente", lambda: modelo)
    assert redactor.proponer_diccionario("erp", "List_OrdenVentasIA")["reglas"] == (
        "Un cliente activo es activo = 1.\nSuspendido = 1 no compra.")
