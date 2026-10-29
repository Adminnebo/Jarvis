"""Herramientas que Jarvis puede ejecutar.

Para agregar un servicio nuevo solo hay que escribir una funcion y decorarla
con @herramienta. El esquema que OpenAI necesita se arma solo a partir de la
firma y del docstring, asi que no hay que mantener JSON a mano.
"""

import inspect
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

import httpx

from . import consumo, memoria

REGISTRO: dict[str, dict] = {}


@dataclass
class ConAdjuntos:
    """Resultado de una herramienta que, ademas del texto para el modelo, trae
    archivos para mostrar en el chat (imagenes, fichas en PDF).

    El modelo solo recibe `texto`: los adjuntos van a la pantalla por su lado,
    y asi una URL larga no termina leida en voz alta.
    """

    texto: str
    adjuntos: list[dict] = field(default_factory=list)


def herramienta(descripcion: str, disponible: Callable[[], bool] | None = None,
                **descripciones_de_parametros: str):
    """Registra una funcion como herramienta disponible para el modelo.

    `disponible` la esconde del catalogo mientras devuelva False: una
    herramienta sin configurar solo le daria al modelo algo que falla.
    """

    def decorador(funcion: Callable):
        firma = inspect.signature(funcion)
        propiedades = {}
        requeridos = []

        for nombre, parametro in firma.parameters.items():
            # 'usuario' lo inyecta ejecutar(), no lo elige el modelo: si
            # apareciera en el esquema podria escribir en la memoria de otro.
            if nombre == "usuario":
                continue
            propiedades[nombre] = {
                "type": "string",
                "description": descripciones_de_parametros.get(nombre, nombre),
            }
            if parametro.default is inspect.Parameter.empty:
                requeridos.append(nombre)

        # Forma plana: es la que usan tanto la Responses API como Realtime.
        REGISTRO[funcion.__name__] = {
            "funcion": funcion,
            "necesita_usuario": "usuario" in firma.parameters,
            "disponible": disponible,
            "esquema": {
                "type": "function",
                "name": funcion.__name__,
                "description": descripcion,
                "parameters": {
                    "type": "object",
                    "properties": propiedades,
                    "required": requeridos,
                },
            },
        }
        return funcion

    return decorador


def esquemas() -> list[dict]:
    return [
        entrada["esquema"]
        for entrada in REGISTRO.values()
        if entrada["disponible"] is None or entrada["disponible"]()
    ]


def ejecutar_completo(nombre: str, argumentos_json: str, usuario: str,
                     quien=None, dispositivo: str = "navegador") -> tuple[str, list[dict]]:
    """Corre una herramienta: el texto para el modelo y los adjuntos, si trae.

    Devuelve siempre texto, incluso si falla. Un error aqui no debe tumbar la
    conversacion: se lo devolvemos al modelo para que lo explique o intente
    otra cosa.

    `quien` (el acceso.Usuario) y `dispositivo` son para las herramientas que
    gastan por su cuenta, como el PDF de la cotizacion: con eso su gasto se
    anota a la organizacion y al aparato de quien la pidio.
    """
    entrada = REGISTRO.get(nombre)
    if entrada is None:
        return f"Error: no existe la herramienta '{nombre}'.", []

    try:
        argumentos = json.loads(argumentos_json or "{}")
    except json.JSONDecodeError:
        # Pasa cuando la respuesta del modelo se corta a mitad de la llamada
        # (por ejemplo, alguien habla encima): los argumentos llegan truncados.
        return (
            f"Los argumentos de {nombre} llegaron cortados o mal formados. "
            "Vuelve a llamar a la herramienta con los argumentos completos."
        ), []

    try:
        if entrada["necesita_usuario"]:
            argumentos["usuario"] = usuario
        with consumo.atribuir(quien, dispositivo):
            resultado = entrada["funcion"](**argumentos)
        if isinstance(resultado, ConAdjuntos):
            return resultado.texto, resultado.adjuntos
        if isinstance(resultado, str):
            return resultado, []
        return json.dumps(resultado, ensure_ascii=False), []
    except Exception as error:  # noqa: BLE001 - se lo pasamos al modelo a proposito
        return f"Error al ejecutar {nombre}: {error}", []


# Las que cambian o muestran la mesa de cotizaciones: despues de cualquiera, la
# tabla de la web se vuelve a pintar.
DE_LA_MESA = {"buscar_cotizacion", "preparar_cotizacion", "crear_variantes",
              "ajustar_precios", "analizar_cotizacion", "emitir_cotizacion"}


def ejecutar(nombre: str, argumentos_json: str, usuario: str) -> str:
    """Como ejecutar_completo, para quien solo necesita el texto."""
    return ejecutar_completo(nombre, argumentos_json, usuario)[0]


# --------------------------------------------------------------------------
# Memoria
# --------------------------------------------------------------------------

@herramienta(
    "Guarda de forma permanente un dato sobre el usuario, sus preferencias, "
    "personas, proyectos o rutinas. Usala en cuanto el usuario mencione algo "
    "que valga la pena recordar en futuras conversaciones, sin preguntarle.",
    contenido="El hecho a recordar, escrito en tercera persona y completo por si solo",
    categoria="Una de: personal, trabajo, preferencias, contactos, proyectos, general",
)
def recordar(contenido: str, categoria: str = "general", usuario: str = "") -> str:
    hecho = memoria.recordar(usuario, contenido, categoria)
    return f"Guardado (id {hecho['id']}): {hecho['contenido']}"


@herramienta(
    "Busca en la memoria de largo plazo. Usala cuando el usuario pregunte por "
    "algo que te conto antes y no lo tengas presente en esta conversacion.",
    consulta="Palabras clave de lo que buscas",
)
def buscar_memoria(consulta: str, usuario: str = "") -> str:
    resultados = memoria.buscar(usuario, consulta)
    if not resultados:
        return "No hay nada en la memoria sobre eso."
    return "\n".join(f"- ({h['categoria']}) {h['contenido']}" for h in resultados)


@herramienta(
    "Borra un hecho de la memoria. Usala solo si el usuario pide olvidar algo "
    "o corrige un dato que resulto ser falso.",
    id_hecho="El id de 8 caracteres del hecho a borrar",
)
def olvidar(id_hecho: str, usuario: str = "") -> str:
    return "Listo, lo olvide." if memoria.olvidar(usuario, id_hecho) else "No encontre ese hecho."


# --------------------------------------------------------------------------
# Base de datos
# --------------------------------------------------------------------------

@herramienta(
    "Consulta la base de datos de cobranzas. Es tu via principal y la mas "
    "rapida: usa siempre una consulta del catalogo si alguna encaja, en vez "
    "de escribir SQL. El catalogo esta en tus instrucciones.",
    consulta="El nombre exacto de la consulta del catalogo",
    parametros='Parametros en JSON, por ejemplo {"limite": 5}. Omitelo si no lleva.',
)
def consultar_datos(consulta: str, parametros: str = "{}") -> str:
    from . import consultas

    try:
        argumentos = json.loads(parametros) if parametros else {}
    except json.JSONDecodeError:
        return "Error: 'parametros' no es JSON valido."

    if not isinstance(argumentos, dict):
        return "Error: 'parametros' debe ser un objeto JSON."

    resultado = consultas.ejecutar(consulta, argumentos)

    if "error" in resultado:
        return resultado["error"]
    if not resultado["filas"]:
        return f"La consulta '{consulta}' no devolvio resultados."

    return json.dumps(resultado["filas"], ensure_ascii=False, default=str)


@herramienta(
    "Devuelve las columnas de una tabla. Usala solo antes de escribir SQL a "
    "mano con execute_sql, cuando ninguna consulta del catalogo sirva.",
    tabla="Nombre exacto de la tabla",
)
def ver_esquema(tabla: str) -> str:
    from . import esquema

    return esquema.columnas_de(tabla)


@herramienta(
    "Ejecuta SQL en una de las fuentes de datos conectadas (PostgreSQL, SQL "
    "Server u otro Supabase). Usala solo para las fuentes listadas en tus "
    "instrucciones; la base de cobranzas principal va por `consultar_datos`.",
    fuente="El id de la fuente, tal como aparece en tus instrucciones",
    sql="La consulta SELECT a ejecutar",
)
def consultar_fuente(fuente: str, sql: str) -> str:
    from . import fuentes

    try:
        filas = fuentes.consultar(fuente, sql, limite=100)
    except ValueError as error:
        return f"Error: {error}"
    except Exception as error:  # noqa: BLE001
        pista = fuentes.pista_de_error(fuente, sql, error)
        return f"Error al consultar: {fuentes.explicar(error)}" + (f"\nPista: {pista}" if pista else "")

    if not filas:
        return "La consulta no devolvio resultados."
    return json.dumps(filas, ensure_ascii=False, default=str)[:6000]


@herramienta(
    "Responde una pregunta frecuente con un acceso directo: una consulta ya "
    "escrita y probada para una fuente. Es la via mas rapida: si la pregunta "
    "encaja con uno de los accesos directos de tus instrucciones, usalo antes "
    "de escribir SQL. Pasa solo las variables (fechas AAAA-MM-DD, numeros, textos).",
    nombre="El nombre del acceso directo, tal como aparece en tus instrucciones",
    parametros='Las variables en JSON, por ejemplo {"desde": "2026-10-26", "hasta": "2026-10-27"}. Omitelo para usar las de por defecto.',
)
def usar_acceso_directo(nombre: str, parametros: str = "{}") -> str:
    from . import accesos

    try:
        valores = json.loads(parametros) if parametros else {}
    except json.JSONDecodeError:
        return "Error: 'parametros' no es JSON valido."
    if not isinstance(valores, dict):
        return "Error: 'parametros' debe ser un objeto JSON."
    resultado = accesos.ejecutar(nombre, valores)
    if "error" in resultado:
        return resultado["error"]
    if not resultado["filas"]:
        return "El acceso directo no devolvio resultados."
    return json.dumps(resultado["filas"], ensure_ascii=False, default=str)[:6000]


@herramienta(
    "Busca filas por texto en una tabla de una fuente conectada. Es tu via "
    "preferida para encontrar un producto, un cliente o cualquier registro a "
    "partir de como lo nombra el usuario: exige que aparezcan todas las "
    "palabras y devuelve las mejores coincidencias primero. Usala en vez de "
    "escribir SQL con LIKE.",
    fuente="El id de la fuente",
    tabla="Nombre de la tabla donde buscar",
    texto="Las palabras del usuario, tal cual las dijo",
)
def buscar_en_fuente(fuente: str, tabla: str, texto: str) -> str:
    from . import fuentes

    try:
        filas = fuentes.buscar_en_tabla(fuente, tabla, texto, limite=8)
    except ValueError as error:
        return f"Error: {error}"
    except Exception as error:  # noqa: BLE001
        return f"Error al buscar: {fuentes.explicar(error)}"

    if not filas:
        return (f"Nada coincide con '{texto}' en {tabla}. "
                "Prueba con menos palabras o solo la marca.")
    return json.dumps(filas, ensure_ascii=False, default=str)[:6000]


@herramienta(
    "Lista las tablas y columnas de una fuente de datos conectada. Usala "
    "antes de escribir SQL para esa fuente.",
    fuente="El id de la fuente",
)
def ver_esquema_fuente(fuente: str) -> str:
    from . import fuentes

    try:
        datos = fuentes.esquema_de(fuente)
    except Exception as error:  # noqa: BLE001
        return f"Error: {fuentes.explicar(error)}"

    if not datos["tablas"]:
        return "Esa fuente no tiene tablas visibles."
    return "\n".join(f"{t['tabla']}: {t['columnas']}" for t in datos["tablas"])[:6000]


# --------------------------------------------------------------------------
# Imagenes y fichas tecnicas
# --------------------------------------------------------------------------

MAX_CODIGOS = 5
NOMBRE_DE_TIPO = {"imagen": "imagen", "ficha": "ficha tecnica"}


def _archivos_disponibles() -> bool:
    from . import archivos

    return archivos.configurado()


@herramienta(
    "Manda al chat la imagen y/o la ficha tecnica en PDF de productos del "
    "catalogo, para que el usuario las vea o las abra. Usala SOLO cuando te "
    "pidan ver, mandar, pasar o ensenar la foto, imagen o ficha tecnica de un "
    "producto. Necesita el Codigo exacto del catalogo: si no lo tienes, "
    "buscalo antes con buscar_en_fuente. Si un producto no tiene ese archivo, "
    "dilo tal cual y no mandes el de un producto parecido.",
    disponible=_archivos_disponibles,
    codigos="Codigo o codigos del catalogo separados por coma, maximo 5. Ej: '305400, 305388'",
    tipo="'imagen', 'ficha' o 'ambas'. Manda solo lo que te pidieron; 'ambas' si no lo dijeron",
    nombres="Opcional: la descripcion de cada producto, en el mismo orden y separadas por '|'",
)
def mandar_archivos_producto(codigos: str, tipo: str = "ambas", nombres: str = ""):
    from . import archivos

    if not archivos.configurado():
        return "Las imagenes y fichas tecnicas no estan configuradas en este servidor."

    tipos = {"imagen": ["imagen"], "ficha": ["ficha"], "ambas": ["imagen", "ficha"]}.get(
        (tipo or "ambas").strip().lower()
    )
    if tipos is None:
        return "Error: 'tipo' tiene que ser 'imagen', 'ficha' o 'ambas'."

    lista: list[str] = []
    for crudo in (codigos or "").split(","):
        codigo = archivos.normalizar(crudo)
        if codigo and codigo not in lista:
            lista.append(codigo)
    if not lista:
        return "Error: falta el Codigo del producto. Buscalo antes con buscar_en_fuente."
    if len(lista) > MAX_CODIGOS:
        return f"Error: son {len(lista)} productos; manda como mucho {MAX_CODIGOS} a la vez."

    titulos = [n.strip() for n in (nombres or "").split("|")]
    titulo_de = {c: (titulos[i] if i < len(titulos) and titulos[i] else c)
                 for i, c in enumerate(lista)}

    encontrados, faltan = archivos.buscar(lista, tipos)
    for adjunto in encontrados:
        adjunto["titulo"] = titulo_de[adjunto["codigo"]]

    partes = []
    if encontrados:
        enviados = ", ".join(
            f"{NOMBRE_DE_TIPO[a['tipo']]} de {a['titulo']}" for a in encontrados
        )
        partes.append(f"Enviado al chat: {enviados}.")
    if faltan:
        no_hay = ", ".join(f"{NOMBRE_DE_TIPO[t]} de {titulo_de[c]}" for c, t in faltan)
        partes.append(
            f"No existe {no_hay}: dilo asi y no ofrezcas el archivo de otro producto."
        )
    partes.append("No leas codigos ni enlaces en voz alta.")

    return ConAdjuntos(" ".join(partes), encontrados)


# --------------------------------------------------------------------------
# Cotizaciones
# --------------------------------------------------------------------------

def _cotizaciones_disponibles() -> bool:
    from . import cotizaciones

    return cotizaciones.configurado()


@herramienta(
    "Prepara el BORRADOR de una cotizacion (no la emite): busca al cliente y "
    "pone los precios del catalogo segun su nivel, o desde el costo si lo "
    "piden (al_costo y margen). Devuelve un resumen para que el usuario "
    "lo confirme. Nunca calcules ni inventes precios tu: salen de aqui. "
    "Necesita el Codigo exacto de cada producto; si no lo tienes, buscalo "
    "antes con buscar_en_fuente.",
    disponible=_cotizaciones_disponibles,
    productos='JSON con los productos y cantidades: [{"codigo": "9681", "cantidad": 100}]',
    cliente="Nombre, RNC o codigo del cliente, tal como lo dijo el usuario",
    contado="'si' solo si el cliente no esta registrado y va de contado (precio P1)",
    ciudad="Opcional: ciudad del cliente, si la dijeron",
    contacto="Opcional: persona de contacto, si la dijeron",
    al_costo="'si' solo si piden cotizar desde el costo en vez del nivel del cliente",
    margen="El margen SOBRE EL COSTO que pidieron ('al costo mas 30' es 30: costo 100 "
           "sale a 130). Solo con al_costo. Vacio o 0 cotiza al costo pelado.",
)
def preparar_cotizacion(productos: str, cliente: str = "", contado: str = "no",
                        ciudad: str = "", contacto: str = "", al_costo: str = "no",
                        margen: str = "", usuario: str = "") -> str:
    from . import cotizaciones

    try:
        return cotizaciones.preparar(
            usuario, cliente, productos,
            contado=(contado or "").strip().lower() in ("si", "sí", "true", "1"),
            ciudad=ciudad, contacto=contacto,
            al_costo=(al_costo or "").strip().lower() in ("si", "sí", "true", "1"),
            margen=margen or 0,
        )
    except cotizaciones.ErrorCotizacion as error:
        return str(error)


@herramienta(
    "Emite cotizaciones sin emitir de la mesa (de preparar_cotizacion, crear_variantes "
    "o ajustar_precios): le da numero (JV-...) a cada una, genera el PDF y lo manda al "
    "chat. Usala SOLO despues de que el usuario confirme con un si claro.",
    disponible=_cotizaciones_disponibles,
    cuales="Vacio para la que se esta trabajando; 'todas' para emitir todas las "
           "variantes; o el nombre de una ('a costo', 'costo + 50%', 'P5').",
)
def emitir_cotizacion(cuales: str = "", usuario: str = ""):
    from . import cotizaciones

    nombre = cotizaciones.nombre_de(usuario)
    try:
        if (cuales or "").strip().lower() in ("todas", "todas las", "las dos", "ambas", "las tres"):
            adjuntos, errores = cotizaciones.emitir_todas(usuario, nombre)
        else:
            adjuntos, errores = [cotizaciones.emitir(usuario, nombre, cuales)], []
    except cotizaciones.ErrorCotizacion as error:
        return str(error)
    emitidas = "; ".join(
        f"{a['numero']} ('{a['variante']}', total RD$ {a['total']:,.2f})" for a in adjuntos
    )
    texto = f"Emitida(s) y enviada(s) al chat: {emitidas}." if adjuntos else ""
    if errores:
        texto += " No se pudieron emitir: " + "; ".join(errores) + ". Dilo."
    texto += (" Confirmalo en una frase; no leas el numero completo ni enlaces salvo que "
              "lo pidan.")
    # El nombre de la variante es para el texto: el adjunto va tal cual a la web
    # y a los puentes.
    return ConAdjuntos(texto.strip(), [{k: v for k, v in a.items() if k != "variante"}
                                       for a in adjuntos])


@herramienta(
    "Busca una cotizacion YA EMITIDA para mostrarla y recordarla, tanto las reales "
    "de JH (numero tipo 3807) como las de Jarvis (numero JV-). Dale lo que diga el "
    "usuario (numero de cotizacion, codigo de cliente, RNC/cedula, nombre o telefono) "
    "y trae la ultima de ese cliente. Si no dicen cliente ni numero ('la ultima en "
    "general', 'la ultima que hicieron'), pasa la consulta tal cual y trae la ultima "
    "REAL de JH (las JV de Jarvis no se cuelan ahi). Usala cuando pidan 'jalame/dame/busca "
    "la cotizacion'. Devuelve sus productos con precio, costo y margen, y la deja como "
    "ORIGINAL en la mesa para sacarle variantes, ajustarla o analizarla. Buscar otra "
    "reemplaza la mesa.",
    disponible=_cotizaciones_disponibles,
    consulta="Lo que dijo el usuario: numero (3807 o JV-00012), codigo/RNC/nombre/telefono del cliente, o 'la ultima en general'",
)
def buscar_cotizacion(consulta: str, usuario: str = "") -> str:
    from . import cotizaciones

    try:
        return cotizaciones.buscar(usuario, consulta)
    except cotizaciones.ErrorCotizacion as error:
        return str(error)


@herramienta(
    "Arma una o varias cotizaciones nuevas (variantes, sin emitir) con los mismos "
    "productos y cantidades de la cotizacion traida con buscar_cotizacion (o del "
    "borrador en curso): a costo, a costo + X %, a un nivel P1..P7, o la misma con un "
    "descuento. Ej.: 'generame una a costo y otra con 50 % sobre el costo' -> dos "
    "variantes en UNA llamada. Despues pregunta si las emite y usa emitir_cotizacion. "
    "Nunca calcules precios tu.",
    disponible=_cotizaciones_disponibles,
    variantes='JSON, una por variante. Formas: {"base": "costo", "margen": 50} '
              '(margen SOBRE EL COSTO: costo 100 con 50 sale a 150; 0 o vacio = a costo), '
              '{"base": "nivel", "nivel": "P5", "utilidad": ""} (el nivel acepta la clave de '
              'JH pegada como "55"; pasala tal cual), {"base": "original", "descuento": 5}.',
    piso="Opcional: el % minimo de margen general que pidieron cuidar ('cuida un 18' es 18; "
         "'sin piso' lo quita). Sobre el costo.",
)
def crear_variantes(variantes: str, piso: str = "", usuario: str = "") -> str:
    from . import cotizaciones

    try:
        return cotizaciones.crear_variantes(usuario, variantes, piso)
    except cotizaciones.ErrorCotizacion as error:
        return str(error)


@herramienta(
    "Cambia el precio de uno o varios productos de una cotizacion en curso y dice el "
    "margen del producto y el general, antes y despues. Ej.: 'al 4 ponle 45 y al 5, 35'; "
    "'que el breaker gane 12 %'; 'bajale 5 % al 3'. Si la cotizacion es la original "
    "traida, ajusta una copia ('ajustada'). Nunca bloquea: si rompe el piso o vende a "
    "perdida se aplica igual y se avisa.",
    disponible=_cotizaciones_disponibles,
    cambios='JSON, uno por producto: {"linea": "4", "precio": 45} (precio unitario en RD$ '
            'con ITBIS), {"linea": "4", "margen": 12} (% sobre el costo), {"linea": "4", '
            '"nivel": "P5"}, {"linea": "4", "descuento": 5}, {"linea": "4", "original": "si"} '
            '(vuelve al precio con que nacio). "linea" es el numero del producto en la '
            'cotizacion, su codigo o parte de su descripcion.',
    cotizacion="Opcional: cual cotizacion de la mesa ('la del 50', 'a costo', 'la original', "
               "'la 1016'). Vacio = la ultima que se toco.",
    piso="Opcional: el % minimo de margen general que pidieron cuidar. Sobre el costo.",
)
def ajustar_precios(cambios: str, cotizacion: str = "", piso: str = "",
                    usuario: str = "") -> str:
    from . import cotizaciones

    try:
        return cotizaciones.ajustar_precios(usuario, cambios, cotizacion, piso)
    except cotizaciones.ErrorCotizacion as error:
        return str(error)


@herramienta(
    "Dice el margen de ganancia (sobre el costo) de una cotizacion en curso, de un "
    "producto dentro de ella, o compara todas, SIN cambiar nada. Ej.: 'cual es mi margen "
    "en la 1016', 'y el producto X en la original?', 'hasta donde puedo bajar el 4 sin "
    "bajar del 18 %', 'comparame las tres'.",
    disponible=_cotizaciones_disponibles,
    cotizacion="Opcional: cual ('la original', 'la 1016', 'la del 50', 'a costo'); 'todas' "
               "para compararlas. Vacio = la ultima que se toco.",
    producto="Opcional: el producto (numero en la cotizacion, codigo o parte de la descripcion).",
    piso="Opcional: el % minimo de margen general a cuidar; con producto, dice el precio "
         "mas bajo posible de ese producto.",
)
def analizar_cotizacion(cotizacion: str = "", producto: str = "", piso: str = "",
                        usuario: str = "") -> str:
    from . import cotizaciones

    try:
        return cotizaciones.analizar(usuario, cotizacion, producto, piso)
    except cotizaciones.ErrorCotizacion as error:
        return str(error)


@herramienta(
    "Margen de ganancia (sobre el costo) de UN producto en las cotizaciones de JH que "
    "ya se hicieron: todas, un periodo o las ultimas N. Ej.: 'cual es mi margen overall "
    "de ese cable en todas las cotizaciones', 'en las ultimas 10', 'desde septiembre'. "
    "JH no guarda el costo en sus cotizaciones: esta herramienta lo estima con la "
    "ultima compra antes de cada una. Usala en vez de escribir SQL o calcular tu.",
    disponible=_cotizaciones_disponibles,
    producto="Codigo del producto (mejor) o palabras de su descripcion.",
    desde="Opcional: fecha inicial AAAA-MM-DD.",
    hasta="Opcional: fecha final AAAA-MM-DD.",
    ultimas="Opcional: solo las N cotizaciones mas recientes con ese producto.",
)
def margen_historico(producto: str, desde: str = "", hasta: str = "", ultimas: str = "") -> str:
    from . import cotizaciones, historial

    try:
        return historial.margen_historico(producto, desde, hasta, ultimas)
    except cotizaciones.ErrorCotizacion as error:
        return str(error)


# --------------------------------------------------------------------------
# WhatsApp
# --------------------------------------------------------------------------

def _whatsapp_disponible() -> bool:
    from . import whatsapp

    return whatsapp.configurado()


@herramienta(
    "Prepara el envio por WhatsApp (no lo manda) de la imagen o ficha tecnica "
    "de productos y/o de una cotizacion a un numero. La cotizacion puede ser de "
    "Jarvis (JV-) o una real de JH (numero tipo 3813), que se arma en PDF tal "
    "cual. Devuelve el resumen para confirmarlo. Usala solo cuando pidan mandar "
    "algo a un numero de WhatsApp. Los productos van por su Codigo del catalogo.",
    disponible=_whatsapp_disponible,
    numero="El numero de WhatsApp tal como lo dijo el usuario",
    codigos="Opcional: codigos de productos separados por coma",
    tipo="Para productos: 'imagen', 'ficha' o 'ambas'. Solo lo que pidieron",
    nombres="Opcional: descripcion de cada producto, en el mismo orden y separadas por '|'",
    cotizacion="Opcional: numero de cotizacion a mandar: JV- de Jarvis (JV-00002) o de JH (3813)",
)
def preparar_envio_whatsapp(numero: str, codigos: str = "", tipo: str = "ambas",
                            nombres: str = "", cotizacion: str = "", usuario: str = "") -> str:
    from . import whatsapp

    try:
        return whatsapp.preparar(usuario, numero, codigos, tipo, nombres, cotizacion)
    except whatsapp.ErrorEnvio as error:
        return str(error)


@herramienta(
    "Manda por WhatsApp el envio preparado con preparar_envio_whatsapp. Usala "
    "SOLO despues de que el usuario confirme el numero y lo que se manda con "
    "un si claro.",
    disponible=_whatsapp_disponible,
)
def confirmar_envio_whatsapp(usuario: str = "") -> str:
    from . import cotizaciones, whatsapp

    try:
        return whatsapp.confirmar(usuario, cotizaciones.nombre_de(usuario))
    except whatsapp.ErrorEnvio as error:
        return str(error)


# --------------------------------------------------------------------------
# Servicios
# --------------------------------------------------------------------------

@herramienta(
    "Devuelve la fecha y hora actuales. Usala siempre que necesites saber "
    "que dia u hora es en lugar de suponerlo."
)
def hora_actual() -> str:
    dias = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
    meses = [
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    ]
    ahora = datetime.now()
    return (
        f"{dias[ahora.weekday()]} {ahora.day} de {meses[ahora.month - 1]} "
        f"de {ahora.year}, {ahora:%H:%M}"
    )


@herramienta(
    "Consulta el clima actual y el pronostico de hoy en cualquier ciudad.",
    ciudad="Nombre de la ciudad, por ejemplo 'Monterrey' o 'Madrid'",
)
def clima(ciudad: str) -> str:
    # Open-Meteo es gratis y no pide API key, por eso es el primer servicio.
    with httpx.Client(timeout=10) as cliente:
        geo = cliente.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": ciudad, "count": 1, "language": "es"},
        ).json()

        lugares = geo.get("results")
        if not lugares:
            return f"No encontre la ciudad '{ciudad}'."
        lugar = lugares[0]

        datos = cliente.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lugar["latitude"],
                "longitude": lugar["longitude"],
                "current": "temperature_2m,relative_humidity_2m,weather_code",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "timezone": "auto",
                "forecast_days": 1,
            },
        ).json()

    actual = datos["current"]
    hoy = datos["daily"]
    nombre = f"{lugar['name']}, {lugar.get('country', '')}".strip(", ")

    return (
        f"{nombre}: {actual['temperature_2m']}C ahora, "
        f"{DESCRIPCION_CLIMA.get(actual['weather_code'], 'condicion desconocida')}, "
        f"humedad {actual['relative_humidity_2m']}%. "
        f"Hoy entre {hoy['temperature_2m_min'][0]}C y {hoy['temperature_2m_max'][0]}C, "
        f"probabilidad de lluvia {hoy['precipitation_probability_max'][0]}%."
    )


# Codigos WMO que devuelve Open-Meteo.
DESCRIPCION_CLIMA = {
    0: "despejado", 1: "mayormente despejado", 2: "parcialmente nublado",
    3: "nublado", 45: "con niebla", 48: "con niebla helada",
    51: "llovizna ligera", 53: "llovizna", 55: "llovizna intensa",
    61: "lluvia ligera", 63: "lluvia", 65: "lluvia fuerte",
    71: "nieve ligera", 73: "nieve", 75: "nieve fuerte",
    80: "chubascos ligeros", 81: "chubascos", 82: "chubascos fuertes",
    95: "con tormenta", 96: "tormenta con granizo", 99: "tormenta fuerte con granizo",
}
