"""Margen por cliente en las cotizaciones de JH que ya se hicieron.

Igual que historial.py, pero por cliente: el detalle de JH no guarda el costo,
asi que cada linea se estima con la ultima COMPRA del producto hasta la fecha
de su cotizacion (List_ComprasIA), y si no hay, con el costo de hoy del
catalogo. Siempre es una aproximacion y la respuesta lo dice.

La Base JH cancela las consultas caras (tope de costo 3000): un OUTER APPLY
por linea no pasa. Por eso se traen tres listas simples -lineas, compras y
costos del catalogo- y la cuenta se hace aqui. Se traen las lineas de TODOS
los clientes del periodo: asi cada cliente se compara con el general.
"""

import bisect
from collections import defaultdict
from datetime import datetime, timedelta

from . import cotizaciones
from .cotizaciones import ErrorCotizacion, _num, _texto, fecha_de_documento
from .historial import _codigo_cliente, _fecha, _leer_fecha

MAX_LINEAS = 60000
# Una compra de hace mas de esto ya no dice el costo de una cotizacion: se usa
# el costo de hoy.
DIAS_DE_COMPRAS = 545
TOPE_DE_CODIGOS_EN_IN = 400
MAX_PRODUCTOS = 3
MAX_CLIENTES = 8

_MESES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")


def _lineas(desde: str, hasta: str) -> list[dict]:
    filtros = ["h.nulo = 0", "d.precio > 0", "d.cantidad > 0"]
    if desde:
        filtros.append(f"h.fecha >= '{desde}'")
    if hasta:
        filtros.append(f"h.fecha < DATEADD(day, 1, '{hasta}')")
    return cotizaciones._consultar(
        "SELECT LTRIM(RTRIM(d.codigo)) AS codigo, d.cantidad, d.precio, d.nfactura, h.fecha, "
        "h.cliente, h.cliente_codigo, h.confirmada FROM dbo.dCotizacionesWebIA d JOIN ("
        "SELECT nfactura, MIN(fecha) AS fecha, MAX(clientenombre) AS cliente, "
        "MAX(cliente) AS cliente_codigo, MAX(CASE WHEN confirmada = 1 THEN 1 ELSE 0 END) AS confirmada, "
        "MAX(CASE WHEN nulo = 1 THEN 1 ELSE 0 END) AS nulo "
        "FROM dbo.iCotizacionesWebIA GROUP BY nfactura) h ON h.nfactura = d.nfactura "
        f"WHERE {' AND '.join(filtros)}",
        limite=MAX_LINEAS,
    )


def _en(codigos: list[str]) -> str:
    """Filtro por codigo, solo si son pocos: con muchos sale mas barato traer todo."""
    validos = sorted({c for c in codigos if cotizaciones.CODIGO.match(c)})
    if not validos or len(validos) > TOPE_DE_CODIGOS_EN_IN:
        return ""
    return " AND LTRIM(RTRIM(Codigo)) IN (" + ", ".join(f"'{c}'" for c in validos) + ")"


def _compras(codigos: list[str], desde: datetime) -> dict[str, tuple[list[datetime], list[float]]]:
    filas = cotizaciones._consultar(
        "SELECT LTRIM(RTRIM(Codigo)) AS Codigo, Fecha, Costo FROM dbo.List_ComprasIA "
        f"WHERE Costo > 0 AND Fecha >= '{desde:%Y-%m-%d}'{_en(codigos)} ORDER BY Fecha",
        limite=MAX_LINEAS * 2,
    )
    por_codigo: dict[str, tuple[list, list]] = defaultdict(lambda: ([], []))
    for f in filas:
        cuando = _fecha(f.get("Fecha"))
        if cuando:
            fechas, costos = por_codigo[_texto(f.get("Codigo")).upper()]
            fechas.append(cuando)
            costos.append(float(f["Costo"]))
    return por_codigo


def _catalogo(codigos: list[str]) -> dict[str, dict]:
    filas = cotizaciones._consultar(
        "SELECT LTRIM(RTRIM(Codigo)) AS Codigo, Descripcion, costo FROM dbo.List_ProductosIA "
        f"WHERE 1 = 1{_en(codigos)}",
        limite=MAX_LINEAS,
    )
    return {_texto(f.get("Codigo")).upper(): f for f in filas}


def _calcular(lineas: list[dict]) -> tuple[list[dict], dict[str, dict], int]:
    """Cada linea con su costo estimado. Devuelve las que tienen costo, el
    catalogo (para las descripciones) y cuantas usaron el costo de hoy."""
    codigos = sorted({_texto(l.get("codigo")).upper() for l in lineas})
    primera = min((_fecha(l.get("fecha")) for l in lineas if _fecha(l.get("fecha"))),
                  default=datetime.now())
    compras = _compras(codigos, primera - timedelta(days=DIAS_DE_COMPRAS))
    catalogo = _catalogo(codigos)
    calculadas, con_actual = [], 0
    for l in lineas:
        codigo = _texto(l.get("codigo")).upper()
        cuando = _fecha(l.get("fecha"))
        fechas, costos = compras.get(codigo, ([], []))
        i = bisect.bisect_right(fechas, cuando) if cuando else 0
        if i:
            costo = costos[i - 1]
        else:
            try:
                costo = float((catalogo.get(codigo) or {}).get("costo") or 0)
            except (TypeError, ValueError):
                costo = 0.0
            if costo <= 0:
                continue
            con_actual += 1
        cantidad = float(l["cantidad"])
        calculadas.append({
            "codigo": codigo, "cuando": cuando, "nfactura": l["nfactura"],
            "cliente": _texto(l.get("cliente")), "cliente_codigo": _codigo_cliente(l.get("cliente_codigo")),
            "confirmada": bool(l.get("confirmada")),
            "venta": float(l["precio"]) * cantidad, "costo": costo * cantidad,
        })
    return calculadas, catalogo, con_actual


def _resumen(filas: list[dict]) -> dict:
    venta = sum(f["venta"] for f in filas)
    costo = sum(f["costo"] for f in filas)
    return {"venta": venta, "costo": costo, "ganancia": venta - costo,
            "margen": (venta - costo) / costo * 100 if costo else None,
            "cotizaciones": len({f["nfactura"] for f in filas})}


def _pct(valor) -> str:
    return "sin costo" if valor is None else f"{valor:.1f}%"


def _periodo(filas: list[dict]) -> str:
    fechas = [f["cuando"] for f in filas if f["cuando"]]
    if not fechas:
        return ""
    return f"del {fecha_de_documento(min(fechas))} al {fecha_de_documento(max(fechas))}"


def _como_se_estimo(con_actual: int, sin_costo: int) -> str:
    return (
        " COMO SE ESTIMO (dilo en una frase): JH no guarda el costo en sus cotizaciones; cada "
        "linea va con el costo de la ultima compra hasta su fecha"
        + (f", y {con_actual} linea(s) sin compra con el costo de hoy" if con_actual else "")
        + (f"; {sin_costo} linea(s) sin ningun costo quedaron fuera" if sin_costo else "")
        + ". Son cotizaciones, no ventas confirmadas. Es aproximado. No hagas otras cuentas: "
        "usa estas cifras."
    )


def _resolver_cliente(texto: str) -> dict:
    encontrados = cotizaciones.buscar_cliente(texto)
    if not encontrados:
        raise ErrorCotizacion(f"No encontre el cliente '{texto}'.")
    if len(encontrados) > 1:
        exacto = [f for f in encontrados if _texto(f.get("codigo")) == texto.strip()]
        if len(exacto) == 1:
            return exacto[0]
        opciones = "; ".join(f"{_texto(f['nombre'])} (codigo {f['codigo']})" for f in encontrados[:5])
        raise ErrorCotizacion(f"'{texto}' coincide con varios clientes: {opciones}. Pregunta cual.")
    return encontrados[0]


def margen_por_cliente(cliente: str = "", desde: str = "", hasta: str = "") -> str:
    desde, hasta = _leer_fecha(desde, "desde"), _leer_fecha(hasta, "hasta")
    datos_cliente = _resolver_cliente(cliente) if (cliente or "").strip() else None
    lineas = _lineas(desde, hasta)
    if not lineas:
        return "No hay cotizaciones de JH en ese periodo."
    calculadas, catalogo, con_actual = _calcular(lineas)
    sin_costo = len(lineas) - len(calculadas)
    general = _resumen(calculadas)
    if datos_cliente:
        return _de_un_cliente(datos_cliente, calculadas, catalogo, general, con_actual, sin_costo,
                              truncado=len(lineas) >= MAX_LINEAS)
    return _ranking(calculadas, general, con_actual, sin_costo, truncado=len(lineas) >= MAX_LINEAS)


def _de_un_cliente(datos_cliente: dict, calculadas: list[dict], catalogo: dict, general: dict,
                   con_actual: int, sin_costo: int, truncado: bool) -> str:
    codigo = _codigo_cliente(datos_cliente.get("codigo"))
    nombre = _texto(datos_cliente.get("nombre"))
    suyas = [f for f in calculadas if f["cliente_codigo"] == codigo]
    if not suyas:
        return f"{nombre} (codigo {codigo}) no tiene cotizaciones de JH con costo en ese periodo."
    total = _resumen(suyas)
    confirmadas = [f for f in suyas if f["confirmada"]]
    texto = (
        f"{nombre} (codigo {codigo}), cotizaciones de JH {_periodo(suyas)}: {total['cotizaciones']} "
        f"cotizacion(es), venta RD$ {_num(total['venta'])}. MARGEN GENERAL ESTIMADO: "
        f"{_pct(total['margen'])} sobre el costo (ganancia aprox RD$ {_num(total['ganancia'])}). "
        f"El general de todos los clientes en el mismo periodo es {_pct(general['margen'])}"
        + (" (le ganas menos que al promedio)." if total["margen"] is not None and general["margen"]
           is not None and total["margen"] < general["margen"] - 0.5 else ".")
    )
    if confirmadas and len(confirmadas) < len(suyas):
        texto += f" Solo las confirmadas ({_resumen(confirmadas)['cotizaciones']}): {_pct(_resumen(confirmadas)['margen'])}."

    por_mes = defaultdict(list)
    for f in suyas:
        if f["cuando"]:
            por_mes[(f["cuando"].year, f["cuando"].month)].append(f)
    if len(por_mes) > 1:
        texto += " Por mes: " + ", ".join(
            f"{_MESES[m - 1]} {_pct(_resumen(filas)['margen'])}"
            for (a, m), filas in sorted(por_mes.items())[-6:]) + "."

    por_producto = defaultdict(list)
    for f in suyas:
        por_producto[f["codigo"]].append(f)
    productos = [(c, _resumen(filas)) for c, filas in por_producto.items()]
    # Donde menos le gana: lo que pesa (al menos 2 % de lo que se le cotizo) con menos margen.
    pesan = [p for p in productos if p[1]["venta"] >= total["venta"] * 0.02 and p[1]["margen"] is not None]
    flojos = sorted(pesan, key=lambda p: p[1]["margen"])[:MAX_PRODUCTOS]
    nombre_de = lambda c: _texto((catalogo.get(c) or {}).get("Descripcion")) or c  # noqa: E731
    if flojos:
        texto += " Donde menos le ganas (de lo que mas pesa): " + "; ".join(
            f"{nombre_de(c)} (cod {c}) {_pct(r['margen'])} en RD$ {_num(r['venta'])}" for c, r in flojos) + "."
    perdida = [(c, r) for c, r in productos if r["ganancia"] < 0]
    if perdida:
        texto += " A PERDIDA: " + "; ".join(
            f"{nombre_de(c)} (cod {c}) {_pct(r['margen'])}" for c, r in perdida[:MAX_PRODUCTOS]) + "."
    if truncado:
        texto += " (Hay mas lineas de las que se pudieron traer: acota el periodo.)"
    return texto + _como_se_estimo(con_actual, sin_costo) + (
        " Por voz di el margen general, como queda contra el promedio y donde menos le ganas.")


def _ranking(calculadas: list[dict], general: dict, con_actual: int, sin_costo: int,
             truncado: bool) -> str:
    por_cliente = defaultdict(list)
    for f in calculadas:
        por_cliente[f["cliente_codigo"]].append(f)
    clientes = sorted(((filas[0]["cliente"], _resumen(filas)) for filas in por_cliente.values()),
                      key=lambda c: -c[1]["venta"])
    grandes = clientes[:30]
    flojos = sorted((c for c in grandes if c[1]["margen"] is not None), key=lambda c: c[1]["margen"])
    linea = lambda c: f"{c[0]} {_pct(c[1]['margen'])} en RD$ {_num(c[1]['venta'])}"  # noqa: E731
    texto = (
        f"Margen por cliente en las cotizaciones de JH {_periodo(calculadas)}: {len(clientes)} "
        f"clientes, venta RD$ {_num(general['venta'])}, MARGEN GENERAL ESTIMADO {_pct(general['margen'])} "
        f"sobre el costo. Los de mas venta: " + "; ".join(linea(c) for c in clientes[:MAX_CLIENTES])
        + ". De esos 30 de mas venta, a los que menos les ganas: "
        + "; ".join(linea(c) for c in flojos[:5]) + "."
    )
    if truncado:
        texto += " (Hay mas lineas de las que se pudieron traer: acota el periodo.)"
    return texto + _como_se_estimo(con_actual, sin_costo) + (
        " Por voz di el general y los dos o tres que menos dejan; la lista si la piden.")
