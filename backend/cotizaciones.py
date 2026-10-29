"""Cotizaciones de Jarvis, en paralelo a las de JH.

Van aparte a proposito: numeracion propia (JV-00001), guardadas en la tabla
jarvis_cotizaciones de Supabase y con el PDF en un bucket privado. No tocan la
Base JH ni la numeracion de Camila, asi que no pueden pisar una cotizacion real
ni disparar la alerta de salto de secuencia. La tabla guarda cliente, lineas y
totales completos para poder conectarlas con JH mas adelante.

Dos pasos, siempre:
  1. preparar() / crear_variantes(): busca cliente y productos en el catalogo y
     calcula. Los precios los pone el servidor, nunca el modelo: Camila
     inventaba precios cuando los tomaba de la conversacion.
  2. emitir(): solo despues de que la persona confirma. Le da numero, arma el
     PDF con el servicio de JH (pdfjh) y lo deja en el chat.

Lo que esta en curso (la cotizacion que se trajo y las variantes sin emitir)
vive en la mesa de cada persona: ver mesa.py. Los margenes, en margenes.py.
"""

import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

from . import consumo, continuidad, cotizacion_html, margenes, mesa

PREFIJO = "JV-"
NIVELES = tuple(f"P{i}" for i in range(1, 8))
MAX_LINEAS = 60
MAX_CANTIDAD = 1_000_000
# La utilidad de la clave de JH es sobre el precio de venta, asi que 100 seria
# dividir por cero. El tope deja afuera lo que ya es un error de dictado: con
# 95 el precio sale veinte veces el coste.
MAX_UTILIDAD = 95
# El margen al cotizar al costo es sobre el costo: 1000 ya es once veces el
# costo, y mas que eso es un numero mal dictado.
MAX_MARGEN = 1000

# El enlace que viaja a la app de los lentes, que descarga sin sesion.
FIRMA_APP = 24 * 3600
# El de la web se pide cada vez que se abre, asi que basta con poco.
FIRMA_WEB = 300

# Servicio HTML->PDF. Antes era PDF.co; ahora el propio de JH (pdfjh, en server2),
# que habla la misma API: POST /v1/pdf/convert/from/html, header x-api-key y
# responde {url}. La URL se puede cambiar por entorno (JARVIS_PDF_URL) y la clave
# sale de JARVIS_PDF_KEY (o del viejo PDFCO_API_KEY, por compatibilidad).
URL_PDF_POR_DEFECTO = "https://pdfjh.neboaiconsulting.com/v1/pdf/convert/from/html"
ZONA = ZoneInfo("America/Santo_Domingo")

# Lo que dice "Usuario:" en el PDF. Es fijo, igual que en las de Camila: el
# cliente ve siempre a la misma vendedora. Quien la pidio en Jarvis queda en la
# columna `usuario` de la tabla.
USUARIO_DOCUMENTO = "Camila Reyes"

CODIGO = re.compile(r"^[A-Za-z0-9-]{1,20}$")
NUMERO = re.compile(r"^JV-\d{5,}$")


class ErrorCotizacion(Exception):
    """Un problema que el modelo puede explicar o corregir."""


# --------------------------------------------------------------------------
# Configuracion
# --------------------------------------------------------------------------

def _env(nombre: str) -> str:
    return os.getenv(nombre, "").strip()


def fuente_catalogo() -> str:
    return _env("JARVIS_FUENTE_CATALOGO")


def bucket() -> str:
    return _env("JARVIS_BUCKET_COTIZACIONES")


def url_pdf() -> str:
    return _env("JARVIS_PDF_URL") or URL_PDF_POR_DEFECTO


def clave_pdf() -> str:
    # JARVIS_PDF_KEY es la del servicio actual (pdfjh); PDFCO_API_KEY queda como
    # respaldo para no romper si alguna vez se vuelve a PDF.co.
    return _env("JARVIS_PDF_KEY") or _env("PDFCO_API_KEY")


def configurado() -> bool:
    return all((
        _env("JARVIS_FUENTE_CATALOGO"), _env("JARVIS_BUCKET_COTIZACIONES"),
        clave_pdf(), _env("SUPABASE_SERVICE_ROLE_KEY"), _env("SUPABASE_PROJECT_REF"),
    ))


def formato(numero: int) -> str:
    return f"{PREFIJO}{int(numero):05d}"


def nombre_de_archivo(cliente: str, texto_numero: str) -> str:
    """Como los de Camila: "CLIENTE - numero.pdf".

    El nombre del cliente es lo que se ve en el chat de WhatsApp: sin el, todas
    las cotizaciones se llaman igual. Se quitan los caracteres que no valen en
    un nombre de archivo.
    """
    limpio = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", cliente or "")
    limpio = re.sub(r"\s+", " ", limpio).strip(" .")[:80]
    return f"{limpio} - {texto_numero}.pdf" if limpio else f"Cotizacion {texto_numero}.pdf"


# --------------------------------------------------------------------------
# Catalogo (Base JH, solo lectura)
# --------------------------------------------------------------------------

def _consultar(sql: str, limite: int = MAX_LINEAS) -> list[dict]:
    from . import fuentes

    return fuentes.consultar(fuente_catalogo(), sql, limite=limite)


def _texto(valor) -> str:
    return "" if valor is None else str(valor).strip()


def productos_del_catalogo(codigos: list[str]) -> dict[str, dict]:
    # Se traen todas las columnas porque el coste no siempre se llama igual
    # (coste, costo, Costo...) y hace falta para cotizar por encima de el.
    lista = ", ".join(f"'{c}'" for c in codigos)
    filas = _consultar(
        "SELECT *, LTRIM(RTRIM(Codigo)) AS CodigoLimpio FROM dbo.List_ProductosIA "
        f"WHERE Codigo IN ({lista})"
    )
    return {_texto(f.get("CodigoLimpio") or f.get("Codigo")).upper(): f for f in filas}


_NOMBRE_PERMITIDO = re.compile(r"[^\w\s.&-]", re.UNICODE)


_COLUMNAS_CLIENTE = (
    "codigo, nombre, RTRIM(rnc) AS rnc, direccion, email, "
    "telefono1, Celular, NivelPrecio, factor"
)

# Un RNC tiene 9 cifras y una cedula 11.
LARGOS_DE_RNC = (9, 10, 11)


def cifras_de_rnc(texto: str) -> str | None:
    """Las cifras, si lo que se dijo es un RNC o una cedula y no un nombre.

    Dictado en voz llega con una cifra de mas o de menos, asi que el largo no
    se exige aqui: '402-21599556-0' tiene doce y sigue siendo un RNC mal oido,
    no el nombre de un cliente.
    """
    limpio = texto.strip()
    cifras = re.sub(r"\D", "", limpio)
    if re.fullmatch(r"[\d\s.-]+", limpio) and 7 <= len(cifras) <= 15:
        return cifras
    return None


def deletreado(cifras: str) -> str:
    """Para que se lea cifra por cifra y no como un numero de doce digitos."""
    return " ".join(cifras)


def a_una_cifra_de(cifras: str) -> list[str]:
    """Los RNC que salen de equivocarse en una sola cifra.

    Una de mas, una de menos, una cambiada o dos vecinas al reves: los errores
    de dictar un numero largo de corrido.
    """
    variantes = set()
    for i in range(len(cifras)):
        variantes.add(cifras[:i] + cifras[i + 1:])
        for digito in "0123456789":
            variantes.add(cifras[:i] + digito + cifras[i + 1:])
    for i in range(len(cifras) + 1):
        for digito in "0123456789":
            variantes.add(cifras[:i] + digito + cifras[i:])
    for i in range(len(cifras) - 1):
        variantes.add(cifras[:i] + cifras[i + 1] + cifras[i] + cifras[i + 2:])
    variantes.discard(cifras)
    return sorted(v for v in variantes if len(v) in LARGOS_DE_RNC)


def clientes_con_rnc_parecido(cifras: str) -> list[dict]:
    """Clientes activos cuyo RNC esta a una cifra del que se dijo."""
    variantes = a_una_cifra_de(cifras)
    if not variantes:
        return []
    lista = ", ".join(f"'{v}'" for v in variantes)
    return _consultar(
        f"SELECT TOP 4 {_COLUMNAS_CLIENTE} FROM dbo.List_ClientesIA "
        "WHERE activo = 1 AND Suspendido = 0 AND "
        f"REPLACE(RTRIM(rnc), '-', '') IN ({lista}) ORDER BY nombre"
    )


def buscar_cliente(texto: str) -> list[dict]:
    """Clientes activos por codigo, RNC o nombre. Nada llega crudo al SQL."""
    limpio = texto.strip()
    solo_digitos = cifras_de_rnc(limpio)

    if re.fullmatch(r"\d{1,6}", limpio):
        condicion = f"codigo = {int(limpio)}"
    elif solo_digitos:
        condicion = f"REPLACE(RTRIM(rnc), '-', '') = '{solo_digitos}'"
    else:
        from . import fuentes

        # Una palabra como COPY o CALL en un nombre la rechazaria el filtro de
        # solo lectura; sin ella la busqueda sigue funcionando.
        palabras = [
            p for p in _NOMBRE_PERMITIDO.sub(" ", limpio).split()
            if re.search(r"[^\W_]", p) and not fuentes.PROHIBIDAS.fullmatch(p)
        ][:6]
        if not palabras:
            return []
        condicion = " AND ".join(f"nombre LIKE '%{p}%'" for p in palabras)

    return _consultar(
        f"SELECT TOP 6 {_COLUMNAS_CLIENTE} FROM dbo.List_ClientesIA "
        f"WHERE activo = 1 AND Suspendido = 0 AND {condicion} ORDER BY nombre"
    )


# --------------------------------------------------------------------------
# Borrador
# --------------------------------------------------------------------------

@dataclass
class Borrador:
    """Una variante sin emitir de la mesa (ver mesa.py)."""
    cliente: dict
    lineas: list[dict]
    totales: dict
    creado: float = field(default_factory=time.time)
    nombre: str = "borrador"


@dataclass
class Encontrada:
    """La original de la mesa: la cotizacion que se trajo con buscar_cotizacion."""
    cliente: dict
    productos: list[dict]
    numero: str
    total: float
    fuente: str = "jv"          # "jv" (jarvis_cotizaciones) o "jh" (Base JH)
    creado: float = field(default_factory=time.time)
    cuando: str = ""            # cuando se cotizo, tal como viene de la base


def encontrada_de(id_usuario: str) -> Encontrada | None:
    original = mesa.cargar(id_usuario)["original"]
    if not original:
        return None
    return Encontrada(original["cliente"], original["lineas"], original["numero"],
                      original["total"], original["fuente"], original["creado"])


def _guardar_variante(id_usuario: str, nombre: str, cliente: dict, lineas: list[dict],
                      origen: str = "") -> dict:
    """Pone una variante en la mesa (reemplaza la del mismo nombre)."""
    with mesa.candado:
        actual = mesa.cargar(id_usuario)
        if mesa.variante(actual, nombre) is None and len(actual["variantes"]) >= mesa.MAX_VARIANTES:
            raise ErrorCotizacion(
                f"Ya hay {mesa.MAX_VARIANTES} cotizaciones sin emitir "
                f"({', '.join(v['nombre'] for v in actual['variantes'])}). Emite o descarta "
                "alguna antes de armar otra."
            )
        nueva = {"nombre": nombre, "cliente": cliente, "lineas": lineas,
                 "totales": totalizar(lineas), "creado": time.time(), "origen": origen}
        mesa.poner_variante(actual, nueva)
        mesa.guardar(id_usuario, actual)
    return nueva


def _completar(linea: dict, fila: dict | None, ajuste: str) -> dict:
    """Agrega a la linea lo que hace falta para analizarla y ajustarla: el
    costo de hoy, los precios de cada nivel y con que precio nacio."""
    return {
        **linea,
        "costo": margenes.costo_de_fila(fila),
        "niveles": {n: float((fila or {}).get(n) or 0) for n in NIVELES},
        "precio_original": linea["precio_unitario"],
        "ajuste": ajuste,
    }


def _leer_productos(productos) -> list[tuple[str, float]]:
    import json

    if isinstance(productos, str):
        try:
            productos = json.loads(productos or "[]")
        except json.JSONDecodeError:
            raise ErrorCotizacion("'productos' no es JSON valido.") from None
    if not isinstance(productos, list) or not productos:
        raise ErrorCotizacion("Faltan los productos: lista de {codigo, cantidad}.")

    cantidades: dict[str, float] = {}
    for item in productos:
        if not isinstance(item, dict):
            raise ErrorCotizacion("Cada producto tiene que ser {codigo, cantidad}.")
        codigo = _texto(item.get("codigo")).upper()
        if not CODIGO.match(codigo):
            raise ErrorCotizacion(f"Codigo invalido: '{codigo}'. Buscalo con buscar_en_fuente.")
        try:
            cantidad = float(item.get("cantidad"))
        except (TypeError, ValueError):
            raise ErrorCotizacion(f"Cantidad invalida para {codigo}.") from None
        if not 0 < cantidad <= MAX_CANTIDAD:
            raise ErrorCotizacion(f"Cantidad invalida para {codigo}.")
        # El mismo producto dos veces es una sola linea.
        cantidades[codigo] = cantidades.get(codigo, 0) + cantidad

    if len(cantidades) > MAX_LINEAS:
        raise ErrorCotizacion(f"Son {len(cantidades)} productos; el maximo es {MAX_LINEAS}.")
    return list(cantidades.items())


def _rnc_sin_cliente(cifras: str) -> str:
    """Que decir cuando el RNC no existe: casi siempre se oyo mal una cifra.

    Un numero largo dictado de corrido llega con una cifra cambiada o de mas.
    En vez de dar al cliente por inexistente, se busca el que esta a una cifra
    y se manda a confirmar el numero en voz alta antes de seguir.
    """
    try:
        parecidos = clientes_con_rnc_parecido(cifras)
    except Exception:  # noqa: BLE001 - sin parecidos se pide repetir igual
        parecidos = []

    if not parecidos:
        return (
            f"No hay ningun cliente con el RNC {deletreado(cifras)}. Lee ese numero "
            "cifra por cifra y pregunta si lo entendiste bien, o si va de contado."
        )

    opciones = "; ".join(
        f"{_texto(f['nombre'])} (RNC {deletreado(re.sub(r'[^0-9]', '', _texto(f.get('rnc'))))}, "
        f"codigo {f['codigo']})"
        for f in parecidos
    )
    return (
        f"No hay ningun cliente con el RNC {deletreado(cifras)}, pero a una cifra "
        f"de diferencia esta: {opciones}. Lee cifra por cifra el RNC que entendiste "
        "y pregunta si es ese cliente. No cotices hasta que lo confirme; si dice "
        "que si, prepara de nuevo con su codigo."
    )


def _resolver_cliente(texto: str, contado: bool, ciudad: str, contacto: str) -> dict:
    extra = {"ciudad": ciudad.strip()[:60], "contacto": contacto.strip()[:60], "sector": ""}

    if contado:
        return {"codigo": "", "nombre": (texto.strip() or "CLIENTE CONTADO")[:80],
                "rnc": "", "direccion": "", "email": "", "telefono": "",
                "nivel": "P1", "factor": 1.0, **extra}

    if not texto.strip():
        raise ErrorCotizacion(
            "Falta el cliente. Pregunta para quien es (nombre, RNC o codigo). "
            "Si no es cliente registrado, puede ir de contado."
        )

    filas = buscar_cliente(texto)
    if not filas and cifras_de_rnc(texto):
        raise ErrorCotizacion(_rnc_sin_cliente(cifras_de_rnc(texto)))
    if not filas:
        raise ErrorCotizacion(
            f"No encontre al cliente '{texto}'. Pregunta el nombre exacto o el RNC, "
            "o si va de contado."
        )
    if len(filas) > 1:
        opciones = "; ".join(f"{_texto(f['nombre'])} (codigo {f['codigo']})" for f in filas[:5])
        raise ErrorCotizacion(
            f"Hay varios clientes que coinciden: {opciones}. Pregunta cual es y "
            "vuelve a preparar con su codigo."
        )

    fila = filas[0]
    nivel = _texto(fila.get("NivelPrecio")).upper()
    try:
        factor = float(fila.get("factor") or 1) or 1.0
    except (TypeError, ValueError):
        factor = 1.0
    return {
        "codigo": _texto(fila.get("codigo")),
        "nombre": _texto(fila.get("nombre")),
        "rnc": _texto(fila.get("rnc")),
        "direccion": _texto(fila.get("direccion")),
        "email": _texto(fila.get("email")),
        "telefono": _texto(fila.get("telefono1")) or _texto(fila.get("Celular")),
        "nivel": nivel if nivel in NIVELES else "P1",
        "factor": factor,
        **extra,
    }


def calcular_linea(fila: dict, cantidad: float, nivel: str, factor: float,
                   coste: dict | None = None, utilidad_nivel: float = 0.0) -> dict:
    """Una linea con los mismos calculos que la plantilla de n8n.

    Los precios del catalogo ya incluyen ITBIS: el bruto se despeja.

    Con `coste` -{margen}- el precio no sale del nivel del cliente sino del
    costo del catalogo con ese margen.
    """
    try:
        tasa = float(fila.get("TipoItbis") or 0)
    except (TypeError, ValueError):
        tasa = 0.0

    if coste is None:
        # Precio del nivel. Con utilidad_nivel (la clave de JH, "55" = P5 con 5)
        # se usa la cuenta de JH, sobre el precio de venta: PV = base / (1 - %/100).
        precio = round(float(fila.get(nivel) or 0) * factor, 2)
        if utilidad_nivel:
            precio = round(precio / (1 - utilidad_nivel / 100), 2)
        base = 0.0
    else:
        # El costo de este catalogo ya trae el ITBIS adentro, igual que los
        # P1..P7: el bruto se despeja abajo. El margen es SOBRE EL COSTO, como
        # en toda la mesa: 1000 con 30% sale a 1300.
        base = margenes.costo_de_fila(fila) or 0.0
        precio = margenes.precio_con_margen(base, coste["margen"])

    bruto = precio / (1 + tasa / 100)
    return {
        "codigo": _texto(fila.get("Codigo")),
        "referencia": _texto(fila.get("Referencia")),
        "descripcion": _texto(fila.get("Descripcion")),
        "unidad": _texto(fila.get("Und")),
        "cantidad": cantidad,
        "coste": round(base, 2),
        "precio_unitario": precio,
        "TipoItbis": tasa,
        "precio_bruto": bruto,
        "itbis_linea": (precio - bruto) * cantidad,
        "subtotal_linea": precio * cantidad,
    }


def totalizar(lineas: list[dict]) -> dict:
    return {
        "subtotal": round(sum(l["precio_bruto"] * l["cantidad"] for l in lineas), 2),
        "itbis": round(sum(l["itbis_linea"] for l in lineas), 2),
        "total": round(sum(l["subtotal_linea"] for l in lineas), 2),
    }


def _num(valor: float) -> str:
    return f"{valor:,.2f}"


def _cantidad(valor: float) -> str:
    return f"{valor:g}"


def _leer_utilidad(utilidad) -> float:
    """El porcentaje de la clave de JH ("55" = P5 con 5), validado. Es la parte
    del precio de venta, como lo cuenta JH."""
    try:
        por_ciento = float(utilidad or 0)
    except (TypeError, ValueError):
        raise ErrorCotizacion(f"El porcentaje de utilidad no es un numero: '{utilidad}'.") from None
    if not 0 <= por_ciento <= MAX_UTILIDAD:
        raise ErrorCotizacion(
            f"El porcentaje de utilidad tiene que estar entre 0 y {MAX_UTILIDAD:g}."
        )
    return por_ciento


def _leer_margen(margen) -> float:
    """El margen sobre el costo para cotizar al costo, validado."""
    try:
        por_ciento = float(str(margen or 0).replace("%", "").replace(",", ".").strip() or 0)
    except ValueError:
        raise ErrorCotizacion(f"El margen no es un numero: '{margen}'.") from None
    if not 0 <= por_ciento <= MAX_MARGEN:
        raise ErrorCotizacion(f"El margen sobre el costo tiene que estar entre 0 y {MAX_MARGEN:g}.")
    return por_ciento


def preparar(id_usuario: str, cliente: str, productos, contado: bool = False,
             ciudad: str = "", contacto: str = "", al_costo: bool = False,
             margen=0) -> str:
    """Arma el borrador y devuelve el resumen para confirmar."""
    pedidos = _leer_productos(productos)
    coste = {"margen": _leer_margen(margen)} if al_costo else None
    datos_cliente = _resolver_cliente(cliente or "", contado, ciudad or "", contacto or "")

    catalogo = productos_del_catalogo([codigo for codigo, _ in pedidos])
    faltan = [codigo for codigo, _ in pedidos if codigo not in catalogo]
    if faltan:
        raise ErrorCotizacion(
            f"No existen en el catalogo: {', '.join(faltan)}. Busca los codigos "
            "correctos con buscar_en_fuente."
        )

    ajuste = (("a costo" if not coste["margen"] else f"costo + {coste['margen']:g}%")
              if coste else datos_cliente["nivel"])
    lineas = [
        _completar(calcular_linea(catalogo[codigo], cantidad, datos_cliente["nivel"],
                                  datos_cliente["factor"], coste),
                   catalogo[codigo], ajuste)
        for codigo, cantidad in pedidos
    ]
    sin_precio = [l["descripcion"] or l["codigo"] for l in lineas if l["precio_unitario"] <= 0]
    if sin_precio:
        falta = "costo" if coste else f"precio {datos_cliente['nivel']}"
        raise ErrorCotizacion(
            f"Sin {falta} en el catalogo: {', '.join(sin_precio)}. "
            "No se puede cotizar asi; dilo."
        )

    totales = _guardar_variante(id_usuario, "borrador", datos_cliente, lineas)["totales"]

    detalle = "; ".join(
        f"{_cantidad(l['cantidad'])} {l['unidad'] or 'UND'} de {l['descripcion']} "
        + (f"(costo {_num(l['coste'])}) " if coste else "")
        + f"a {_num(l['precio_unitario'])} = {_num(l['subtotal_linea'])}"
        for l in lineas
    )
    if coste:
        # Se dice como se calculo, para que quien cotiza lo vea antes de emitir.
        tipo_cliente = (
            "al costo"
            + (f" + {coste['margen']:g}% sobre el costo" if coste["margen"] else "")
            + ", ITBIS incluido"
        )
    else:
        tipo_cliente = "de contado" if contado else f"precio {datos_cliente['nivel']}"

    return (
        f"Borrador listo (aun NO emitido). Cliente: {datos_cliente['nombre']} ({tipo_cliente}). "
        f"{len(lineas)} producto(s): {detalle}. Total RD$ {_num(totales['total'])}, "
        f"ITBIS incluido RD$ {_num(totales['itbis'])}. "
        "Resume cliente, cantidad de productos y total, y pregunta si la emite. "
        + ("Al resumir, di sobre que precio se calculo y el total; el costo de "
           "cada producto no se lee salvo que lo pidan. " if coste else "")
        + "Llama a emitir_cotizacion solo si dice que si; si pide cambios, vuelve a "
        "llamar a preparar_cotizacion."
    )


def _a_borrador(variante: dict) -> Borrador:
    return Borrador(variante["cliente"], variante["lineas"], variante["totales"],
                    variante["creado"], variante["nombre"])


def borrador_de(id_usuario: str) -> Borrador | None:
    """La variante con la que se esta trabajando, o None."""
    variante = mesa.activa(mesa.cargar(id_usuario))
    return _a_borrador(variante) if variante else None


# --------------------------------------------------------------------------
# Supabase y PDF.co
# --------------------------------------------------------------------------

def _supabase() -> str:
    return f"https://{_env('SUPABASE_PROJECT_REF')}.supabase.co"


def _cabeceras() -> dict:
    llave = _env("SUPABASE_SERVICE_ROLE_KEY")
    return {"apikey": llave, "Authorization": f"Bearer {llave}"}


def _insertar(fila: dict) -> int:
    respuesta = httpx.post(
        f"{_supabase()}/rest/v1/jarvis_cotizaciones",
        headers={**_cabeceras(), "Prefer": "return=representation"},
        json=fila, timeout=20,
    )
    respuesta.raise_for_status()
    return int(respuesta.json()[0]["numero"])


def _actualizar(numero: int, cambios: dict) -> None:
    respuesta = httpx.patch(
        f"{_supabase()}/rest/v1/jarvis_cotizaciones?numero=eq.{int(numero)}",
        headers=_cabeceras(), json=cambios, timeout=20,
    )
    respuesta.raise_for_status()


def _pdf(html: str, nombre: str) -> bytes:
    respuesta = httpx.post(
        url_pdf(),
        headers={"x-api-key": clave_pdf()},
        json={
            "html": html, "name": nombre, "paperSize": "Letter",
            # Los mismos margenes que usa n8n: la plantilla esta calibrada ahi.
            "margins": "3mm 10mm 2mm 10mm", "async": False, "inline": False,
        },
        timeout=120,
    )
    datos = respuesta.json()
    if respuesta.status_code >= 400 or datos.get("error") or not datos.get("url"):
        raise RuntimeError(f"servicio PDF: {datos.get('message') or respuesta.status_code}")
    # pdfjh no cobra creditos (devuelve credits:0); se anota igual por si algun
    # dia vuelve PDF.co, que si cobra la conversion llegue o no el archivo.
    consumo.registrar_cotizacion(datos.get("credits") or 0)
    archivo = httpx.get(datos["url"], timeout=60)
    archivo.raise_for_status()
    if not archivo.content.startswith(b"%PDF"):
        raise RuntimeError("El servicio PDF no devolvio un PDF.")
    return archivo.content


def _subir(ruta: str, contenido: bytes) -> None:
    respuesta = httpx.post(
        f"{_supabase()}/storage/v1/object/{bucket()}/{quote(ruta)}",
        headers={**_cabeceras(), "Content-Type": "application/pdf", "x-upsert": "true"},
        content=contenido, timeout=60,
    )
    respuesta.raise_for_status()


def firmar(ruta: str, segundos: int) -> str:
    respuesta = httpx.post(
        f"{_supabase()}/storage/v1/object/sign/{bucket()}/{quote(ruta)}",
        headers=_cabeceras(), json={"expiresIn": segundos}, timeout=20,
    )
    respuesta.raise_for_status()
    return f"{_supabase()}/storage/v1{respuesta.json()['signedURL']}"


def _imagenes(codigos: list[str]) -> dict[str, str]:
    from . import archivos

    if not archivos.configurado():
        return {}
    try:
        encontrados, _ = archivos.buscar(codigos, ["imagen"])
    except Exception:  # noqa: BLE001 - sin fotos la cotizacion sigue valiendo
        return {}
    return {a["codigo"]: a["url"] for a in encontrados}


# --------------------------------------------------------------------------
# Emision
# --------------------------------------------------------------------------

def _sacar_para_emitir(id_usuario: str, cual: str) -> dict:
    """Saca de la mesa la variante a emitir. Se saca antes de emitir: un "si"
    repetido no debe emitir dos veces."""
    with mesa.candado:
        actual = mesa.cargar(id_usuario)
        if not actual["variantes"]:
            raise ErrorCotizacion(
                "No hay ninguna cotizacion sin emitir (o pasaron 2 horas sin usarla). "
                "Preparala otra vez con preparar_cotizacion o crear_variantes."
            )
        variante = (_resolver_variante(actual, cual) if (cual or "").strip()
                    else mesa.activa(actual))
        actual["variantes"].remove(variante)
        mesa.guardar(id_usuario, actual)
    return variante


def _devolver_a_la_mesa(id_usuario: str, variante: dict) -> None:
    with mesa.candado:
        actual = mesa.cargar(id_usuario)
        if mesa.variante(actual, variante["nombre"]) is None:
            mesa.poner_variante(actual, variante)
            mesa.guardar(id_usuario, actual)


def _para_guardar(linea: dict) -> dict:
    # Los precios de cada nivel solo sirven mientras se ajusta.
    return {k: v for k, v in linea.items() if k != "niveles"} | {
        "margen": margenes.margen(linea["precio_unitario"], linea.get("costo")),
    }


def emitir(id_usuario: str, nombre_usuario: str, cual: str = "") -> dict:
    """Emite una variante de la mesa (la activa, o la que diga `cual`).
    Devuelve el adjunto para el chat."""
    variante = _sacar_para_emitir(id_usuario, cual)
    borrador = _a_borrador(variante)
    cliente = dict(borrador.cliente)
    if variante.get("origen"):
        cliente["cotizacion_origen"] = variante["origen"]

    try:
        numero = _insertar({
            "usuario": nombre_usuario,
            "cliente": cliente,
            "productos": [_para_guardar(l) for l in borrador.lineas],
            **borrador.totales,
            "estado": "generando",
        })
    except Exception as error:  # noqa: BLE001
        _devolver_a_la_mesa(id_usuario, variante)
        raise ErrorCotizacion(f"No se pudo registrar la cotizacion: {error}") from None

    texto_numero = formato(numero)
    try:
        fecha = fecha_de_documento(datetime.now(ZONA))
        html = cotizacion_html.generar(
            texto_numero, fecha, borrador.cliente, borrador.lineas, borrador.totales,
            USUARIO_DOCUMENTO, _imagenes([l["codigo"] for l in borrador.lineas]),
        )
        ruta = f"{texto_numero}.pdf"
        _subir(ruta, _pdf(html, nombre_de_archivo(borrador.cliente["nombre"], texto_numero)))
        _actualizar(numero, {"pdf_ruta": ruta, "estado": "emitida"})
        url = firmar(ruta, FIRMA_APP)
        continuidad.anotar_emision(
            id_usuario, texto_numero, borrador.cliente["nombre"], borrador.totales["total"],
        )
    except Exception as error:  # noqa: BLE001
        try:
            _actualizar(numero, {"estado": "fallida"})
        except Exception:  # noqa: BLE001
            pass
        # La variante vuelve: reintentar da otro numero, y el fallido queda
        # marcado en la tabla.
        _devolver_a_la_mesa(id_usuario, variante)
        raise ErrorCotizacion(f"No se pudo generar el PDF de la cotizacion: {error}") from None

    return {
        "tipo": "cotizacion",
        "numero": texto_numero,
        "titulo": f"Cotización {texto_numero} · {borrador.cliente['nombre']}",
        "archivo": ruta,
        "url": url,
        "enlace": f"/api/cotizaciones/{texto_numero}.pdf",
        "total": borrador.totales["total"],
        "variante": variante["nombre"],
    }


def emitir_todas(id_usuario: str, nombre_usuario: str) -> tuple[list[dict], list[str]]:
    """Emite todas las variantes de la mesa. Devuelve (adjuntos, errores): una
    que falla no frena a las demas."""
    nombres = [v["nombre"] for v in mesa.cargar(id_usuario)["variantes"]]
    if not nombres:
        raise ErrorCotizacion(
            "No hay ninguna cotizacion sin emitir (o pasaron 2 horas sin usarla)."
        )
    adjuntos, errores = [], []
    for nombre in nombres:
        try:
            adjuntos.append(emitir(id_usuario, nombre_usuario, nombre))
        except ErrorCotizacion as error:
            errores.append(f"{nombre}: {error}")
    return adjuntos, errores


def buscar_emitida(texto_numero: str) -> dict | None:
    """La cotizacion ya emitida con ese numero, o None."""
    if not NUMERO.match(texto_numero):
        return None
    respuesta = httpx.get(
        f"{_supabase()}/rest/v1/jarvis_cotizaciones",
        headers=_cabeceras(),
        params={"numero": f"eq.{int(texto_numero[len(PREFIJO):])}", "estado": "eq.emitida",
                "select": "numero,pdf_ruta,cliente->>nombre"},
        timeout=20,
    )
    respuesta.raise_for_status()
    filas = respuesta.json()
    if not filas or not filas[0].get("pdf_ruta"):
        return None
    return {"pdf_ruta": filas[0]["pdf_ruta"], "cliente": filas[0].get("nombre") or ""}


# --------------------------------------------------------------------------
# Buscar una cotizacion emitida para trabajar sobre ella
# --------------------------------------------------------------------------

_SELECT_ENCONTRADA = "numero,creada_at,cliente,productos,total"


def _filas_emitidas(params: dict) -> list[dict]:
    """Filas de jarvis_cotizaciones segun los filtros de PostgREST que se pasen."""
    respuesta = httpx.get(
        f"{_supabase()}/rest/v1/jarvis_cotizaciones",
        headers=_cabeceras(), params=params, timeout=20,
    )
    respuesta.raise_for_status()
    return respuesta.json()


def _normalizar_jv(texto: str) -> str | None:
    """"JV-12", "la jv 12" -> "JV-00012". None si no se dijo un numero JV."""
    limpio = texto.strip().upper().replace(" ", "")
    encontrado = re.search(r"JV-?(\d+)", limpio)
    return formato(int(encontrado.group(1))) if encontrado else None


def _fecha_corta(iso) -> str:
    try:
        momento = datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(ZONA)
        return fecha_de_documento(momento)
    except Exception:  # noqa: BLE001 - sin fecha legible, mejor no decir nada
        return ""


def _dia(cuando: str) -> str:
    """AAAA-MM-DD en Santo Domingo, o "" si no se entiende."""
    try:
        momento = datetime.fromisoformat(str(cuando).replace("Z", "+00:00"))
    except ValueError:
        return ""
    if momento.tzinfo:
        momento = momento.astimezone(ZONA)
    return momento.strftime("%Y-%m-%d")


def _lineas_de_original(productos: list[dict], cuando: str = "") -> list[dict]:
    """Las lineas de una cotizacion ya hecha, con los precios con que se cotizo
    (no se recalculan) y dos costos:
    - `costo`: el de HOY del catalogo. Es el que sirve para repetirla o sacar
      variantes.
    - `costo_cotizado`: el que habia cuando se cotizo. Las de Jarvis lo
      guardan; las de JH no (su detalle trae costo 0), y se toma el de la
      ultima compra hasta ese dia. None si no hay como saberlo.
    """
    from . import historial

    codigos = [_texto(p.get("codigo")).upper() for p in productos]
    catalogo = productos_del_catalogo(codigos) if codigos else {}
    guardados = {c: float(p.get("costo") or 0) for c, p in zip(codigos, productos)}
    faltan = [c for c in codigos if not guardados.get(c)]
    dia = _dia(cuando)
    comprados = historial.costos_a_la_fecha(faltan, dia) if faltan and dia else {}
    lineas = []
    for producto, codigo in zip(productos, codigos):
        fila = catalogo.get(codigo) or {}
        tasa = producto.get("TipoItbis")
        if tasa is None:
            tasa = fila.get("TipoItbis", 18)
        base = {
            "codigo": _texto(producto.get("codigo")),
            "referencia": _texto(producto.get("referencia") or fila.get("Referencia")),
            "descripcion": _texto(producto.get("descripcion") or fila.get("Descripcion")),
            "unidad": _texto(producto.get("unidad") or fila.get("Und")),
            "cantidad": float(producto.get("cantidad") or 0),
            "coste": float(producto.get("coste") or 0),
            "TipoItbis": float(tasa or 0),
        }
        precio = float(producto.get("precio_unitario") or producto.get("precio") or 0)
        linea = _completar(margenes.con_precio(base, precio), fila or None, "original")
        linea["costo_cotizado"] = guardados.get(codigo) or comprados.get(codigo)
        lineas.append(linea)
    return lineas


def _de_hoy(linea: dict) -> dict:
    """Una linea que se va a volver a cotizar: el costo de la original ya no aplica."""
    return {k: v for k, v in linea.items() if k != "costo_cotizado"}


def _al_cotizar(lineas: list[dict]) -> list[dict]:
    """Las lineas con el costo de cuando se cotizo en vez del de hoy. Las que
    no lo tienen se quedan con el de hoy."""
    return [dict(l, costo=l.get("costo_cotizado") or l.get("costo")) for l in lineas]


def _margen_al_cotizar(original: dict) -> str:
    """El margen de cuando se cotizo, al lado del de hoy, si son distintos."""
    lineas = original["lineas"]
    con_dato = [l for l in lineas if l.get("costo_cotizado")]
    if not con_dato:
        return (" No hay costo de cuando se cotizo (ni guardado ni compras de antes): solo "
                "se puede decir el margen con el costo de hoy.")
    antes = margenes.analizar(_al_cotizar(lineas))
    hoy = margenes.analizar(lineas)
    if antes["margen"] is None or hoy["margen"] is None:
        return ""
    if abs(antes["margen"] - hoy["margen"]) < 0.5:
        return (f" Cuando se cotizo el margen era practicamente el mismo "
                f"({_pct(antes['margen'])}): el costo no ha cambiado.")
    sube = "subio" if antes["margen"] > hoy["margen"] else "bajo"
    return (
        f" CUANDO SE COTIZO dejaba {_pct(antes['margen'])} sobre el costo (ganancia RD$ "
        f"{_num(antes['ganancia'])}); en conjunto el costo {sube} desde entonces, y si se repite igual "
        f"HOY deja {_pct(hoy['margen'])}"
        + (f". {len(lineas) - len(con_dato)} producto(s) sin costo de esa fecha van con el de hoy"
           if len(con_dato) < len(lineas) else "")
        + ". Al dar el margen, di los dos, cada uno con su nombre."
    )


def _resumen(id_usuario: str, encontrada: Encontrada, fecha: str = "",
             estado: str = "", nota: str = "") -> str:
    """Pone la cotizacion encontrada como ORIGINAL de una mesa nueva y la resume."""
    lineas = _lineas_de_original(encontrada.productos, encontrada.cuando)
    with mesa.candado:
        descartadas = [v["nombre"] for v in mesa.cargar(id_usuario)["variantes"]]
        nueva = mesa.vacia()
        nueva["original"] = {
            "numero": encontrada.numero, "fuente": encontrada.fuente,
            "cliente": encontrada.cliente, "lineas": lineas, "total": encontrada.total,
            "fecha": fecha, "creado": time.time(),
        }
        nueva["ultima"] = "original"
        mesa.guardar(id_usuario, nueva)

    aviso = (
        f"Se descartaron cotizaciones que estaban sin emitir ({', '.join(descartadas)}): dilo. "
        if descartadas else ""
    )
    return (
        f"{nota}Cotizacion {encontrada.numero} de {encontrada.cliente.get('nombre')}"
        + (f" ({fecha})" if fecha else "")
        + f", total RD$ {_num(encontrada.total)}"
        + (f", {estado}" if estado else "")
        + f". {len(lineas)} producto(s):\n{_tabla(lineas)}\n"
        + _general(margenes.analizar(lineas)) + _margen_al_cotizar(nueva["original"]) + "\n"
        + aviso
        + "Desde aqui se pueden sacar variantes (a costo, costo + X %, otro nivel) con "
        "crear_variantes, ajustar precios con ajustar_precios o analizarla con "
        "analizar_cotizacion. Por voz di cliente, fecha, total, cuantos productos y el "
        "margen general; la lista solo si la piden. Por escrito muestra la tabla. "
        "No leas el numero completo salvo que lo pidan."
    )


def _guardar_y_resumir(id_usuario: str, fila: dict, nota: str = "") -> str:
    encontrada = Encontrada(
        cliente=fila["cliente"], productos=fila["productos"],
        numero=formato(int(fila["numero"])), total=float(fila["total"]), fuente="jv",
        cuando=str(fila.get("creada_at") or ""),
    )
    return _resumen(id_usuario, encontrada, _fecha_corta(fila.get("creada_at")), nota=nota)


# --- Cotizaciones reales de JH (solo lectura, vistas iCotizacionesWebIA / dCotizacionesWebIA) ---

_COLUMNAS_COTIZ_JH = (
    "nfactura, cliente, clientenombre, RTRIM(RNC) AS RNC, Telefono, Direccion, "
    "Correo, Ciudad, Sector, Contacto, fecha, total, confirmada, pago"
)


def _cotiz_jh_por_numero(nfactura: int) -> dict | None:
    filas = _consultar(
        f"SELECT TOP 1 {_COLUMNAS_COTIZ_JH} FROM dbo.iCotizacionesWebIA "
        f"WHERE nfactura = {int(nfactura)}"
    )
    return filas[0] if filas else None


def _cotiz_jh_de_cliente(codigo: int, limite: int = 5) -> list[dict]:
    return _consultar(
        f"SELECT TOP {int(limite)} {_COLUMNAS_COTIZ_JH} FROM dbo.iCotizacionesWebIA "
        f"WHERE cliente = {int(codigo)} ORDER BY fecha DESC, nfactura DESC"
    )


def _detalle_jh(nfactura: int) -> list[dict]:
    return _consultar(
        "SELECT LTRIM(RTRIM(codigo)) AS codigo, cantidad, precio, Descripcion, Und "
        f"FROM dbo.dCotizacionesWebIA WHERE nfactura = {int(nfactura)}"
    )


def _encontrada_desde_jh(header: dict) -> Encontrada:
    """Normaliza una cabecera de JH + sus lineas a la forma de Encontrada."""
    nivel = f"P{int(header.get('nivel') or 0)}"
    cliente = {
        "codigo": _texto(header.get("cliente")),
        "nombre": _texto(header.get("clientenombre")),
        "rnc": _texto(header.get("RNC")),
        "direccion": _texto(header.get("Direccion")),
        "email": _texto(header.get("Correo")),
        "telefono": _texto(header.get("Telefono")),
        "nivel": nivel if nivel in NIVELES else "P1",
        "factor": 1.0,
        "ciudad": _texto(header.get("Ciudad")),
        "contacto": _texto(header.get("Contacto")),
        "sector": _texto(header.get("Sector")),
    }
    productos = [
        {"codigo": _texto(l.get("codigo")), "cantidad": float(l.get("cantidad") or 0),
         "precio": float(l.get("precio") or 0),
         "descripcion": _texto(l.get("Descripcion")), "unidad": _texto(l.get("Und"))}
        for l in _detalle_jh(int(header["nfactura"]))
    ]
    return Encontrada(cliente, productos, str(int(header["nfactura"])),
                      float(header.get("total") or 0), fuente="jh",
                      cuando=str(header.get("fecha") or ""))


def _estado_jh(header: dict) -> str:
    partes = ["confirmada" if header.get("confirmada") else "sin confirmar"]
    partes.append("pagada" if header.get("pago") else "no pagada")
    return ", ".join(partes)


def _ultima_jh() -> dict | None:
    filas = _consultar(
        f"SELECT TOP 1 {_COLUMNAS_COTIZ_JH} FROM dbo.iCotizacionesWebIA "
        "ORDER BY fecha DESC, nfactura DESC"
    )
    return filas[0] if filas else None


def _ultima_jv() -> dict | None:
    filas = _filas_emitidas({
        "estado": "eq.emitida", "order": "creada_at.desc", "limit": "1",
        "select": _SELECT_ENCONTRADA,
    })
    return filas[0] if filas else None


def _ultima_general(id_usuario: str) -> str:
    """La ultima cotizacion "en general": la real de JH. Las JV de Jarvis son
    aparte (de prueba o hechas a mano), asi que no se cuelan aqui aunque sean mas
    recientes; solo se menciona cual es la ultima JV, por si la quieren."""
    header = _ultima_jh()
    jv = _ultima_jv()
    if header:
        otra = f" La mas reciente de Jarvis es la {formato(int(jv['numero']))}." if jv else ""
        enc = _encontrada_desde_jh(header)
        return _resumen(id_usuario, enc, _fecha_corta(header.get("fecha")), _estado_jh(header),
                        nota=f"La ultima en general es de JH.{otra} ")
    if jv:
        return _guardar_y_resumir(id_usuario, jv, nota="Solo hay cotizaciones de Jarvis. ")
    raise ErrorCotizacion("No encontre ninguna cotizacion emitida todavia.")


# --- PDF de una cotizacion de JH, para mandarla tal cual por WhatsApp ---

def _lineas_pdf_jh(nfactura: int) -> list[dict]:
    """Las lineas de una cotizacion de JH, con sus precios reales, en la forma
    que espera la plantilla del PDF."""
    filas = _consultar(
        "SELECT LTRIM(RTRIM(codigo)) AS codigo, cantidad, precio, porItbis, "
        f"Descripcion, Und FROM dbo.dCotizacionesWebIA WHERE nfactura = {int(nfactura)}"
    )
    lineas = []
    for f in filas:
        cantidad = float(f.get("cantidad") or 0)
        precio = round(float(f.get("precio") or 0), 2)
        tasa = float(f.get("porItbis") or 0)
        bruto = precio / (1 + tasa / 100) if tasa else precio
        lineas.append({
            "codigo": _texto(f.get("codigo")), "referencia": "",
            "descripcion": _texto(f.get("Descripcion")), "unidad": _texto(f.get("Und")),
            "cantidad": cantidad, "precio_unitario": precio, "TipoItbis": tasa,
            "precio_bruto": bruto, "itbis_linea": (precio - bruto) * cantidad,
            "subtotal_linea": precio * cantidad,
        })
    return lineas


def _generar_pdf_jh(header: dict) -> str:
    """Arma el PDF de la cotizacion de JH tal cual (sus precios y numero reales),
    lo sube al bucket y devuelve la ruta."""
    nfactura = int(header["nfactura"])
    lineas = _lineas_pdf_jh(nfactura)
    if not lineas:
        raise ErrorCotizacion(f"La cotizacion {nfactura} de JH no tiene productos para el PDF.")
    itbis = round(float(header.get("itbis") or 0), 2)
    total = round(float(header.get("total") or 0), 2)
    totales = {"subtotal": round(total - itbis, 2), "itbis": itbis, "total": total}
    cliente = {
        "codigo": _texto(header.get("cliente")), "nombre": _texto(header.get("clientenombre")),
        "rnc": _texto(header.get("RNC")), "direccion": _texto(header.get("Direccion")),
        "email": _texto(header.get("Correo")), "telefono": _texto(header.get("Telefono")),
        "ciudad": _texto(header.get("Ciudad")), "sector": _texto(header.get("Sector")),
        "contacto": _texto(header.get("Contacto")),
    }
    html = cotizacion_html.generar(
        str(nfactura), _fecha_corta(header.get("fecha")), cliente, lineas, totales,
        USUARIO_DOCUMENTO, _imagenes([l["codigo"] for l in lineas]),
    )
    ruta = f"jh-{nfactura}.pdf"
    _subir(ruta, _pdf(html, nombre_de_archivo(cliente["nombre"], str(nfactura))))
    return ruta


def archivo_para_envio(numero: str) -> dict:
    """El PDF a mandar por WhatsApp: {referencia, titulo, ruta}. Resuelve tanto
    las JV de Jarvis (ya tienen PDF) como las reales de JH (lo genera al vuelo)."""
    texto = (numero or "").strip().upper()

    if "JV" in texto:
        jv = _normalizar_jv(texto)
        if not jv:
            raise ErrorCotizacion(f"'{numero}' no es un numero de cotizacion valido.")
        fila = buscar_emitida(jv)
        if fila is None:
            raise ErrorCotizacion(f"No existe una cotizacion {jv} emitida.")
        return {"referencia": jv, "titulo": fila["cliente"], "ruta": fila["pdf_ruta"]}

    if re.fullmatch(r"\d{1,}", texto):
        header = _cotiz_jh_por_numero(int(texto))
        if header:
            return {"referencia": str(int(texto)),
                    "titulo": _texto(header.get("clientenombre")),
                    "ruta": _generar_pdf_jh(header)}
        jv = formato(int(texto))
        fila = buscar_emitida(jv)
        if fila is not None:
            return {"referencia": jv, "titulo": fila["cliente"], "ruta": fila["pdf_ruta"]}
        raise ErrorCotizacion(
            f"No encontre la cotizacion {texto} (ni de Jarvis ni de JH) para enviar."
        )

    raise ErrorCotizacion(f"'{numero}' no es un numero de cotizacion.")


# Palabras de relleno al pedir "la cotizacion numero X": si al quitarlas solo
# queda un numero, ese numero es el de una cotizacion (no el codigo de un cliente).
_FILLER = {
    "la", "el", "los", "las", "de", "del", "por", "favor", "dame", "muestra",
    "cotizacion", "cotización", "numero", "número", "nro", "factura", "orden",
    "nota", "ver", "y", "jv", "jarvis", "n", "cliente", "clienta",
    # Como se pide en voz: "jalame la 1016", "traeme la cotizacion 3807".
    "jalame", "jálame", "trae", "traeme", "tráeme", "busca", "buscame", "búscame",
    "abre", "abreme", "ábreme", "dime", "que", "qué", "tiene", "me",
}


def _numero_suelto(texto: str) -> int | None:
    """El numero, si el texto es solo un numero con palabras de relleno."""
    tokens = re.findall(r"[0-9]+|[a-záéíóúñ#]+", texto.lower())
    numeros = [t for t in tokens if t.isdigit()]
    letras = [t for t in tokens if not t.isdigit() and t.strip("#") not in _FILLER]
    return int(numeros[0]) if len(numeros) == 1 and not letras else None


# Palabras de "la ultima/en general": si al quitarlas no queda ni cliente ni
# numero, se pide la cotizacion mas reciente de todas.
_FILLER_GENERAL = _FILLER | {
    "ultima", "último", "última", "ultimas", "últimas", "general", "reciente",
    "recientes", "que", "hicieron", "hizo", "hicimos", "generada", "generadas",
    "genero", "generó", "generaron", "se", "en", "mas", "más", "nueva", "nuevas",
    "cual", "cuál", "fue", "todas", "todos", "hecha", "hechas", "cotizaciones",
}


def _es_general(texto: str) -> bool:
    """True si el texto pide 'la ultima en general', sin cliente ni numero."""
    tokens = re.findall(r"[0-9]+|[a-záéíóúñ#]+", texto.lower())
    meaningful = [t for t in tokens if not t.isdigit() and t.strip("#") not in _FILLER_GENERAL]
    return bool(tokens) and not meaningful and not any(t.isdigit() for t in tokens)


def _jv_por_numero(id_usuario: str, numero: str) -> str:
    filas = _filas_emitidas({
        "numero": f"eq.{int(numero[len(PREFIJO):])}",
        "estado": "eq.emitida", "select": _SELECT_ENCONTRADA,
    })
    if not filas:
        raise ErrorCotizacion(f"No encontre la cotizacion {numero} emitida.")
    return _guardar_y_resumir(id_usuario, filas[0])


def buscar(id_usuario: str, consulta: str) -> str:
    """Encuentra la ultima cotizacion (JH o JV) para mostrarla y recordarla."""
    texto = (consulta or "").strip()
    if not texto:
        raise ErrorCotizacion("Dime de que cliente o que numero de cotizacion busco.")

    # 1. Numero JV explicito -> cotizaciones de Jarvis.
    numero_jv = _normalizar_jv(texto)
    if numero_jv:
        return _jv_por_numero(id_usuario, numero_jv)

    # 2. "La ultima en general" (sin cliente ni numero) -> la mas reciente de todas.
    if _es_general(texto):
        return _ultima_general(id_usuario)

    # 3. Numero suelto -> cotizacion real de JH por su nfactura.
    consulta_cliente = texto
    numero = _numero_suelto(texto)
    if numero is not None:
        header = _cotiz_jh_por_numero(numero)
        if header:
            enc = _encontrada_desde_jh(header)
            return _resumen(id_usuario, enc, _fecha_corta(header.get("fecha")), _estado_jh(header))
        consulta_cliente = str(numero)   # no es una cotizacion; pruebalo como codigo
        # Si al final sale un cliente con ese codigo, que se sepa que NO era
        # una cotizacion: "la 1000" no existe, pero el cliente 1000 si. Salvo
        # que hayan dicho "cliente": entonces pedian eso.
        pidio_cliente = re.search(r"\bclient[ea]\b", texto.lower())
        no_existe = ("" if pidio_cliente else
                     f"La cotizacion {numero} no existe en JH; {numero} es el codigo de un cliente. ")
    else:
        no_existe = ""

    # 4. Resolver el cliente y buscar en AMBAS fuentes.
    clientes = buscar_cliente(consulta_cliente)
    if len(clientes) > 1:
        opciones = "; ".join(f"{_texto(c['nombre'])} (codigo {c['codigo']})" for c in clientes[:5])
        raise ErrorCotizacion(
            f"Hay varios clientes que coinciden: {opciones}. Dime cual es y busco su ultima cotizacion."
        )
    if clientes:
        codigo = _texto(clientes[0].get("codigo"))
        nombre_cli = _texto(clientes[0].get("nombre"))
        jh = _cotiz_jh_de_cliente(int(codigo)) if codigo.isdigit() else []
        jv = _filas_emitidas({
            "cliente->>codigo": f"eq.{codigo}", "estado": "eq.emitida",
            "order": "numero.desc", "limit": "5", "select": _SELECT_ENCONTRADA,
        })
        if jh and jv:
            h, v = jh[0], jv[0]
            raise ErrorCotizacion(
                f"{no_existe}{nombre_cli} tiene cotizaciones en los dos lados: la {int(h['nfactura'])} de JH "
                f"({_fecha_corta(h.get('fecha'))}, RD$ {_num(float(h.get('total') or 0))}) y la "
                f"{formato(int(v['numero']))} de Jarvis ({_fecha_corta(v.get('creada_at'))}, "
                f"RD$ {_num(float(v['total']))}). Dime con cual sigo, por el numero."
            )
        if jh:
            header = jh[0]
            nota = no_existe + (f"(hay {len(jh)} de JH de este cliente; esta es la ultima) " if len(jh) > 1 else "")
            enc = _encontrada_desde_jh(header)
            return _resumen(id_usuario, enc, _fecha_corta(header.get("fecha")), _estado_jh(header), nota)
        if jv:
            nota = no_existe + (f"(hay {len(jv)} de Jarvis de este cliente; esta es la ultima) " if len(jv) > 1 else "")
            return _guardar_y_resumir(id_usuario, jv[0], nota)
        raise ErrorCotizacion(
            f"{no_existe}No encontre cotizaciones de {nombre_cli}. Si quieres, preparo una nueva "
            "con preparar_cotizacion."
        )

    if numero is not None:
        raise ErrorCotizacion(f"No existe la cotizacion {numero} (ni en JH ni en Jarvis) "
                              "ni un cliente con ese codigo.")

    # 5. Respaldo: por nombre dentro de las JV (sirve para clientes de contado).
    filas = _filas_emitidas({
        "cliente->>nombre": f"ilike.*{texto}*", "estado": "eq.emitida",
        "order": "numero.desc", "limit": "5", "select": _SELECT_ENCONTRADA,
    })
    if not filas:
        raise ErrorCotizacion(
            f"No encontre cotizaciones de '{texto}'. Si quieres, preparo una nueva con preparar_cotizacion."
        )
    nota = f"(hay {len(filas)}; esta es la ultima) " if len(filas) > 1 else ""
    return _guardar_y_resumir(id_usuario, filas[0], nota)


def _normalizar_nivel(texto: str) -> str:
    """"7", "P7", "precio 7" -> "P7". Error si no es P1..P7."""
    encontrado = re.search(r"[1-7]", str(texto or ""))
    if not encontrado:
        raise ErrorCotizacion("El nivel tiene que ser de P1 a P7. ¿A que nivel la quieres?")
    return f"P{encontrado.group(0)}"


def _nivel_y_utilidad(nivel, utilidad) -> tuple[str, float]:
    """El nivel (P1..P7) y el % de utilidad.

    Soporta la nomenclatura de JH, un numero pegado donde la PRIMERA cifra es el
    nivel y el RESTO el porcentaje de utilidad: "55" = P5 con 5%, "47" = P4 con
    7%, "550" = P5 con 50%. Solo cuando no vino la utilidad por separado.
    """
    nivel_txt = str(nivel or "").strip()
    util_txt = str(utilidad or "").strip()
    solo = re.sub(r"\D", "", nivel_txt)
    if not util_txt and len(solo) >= 2:
        if solo[0] not in "1234567":
            raise ErrorCotizacion("El nivel (la primera cifra) tiene que ser de 1 a 7.")
        return f"P{solo[0]}", _leer_utilidad(solo[1:])
    return _normalizar_nivel(nivel_txt), _leer_utilidad(util_txt)


# --------------------------------------------------------------------------
# Mesa: variantes, ajustes y margenes
# --------------------------------------------------------------------------

def _pct(valor: float | None) -> str:
    return "sin costo" if valor is None else f"{valor:.1f}%"


def _tabla(lineas: list[dict]) -> str:
    """Una fila por producto, numeradas como en el PDF."""
    filas = []
    for n, l in enumerate(lineas, start=1):
        costo = l.get("costo")
        filas.append(
            f"{n}. {_cantidad(float(l['cantidad']))} {l.get('unidad') or 'UND'} de "
            f"{l.get('descripcion') or l['codigo']} (cod {l['codigo']}): "
            f"RD$ {_num(l['precio_unitario'])} c/u, "
            + (f"costo {_num(costo)}, margen {_pct(margenes.margen(l['precio_unitario'], costo))}, "
               f"ganancia RD$ {_num((l['precio_unitario'] - costo) * float(l['cantidad']))}"
               if costo else "sin costo en el catalogo")
            + _linea_al_cotizar(l)
        )
    return "\n".join(filas)


def _linea_al_cotizar(linea: dict) -> str:
    entonces, hoy = linea.get("costo_cotizado"), linea.get("costo")
    if not entonces or (hoy and abs(entonces - hoy) < 0.005):
        return ""
    return (f" (al cotizar: costo {_num(entonces)}, margen "
            f"{_pct(margenes.margen(linea['precio_unitario'], entonces))})")


def _general(analisis: dict, piso: float | None = None) -> str:
    return (
        f"Margen general: {_pct(analisis['margen'])} sobre el costo "
        f"(costo RD$ {_num(analisis['costo'])}, venta RD$ {_num(analisis['venta'])}, "
        f"ganancia RD$ {_num(analisis['ganancia'])}), con el costo de hoy del catalogo."
        + _avisos(analisis, piso)
    )


def _avisos(analisis: dict, piso: float | None) -> str:
    """Lo que hay que decir si o si: sin costo, a perdida y el piso."""
    texto = ""
    if analisis["sin_costo"]:
        texto += (f" Sin costo en el catalogo (fuera del calculo): producto(s) "
                  f"{', '.join(map(str, analisis['sin_costo']))}.")
    if analisis["a_perdida"]:
        texto += (f" A PERDIDA (precio bajo el costo): producto(s) "
                  f"{', '.join(map(str, analisis['a_perdida']))}.")
    if piso is not None and analisis["margen"] is not None:
        diferencia = analisis["margen"] - piso
        texto += (f" Piso {piso:g}%: le sobran {diferencia:.1f} puntos." if diferencia >= 0
                  else f" ROMPE EL PISO de {piso:g}%: le faltan {-diferencia:.1f} puntos.")
    return texto


def _normal(texto: str) -> str:
    import unicodedata

    sin_tildes = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", sin_tildes.lower())).strip()


# Palabras que se dicen al nombrar una cotizacion y no la distinguen.
_RELLENO_REF = {"la", "el", "de", "del", "a", "al", "con", "que", "esta", "cotizacion",
                "variante", "una", "otra", "por", "ciento", "porciento", "mas"}


def _palabras(texto: str) -> list[str]:
    return [p for p in _normal(texto).split() if p not in _RELLENO_REF]


def _es_la_original(m: dict, ref: str) -> bool:
    original = m.get("original")
    if not original:
        return False
    palabras = _palabras(ref)
    if palabras in (["original"], ["vieja"]):
        return True
    cifras = re.sub(r"\D", "", ref)
    return bool(cifras) and cifras.lstrip("0") == re.sub(r"\D", "", original["numero"]).lstrip("0")


def _resolver_variante(m: dict, ref: str) -> dict:
    """La variante que se nombro ("la del 50", "a costo", "P5")."""
    nombres = [v["nombre"] for v in m["variantes"]]
    if not nombres:
        raise ErrorCotizacion("No hay variantes sin emitir. Armalas con crear_variantes.")
    buscadas = _palabras(ref)
    exactas = [v for v in m["variantes"] if _palabras(v["nombre"]) == buscadas]
    if len(exactas) == 1:
        return exactas[0]
    parecidas = [v for v in m["variantes"]
                 if buscadas and all(p in _palabras(v["nombre"]) for p in buscadas)]
    if len(parecidas) == 1:
        return parecidas[0]
    if parecidas:
        raise ErrorCotizacion(
            f"'{ref}' puede ser: {', '.join(v['nombre'] for v in parecidas)}. Pregunta cual."
        )
    raise ErrorCotizacion(f"No hay una cotizacion '{ref}'. En la mesa estan: "
                          + ", ".join((["la original " + m["original"]["numero"]]
                                       if m.get("original") else []) + nombres) + ".")


def _resolver(m: dict, ref: str) -> tuple[str, dict]:
    """("original", datos) o ("variante", datos) segun lo que se nombro; sin
    nombre, la ultima que se toco."""
    ref = (ref or "").strip()
    if not ref:
        ultima = m.get("ultima")
        if ultima == "original" and m.get("original"):
            return "original", m["original"]
        variante = mesa.activa(m)
        if variante:
            return "variante", variante
        if m.get("original"):
            return "original", m["original"]
        raise ErrorCotizacion(
            "No hay ninguna cotizacion en curso (o pasaron 2 horas sin usarla). Busca una "
            "con buscar_cotizacion o arma una con preparar_cotizacion."
        )
    if _es_la_original(m, ref):
        return "original", m["original"]
    return "variante", _resolver_variante(m, ref)


def _resolver_linea(lineas: list[dict], ref) -> int:
    """El numero de linea (1..N) de lo que se nombro: el numero, el codigo o
    un pedazo de la descripcion."""
    texto = str(ref or "").strip()
    if not texto:
        raise ErrorCotizacion("Falta decir de que producto se habla.")
    cifras = re.sub(r"\D", "", texto)
    if cifras and cifras == texto.replace(" ", "") and 1 <= int(cifras) <= len(lineas):
        return int(cifras)
    for n, linea in enumerate(lineas, start=1):
        if _texto(linea["codigo"]).upper() == texto.upper():
            return n
    buscadas = _normal(texto).split()
    candidatas = [n for n, l in enumerate(lineas, start=1)
                  if buscadas and all(p in _normal(l.get("descripcion")) for p in buscadas)]
    if len(candidatas) == 1:
        return candidatas[0]
    if candidatas:
        opciones = "; ".join(f"{n}. {lineas[n - 1]['descripcion']}" for n in candidatas[:6])
        raise ErrorCotizacion(f"'{texto}' coincide con varios productos: {opciones}. Pregunta cual.")
    raise ErrorCotizacion(f"No hay un producto '{texto}' en esa cotizacion (tiene {len(lineas)}).")


def _leer_piso(m: dict, piso) -> None:
    """Fija, cambia o quita el piso de la mesa segun lo que se dijo."""
    texto = str(piso or "").strip().lower()
    if not texto:
        return
    if texto in ("no", "sin", "quitar", "quita", "ninguno", "nada"):
        m["piso"] = None
        return
    try:
        m["piso"] = float(texto.replace("%", "").replace(",", ".").strip())
    except ValueError:
        raise ErrorCotizacion(f"El piso no es un porcentaje: '{piso}'.") from None


def _leer_lista(texto, que: str) -> list[dict]:
    import json

    try:
        datos = json.loads(texto) if isinstance(texto, str) else texto
    except json.JSONDecodeError:
        raise ErrorCotizacion(f"Los {que} no son un JSON valido.") from None
    if isinstance(datos, dict):
        datos = [datos]
    if not isinstance(datos, list) or not datos or not all(isinstance(d, dict) for d in datos):
        raise ErrorCotizacion(f"Faltan los {que}.")
    return datos


def _numero(valor, que: str) -> float:
    try:
        return float(str(valor).replace("%", "").replace(",", "").strip())
    except (TypeError, ValueError):
        raise ErrorCotizacion(f"{que} no es un numero: '{valor}'.") from None


def _base_para_variantes(m: dict) -> tuple[dict, list[dict], str]:
    """Cliente, lineas y numero de origen de donde salen las variantes: la
    original si hay, si no la variante activa."""
    if m.get("original"):
        return m["original"]["cliente"], m["original"]["lineas"], m["original"]["numero"]
    activa = mesa.activa(m)
    if activa:
        return activa["cliente"], activa["lineas"], activa.get("origen") or ""
    raise ErrorCotizacion(
        "No hay ninguna cotizacion de donde sacar variantes (o pasaron 2 horas sin "
        "usarla). Busca una con buscar_cotizacion o arma una con preparar_cotizacion."
    )


def _variante(lineas: list[dict], pedido: dict) -> tuple[str, list[dict]]:
    """El nombre y las lineas de una variante pedida."""
    base = _normal(pedido.get("base") or "")
    if "costo" in base or "coste" in base:
        por_ciento = _numero(pedido.get("margen") or 0, "El margen")
        if por_ciento < 0:
            raise ErrorCotizacion("El margen sobre el costo no puede ser negativo.")
        sin_costo = [l["descripcion"] or l["codigo"] for l in lineas if not l.get("costo")]
        if sin_costo:
            raise ErrorCotizacion(
                f"Sin costo en el catalogo: {', '.join(sin_costo)}. No se puede cotizar a "
                "costo con esos productos; dilo."
            )
        nombre = "a costo" if not por_ciento else f"costo + {por_ciento:g}%"
        precios = [margenes.precio_con_margen(l["costo"], por_ciento) for l in lineas]
    elif "nivel" in base or "precio" in base:
        nivel, por_ciento = _nivel_y_utilidad(pedido.get("nivel"), pedido.get("utilidad"))
        nombre = nivel + (f" + {por_ciento:g}%" if por_ciento else "")
        # Igual que la recotizacion de antes: la utilidad del nivel es la de JH,
        # sobre el precio de venta.
        precios = [round(l["niveles"].get(nivel, 0) / (1 - por_ciento / 100), 2) for l in lineas]
        sin_precio = [l["descripcion"] or l["codigo"] for l, p in zip(lineas, precios) if p <= 0]
        if sin_precio:
            raise ErrorCotizacion(f"Sin precio {nivel} en el catalogo: {', '.join(sin_precio)}. "
                                  "No se puede cotizar asi; dilo.")
    elif "original" in base or "descuento" in base:
        por_ciento = _numero(pedido.get("descuento") or 0, "El descuento")
        if not 0 <= por_ciento < 100:
            raise ErrorCotizacion("El descuento tiene que estar entre 0 y 100.")
        nombre = "original" + (f" - {por_ciento:g}%" if por_ciento else "")
        precios = [round(l["precio_unitario"] * (1 - por_ciento / 100), 2) for l in lineas]
    else:
        raise ErrorCotizacion(
            f"Base de variante desconocida: '{pedido.get('base')}'. Es costo, nivel u original."
        )
    nuevas = []
    for linea, precio in zip(lineas, precios):
        nueva = _de_hoy(margenes.con_precio(linea, precio))
        nueva["precio_original"] = nueva["precio_unitario"]
        nueva["ajuste"] = nombre
        nuevas.append(nueva)
    return nombre, nuevas


def crear_variantes(id_usuario: str, variantes, piso="") -> str:
    """Saca una o varias variantes de la original (o del borrador) y las deja
    en la mesa, sin emitir."""
    pedidos = _leer_lista(variantes, "datos de las variantes")
    with mesa.candado:
        m = mesa.cargar(id_usuario)
        cliente, lineas, origen = _base_para_variantes(m)
        armadas = [_variante(lineas, pedido) for pedido in pedidos]
        _leer_piso(m, piso)
        mesa.guardar(id_usuario, m)
        for nombre, nuevas in armadas:
            _guardar_variante(id_usuario, nombre, cliente, nuevas, origen)
        piso_actual = mesa.cargar(id_usuario)["piso"]

    partes = []
    for nombre, nuevas in armadas:
        analisis = margenes.analizar(nuevas)
        partes.append(f"'{nombre}': total RD$ {_num(totalizar(nuevas)['total'])}, "
                      f"margen general {_pct(analisis['margen'])} sobre el costo"
                      + (" (a perdida en algun producto)" if analisis["a_perdida"] else ""))
    return (
        f"Listas {len(armadas)} variante(s) sin emitir, con los productos de "
        f"{origen or 'la cotizacion'} para {cliente.get('nombre')}: " + "; ".join(partes) + ". "
        + (f"Piso: {piso_actual:g}%. " if piso_actual is not None else "")
        + "Di el total y el margen de cada una y pregunta si las emite (todas o cuales). "
        "Llama a emitir_cotizacion solo si dice que si."
    )


def ajustar_precios(id_usuario: str, cambios, cotizacion: str = "", piso="") -> str:
    """Cambia el precio de una o varias lineas de una variante. Nunca bloquea:
    si rompe el piso o vende a perdida, lo aplica igual y lo avisa."""
    pedidos = _leer_lista(cambios, "cambios")
    with mesa.candado:
        m = mesa.cargar(id_usuario)
        tipo, cual = _resolver(m, cotizacion)
        if tipo == "original":
            # La original no se toca: se ajusta una copia.
            cual = _guardar_variante(id_usuario, "ajustada", cual["cliente"],
                                     [_de_hoy(dict(l, ajuste="original")) for l in cual["lineas"]],
                                     cual["numero"])
            m = mesa.cargar(id_usuario)
            cual = mesa.variante(m, cual["nombre"])
        _leer_piso(m, piso)
        antes = [dict(l) for l in cual["lineas"]]
        cambiadas = []
        for pedido in pedidos:
            n = _resolver_linea(cual["lineas"], pedido.get("linea") or pedido.get("producto"))
            linea = cual["lineas"][n - 1]
            if pedido.get("precio") not in (None, ""):
                precio, como = _numero(pedido["precio"], "El precio"), "precio fijo"
            elif pedido.get("margen") not in (None, ""):
                if not linea.get("costo"):
                    raise ErrorCotizacion(f"El producto {n} no tiene costo en el catalogo: no se "
                                          "le puede poner un margen. Dale un precio.")
                por_ciento = _numero(pedido["margen"], "El margen")
                precio, como = margenes.precio_con_margen(linea["costo"], por_ciento), f"costo + {por_ciento:g}%"
            elif pedido.get("nivel") not in (None, ""):
                nivel, util = _nivel_y_utilidad(pedido["nivel"], pedido.get("utilidad"))
                precio = round(linea["niveles"].get(nivel, 0) / (1 - util / 100), 2)
                como = nivel + (f" + {util:g}%" if util else "")
            elif pedido.get("descuento") not in (None, ""):
                por_ciento = _numero(pedido["descuento"], "El descuento")
                precio, como = round(linea["precio_unitario"] * (1 - por_ciento / 100), 2), f"- {por_ciento:g}%"
            elif str(pedido.get("original") or "").strip().lower() in ("si", "true", "1", "sí"):
                precio, como = linea["precio_original"], linea.get("ajuste") or "original"
            else:
                raise ErrorCotizacion(f"No dice que hacerle al producto {n}: precio, margen, "
                                      "nivel, descuento u original.")
            if precio <= 0:
                raise ErrorCotizacion(f"El producto {n} quedaria sin precio; no se aplico nada.")
            nueva = margenes.con_precio(linea, precio)
            nueva["ajuste"] = como
            cual["lineas"][n - 1] = nueva
            cambiadas.append(n)
        cual["totales"] = totalizar(cual["lineas"])
        m["ultima"] = cual["nombre"]
        mesa.guardar(id_usuario, m)
        piso_actual = m["piso"]

    general_antes = margenes.analizar(antes)
    general = margenes.analizar(cual["lineas"])
    detalle = []
    for n in sorted(set(cambiadas)):
        a, d = antes[n - 1], cual["lineas"][n - 1]
        texto = (f"{n}. {d['descripcion']}: RD$ {_num(a['precio_unitario'])} -> "
                 f"RD$ {_num(d['precio_unitario'])}, margen {_pct(margenes.margen(a['precio_unitario'], a.get('costo')))}"
                 f" -> {_pct(margenes.margen(d['precio_unitario'], d.get('costo')))}")
        if d.get("costo") and d["precio_unitario"] < d["costo"]:
            texto += f" (A PERDIDA: el costo es {_num(d['costo'])})"
        if piso_actual is not None and general["margen"] is not None and general["margen"] < piso_actual:
            minimo = margenes.precio_minimo(cual["lineas"], n, piso_actual)
            if minimo is not None:
                texto += f" (para no romper el piso, lo mas bajo seria RD$ {_num(minimo)})"
        detalle.append(texto)
    return (
        f"Ajustada '{cual['nombre']}' (sin emitir). " + "; ".join(detalle) + ". "
        f"Margen general: {_pct(general_antes['margen'])} -> {_pct(general['margen'])} sobre el costo; "
        f"total RD$ {_num(cual['totales']['total'])}. "
        + _avisos(general, piso_actual).strip()
        + " Di el producto cambiado (precio y margen nuevo) y el margen general antes y "
        "despues. Si rompio el piso o quedo a perdida, dilo en la misma frase con la cifra; "
        "se aplico igual."
    )


def analizar(id_usuario: str, cotizacion: str = "", producto: str = "", piso="") -> str:
    """Margenes de una cotizacion de la mesa, sin cambiar nada."""
    with mesa.candado:
        m = mesa.cargar(id_usuario)
        _leer_piso(m, piso)
        if _normal(cotizacion) in ("todas", "todas las", "compara", "comparar", "compara todas"):
            mesa.guardar(id_usuario, m)
            filas = ([("original " + m["original"]["numero"], m["original"]["lineas"])]
                     if m.get("original") else [])
            filas += [(v["nombre"], v["lineas"]) for v in m["variantes"]]
            if not filas:
                raise ErrorCotizacion("No hay cotizaciones en curso. Busca una con buscar_cotizacion.")
            return (
                "Comparacion: " + "; ".join(
                    f"{nombre}: total RD$ {_num(totalizar(lineas)['total'])}, margen general "
                    f"{_pct(margenes.analizar(lineas)['margen'])}, ganancia RD$ "
                    f"{_num(margenes.analizar(lineas)['ganancia'])}" for nombre, lineas in filas)
                + ". Margenes sobre el costo, con el costo de hoy del catalogo."
                + (_margen_al_cotizar(m["original"]).replace(" Al dar el margen, di los dos, "
                                                             "cada uno con su nombre.", "")
                   if m.get("original") else "")
            )
        tipo, cual = _resolver(m, cotizacion)
        m["ultima"] = "original" if tipo == "original" else cual["nombre"]
        mesa.guardar(id_usuario, m)
        piso_actual = m["piso"]

    lineas = cual["lineas"]
    nombre = f"{cual['numero']} (original)" if tipo == "original" else f"'{cual['nombre']}'"
    general = margenes.analizar(lineas)
    texto = f"Cotizacion {nombre}, total RD$ {_num(totalizar(lineas)['total'])}. {_general(general, piso_actual)}"
    if tipo == "original":
        texto += _margen_al_cotizar(cual)

    if (producto or "").strip():
        n = _resolver_linea(lineas, producto)
        linea = lineas[n - 1]
        costo = linea.get("costo")
        if costo:
            ganancia = (linea["precio_unitario"] - costo) * float(linea["cantidad"])
            peso = ganancia / general["ganancia"] * 100 if general["ganancia"] else None
            texto += (f" Producto {n}, {linea['descripcion']}: RD$ {_num(linea['precio_unitario'])} c/u, "
                      f"costo {_num(costo)}, margen {_pct(margenes.margen(linea['precio_unitario'], costo))}, "
                      f"ganancia RD$ {_num(ganancia)}"
                      + (f" ({peso:.0f}% de la ganancia de la cotizacion)" if peso is not None else "")
                      + ".")
            entonces = linea.get("costo_cotizado")
            if entonces and abs(entonces - costo) >= 0.005:
                texto += (f" Cuando se cotizo: costo {_num(entonces)}, margen "
                          f"{_pct(margenes.margen(linea['precio_unitario'], entonces))}.")
            if piso_actual is not None:
                minimo = margenes.precio_minimo(lineas, n, piso_actual)
                texto += (f" Para no bajar del {piso_actual:g}% general, lo mas bajo que se puede "
                          f"dejar es RD$ {_num(minimo)}" + (" (eso ya es a perdida)" if minimo < costo else "")
                          + "." if minimo else f" Cualquier precio mantiene el {piso_actual:g}% general.")
        else:
            texto += f" El producto {n}, {linea['descripcion']}, no tiene costo en el catalogo."
        texto += " Di el margen del producto y el general."
    else:
        con_costo = [(n, margenes.margen(l["precio_unitario"], l["costo"]))
                     for n, l in enumerate(lineas, start=1) if l.get("costo")]
        if con_costo:
            n, valor = min(con_costo, key=lambda x: x[1])
            texto += f" El de menos margen es el {n} ({lineas[n - 1]['descripcion']}, {_pct(valor)})."
            holgados = sorted(con_costo, key=lambda x: -x[1])[:3]
            texto += " Los de mas margen: " + ", ".join(f"{k} ({_pct(v)})" for k, v in holgados) + "."
        texto += (f"\n{_tabla(lineas)}\nPor voz di el margen general, la ganancia y lo que llama "
                  "la atencion; la tabla solo si la piden. Por escrito muestra la tabla.")
    return texto


# Como toLocaleDateString('en-GB') en n8n: septiembre es "Sept".
_MESES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sept", "Oct", "Nov", "Dec")


def fecha_de_documento(momento: datetime) -> str:
    return f"{momento.day:02d}-{_MESES[momento.month - 1]}-{momento.year}"


def nombre_de(id_usuario: str) -> str:
    """El nombre de quien pide, para el campo Usuario del PDF."""
    from . import acceso, supabase_sesion

    for usuario in acceso.usuarios():
        if usuario.id == id_usuario:
            return usuario.nombre
    if id_usuario.startswith(supabase_sesion.PREFIJO):
        try:
            usuario = supabase_sesion.usuario_de_perfil(
                supabase_sesion.perfil_cacheado(id_usuario[len(supabase_sesion.PREFIJO):])
            )
            if usuario:
                return usuario.nombre
        except Exception:  # noqa: BLE001
            pass
    return id_usuario
