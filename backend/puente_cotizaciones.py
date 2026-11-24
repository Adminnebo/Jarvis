"""Puente de ventas por producto para el cruce de cotizaciones del panel de JH.

El cruce por productos (jh-panel-completo, cotizaciones/cruceProductos.js) compara los
productos de cada cotizacion de Camila con las facturas del cliente. Esas lineas viven en
List_VentasxProductosIA de Nueva Data JH (gemelo-kpi), que solo acepta este servidor.

Entra con la misma clave del panel de JH que Reactivacion (JARVIS_REACTIVACION_CLAVE, ver
puente_reactivacion.py); sin ella la ruta responde como si no existiera. Quien llama manda
un rango de fechas y codigos de cliente, nunca SQL: las fechas van como parametro y los
clientes se validan como enteros antes de ir al IN.

Las fechas del ERP no traen zona: salen marcadas como UTC ("...Z"), que es como las lee el
panel cuando va directo con el driver de MSSQL.
"""

from datetime import datetime, timedelta
from decimal import Decimal

from . import fuentes, puente_reactivacion

FUENTE_POR_DEFECTO = puente_reactivacion.FUENTE_POR_DEFECTO  # Nueva Data JH

MAXIMO_DIAS = 400          # el retro va desde la primera cotizacion (may-2026) con margen
MAXIMO_CLIENTES = 6000
TANDA = 500                # clientes por consulta
LIMITE = 300_000           # lineas por tanda

SQL_LINEAS = """
SELECT nfactura, FechaHora, cliente, Codigo, Cantidad, TotalVenta FROM dbo.List_VentasxProductosIA
 WHERE FechaHora >= %(desde)s AND FechaHora <= %(hasta)s AND cliente IN ({clientes})
"""
SQL_HASTA = "SELECT MAX(FechaHora) AS hasta FROM dbo.List_VentasxProductosIA"


def _fecha(texto) -> datetime:
    if not isinstance(texto, str) or not texto.strip():
        raise ValueError("Faltan las fechas 'desde' y 'hasta' (ISO).")
    try:
        f = datetime.fromisoformat(texto.strip().replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("Las fechas tienen que ser ISO (AAAA-MM-DDTHH:MM:SSZ).") from None
    return f.replace(tzinfo=None)


def pedido_de(cuerpo) -> dict:
    """Valida lo que manda el panel. Devuelve fechas ISO sin zona y los clientes como enteros."""
    if not isinstance(cuerpo, dict):
        raise ValueError("Se espera un JSON con desde, hasta y clientes.")
    desde, hasta = _fecha(cuerpo.get("desde")), _fecha(cuerpo.get("hasta"))
    if hasta <= desde:
        raise ValueError("'hasta' tiene que ser despues de 'desde'.")
    if hasta - desde > timedelta(days=MAXIMO_DIAS):
        raise ValueError(f"El rango no puede pasar de {MAXIMO_DIAS} dias.")
    clientes = cuerpo.get("clientes")
    if not isinstance(clientes, list) or not clientes:
        raise ValueError("Faltan los clientes.")
    if len(clientes) > MAXIMO_CLIENTES:
        raise ValueError(f"No mas de {MAXIMO_CLIENTES} clientes por pedido.")
    if not all(isinstance(c, int) and not isinstance(c, bool) and c > 0 for c in clientes):
        raise ValueError("Los clientes tienen que ser codigos enteros positivos.")
    return {"desde": _sql(desde), "hasta": _sql(hasta), "clientes": sorted(set(clientes), key=clientes.index)}


def _sql(f: datetime) -> str:
    """Texto que SQL Server convierte a datetime: a lo mas 3 decimales (isoformat da 6 y falla)."""
    return f.strftime("%Y-%m-%dT%H:%M:%S.") + f"{f.microsecond // 1000:03d}"


def _iso(f) -> str | None:
    if f is None:
        return None
    return f.strftime("%Y-%m-%dT%H:%M:%S.") + f"{f.microsecond // 1000:03d}Z"


def _num(x):
    if isinstance(x, Decimal):
        return int(x) if x == x.to_integral_value() else float(x)
    return x


def ventas_productos(pedido: dict) -> dict:
    """Lineas de factura de esos clientes en el rango y la ultima venta que tiene la vista."""
    id_fuente = puente_reactivacion.fuente()
    parametros = {"desde": pedido["desde"], "hasta": pedido["hasta"]}
    filas = []
    clientes = pedido["clientes"]
    for i in range(0, len(clientes), TANDA):
        lote = ",".join(str(int(c)) for c in clientes[i:i + TANDA])
        for f in fuentes.consultar(id_fuente, SQL_LINEAS.format(clientes=lote), LIMITE, parametros=parametros):
            filas.append({"nfactura": _num(f["nfactura"]), "FechaHora": _iso(f["FechaHora"]), "cliente": _num(f["cliente"]),
                          "Codigo": str(f["Codigo"] or "").strip(), "Cantidad": float(f["Cantidad"] or 0),
                          "TotalVenta": float(f["TotalVenta"] or 0)})
    hasta = fuentes.consultar(id_fuente, SQL_HASTA, 1)
    return {"filas": filas, "datosHasta": _iso(hasta[0]["hasta"]) if hasta else None}
