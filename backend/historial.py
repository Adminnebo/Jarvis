"""Margen de un producto en las cotizaciones de JH que ya se hicieron.

El detalle de las cotizaciones de JH (dCotizacionesWebIA) guarda el precio pero
NO el costo (viene en 0). El costo de cada cotizacion se estima con la ultima
COMPRA del producto antes de su fecha (List_ComprasIA, que esta en la misma base
que el catalogo: el costo del catalogo es la ultima compra). Si no hubo compra
antes, se usa el costo actual del catalogo. Siempre es una aproximacion, y la
respuesta lo dice.

Todo el calculo pasa aqui: antes el modelo hacia la cuenta de cabeza.
"""

import bisect
import re
from datetime import date, datetime

from . import cotizaciones, margenes
from .cotizaciones import ErrorCotizacion, _num, _texto, fecha_de_documento

MAX_FILAS = 5000
MAX_RECIENTES = 5
FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _producto(texto: str) -> dict:
    """La fila del catalogo de lo que se nombro: el codigo, o palabras de la
    descripcion si dan un solo producto."""
    texto = (texto or "").strip()
    if not texto:
        raise ErrorCotizacion("Falta decir de que producto.")
    if re.fullmatch(r"[A-Za-z0-9-]{1,20}", texto):
        fila = cotizaciones.productos_del_catalogo([texto.upper()]).get(texto.upper())
        if fila:
            return fila
    # Solo letras y cifras van al SQL: lo demas se descarta.
    palabras = [p for p in re.findall(r"[A-Za-z0-9]+", texto.upper()) if len(p) > 1][:6]
    if not palabras:
        raise ErrorCotizacion(f"No encontre el producto '{texto}'.")
    filtro = " AND ".join(f"UPPER(Descripcion) LIKE '%{p}%'" for p in palabras)
    filas = cotizaciones._consultar(f"SELECT TOP 8 *, LTRIM(RTRIM(Codigo)) AS CodigoLimpio "
                       f"FROM dbo.List_ProductosIA WHERE {filtro}")
    if len(filas) == 1:
        return filas[0]
    if not filas:
        raise ErrorCotizacion(f"No encontre el producto '{texto}'. Buscalo con buscar_en_fuente "
                              "y pasa su codigo.")
    opciones = "; ".join(f"{_texto(f.get('CodigoLimpio'))} {_texto(f.get('Descripcion'))}"
                         for f in filas[:6])
    raise ErrorCotizacion(f"'{texto}' coincide con varios productos: {opciones}. Pregunta cual.")


def _lineas(codigo: str, desde: str, hasta: str) -> list[dict]:
    """Las lineas de ese producto en cotizaciones de JH no anuladas, la mas
    reciente primero. La cabecera tiene numeros repetidos: se agrupa para no
    contar una linea dos veces."""
    filtros = [f"LTRIM(RTRIM(d.codigo)) = '{codigo}'", "h.nulo = 0"]
    if desde:
        filtros.append(f"h.fecha >= '{desde}'")
    if hasta:
        filtros.append(f"h.fecha < DATEADD(day, 1, '{hasta}')")
    return cotizaciones._consultar(
        "SELECT d.nfactura, d.cantidad, d.precio, h.fecha, h.cliente, h.confirmada "
        "FROM dbo.dCotizacionesWebIA d JOIN ("
        "SELECT nfactura, MIN(fecha) AS fecha, MAX(clientenombre) AS cliente, "
        "MAX(CASE WHEN confirmada = 1 THEN 1 ELSE 0 END) AS confirmada, "
        "MAX(CASE WHEN nulo = 1 THEN 1 ELSE 0 END) AS nulo "
        "FROM dbo.iCotizacionesWebIA GROUP BY nfactura) h ON h.nfactura = d.nfactura "
        f"WHERE {' AND '.join(filtros)} ORDER BY h.fecha DESC, d.nfactura DESC",
        limite=MAX_FILAS,
    )


def _compras(codigo: str) -> list[tuple[datetime, float]]:
    filas = cotizaciones._consultar(
        f"SELECT Fecha, Costo FROM dbo.List_ComprasIA WHERE Codigo = '{codigo}' "
        "AND Costo > 0 ORDER BY Fecha",
        limite=MAX_FILAS,
    )
    return [(_fecha(f["Fecha"]), float(f["Costo"])) for f in filas if _fecha(f["Fecha"])]


def costos_a_la_fecha(codigos: list[str], dia: str) -> dict[str, float]:
    """El costo de la ultima compra de cada producto hasta ese dia (AAAA-MM-DD),
    en una sola consulta. Los que no tienen compra antes no aparecen."""
    codigos = sorted({c for c in codigos if cotizaciones.CODIGO.match(c or "")})
    if not codigos or not FECHA.match(dia or ""):
        return {}
    lista = ", ".join(f"'{c}'" for c in codigos)
    filas = cotizaciones._consultar(
        "SELECT Codigo, Costo FROM (SELECT LTRIM(RTRIM(Codigo)) AS Codigo, Costo, "
        "ROW_NUMBER() OVER (PARTITION BY LTRIM(RTRIM(Codigo)) ORDER BY Fecha DESC) AS n "
        f"FROM dbo.List_ComprasIA WHERE LTRIM(RTRIM(Codigo)) IN ({lista}) AND Costo > 0 "
        f"AND Fecha < DATEADD(day, 1, '{dia}')) x WHERE n = 1",
        limite=len(codigos),
    )
    return {_texto(f.get("Codigo")).upper(): float(f["Costo"]) for f in filas
            if f.get("Codigo") and f.get("Costo")}


def _fecha(valor) -> datetime | None:
    if isinstance(valor, datetime):
        return valor.replace(tzinfo=None)
    if isinstance(valor, date):
        return datetime(valor.year, valor.month, valor.day)
    try:
        return datetime.fromisoformat(str(valor).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _leer_fecha(texto: str, que: str) -> str:
    texto = (texto or "").strip()
    if texto and not FECHA.match(texto):
        raise ErrorCotizacion(f"La fecha '{que}' tiene que ir como AAAA-MM-DD: '{texto}'.")
    return texto


def margen_historico(producto: str, desde: str = "", hasta: str = "", ultimas="") -> str:
    fila = _producto(producto)
    codigo = _texto(fila.get("CodigoLimpio") or fila.get("Codigo")).upper()
    descripcion = _texto(fila.get("Descripcion"))
    desde, hasta = _leer_fecha(desde, "desde"), _leer_fecha(hasta, "hasta")

    lineas = _lineas(codigo, desde, hasta)
    if str(ultimas or "").strip():
        try:
            n = max(1, int(float(str(ultimas))))
        except ValueError:
            raise ErrorCotizacion(f"'ultimas' no es un numero: '{ultimas}'.") from None
        cotizaciones = []
        for linea in lineas:
            if linea["nfactura"] not in cotizaciones:
                cotizaciones.append(linea["nfactura"])
        lineas = [l for l in lineas if l["nfactura"] in cotizaciones[:n]]
    if not lineas:
        return (f"{descripcion} (cod {codigo}) no aparece en cotizaciones de JH"
                + (" en ese periodo." if desde or hasta else "."))

    compras = _compras(codigo)
    fechas_compra = [f for f, _ in compras]
    costo_actual = margenes.costo_de_fila(fila)
    calculadas, con_actual, sin_costo = [], 0, 0
    for linea in lineas:
        cuando = _fecha(linea["fecha"])
        i = bisect.bisect_right(fechas_compra, cuando) if cuando else 0
        if i:
            costo = compras[i - 1][1]
        elif costo_actual:
            costo, con_actual = costo_actual, con_actual + 1
        else:
            sin_costo += 1
            continue
        calculadas.append({**linea, "cuando": cuando, "costo": costo,
                           "cantidad": float(linea["cantidad"] or 0),
                           "precio": float(linea["precio"] or 0)})
    if not calculadas:
        return (f"{descripcion} (cod {codigo}) aparece en {len(lineas)} linea(s) de cotizaciones "
                "de JH, pero no tiene costo ni en compras ni en el catalogo: no se puede "
                "estimar el margen.")

    def resumen(filas):
        costo = sum(f["costo"] * f["cantidad"] for f in filas)
        venta = sum(f["precio"] * f["cantidad"] for f in filas)
        return costo, venta, (venta - costo) / costo * 100 if costo else None

    costo, venta, margen = resumen(calculadas)
    confirmadas = [f for f in calculadas if f["confirmada"]]
    cantidad = sum(f["cantidad"] for f in calculadas)
    precios = [f["precio"] for f in calculadas]
    costos = [f["costo"] for f in calculadas]
    numeros = {f["nfactura"] for f in calculadas}
    primero = min(f["cuando"] for f in calculadas if f["cuando"])
    ultimo = max(f["cuando"] for f in calculadas if f["cuando"])

    texto = (
        f"{descripcion} (cod {codigo}) en cotizaciones de JH, del {fecha_de_documento(primero)} "
        f"al {fecha_de_documento(ultimo)}: {len(calculadas)} linea(s) en {len(numeros)} "
        f"cotizacion(es), {cantidad:,.0f} {_texto(fila.get('Und')) or 'UND'}, venta RD$ {_num(venta)}. "
        f"MARGEN GENERAL ESTIMADO: {margen:.1f}% sobre el costo (ganancia aprox RD$ "
        f"{_num(venta - costo)}). Precio cotizado de {_num(min(precios))} a {_num(max(precios))} "
        f"(promedio {_num(venta / cantidad if cantidad else 0)}); costo usado de "
        f"{_num(min(costos))} a {_num(max(costos))}"
        + (f"; costo actual {_num(costo_actual)}" if costo_actual else "") + ". "
    )
    if confirmadas and len(confirmadas) < len(calculadas):
        texto += (f"Solo las confirmadas ({len({f['nfactura'] for f in confirmadas})}): margen "
                  f"{resumen(confirmadas)[2]:.1f}%. ")
    texto += "Las mas recientes: " + "; ".join(
        f"{fecha_de_documento(f['cuando'])} la {int(f['nfactura'])} ({_texto(f['cliente'])}): "
        f"{f['cantidad']:,.0f} a {_num(f['precio'])}, costo {_num(f['costo'])}, margen "
        f"{(f['precio'] - f['costo']) / f['costo'] * 100:.1f}%"
        for f in calculadas[:MAX_RECIENTES]
    ) + ". "
    texto += (
        "COMO SE ESTIMO (dilo en una frase al dar el numero): JH no guarda el costo en sus "
        "cotizaciones; para cada una se tomo el costo de la ultima compra antes de su fecha"
        + (f", y en {con_actual} linea(s) sin compra anterior, el costo actual" if con_actual else "")
        + (f". {sin_costo} linea(s) quedaron fuera por no tener costo" if sin_costo else "")
        + ". Es aproximado. No hagas otras cuentas: usa estas cifras."
    )
    return texto
