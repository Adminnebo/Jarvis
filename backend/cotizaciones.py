"""Cotizaciones de Jarvis, en paralelo a las de JH.

Van aparte a proposito: numeracion propia (JV-00001), guardadas en la tabla
jarvis_cotizaciones de Supabase y con el PDF en un bucket privado. No tocan la
Base JH ni la numeracion de Camila, asi que no pueden pisar una cotizacion real
ni disparar la alerta de salto de secuencia. La tabla guarda cliente, lineas y
totales completos para poder conectarlas con JH mas adelante.

Dos pasos, siempre:
  1. preparar(): busca cliente y productos en el catalogo y calcula. Los
     precios los pone el servidor, nunca el modelo: Camila inventaba precios
     cuando los tomaba de la conversacion.
  2. emitir(): solo despues de que la persona confirma. Le da numero, arma el
     PDF con PDF.co y lo deja en el chat.
"""

import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

from . import cotizacion_html

PREFIJO = "JV-"
NIVELES = tuple(f"P{i}" for i in range(1, 8))
MAX_LINEAS = 60
MAX_CANTIDAD = 1_000_000
VIGENCIA_BORRADOR = 30 * 60

# El enlace que viaja a la app de los lentes, que descarga sin sesion.
FIRMA_APP = 24 * 3600
# El de la web se pide cada vez que se abre, asi que basta con poco.
FIRMA_WEB = 300

URL_PDFCO = "https://api.pdf.co/v1/pdf/convert/from/html"
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


def configurado() -> bool:
    return all(_env(v) for v in (
        "JARVIS_FUENTE_CATALOGO", "JARVIS_BUCKET_COTIZACIONES", "PDFCO_API_KEY",
        "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_PROJECT_REF",
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

def _consultar(sql: str) -> list[dict]:
    from . import fuentes

    return fuentes.consultar(fuente_catalogo(), sql, limite=MAX_LINEAS)


def _texto(valor) -> str:
    return "" if valor is None else str(valor).strip()


def productos_del_catalogo(codigos: list[str]) -> dict[str, dict]:
    lista = ", ".join(f"'{c}'" for c in codigos)
    filas = _consultar(
        "SELECT LTRIM(RTRIM(Codigo)) AS Codigo, Referencia, Descripcion, Und, "
        f"{', '.join(NIVELES)}, TipoItbis FROM dbo.List_ProductosIA "
        f"WHERE Codigo IN ({lista})"
    )
    return {_texto(f["Codigo"]).upper(): f for f in filas}


_NOMBRE_PERMITIDO = re.compile(r"[^\w\s.&-]", re.UNICODE)


def buscar_cliente(texto: str) -> list[dict]:
    """Clientes activos por codigo, RNC o nombre. Nada llega crudo al SQL."""
    limpio = texto.strip()
    solo_digitos = re.sub(r"\D", "", limpio)

    if re.fullmatch(r"\d{1,6}", limpio):
        condicion = f"codigo = {int(limpio)}"
    elif re.fullmatch(r"[\d\s-]{9,15}", limpio) and 9 <= len(solo_digitos) <= 11:
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
        "SELECT TOP 6 codigo, nombre, RTRIM(rnc) AS rnc, direccion, email, "
        "telefono1, Celular, NivelPrecio, factor FROM dbo.List_ClientesIA "
        f"WHERE activo = 1 AND Suspendido = 0 AND {condicion} ORDER BY nombre"
    )


# --------------------------------------------------------------------------
# Borrador
# --------------------------------------------------------------------------

@dataclass
class Borrador:
    cliente: dict
    lineas: list[dict]
    totales: dict
    creado: float = field(default_factory=time.time)


_borradores: dict[str, Borrador] = {}
_candado = threading.Lock()


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


def calcular_linea(fila: dict, cantidad: float, nivel: str, factor: float) -> dict:
    """Una linea con los mismos calculos que la plantilla de n8n.

    Los precios del catalogo ya incluyen ITBIS: el bruto se despeja.
    """
    precio = round(float(fila.get(nivel) or 0) * factor, 2)
    try:
        tasa = float(fila.get("TipoItbis") or 0)
    except (TypeError, ValueError):
        tasa = 0.0
    bruto = precio / (1 + tasa / 100)
    return {
        "codigo": _texto(fila.get("Codigo")),
        "referencia": _texto(fila.get("Referencia")),
        "descripcion": _texto(fila.get("Descripcion")),
        "unidad": _texto(fila.get("Und")),
        "cantidad": cantidad,
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


def preparar(id_usuario: str, cliente: str, productos, contado: bool = False,
             ciudad: str = "", contacto: str = "") -> str:
    """Arma el borrador y devuelve el resumen para confirmar."""
    pedidos = _leer_productos(productos)
    datos_cliente = _resolver_cliente(cliente or "", contado, ciudad or "", contacto or "")

    catalogo = productos_del_catalogo([codigo for codigo, _ in pedidos])
    faltan = [codigo for codigo, _ in pedidos if codigo not in catalogo]
    if faltan:
        raise ErrorCotizacion(
            f"No existen en el catalogo: {', '.join(faltan)}. Busca los codigos "
            "correctos con buscar_en_fuente."
        )

    lineas = [
        calcular_linea(catalogo[codigo], cantidad, datos_cliente["nivel"], datos_cliente["factor"])
        for codigo, cantidad in pedidos
    ]
    sin_precio = [l["descripcion"] or l["codigo"] for l in lineas if l["precio_unitario"] <= 0]
    if sin_precio:
        raise ErrorCotizacion(
            f"Sin precio {datos_cliente['nivel']} en el catalogo: {', '.join(sin_precio)}. "
            "No se puede cotizar asi; dilo."
        )

    totales = totalizar(lineas)
    with _candado:
        _borradores[id_usuario] = Borrador(datos_cliente, lineas, totales)

    detalle = "; ".join(
        f"{_cantidad(l['cantidad'])} {l['unidad'] or 'UND'} de {l['descripcion']} "
        f"a {_num(l['precio_unitario'])} = {_num(l['subtotal_linea'])}"
        for l in lineas
    )
    tipo_cliente = "de contado" if contado else f"precio {datos_cliente['nivel']}"
    return (
        f"Borrador listo (aun NO emitido). Cliente: {datos_cliente['nombre']} ({tipo_cliente}). "
        f"{len(lineas)} producto(s): {detalle}. Total RD$ {_num(totales['total'])}, "
        f"ITBIS incluido RD$ {_num(totales['itbis'])}. "
        "Resume cliente, cantidad de productos y total, y pregunta si la emite. "
        "Llama a emitir_cotizacion solo si dice que si; si pide cambios, vuelve a "
        "llamar a preparar_cotizacion."
    )


def borrador_de(id_usuario: str) -> Borrador | None:
    with _candado:
        borrador = _borradores.get(id_usuario)
    if borrador and time.time() - borrador.creado > VIGENCIA_BORRADOR:
        return None
    return borrador


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
        URL_PDFCO,
        headers={"x-api-key": _env("PDFCO_API_KEY")},
        json={
            "html": html, "name": nombre, "paperSize": "Letter",
            # Los mismos margenes que usa n8n: la plantilla esta calibrada ahi.
            "margins": "3mm 10mm 2mm 10mm", "async": False, "inline": False,
        },
        timeout=120,
    )
    datos = respuesta.json()
    if respuesta.status_code >= 400 or datos.get("error") or not datos.get("url"):
        raise RuntimeError(f"PDF.co: {datos.get('message') or respuesta.status_code}")
    archivo = httpx.get(datos["url"], timeout=60)
    archivo.raise_for_status()
    if not archivo.content.startswith(b"%PDF"):
        raise RuntimeError("PDF.co no devolvio un PDF.")
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

def emitir(id_usuario: str, nombre_usuario: str) -> dict:
    """Emite el borrador de esa persona. Devuelve el adjunto para el chat."""
    borrador = borrador_de(id_usuario)
    if borrador is None:
        raise ErrorCotizacion(
            "No hay un borrador pendiente (o paso mas de media hora). Prepara la "
            "cotizacion otra vez con preparar_cotizacion."
        )

    # Se saca antes de emitir: un "si" repetido no debe emitir dos veces.
    with _candado:
        _borradores.pop(id_usuario, None)

    try:
        numero = _insertar({
            "usuario": nombre_usuario,
            "cliente": borrador.cliente,
            "productos": borrador.lineas,
            **borrador.totales,
            "estado": "generando",
        })
    except Exception as error:  # noqa: BLE001
        with _candado:
            _borradores.setdefault(id_usuario, borrador)
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
    except Exception as error:  # noqa: BLE001
        try:
            _actualizar(numero, {"estado": "fallida"})
        except Exception:  # noqa: BLE001
            pass
        # El borrador vuelve: reintentar da otro numero, y el fallido queda
        # marcado en la tabla.
        with _candado:
            _borradores.setdefault(id_usuario, borrador)
        raise ErrorCotizacion(f"No se pudo generar el PDF de la cotizacion: {error}") from None

    return {
        "tipo": "cotizacion",
        "numero": texto_numero,
        "titulo": f"Cotización {texto_numero} · {borrador.cliente['nombre']}",
        "archivo": ruta,
        "url": url,
        "enlace": f"/api/cotizaciones/{texto_numero}.pdf",
        "total": borrador.totales["total"],
    }


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
