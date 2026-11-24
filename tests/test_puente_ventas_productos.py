"""Puente de ventas por producto para el cruce de cotizaciones del panel de JH.

El cruce por productos (jh-panel-completo, cotizaciones/cruceProductos.js) necesita las
lineas de List_VentasxProductosIA de Nueva Data JH, que solo acepta la IP de este
servidor. Entra con la misma clave del panel de JH que Reactivacion; manda un rango de
fechas y codigos de cliente, nunca SQL.
"""

from datetime import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from backend import fuentes, puente_cotizaciones

CLAVE = "clave-del-panel-de-jh"
RUTA = "/api/puente/cotizaciones/ventas-productos"
CUERPO = {"desde": "2026-07-01T00:00:00Z", "hasta": "2026-07-09T00:00:00Z", "clientes": [76, 5853]}


@pytest.fixture
def consultas(monkeypatch):
    pedidas = []

    def falsa(id_fuente, sql, limite=200, parametros=None):
        fuentes.validar_solo_lectura(sql)
        pedidas.append({"fuente": id_fuente, "sql": sql, "limite": limite, "parametros": parametros})
        if "MAX(FechaHora)" in sql:
            return [{"hasta": datetime(2026, 10, 19, 15, 12, 6, 913000)}]
        return [{"nfactura": Decimal("1010391175"), "FechaHora": datetime(2026, 7, 2, 10, 0, 0, 360000),
                 "cliente": Decimal("5853"), "Codigo": "5741  ", "Cantidad": 2.0, "TotalVenta": 300.5}]

    monkeypatch.setattr(fuentes, "consultar", falsa)
    return pedidas


def test_pedido_valido():
    p = puente_cotizaciones.pedido_de(CUERPO)
    assert p == {"desde": "2026-07-01T00:00:00.000", "hasta": "2026-07-09T00:00:00.000", "clientes": [76, 5853]}


def test_milisegundos_del_panel_quedan_en_3_decimales():
    # el panel manda toISOString() (".037Z"); con 6 decimales SQL Server no convierte la fecha
    p = puente_cotizaciones.pedido_de({**CUERPO, "desde": "2026-11-15T16:21:46.037Z", "hasta": "2026-11-23T16:21:46.5Z"})
    assert p["desde"] == "2026-11-15T16:21:46.037"
    assert p["hasta"] == "2026-11-23T16:21:46.500"


@pytest.mark.parametrize("malo", [
    None, [], {"desde": "ayer", "hasta": "2026-07-09", "clientes": [1]},
    {"desde": "2026-07-09", "hasta": "2026-07-01", "clientes": [1]},              # al reves
    {"desde": "2024-01-01", "hasta": "2026-07-01", "clientes": [1]},              # demasiado largo
    {"desde": "2026-07-01", "hasta": "2026-07-09", "clientes": []},
    {"desde": "2026-07-01", "hasta": "2026-07-09", "clientes": ["1; DROP TABLE x"]},
    {"desde": "2026-07-01", "hasta": "2026-07-09", "clientes": [0]},
    {"desde": "2026-07-01", "hasta": "2026-07-09", "clientes": [True]},
    {"desde": "2026-07-01", "hasta": "2026-07-09", "clientes": list(range(1, 6002))},
])
def test_pedido_malo(malo):
    with pytest.raises(ValueError):
        puente_cotizaciones.pedido_de(malo)


def test_ventas_solo_lectura_fechas_como_parametro_y_clientes_validados(consultas):
    datos = puente_cotizaciones.ventas_productos(puente_cotizaciones.pedido_de(CUERPO))
    assert len(consultas) == 2
    lineas = consultas[0]
    assert lineas["fuente"] == puente_cotizaciones.FUENTE_POR_DEFECTO
    assert lineas["parametros"] == {"desde": "2026-07-01T00:00:00.000", "hasta": "2026-07-09T00:00:00.000"}
    assert "2026-07-01" not in lineas["sql"], "las fechas van como parametro"
    assert "cliente IN (76,5853)" in lineas["sql"]
    # hora del ERP marcada como UTC, igual que la lee el panel con el driver de MSSQL
    assert datos["datosHasta"] == "2026-10-19T15:12:06.913Z"
    assert datos["filas"] == [{"nfactura": 1010391175, "FechaHora": "2026-07-02T10:00:00.360Z", "cliente": 5853,
                               "Codigo": "5741", "Cantidad": 2.0, "TotalVenta": 300.5}]


def test_muchos_clientes_van_en_tandas(consultas):
    pedido = puente_cotizaciones.pedido_de({**CUERPO, "clientes": list(range(1, 1201))})
    puente_cotizaciones.ventas_productos(pedido)
    assert len([c for c in consultas if "cliente IN" in c["sql"]]) == 3


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-contrasena-del-admin")
    from backend.main import app

    with TestClient(app) as cliente:
        yield cliente


def test_sin_la_variable_la_ruta_no_existe(cliente):
    assert cliente.post(RUTA, json=CUERPO).status_code == 404


def test_sin_clave_o_con_otra_no_entra(cliente, monkeypatch, consultas):
    monkeypatch.setenv("JARVIS_REACTIVACION_CLAVE", CLAVE)
    assert cliente.post(RUTA, json=CUERPO).status_code == 401
    assert cliente.post(RUTA, json=CUERPO, headers={"Authorization": "Bearer otra"}).status_code == 401
    assert consultas == []


def test_con_la_clave_devuelve_las_lineas(cliente, monkeypatch, consultas):
    monkeypatch.setenv("JARVIS_REACTIVACION_CLAVE", CLAVE)
    r = cliente.post(RUTA, json=CUERPO, headers={"Authorization": f"Bearer {CLAVE}"})
    assert r.status_code == 200
    assert r.json()["datosHasta"] == "2026-10-19T15:12:06.913Z"
    assert r.json()["filas"][0]["nfactura"] == 1010391175


def test_pedido_malo_es_400_sin_tocar_la_base(cliente, monkeypatch, consultas):
    monkeypatch.setenv("JARVIS_REACTIVACION_CLAVE", CLAVE)
    r = cliente.post(RUTA, json={**CUERPO, "clientes": ["x"]}, headers={"Authorization": f"Bearer {CLAVE}"})
    assert r.status_code == 400
    assert consultas == []


def test_si_la_base_falla_es_502_sin_detalles(cliente, monkeypatch):
    monkeypatch.setenv("JARVIS_REACTIVACION_CLAVE", CLAVE)

    def caida(*_a, **_k):
        raise RuntimeError("Adaptive Server connection failed usuario LMNeboUsrIA")

    monkeypatch.setattr(fuentes, "consultar", caida)
    r = cliente.post(RUTA, json=CUERPO, headers={"Authorization": f"Bearer {CLAVE}"})
    assert r.status_code == 502
    assert "LMNeboUsrIA" not in r.text


# --------------------------------------------------------------------------
# Una factura con sus productos
# --------------------------------------------------------------------------

RUTA_FACTURA = "/api/puente/cotizaciones/factura"


@pytest.fixture
def factura_falsa(monkeypatch):
    pedidas = []

    def falsa(id_fuente, sql, limite=200, parametros=None):
        fuentes.validar_solo_lectura(sql)
        pedidas.append({"sql": sql, "parametros": parametros})
        if "MAX(FechaHora)" in sql:
            return [{"hasta": datetime(2026, 10, 19, 15, 12, 6, 913000)}]
        if parametros and parametros.get("numero") == 404:
            return []
        return [{"nfactura": Decimal("1010391175"), "FechaHora": datetime(2026, 7, 2, 10, 0, 0, 360000), "ncf": "B0100000001 ",
                 "Empresa": "EMPRESA DE PRUEBA", "cliente": Decimal("5853"), "NombreCliente": "CLIENTE DE PRUEBA ", "Contado": 1,
                 "PreFacturador": "FACTURADOR DE PRUEBA", "Codigo": "5741 ", "Descripcion": "PRODUCTO DE PRUEBA", "Und": "UND       ",
                 "Cantidad": 2.0, "Precio": 150.25, "TotalVenta": 300.5, "MontoITBIS": 45.84}]

    monkeypatch.setattr(fuentes, "consultar", falsa)
    return pedidas


@pytest.mark.parametrize("malo", [None, {}, {"numero": "1"}, {"numero": 0}, {"numero": True}, {"numero": 1.5}])
def test_numero_malo(malo):
    with pytest.raises(ValueError):
        puente_cotizaciones.numero_de(malo)


def test_factura_con_sus_lineas_y_el_numero_como_parametro(factura_falsa):
    f = puente_cotizaciones.factura(1010391175)
    assert factura_falsa[0]["parametros"] == {"numero": 1010391175}
    assert "1010391175" not in factura_falsa[0]["sql"]
    assert f["encontrada"] is True and f["fecha"] == "2026-07-02T10:00:00.360Z"
    assert f["ncf"] == "B0100000001" and f["contado"] is True and f["cliente"] == 5853
    assert f["lineas"] == [{"codigo": "5741", "descripcion": "PRODUCTO DE PRUEBA", "unidad": "UND", "cantidad": 2.0,
                            "precio": 150.25, "total": 300.5, "itbis": 45.84}]


def test_factura_que_no_esta(factura_falsa):
    assert puente_cotizaciones.factura(404) == {"encontrada": False, "numero": 404, "datosHasta": "2026-10-19T15:12:06.913Z"}


def test_ruta_factura_con_y_sin_clave(cliente, monkeypatch, factura_falsa):
    assert cliente.post(RUTA_FACTURA, json={"numero": 1}).status_code == 404
    monkeypatch.setenv("JARVIS_REACTIVACION_CLAVE", CLAVE)
    assert cliente.post(RUTA_FACTURA, json={"numero": 1}).status_code == 401
    assert factura_falsa == []
    r = cliente.post(RUTA_FACTURA, json={"numero": 1010391175}, headers={"Authorization": f"Bearer {CLAVE}"})
    assert r.status_code == 200 and r.json()["lineas"][0]["codigo"] == "5741"
    assert cliente.post(RUTA_FACTURA, json={"numero": "x"}, headers={"Authorization": f"Bearer {CLAVE}"}).status_code == 400
