"""Herramientas que Jarvis puede ejecutar.

Para agregar un servicio nuevo solo hay que escribir una funcion y decorarla
con @herramienta. El esquema que OpenAI necesita se arma solo a partir de la
firma y del docstring, asi que no hay que mantener JSON a mano.
"""

import inspect
import json
from datetime import datetime
from typing import Callable

import httpx

from . import memoria

REGISTRO: dict[str, dict] = {}


def herramienta(descripcion: str, **descripciones_de_parametros: str):
    """Registra una funcion como herramienta disponible para el modelo."""

    def decorador(funcion: Callable):
        firma = inspect.signature(funcion)
        propiedades = {}
        requeridos = []

        for nombre, parametro in firma.parameters.items():
            propiedades[nombre] = {
                "type": "string",
                "description": descripciones_de_parametros.get(nombre, nombre),
            }
            if parametro.default is inspect.Parameter.empty:
                requeridos.append(nombre)

        # Forma plana: es la que usan tanto la Responses API como Realtime.
        REGISTRO[funcion.__name__] = {
            "funcion": funcion,
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
    return [entrada["esquema"] for entrada in REGISTRO.values()]


def ejecutar(nombre: str, argumentos_json: str) -> str:
    """Corre una herramienta y devuelve siempre texto, incluso si falla.

    Un error aqui no debe tumbar la conversacion: se lo devolvemos al modelo
    como resultado para que lo explique o intente otra cosa.
    """
    entrada = REGISTRO.get(nombre)
    if entrada is None:
        return f"Error: no existe la herramienta '{nombre}'."

    try:
        argumentos = json.loads(argumentos_json or "{}")
        resultado = entrada["funcion"](**argumentos)
        if isinstance(resultado, str):
            return resultado
        return json.dumps(resultado, ensure_ascii=False)
    except Exception as error:  # noqa: BLE001 - se lo pasamos al modelo a proposito
        return f"Error al ejecutar {nombre}: {error}"


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
def recordar(contenido: str, categoria: str = "general") -> str:
    hecho = memoria.recordar(contenido, categoria)
    return f"Guardado (id {hecho['id']}): {hecho['contenido']}"


@herramienta(
    "Busca en la memoria de largo plazo. Usala cuando el usuario pregunte por "
    "algo que te conto antes y no lo tengas presente en esta conversacion.",
    consulta="Palabras clave de lo que buscas",
)
def buscar_memoria(consulta: str) -> str:
    resultados = memoria.buscar(consulta)
    if not resultados:
        return "No hay nada en la memoria sobre eso."
    return "\n".join(f"- ({h['categoria']}) {h['contenido']}" for h in resultados)


@herramienta(
    "Borra un hecho de la memoria. Usala solo si el usuario pide olvidar algo "
    "o corrige un dato que resulto ser falso.",
    id_hecho="El id de 8 caracteres del hecho a borrar",
)
def olvidar(id_hecho: str) -> str:
    return "Listo, lo olvide." if memoria.olvidar(id_hecho) else "No encontre ese hecho."


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
        return f"Error al consultar: {fuentes.explicar(error)}"

    if not filas:
        return "La consulta no devolvio resultados."
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
