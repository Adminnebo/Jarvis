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
import statistics
from datetime import date, datetime

from . import cotizaciones, margenes
from .cotizaciones import ErrorCotizacion, _num, _texto, fecha_de_documento

MAX_FILAS = 5000
MAX_RECIENTES = 5
# Ventana de "lo que se suele cotizar". JH tiene cotizaciones desde 2026-05-31.
DIAS_REFERENCIA = 180
# Con menos cotizaciones que esto no se habla de "lo normal": se dicen los precios.
MIN_PARA_NORMAL = 4
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


# --------------------------------------------------------------------------
# A cuanto se ha cotizado: referencia de precio por producto
# --------------------------------------------------------------------------

def _codigo_cliente(valor) -> str:
    try:
        return str(int(float(valor)))
    except (TypeError, ValueError):
        return _texto(valor)


def referencias(codigos: list[str], cliente: str = "", excluir: int | None = None) -> dict[str, dict]:
    """Lo que se cotizo de cada producto en las cotizaciones de JH de los
    ultimos DIAS_REFERENCIA dias, en una sola consulta.

    Por codigo: cuantas cotizaciones, minimo, cuartiles y maximo del precio,
    la ultima y la ultima a `cliente` (su codigo). `excluir` es la cotizacion
    que se esta mirando: no cuenta como referencia de si misma.
    """
    codigos = sorted({c for c in codigos if cotizaciones.CODIGO.match(c or "")})
    if not codigos:
        return {}
    lista = ", ".join(f"'{c}'" for c in codigos)
    sin_esa = f" AND d.nfactura <> {int(excluir)}" if excluir else ""
    filas = cotizaciones._consultar(
        "SELECT LTRIM(RTRIM(d.codigo)) AS codigo, d.precio, d.nfactura, h.fecha, h.cliente, "
        "h.cliente_codigo FROM dbo.dCotizacionesWebIA d JOIN ("
        "SELECT nfactura, MIN(fecha) AS fecha, MAX(clientenombre) AS cliente, "
        "MAX(cliente) AS cliente_codigo, MAX(CASE WHEN nulo = 1 THEN 1 ELSE 0 END) AS nulo "
        "FROM dbo.iCotizacionesWebIA GROUP BY nfactura) h ON h.nfactura = d.nfactura "
        f"WHERE LTRIM(RTRIM(d.codigo)) IN ({lista}) AND h.nulo = 0 AND d.precio > 0{sin_esa} "
        f"AND h.fecha >= DATEADD(day, -{DIAS_REFERENCIA}, GETDATE()) "
        "ORDER BY h.fecha DESC, d.nfactura DESC",
        limite=MAX_FILAS,
    )
    cliente = _codigo_cliente(cliente) if str(cliente or "").strip() else ""
    por_codigo: dict[str, list[dict]] = {}
    for f in filas:
        por_codigo.setdefault(_texto(f.get("codigo")).upper(), []).append(f)
    resultado = {}
    for codigo, lineas in por_codigo.items():
        precios = sorted(float(l["precio"]) for l in lineas)
        ultima = lineas[0]
        al_cliente = next((l for l in lineas
                           if cliente and _codigo_cliente(l.get("cliente_codigo")) == cliente), None)
        ref = {
            "n": len({l["nfactura"] for l in lineas}),
            "minimo": precios[0], "maximo": precios[-1],
            "mediana": statistics.median(precios),
            "ultima": _resumen_linea(ultima),
            "al_cliente": _resumen_linea(al_cliente) if al_cliente else None,
            "precios": [float(l["precio"]) for l in lineas[:MAX_RECIENTES]],
        }
        if ref["n"] >= MIN_PARA_NORMAL:
            cuartiles = statistics.quantiles(precios, n=4, method="inclusive")
            ref["p25"], ref["p75"] = cuartiles[0], cuartiles[2]
        resultado[codigo] = ref
    return resultado


def _resumen_linea(linea: dict) -> dict:
    cuando = _fecha(linea.get("fecha"))
    return {"precio": float(linea["precio"]), "nfactura": int(linea["nfactura"]),
            "cliente": _texto(linea.get("cliente")),
            "fecha": fecha_de_documento(cuando) if cuando else ""}


def bajo_lo_normal(precio: float, ref: dict | None, lista: float | None = None) -> bool:
    """Por debajo del cuartil de abajo de lo que se suele cotizar (con margen
    de 1 % para no avisar por centavos).

    Casi todo se cotiza de P1 a P3: un cliente grande (P4..P7) siempre saldria
    "bajo". Por eso no cuenta si el precio llega a su precio de lista (`lista`,
    el de su nivel) o a lo que ya se le dio a ese mismo cliente."""
    if not (ref and ref.get("p25") and precio < ref["p25"] * 0.99):
        return False
    if lista and precio >= lista - 0.005:
        return False
    cliente = ref.get("al_cliente")
    return not (cliente and precio >= cliente["precio"] - 0.005)


def texto_de_referencia(ref: dict | None, precio: float | None = None,
                        lista: float | None = None) -> str:
    """Una frase: a cuanto se suele cotizar y, si se sabe, a cuanto se le dio a
    este cliente."""
    if not ref:
        return "no se ha cotizado en los ultimos 6 meses"
    if ref.get("p25"):
        texto = (f"se suele cotizar entre {_num(ref['p25'])} y {_num(ref['p75'])} (mediana "
                 f"{_num(ref['mediana'])}, de {_num(ref['minimo'])} a {_num(ref['maximo'])}, "
                 f"{ref['n']} cotizaciones)")
    else:
        texto = (f"se cotizo {ref['n']} {'vez' if ref['n'] == 1 else 'veces'}, a: "
                 + ", ".join(_num(p) for p in ref["precios"]))
    if ref.get("al_cliente"):
        c = ref["al_cliente"]
        texto += f"; a este cliente, la ultima vez a {_num(c['precio'])} ({c['fecha']}, la {c['nfactura']})"
    if precio is not None and bajo_lo_normal(precio, ref, lista):
        texto += "; ESTA POR DEBAJO DE LO NORMAL"
    elif (precio is not None and ref["n"] >= 2 and precio < ref["minimo"] - 0.005
          and not (lista and precio >= lista - 0.005)):
        texto += "; es el precio mas bajo al que se ha cotizado"
    return texto


def precios_dados(producto: str, cliente: str = "") -> str:
    """A cuanto se ha cotizado un producto, y a cuanto a un cliente."""
    fila = _producto(producto)
    codigo = _texto(fila.get("CodigoLimpio") or fila.get("Codigo")).upper()
    descripcion = _texto(fila.get("Descripcion"))
    datos_cliente = None
    if (cliente or "").strip():
        encontrados = cotizaciones.buscar_cliente(cliente)
        if not encontrados:
            raise ErrorCotizacion(f"No encontre el cliente '{cliente}'.")
        if len(encontrados) > 1:
            opciones = "; ".join(f"{_texto(f['nombre'])} (codigo {f['codigo']})" for f in encontrados[:5])
            raise ErrorCotizacion(f"'{cliente}' coincide con varios clientes: {opciones}. Pregunta cual.")
        datos_cliente = encontrados[0]
    ref = referencias([codigo], datos_cliente["codigo"] if datos_cliente else "").get(codigo)
    costo = margenes.costo_de_fila(fila)
    texto = f"{descripcion} (cod {codigo}): {texto_de_referencia(ref)}."
    if datos_cliente and ref and not ref.get("al_cliente"):
        texto += f" A {_texto(datos_cliente['nombre'])} no se le ha cotizado en los ultimos 6 meses."
    if ref:
        u = ref["ultima"]
        texto += f" La mas reciente: {_num(u['precio'])} a {u['cliente']} ({u['fecha']}, la {u['nfactura']})."
        if costo and ref.get("p25"):
            texto += (f" Con el costo de hoy ({_num(costo)}), a la mediana deja "
                      f"{margenes.margen(ref['mediana'], costo):.1f}% sobre el costo y al precio "
                      f"mas bajo {margenes.margen(ref['minimo'], costo):.1f}%.")
    niveles = ", ".join(f"{n} {_num(float(fila.get(n) or 0))}" for n in cotizaciones.NIVELES
                        if float(fila.get(n) or 0) > 0)
    if niveles:
        texto += f" Precios de lista hoy: {niveles}."
    return texto + (" Son cotizaciones de JH (no ventas confirmadas). Por voz di el rango normal y, "
                    "si hay, el ultimo precio a ese cliente; lo demas si lo piden.")
