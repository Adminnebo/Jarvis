"""Margen por cliente en las cotizaciones de JH, con el costo de la ultima compra
hasta cada fecha."""

import json
from datetime import datetime

import pytest

from backend import cotizaciones, herramientas

# El 6177 tiene dos cotizaciones; el 4926, una.
LINEAS = [
    {"codigo": "9681", "cantidad": 100.0, "precio": 13.0, "nfactura": 10, "fecha": datetime(2026, 9, 10),
     "cliente": "FERRETERIA ELIAM MAX EIRL", "cliente_codigo": 6177, "confirmada": 1},
    {"codigo": "3790", "cantidad": 2.0, "precio": 150.0, "nfactura": 10, "fecha": datetime(2026, 9, 10),
     "cliente": "FERRETERIA ELIAM MAX EIRL", "cliente_codigo": 6177, "confirmada": 1},
    {"codigo": "9681", "cantidad": 100.0, "precio": 11.0, "nfactura": 11, "fecha": datetime(2026, 10, 5),
     "cliente": "FERRETERIA ELIAM MAX EIRL", "cliente_codigo": 6177, "confirmada": 0},
    {"codigo": "9681", "cantidad": 100.0, "precio": 15.0, "nfactura": 12, "fecha": datetime(2026, 10, 6),
     "cliente": "FERRETERIA OTRA", "cliente_codigo": 4926, "confirmada": 1},
]
# El breaker no tiene compras: va con el costo de hoy del catalogo.
COMPRAS = [
    {"Codigo": "9681", "Fecha": datetime(2026, 9, 1), "Costo": 10.0},
    {"Codigo": "9681", "Fecha": datetime(2026, 10, 1), "Costo": 10.5},
]
CATALOGO = [
    {"Codigo": "9681", "Descripcion": "KEYARD ALAMBRE THHN #12 ROJO", "costo": 10.8},
    {"Codigo": "3790", "Descripcion": "BREAKER 2P 40AMP", "costo": 100.0},
]
CLIENTE = {"codigo": 6177, "nombre": "FERRETERIA ELIAM MAX EIRL", "rnc": "131832334", "direccion": "",
           "email": None, "telefono1": "", "Celular": "", "NivelPrecio": "P4", "factor": 1.0}


@pytest.fixture
def base(entorno_limpio, monkeypatch):
    monkeypatch.setenv("JARVIS_FUENTE_CATALOGO", "656ef47a")
    monkeypatch.setenv("JARVIS_PDF_KEY", "x")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "llave")
    monkeypatch.setenv("SUPABASE_PROJECT_REF", "abcdefghijklmnopqrst")
    monkeypatch.setenv("JARVIS_BUCKET_COTIZACIONES", "b")
    consultas = []

    def consultar(sql, limite=60):
        consultas.append((sql, limite))
        if "dCotizacionesWebIA" in sql:
            if "h.fecha >= '2026-10-01'" in sql:
                return [l for l in LINEAS if l["fecha"] >= datetime(2026, 10, 1)]
            return LINEAS
        if "List_ComprasIA" in sql:
            return COMPRAS
        if "List_ProductosIA" in sql:
            return CATALOGO
        if "List_ClientesIA" in sql:
            return [CLIENTE] if "6177" in sql or "ELIAM" in sql else []
        return []

    monkeypatch.setattr(cotizaciones, "_consultar", consultar)
    return consultas


def _margen(**argumentos):
    return herramientas.ejecutar("margen_por_cliente", json.dumps(argumentos), "admin")


def test_un_cliente_contra_el_promedio(base):
    texto = _margen(cliente="6177")
    # 10: keyard 1300/1000 (compra 1-sep), breaker 300/200 (costo de hoy).
    # 11: keyard 1100/1050 (compra 1-oct). -> venta 2700, costo 2250: 20.0%.
    # Todos: + la 12 del otro, 1500/1050 -> 4200/3300: 27.3%.
    assert "MARGEN GENERAL ESTIMADO: 20.0% sobre el costo (ganancia aprox RD$ 450.00)" in texto
    assert "El general de todos los clientes en el mismo periodo es 27.3% (le ganas menos" in texto
    assert "Solo las confirmadas (1): 33.3%" in texto
    assert "Por mes: sep 33.3%, oct 4.8%" in texto
    assert "Donde menos le ganas (de lo que mas pesa): KEYARD ALAMBRE THHN #12 ROJO (cod 9681) 17.1%" in texto
    assert "1 linea(s) sin compra con el costo de hoy" in texto


def test_todos_los_clientes(base):
    texto = _margen()
    assert "2 clientes, venta RD$ 4,200.00, MARGEN GENERAL ESTIMADO 27.3%" in texto
    assert ("Los de mas venta: FERRETERIA ELIAM MAX EIRL 20.0% en RD$ 2,700.00; "
            "FERRETERIA OTRA 42.9% en RD$ 1,500.00") in texto


def test_el_periodo_va_al_sql(base):
    texto = _margen(cliente="ELIAM", desde="2026-10-01")
    assert "MARGEN GENERAL ESTIMADO: 4.8%" in texto
    lineas = next(s for s, _ in base if "dCotizacionesWebIA" in s)
    assert "h.fecha >= '2026-10-01'" in lineas and "h.nulo = 0" in lineas
    # Pocos codigos: compras y catalogo solo de los de ese periodo.
    compras = next(s for s, _ in base if "List_ComprasIA" in s)
    assert "IN ('9681')" in compras


def test_cliente_que_no_existe_y_fecha_mala(base):
    assert "No encontre el cliente" in _margen(cliente="nadie")
    assert "AAAA-MM-DD" in _margen(desde="ayer")
