"""Margenes de una cotizacion: por producto, general y precio minimo.

Calculo puro, sin red ni estado. El margen es SOBRE EL COSTO (decision del
2026-10-29): costo 100 con 50% sale a 150. El costo del catalogo de JH esta en
la misma base que sus precios (los dos con ITBIS adentro), asi que se comparan
directo.
"""

import math
import os

COLUMNA_COSTO_POR_DEFECTO = "costo"


def columna_costo() -> str:
    """La columna del costo en el catalogo. Fija: el modelo no la elige, porque
    una columna equivocada daria margenes falsos sin que nadie lo note."""
    return os.getenv("JARVIS_COLUMNA_COSTO", "").strip() or COLUMNA_COSTO_POR_DEFECTO


def costo_de_fila(fila: dict | None) -> float | None:
    """El costo unitario de una fila del catalogo, o None si no tiene."""
    if not fila:
        return None
    nombre = columna_costo().lower()
    clave = next((c for c in fila if str(c).strip().lower() == nombre), None)
    try:
        valor = float(fila.get(clave) or 0) if clave else 0.0
    except (TypeError, ValueError):
        return None
    return valor if valor > 0 else None


def con_precio(linea: dict, precio: float) -> dict:
    """La misma linea con otro precio unitario (ITBIS incluido), con el bruto,
    el ITBIS y el subtotal recalculados igual que calcular_linea."""
    precio = round(float(precio), 2)
    tasa = float(linea.get("TipoItbis") or 0)
    cantidad = float(linea["cantidad"])
    bruto = precio / (1 + tasa / 100)
    return {
        **linea,
        "precio_unitario": precio,
        "precio_bruto": bruto,
        "itbis_linea": (precio - bruto) * cantidad,
        "subtotal_linea": precio * cantidad,
    }


def margen(precio: float, costo: float | None) -> float | None:
    """% sobre el costo, o None si no hay costo."""
    if not costo:
        return None
    return (float(precio) - costo) / costo * 100


def precio_con_margen(costo: float, por_ciento: float) -> float:
    return round(costo * (1 + por_ciento / 100), 2)


def analizar(lineas: list[dict]) -> dict:
    """Costo, venta, ganancia y margen general (sobre el costo).

    Las lineas sin costo no entran en el calculo: se devuelven aparte para
    decir cuantas son. `venta_total` si las incluye, porque es lo que se cobra.
    """
    costo = venta = 0.0
    sin_costo, a_perdida = [], []
    for indice, linea in enumerate(lineas, start=1):
        c = linea.get("costo")
        p = float(linea["precio_unitario"])
        q = float(linea["cantidad"])
        if not c:
            sin_costo.append(indice)
            continue
        costo += c * q
        venta += p * q
        if p < c:
            a_perdida.append(indice)
    ganancia = venta - costo
    return {
        "costo": costo,
        "venta": venta,
        "venta_total": sum(float(l["precio_unitario"]) * float(l["cantidad"]) for l in lineas),
        "ganancia": ganancia,
        "margen": ganancia / costo * 100 if costo else None,
        "sin_costo": sin_costo,
        "a_perdida": a_perdida,
    }


def precio_minimo(lineas: list[dict], indice: int, piso: float) -> float | None:
    """El precio mas bajo de la linea `indice` (1..N) que deja el margen general
    en `piso` % o mas, con las demas lineas como estan.

    0 si cualquier precio cumple. None si la linea no tiene costo.
    """
    linea = lineas[indice - 1]
    c = linea.get("costo")
    if not c:
        return None
    q = float(linea["cantidad"])
    resto = analizar([l for i, l in enumerate(lineas, start=1) if i != indice])
    f = piso / 100
    # (G' + (p - c)q) >= f (C' + c q)  ->  p >= c + (f (C' + c q) - G') / q
    minimo = c + (f * (resto["costo"] + c * q) - resto["ganancia"]) / q
    # Hacia arriba al centavo, para que ese precio si cumpla el piso.
    return max(0.0, math.ceil(minimo * 100 - 1e-6) / 100)
