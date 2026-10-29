"""Margenes sobre el costo: por producto, general y precio minimo."""

import pytest

from backend import margenes


def _linea(precio, costo, cantidad=1, tasa=18):
    return margenes.con_precio({"cantidad": cantidad, "TipoItbis": tasa, "costo": costo}, precio)


def test_el_margen_es_sobre_el_costo():
    # Decision del 2026-10-29: costo 100 con 50% sale a 150, no a 200.
    assert margenes.margen(150, 100) == 50
    assert margenes.precio_con_margen(100, 50) == 150
    assert margenes.margen(150, None) is None


def test_con_precio_recalcula_itbis_y_subtotal():
    linea = _linea(118, 50, cantidad=3)
    assert linea["precio_unitario"] == 118
    assert round(linea["precio_bruto"], 2) == 100
    assert round(linea["itbis_linea"], 2) == 54
    assert linea["subtotal_linea"] == 354


def test_el_general_va_ponderado_por_lo_que_pesa_cada_producto():
    # Uno barato regalado casi no mueve el general; lo que pesa es el caro.
    lineas = [_linea(200, 100, cantidad=10), _linea(1, 2, cantidad=1)]
    analisis = margenes.analizar(lineas)
    assert analisis["costo"] == 1002 and analisis["venta"] == 2001
    assert round(analisis["margen"], 1) == 99.7
    assert analisis["a_perdida"] == [2]


def test_sin_costo_queda_fuera_del_calculo_pero_se_cobra():
    lineas = [_linea(150, 100), _linea(80, None)]
    analisis = margenes.analizar(lineas)
    assert analisis["margen"] == 50 and analisis["sin_costo"] == [2]
    assert analisis["venta_total"] == 230


def test_el_ejemplo_del_audio():
    # Diez productos a costo 30 y precio 50 (66.7%); el 4 baja a 45 y el 5 a 35.
    lineas = [_linea(50, 30) for _ in range(10)]
    antes = margenes.analizar(lineas)["margen"]
    lineas[3] = margenes.con_precio(lineas[3], 45)
    lineas[4] = margenes.con_precio(lineas[4], 35)
    despues = margenes.analizar(lineas)
    assert round(antes, 1) == 66.7
    assert margenes.margen(45, 30) == 50 and round(margenes.margen(35, 30), 1) == 16.7
    # (8*20 + 15 + 5) / 300 = 180 / 300
    assert despues["margen"] == pytest.approx(60.0)


def test_precio_minimo_para_no_romper_el_piso():
    lineas = [_linea(150, 100, cantidad=2), _linea(80, 60, cantidad=5)]
    minimo = margenes.precio_minimo(lineas, 2, 25)
    # Costo total 500 -> hace falta ganar 125; el 1 ya gana 100 -> 5(p - 60) >= 25.
    assert minimo == 65.0
    con_minimo = [lineas[0], margenes.con_precio(lineas[1], minimo)]
    assert margenes.analizar(con_minimo)["margen"] >= 25
    un_centavo_menos = [lineas[0], margenes.con_precio(lineas[1], minimo - 0.01)]
    assert margenes.analizar(un_centavo_menos)["margen"] < 25


def test_precio_minimo_puede_ser_a_perdida_si_el_resto_sobra():
    # Costo total 1060 -> hace falta ganar 265; el 1 ya gana 300 -> p - 60 >= -35.
    lineas = [_linea(130, 100, cantidad=10), _linea(80, 60)]
    assert margenes.precio_minimo(lineas, 2, 25) == 25.0   # el resto aguanta vender este bajo costo


def test_precio_minimo_cero_si_cualquier_precio_cumple():
    lineas = [_linea(10000, 100, cantidad=10), _linea(80, 60)]
    assert margenes.precio_minimo(lineas, 2, 10) == 0


def test_precio_minimo_sin_costo_es_none():
    assert margenes.precio_minimo([_linea(80, None)], 1, 10) is None


def test_la_columna_del_costo_es_fija_y_se_puede_cambiar(monkeypatch):
    assert margenes.costo_de_fila({"Codigo": "1", "costo": 61000.0, "Coste": 5}) == 61000.0
    assert margenes.costo_de_fila({"Codigo": "1", "costo": 0}) is None
    monkeypatch.setenv("JARVIS_COLUMNA_COSTO", "CostoPromedio")
    assert margenes.costo_de_fila({"costopromedio": 7.5, "costo": 9}) == 7.5
