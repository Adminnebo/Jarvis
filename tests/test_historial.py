"""Margen de un producto en las cotizaciones de JH ya hechas, con el costo de la
ultima compra antes de cada una."""

import json
from datetime import datetime

import pytest

from backend import cotizaciones, herramientas

CABLE = {"Codigo": "9679", "CodigoLimpio": "9679", "Descripcion": "KEYARD ALAMBRE THHN #12 NEGRO",
         "Und": "PIES", "costo": 11.03, "TipoItbis": 18}
# La mas reciente primero, como las ordena la consulta.
LINEAS = [
    {"nfactura": 3760, "cantidad": 1000.0, "precio": 12.83, "fecha": datetime(2026, 10, 26),
     "cliente": "FERRETERIA A", "confirmada": 1},
    {"nfactura": 3500, "cantidad": 500.0, "precio": 14.97, "fecha": datetime(2026, 9, 20),
     "cliente": "FERRETERIA B", "confirmada": 0},
    {"nfactura": 3100, "cantidad": 200.0, "precio": 14.0, "fecha": datetime(2026, 6, 1),
     "cliente": "FERRETERIA C", "confirmada": 1},
]
COMPRAS = [
    {"Fecha": datetime(2026, 8, 14), "Costo": 10.0},
    {"Fecha": datetime(2026, 9, 28), "Costo": 11.0},
]


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
            return LINEAS if "'9679'" in sql and "2030" not in sql else []
        if "List_ComprasIA" in sql:
            return COMPRAS if "'9679'" in sql else []
        if "List_ProductosIA" in sql:
            if "Codigo IN ('9679')" in sql or "LIKE '%NEGRO%'" in sql:
                return [CABLE]
            if "LIKE '%KEYARD%'" in sql:
                return [CABLE, {**CABLE, "CodigoLimpio": "9681", "Descripcion": "KEYARD ALAMBRE THHN #12 ROJO"}]
        return []

    monkeypatch.setattr(cotizaciones, "_consultar", consultar)
    return consultas


def _historial(**argumentos):
    return herramientas.ejecutar("margen_historico", json.dumps(argumentos), "admin")


def test_cada_cotizacion_usa_la_ultima_compra_antes_de_su_fecha(base):
    texto = _historial(producto="9679")
    # 3760 (26-oct) -> compra del 28-sep a 11; 3500 (20-sep) -> compra del 14-ago a 10;
    # 3100 (1-jun) no tiene compra anterior -> costo actual 11.03.
    # Costo 11000 + 5000 + 2206 = 18206; venta 12830 + 7485 + 2800 = 23115.
    assert "MARGEN GENERAL ESTIMADO: 27.0% sobre el costo" in texto
    assert "ganancia aprox RD$ 4,909.00" in texto
    assert "26-Oct-2026 la 3760 (FERRETERIA A): 1,000 a 12.83, costo 11.00, margen 16.6%" in texto
    assert "20-Sept-2026 la 3500 (FERRETERIA B): 500 a 14.97, costo 10.00, margen 49.7%" in texto
    assert "en 1 linea(s) sin compra anterior, el costo actual" in texto
    # Las confirmadas aparte: 3760 y 3100 -> costo 13206, venta 15630.
    assert "Solo las confirmadas (2): margen 18.4%" in texto


def test_las_ultimas_n_cotizaciones(base):
    texto = _historial(producto="9679", ultimas="1")
    assert "1 linea(s) en 1 cotizacion(es)" in texto and "margen 16.6%" in texto


def test_el_periodo_va_al_sql_y_la_consulta_trae_muchas_filas(base):
    _historial(producto="9679", desde="2026-09-01", hasta="2026-10-31")
    sql, limite = next((s, l) for s, l in base if "dCotizacionesWebIA" in s)
    assert "h.fecha >= '2026-09-01'" in sql and "DATEADD(day, 1, '2026-10-31')" in sql
    assert "h.nulo = 0" in sql and "GROUP BY nfactura" in sql
    assert limite > 1000


def test_fecha_mal_escrita(base):
    assert "AAAA-MM-DD" in _historial(producto="9679", desde="septiembre")


def test_por_descripcion_y_si_hay_varios_pregunta(base):
    assert "MARGEN GENERAL ESTIMADO" in _historial(producto="cable negro")
    texto = _historial(producto="keyard")
    assert "Pregunta cual" in texto and "9681" in texto


def test_lo_que_no_va_al_sql(base):
    _historial(producto="cable'; DROP TABLE x --")
    assert not any("DROP TABLE" in s or "';" in s for s, _ in base)


def test_producto_sin_cotizaciones(base):
    assert "no aparece en cotizaciones de JH en ese periodo" in _historial(producto="9679", desde="2030-01-01")


def test_dice_como_se_estimo(base):
    texto = _historial(producto="9679")
    assert "JH no guarda el costo en sus cotizaciones" in texto
    assert "No hagas otras cuentas" in texto


def test_costos_a_la_fecha_en_una_consulta(base):
    from backend import historial

    historial.costos_a_la_fecha(["9679", "3790", "x'; DROP TABLE y --"], "2026-10-28")
    (sql, limite), = [(s, l) for s, l in base if "List_ComprasIA" in s]
    assert "IN ('3790', '9679')" in sql and "DROP" not in sql
    assert "DATEADD(day, 1, '2026-10-28')" in sql and "ROW_NUMBER()" in sql
    assert limite == 2
    assert historial.costos_a_la_fecha(["9679"], "ayer") == {}
