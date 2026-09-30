"""Cuanto gasta Jarvis: tokens y dolares, por turno.

Guarda un registro por respuesta y otro por sesion de voz. Con eso se puede
responder lo que de verdad importa: cuanto cuesta un minuto hablando.

Ademas de texto y voz se anota lo que cobra aparte: la transcripcion de lo que
dice el usuario en la voz, el TTS de los puentes y el PDF de cada cotizacion.
Quien lo gasta manda el uso (tokens, segundos, creditos); el precio lo pone
siempre este modulo.

Los precios viven en data/precios.json, que se crea solo la primera vez. Si
OpenAI los cambia, se editan ahi sin tocar codigo.
"""

import contextlib
import contextvars
import json
import sqlite3
import threading
from datetime import datetime, timedelta

from . import basedatos, rutas

_candado = threading.Lock()

MAXIMO_REGISTROS = 5000

# Los modos que se registran. 'sesion' (lo que duro una sesion de voz) y
# 'apertura' (que se abrio una) solo cuentan tiempo y sesiones: no cuestan ni se
# cobran, y no son consultas.
MODOS = ("texto", "voz", "transcripcion", "tts", "cotizacion", "sesion", "apertura")
SIN_COSTO = ("sesion", "apertura")
# Los que un navegador o un puente pueden informar por /api/consumo/voz.
MODOS_INFORMADOS = ("voz", "transcripcion", "tts", "apertura")

MODELO_TRANSCRIPCION = "gpt-live-transcribe"
MODELO_PDF = "pdfco"


def archivo() -> "object":
    return rutas.archivo("consumo.jsonl")


def archivo_precios() -> "object":
    return rutas.archivo("precios.json")


# --------------------------------------------------------------------------
# Precios: dolares por millon de tokens
# --------------------------------------------------------------------------

# Los de gpt-realtime-2.1 y los modelos de texto salen de la documentacion de
# OpenAI. Los de -mini estan solo publicados para audio; los de texto son una
# estimacion conservadora y estan marcados como tal.
PRECIOS_POR_DEFECTO = {
    "gpt-realtime-2.1": {
        "texto_entrada": 4.0, "texto_cache": 0.4, "texto_salida": 24.0,
        "audio_entrada": 32.0, "audio_cache": 0.4, "audio_salida": 64.0,
        "imagen_entrada": 5.0,
        "confirmado": True,
    },
    "gpt-realtime-2.1-mini": {
        "texto_entrada": 1.25, "texto_cache": 0.15, "texto_salida": 7.5,
        "audio_entrada": 10.0, "audio_cache": 0.3, "audio_salida": 20.0,
        "confirmado": False,   # el audio si, el texto es estimado
    },
    "gpt-5.6-sol": {
        "texto_entrada": 5.0, "texto_cache": 0.5, "texto_salida": 30.0,
        "audio_entrada": 0.0, "audio_cache": 0.0, "audio_salida": 0.0,
        "confirmado": True,
    },
    "gpt-5.6-terra": {
        "texto_entrada": 2.0, "texto_cache": 0.2, "texto_salida": 12.0,
        "audio_entrada": 0.0, "audio_cache": 0.0, "audio_salida": 0.0,
        "confirmado": True,
    },
    "gpt-5.6-luna": {
        "texto_entrada": 0.2, "texto_cache": 0.02, "texto_salida": 1.2,
        "audio_entrada": 0.0, "audio_cache": 0.0, "audio_salida": 0.0,
        "confirmado": True,
    },
    "gpt-4o": {
        "texto_entrada": 2.5, "texto_cache": 1.25, "texto_salida": 10.0,
        "audio_entrada": 0.0, "audio_cache": 0.0, "audio_salida": 0.0,
        "confirmado": True,
    },
    # Transcribe lo que dice el usuario en la voz. Se cobra por duracion
    # ($0.017 el minuto, redondeado al segundo), no por tokens: su 'usage'
    # llega como {"type": "duration", "seconds": N}.
    MODELO_TRANSCRIPCION: {"minuto": 0.017, "confirmado": True},
    # El TTS de los puentes. Con stream_format "sse" devuelve input_tokens
    # (texto) y output_tokens (audio): ~25 tokens por segundo de voz.
    "gpt-4o-mini-tts": {
        "texto_entrada": 0.6, "texto_cache": 0.0, "texto_salida": 0.0,
        "audio_entrada": 0.0, "audio_cache": 0.0, "audio_salida": 12.0,
        "confirmado": True,
    },
    # PDF.co cobra en creditos (una cotizacion de una pagina, ~9). El precio
    # del credito depende del plan de la cuenta: este es el del Basic.
    MODELO_PDF: {"credito": 0.0006, "confirmado": False},
}


def precios() -> dict:
    """Los precios por defecto con lo que diga data/precios.json encima.

    El archivo se crea una vez y despues nadie lo actualiza: si se leyera solo,
    cada modelo o casilla que se agregue aqui despues -la transcripcion, el
    TTS, la imagen- no existiria en un volumen que ya tenia su archivo, y se
    anotaria a costo cero. Por eso se juntan, y lo escrito a mano gana.
    """
    ruta = archivo_precios()
    if not ruta.exists():
        ruta.write_text(
            json.dumps(PRECIOS_POR_DEFECTO, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {modelo: dict(tarifa) for modelo, tarifa in PRECIOS_POR_DEFECTO.items()}
    try:
        escritos = json.loads(ruta.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        escritos = {}

    juntos = {modelo: dict(tarifa) for modelo, tarifa in PRECIOS_POR_DEFECTO.items()}
    for modelo, tarifa in escritos.items():
        if isinstance(tarifa, dict):
            juntos[modelo] = {**juntos.get(modelo, {}), **tarifa}
    return juntos


def precio_de(modelo: str) -> dict:
    tabla = precios()
    if modelo in tabla:
        return tabla[modelo]
    # Un modelo desconocido no debe romper el tablero: se cuenta sin costo y
    # la interfaz avisa de que falta su precio.
    return {
        "texto_entrada": 0.0, "texto_cache": 0.0, "texto_salida": 0.0,
        "audio_entrada": 0.0, "audio_cache": 0.0, "audio_salida": 0.0,
        "confirmado": False, "desconocido": True,
    }


# --------------------------------------------------------------------------
# Normalizar el uso que devuelve cada API
# --------------------------------------------------------------------------

def desglosar(uso: dict) -> dict:
    """Separa el uso en las casillas que se cobran distinto.

    Realtime usa 'input_token_details' y Responses 'input_tokens_details'.
    Ademas los tokens cacheados vienen DENTRO de los de entrada, asi que hay
    que restarlos para no cobrarlos dos veces.

    Las imagenes llegan aparte, en 'image_tokens'. Sin su casilla se perdian:
    como el texto si venia desglosado, nadie las sumaba.
    """
    if not isinstance(uso, dict):
        return casillas_vacias()

    entrada = uso.get("input_token_details") or uso.get("input_tokens_details") or {}
    salida = uso.get("output_token_details") or uso.get("output_tokens_details") or {}
    cache = entrada.get("cached_tokens_details") or {}

    total_entrada = int(uso.get("input_tokens") or 0)
    total_salida = int(uso.get("output_tokens") or 0)

    entrada_texto = int(entrada.get("text_tokens") or 0)
    entrada_audio = int(entrada.get("audio_tokens") or 0)
    entrada_imagen = int(entrada.get("image_tokens") or 0)
    cacheados = int(entrada.get("cached_tokens") or 0)

    cache_texto = int(cache.get("text_tokens") or 0)
    cache_audio = int(cache.get("audio_tokens") or 0)
    cache_imagen = int(cache.get("image_tokens") or 0)

    # Si no hay desglose del cache, se atribuye todo al texto: es lo que pasa
    # en el modo texto, donde no hay audio.
    if cacheados and not (cache_texto or cache_audio or cache_imagen):
        cache_texto = cacheados

    # Lo que el total trae y el desglose no explica se cobra como texto. Cubre
    # el modo texto, que no desglosa, y cualquier modalidad que OpenAI agregue
    # manana: asi se quedaron fuera las imagenes, y no debe volver a pasar.
    entrada_texto += max(0, total_entrada - (entrada_texto + entrada_audio + entrada_imagen))

    salida_texto = int(salida.get("text_tokens") or 0)
    salida_audio = int(salida.get("audio_tokens") or 0)
    salida_texto += max(0, total_salida - (salida_texto + salida_audio))

    return {
        "entrada_texto": max(0, entrada_texto - cache_texto),
        "entrada_audio": max(0, entrada_audio - cache_audio),
        "entrada_imagen": max(0, entrada_imagen - cache_imagen),
        "cache_texto": cache_texto,
        "cache_audio": cache_audio,
        "cache_imagen": cache_imagen,
        "salida_texto": salida_texto,
        "salida_audio": salida_audio,
    }


def casillas_vacias() -> dict:
    return {
        "entrada_texto": 0, "entrada_audio": 0, "entrada_imagen": 0,
        "cache_texto": 0, "cache_audio": 0, "cache_imagen": 0,
        "salida_texto": 0, "salida_audio": 0,
    }


def calcular_costo(modelo: str, casillas: dict, segundos: float | None = None,
                   creditos: float | None = None) -> float:
    """Dolares de un registro: por tokens, por duracion o por creditos, segun
    lo que cobre ese modelo. Un modelo cobra de una sola forma, pero sumar las
    tres no cuesta nada y no obliga a saber de antemano cual es."""
    tarifa = precio_de(modelo)
    texto_entrada = tarifa.get("texto_entrada", 0.0)
    texto_cache = tarifa.get("texto_cache", 0.0)
    # Las tablas de precios de los modelos de texto no traen imagen: la cobran
    # como texto de entrada. Realtime si la cobra aparte (imagen_entrada).
    imagen_entrada = tarifa.get("imagen_entrada", texto_entrada)
    imagen_cache = tarifa.get("imagen_cache", texto_cache)
    por_tokens = (
        casillas["entrada_texto"] * texto_entrada
        + casillas["cache_texto"] * texto_cache
        + casillas["salida_texto"] * tarifa.get("texto_salida", 0.0)
        + casillas["entrada_audio"] * tarifa.get("audio_entrada", 0.0)
        + casillas["cache_audio"] * tarifa.get("audio_cache", 0.0)
        + casillas["salida_audio"] * tarifa.get("audio_salida", 0.0)
        + casillas["entrada_imagen"] * imagen_entrada
        + casillas["cache_imagen"] * imagen_cache
    ) / 1_000_000
    por_tiempo = (segundos or 0) / 60 * tarifa.get("minuto", 0.0)
    por_creditos = (creditos or 0) * tarifa.get("credito", 0.0)
    return por_tokens + por_tiempo + por_creditos


# --------------------------------------------------------------------------
# Registro
# --------------------------------------------------------------------------

CAMPOS = (
    "cuando", "modo", "modelo", "usuario_id", "organizacion_id", "dispositivo",
    *casillas_vacias(), "tokens", "segundos", "costo",
)


# Columnas que no admiten NULL. Un registro viejo puede no traerlas -las
# casillas de imagen, por ejemplo, no existian- y pasar NULL a mano no dispara
# el DEFAULT de la tabla: hay que poner el cero aqui.
_OBLIGATORIOS = {*casillas_vacias(), "tokens", "costo"}


def _guardar(registro: dict) -> dict:
    columnas = ", ".join(CAMPOS)
    huecos = ", ".join("?" for _ in CAMPOS)
    valores = tuple(
        registro.get(campo) if registro.get(campo) is not None
        else (0 if campo in _OBLIGATORIOS else None)
        for campo in CAMPOS
    )
    with _candado:
        with basedatos.conexion() as con:
            con.execute(f"INSERT INTO consumo ({columnas}) VALUES ({huecos})", valores)
    return registro


# Lo que llega de un reloj que todavia no manda su token: entra con la clave
# del puente, asi que su usuario es el del puente y no el de quien lo lleva.
RELOJ_SIN_VINCULAR = "reloj-sin-vincular"
LENTES_SIN_VINCULAR = "lentes-sin-vincular"

# Un puente que entra con la clave del admin puede decir quien es con el
# encabezado X-Jarvis-Puente. Es una pista, no una credencial: sigue entrando
# como admin -su memoria y su conversacion son las del admin- y solo cambia a
# quien se le anota el gasto.
PISTAS = {"reloj": RELOJ_SIN_VINCULAR, "lentes": LENTES_SIN_VINCULAR}
_PUENTE_DE_LA_PISTA = {pista: puente for puente, pista in PISTAS.items()}


def _a_quien_se_le_anota(usuario, dispositivo: str) -> tuple:
    """A que usuario y organizacion se le cuenta esto, y desde que aparato.

    Un reloj vinculado trae su propio token y cuenta por persona, como debe
    ser. Un puente (reloj o lentes) que entra con su propia clave no tiene a
    quien atribuirselo: se junta todo bajo el nombre del puente, en la
    organizacion que diga JARVIS_<PUENTE>_ORGANIZACION.
    """
    from . import cuentas

    id_usuario = usuario.id if usuario else None
    organizacion = getattr(usuario, "organizacion_id", None)

    # La clave propia del puente gana: vale para todo -chat, voz, fotos- y
    # para cualquier pista. Sin ella, el puente se reconoce por su pista: el
    # encabezado X-Jarvis-Puente o, en el chat del reloj, pedir respuestas
    # cortas (que los lentes tambien piden, pero ellos mandan el encabezado).
    if cuentas.es_puente(id_usuario):
        puente = id_usuario
    elif dispositivo in _PUENTE_DE_LA_PISTA:
        puente = _PUENTE_DE_LA_PISTA[dispositivo]
    else:
        return id_usuario, organizacion, dispositivo

    destino = cuentas.organizacion_del_puente(puente)
    if destino:
        id_usuario, organizacion = puente, destino
    return id_usuario, organizacion, puente


_sin_precio_avisados: set = set()


def _avisar_si_no_tiene_precio(modelo: str) -> None:
    """Un modelo sin precio se anota a costo cero, y por lo tanto no se cobra.
    El tablero ya lo marca; el log lo dice una vez, para quien mira Railway."""
    if modelo in _sin_precio_avisados or not precio_de(modelo).get("desconocido"):
        return
    _sin_precio_avisados.add(modelo)
    print(f"  AVISO: no hay precio para '{modelo}': se anota a costo cero y no "
          "se cobra. Agregalo en data/precios.json.")


def _desglose_segun_modo(modo: str, uso: dict) -> tuple[dict, float | None]:
    """Las casillas de tokens y los segundos que se cobran, segun el modo.

    - transcripcion: OpenAI la cobra por duracion y su usage lo dice asi,
      {"type": "duration", "seconds": N}. Si algun dia llega en tokens, se
      desglosa como cualquier otro.
    - tts: el usage de la sintesis no desglosa, y lo que sale es audio: los
      output_tokens van a la casilla de audio, no a la de texto.
    """
    if not isinstance(uso, dict):
        return casillas_vacias(), None

    if modo == "transcripcion" and uso.get("type") == "duration":
        return casillas_vacias(), float(uso.get("seconds") or 0)

    casillas = desglosar(uso)
    if modo == "tts" and not (uso.get("output_token_details") or uso.get("output_tokens_details")):
        casillas["salida_audio"] += casillas["salida_texto"]
        casillas["salida_texto"] = 0
    return casillas, None


def registrar(modo: str, modelo: str, uso: dict,
              segundos: float | None = None, usuario=None,
              dispositivo: str = "navegador") -> dict:
    """Anota una respuesta: 'texto', 'voz', 'transcripcion' o 'tts'.

    `usuario` es un acceso.Usuario (o None: quien llamaba antes de que esto
    existiera). Sin el no hay a quien atribuirle el gasto; con el, se guarda
    tambien su organizacion si tiene una, para poder cobrarle a ella.
    """
    casillas, por_duracion = _desglose_segun_modo(modo, uso)
    if por_duracion is not None:
        segundos = por_duracion
    id_usuario, organizacion, dispositivo = _a_quien_se_le_anota(usuario, dispositivo)
    _avisar_si_no_tiene_precio(modelo)
    return _guardar({
        "cuando": datetime.now().isoformat(timespec="seconds"),
        "modo": modo,
        "modelo": modelo,
        "usuario_id": id_usuario,
        "organizacion_id": organizacion,
        "dispositivo": dispositivo,
        **casillas,
        "tokens": sum(casillas.values()),
        "segundos": round(segundos, 2) if segundos else None,
        "costo": round(calcular_costo(
            modelo, casillas, segundos if por_duracion is not None else None
        ), 6),
    })


def registrar_sesion(modelo: str, segundos: float, usuario=None,
                     dispositivo: str = "navegador") -> dict:
    """Anota cuanto duro una sesion de voz, para el costo por minuto."""
    id_usuario, organizacion, dispositivo = _a_quien_se_le_anota(usuario, dispositivo)
    return _guardar({
        "cuando": datetime.now().isoformat(timespec="seconds"),
        "modo": "sesion",
        "modelo": modelo,
        "usuario_id": id_usuario,
        "organizacion_id": organizacion,
        "dispositivo": dispositivo,
        "segundos": round(segundos, 2),
        "tokens": 0,
        "costo": 0.0,
        **casillas_vacias(),
    })


def registrar_apertura(modelo: str, usuario=None, dispositivo: str = "navegador") -> dict:
    """Anota que se abrio una sesion de voz. No cuesta nada por si sola: sirve
    para comparar las sesiones que se abren con las que informan su gasto, y
    notar a quien dejo de informarlo (un puente caido, una app vieja)."""
    id_usuario, organizacion, dispositivo = _a_quien_se_le_anota(usuario, dispositivo)
    return _guardar({
        "cuando": datetime.now().isoformat(timespec="seconds"),
        "modo": "apertura",
        "modelo": modelo,
        "usuario_id": id_usuario,
        "organizacion_id": organizacion,
        "dispositivo": dispositivo,
        "tokens": 0,
        "costo": 0.0,
        **casillas_vacias(),
    })


# Quien esta usando Jarvis mientras corre una herramienta. Las herramientas
# solo reciben el id de la persona, y una que gasta por su cuenta -la
# cotizacion, en PDF.co- necesita tambien su organizacion y su aparato para
# anotarlo donde corresponde. Lo pone herramientas.ejecutar_completo.
_quien: contextvars.ContextVar = contextvars.ContextVar("consumo_quien", default=None)


@contextlib.contextmanager
def atribuir(usuario, dispositivo: str = "navegador"):
    marca = _quien.set((usuario, dispositivo))
    try:
        yield
    finally:
        _quien.reset(marca)


def registrar_cotizacion(creditos: float) -> dict | None:
    """Anota el PDF de una cotizacion con los creditos que dijo PDF.co.

    Nunca debe tumbar la cotizacion: el PDF ya existe y el cliente lo espera.
    """
    usuario, dispositivo = _quien.get() or (None, "navegador")
    try:
        id_usuario, organizacion, dispositivo = _a_quien_se_le_anota(usuario, dispositivo)
        return _guardar({
            "cuando": datetime.now().isoformat(timespec="seconds"),
            "modo": "cotizacion",
            "modelo": MODELO_PDF,
            "usuario_id": id_usuario,
            "organizacion_id": organizacion,
            "dispositivo": dispositivo,
            **casillas_vacias(),
            # En 'tokens' van las unidades que cobra el proveedor: aqui,
            # creditos de PDF.co.
            "tokens": int(creditos or 0),
            "costo": round(calcular_costo(MODELO_PDF, casillas_vacias(), creditos=creditos), 6),
        })
    except Exception:  # noqa: BLE001 - contabilizar no es critico
        return None


def todos() -> list[dict]:
    """Los registros mas recientes, del mas viejo al mas nuevo."""
    with basedatos.conexion() as con:
        filas = con.execute(
            f"SELECT {', '.join(CAMPOS)} FROM consumo ORDER BY id DESC LIMIT ?",
            (MAXIMO_REGISTROS,),
        ).fetchall()
    return [dict(fila) for fila in reversed(filas)]


def borrar() -> None:
    with _candado:
        with basedatos.conexion() as con:
            con.execute("DELETE FROM consumo")


def migrar_jsonl() -> None:
    """Sube a la base el consumo.jsonl de cuando esto era un archivo plano.

    Se ejecuta al arrancar. Es idempotente: si ya hay registros en la tabla no
    toca nada. El archivo viejo no se borra, se renombra: queda como respaldo
    frio por si algo salio mal.
    """
    ruta = archivo()
    if not ruta.exists():
        return

    with basedatos.conexion() as con:
        if con.execute("SELECT 1 FROM consumo LIMIT 1").fetchone():
            return

    migrados = 0
    with ruta.open(encoding="utf-8") as entrada:
        for linea in entrada:
            linea = linea.strip()
            if not linea:
                continue
            try:
                _guardar(json.loads(linea))
                migrados += 1
            except (json.JSONDecodeError, sqlite3.DatabaseError):
                # Una linea rota del archivo viejo no puede impedir arrancar.
                continue

    ruta.rename(ruta.with_suffix(".jsonl.migrado"))
    print(f"  Consumo migrado a la base de datos: {migrados} registros.")


# --------------------------------------------------------------------------
# Consulta con filtros
# --------------------------------------------------------------------------

PERIODOS = {
    "hoy": lambda: datetime.now().replace(hour=0, minute=0, second=0, microsecond=0),
    "24h": lambda: datetime.now() - timedelta(hours=24),
    "7d": lambda: datetime.now() - timedelta(days=7),
    "30d": lambda: datetime.now() - timedelta(days=30),
    "todo": lambda: datetime.min,
}


def del_periodo(desde: datetime) -> list[dict]:
    """Todos los registros desde esa fecha, del mas viejo al mas nuevo.

    Filtra en la base y no sobre los ultimos MAXIMO_REGISTROS: con mucho uso,
    30 dias pasan de 5000 registros y el tablero se quedaba corto. 'cuando' se
    guarda en ISO, asi que comparar texto es comparar fechas.
    """
    with basedatos.conexion() as con:
        filas = con.execute(
            f"SELECT {', '.join(CAMPOS)} FROM consumo WHERE cuando >= ? ORDER BY id",
            (desde.isoformat(timespec="seconds"),),
        ).fetchall()
    return [dict(fila) for fila in filas]


def modelos_registrados() -> list[str]:
    with basedatos.conexion() as con:
        filas = con.execute("SELECT DISTINCT modelo FROM consumo").fetchall()
    return sorted(fila["modelo"] for fila in filas)


def consultar(periodo: str = "7d", modo: str = "todos",
              modelo: str = "todos", organizacion: str = "todas") -> dict:
    """Resumen y detalle, con los filtros que pida la interfaz."""
    desde = PERIODOS.get(periodo, PERIODOS["7d"])()

    registros = [
        registro for registro in del_periodo(desde)
        if (modo == "todos" or registro.get("modo") == modo)
        and (modelo == "todos" or registro.get("modelo") == modelo)
        and (organizacion == "todas" or registro.get("organizacion_id") == organizacion)
    ]

    return {
        "periodo": periodo,
        "registros": list(reversed(registros[-200:])),
        "por_modelo": agrupar(registros),
        "por_origen": agrupar_por_origen(registros),
        "por_organizacion": agrupar_por_organizacion(registros),
        "totales": totalizar(registros),
        "modelos": modelos_registrados(),
        "precios": precios(),
    }


def agrupar(registros: list[dict]) -> list[dict]:
    """Una fila por modelo y modo, con sus ritmos por segundo y por minuto."""
    grupos: dict[tuple, dict] = {}

    for registro in registros:
        modo = registro.get("modo", "?")
        if modo == "apertura":
            continue
        # Las sesiones solo aportan tiempo; su costo ya esta en las respuestas.
        clave = (registro.get("modelo", "?"), "voz" if modo == "sesion" else modo)

        fila = grupos.setdefault(clave, {
            "modelo": clave[0], "modo": clave[1],
            "consultas": 0, "tokens": 0, "costo": 0.0, "segundos": 0.0,
            **casillas_vacias(),
        })

        if modo == "sesion":
            fila["segundos"] += registro.get("segundos") or 0
            continue

        fila["consultas"] += 1
        fila["tokens"] += registro.get("tokens", 0)
        fila["costo"] += registro.get("costo", 0.0)
        if registro.get("segundos"):
            fila["segundos"] += registro["segundos"]
        for casilla in casillas_vacias():
            fila[casilla] += registro.get(casilla, 0)

    filas = []
    for fila in grupos.values():
        consultas = fila["consultas"] or 1
        minutos = fila["segundos"] / 60 if fila["segundos"] else 0

        fila["costo"] = round(fila["costo"], 6)
        fila["costo_por_consulta"] = round(fila["costo"] / consultas, 6)
        fila["tokens_por_consulta"] = round(fila["tokens"] / consultas, 1)
        fila["costo_por_minuto"] = round(fila["costo"] / minutos, 6) if minutos else None
        fila["tokens_por_minuto"] = round(fila["tokens"] / minutos, 1) if minutos else None
        fila["costo_por_segundo"] = round(fila["costo"] / fila["segundos"], 8) if fila["segundos"] else None
        fila["tokens_por_segundo"] = round(fila["tokens"] / fila["segundos"], 2) if fila["segundos"] else None
        fila["minutos"] = round(minutos, 2)
        filas.append(fila)

    return sorted(filas, key=lambda f: f["costo"], reverse=True)


def agrupar_por_organizacion(registros: list[dict]) -> list[dict]:
    """Una fila por organizacion, para saber a quien cobrarle, y dentro de
    cada una lo de cada persona.

    Los registros sin organizacion -de antes de que esto existiera, o de
    gente sin organizacion- se agrupan aparte, sin inventarles una.
    """
    from . import cuentas

    grupos: dict[str | None, dict] = {}

    for registro in registros:
        if registro.get("modo") in SIN_COSTO:
            continue
        clave = registro.get("organizacion_id")
        fila = grupos.setdefault(clave, {
            "organizacion_id": clave,
            "organizacion": cuentas.nombre_organizacion(clave) or "(sin organizacion)",
            "margen": cuentas.margen(clave),
            "markup": cuentas.markup(clave),
            "consultas": 0, "tokens": 0, "costo": 0.0,
            "usuarios": {},
        })
        persona = fila["usuarios"].setdefault(registro.get("usuario_id"), {
            "usuario_id": registro.get("usuario_id"),
            "consultas": 0, "tokens": 0, "costo": 0.0,
        })
        for acumulado in (fila, persona):
            acumulado["consultas"] += 1
            acumulado["tokens"] += registro.get("tokens", 0)
            acumulado["costo"] += registro.get("costo", 0.0)

    # Los nombres se buscan una vez para todos: los de los paneles viven en
    # Supabase y pedirlos de a uno haria esperar al tablero.
    nombres = cuentas.nombres_de_usuarios(
        id_usuario for fila in grupos.values() for id_usuario in fila["usuarios"]
    )

    filas = list(grupos.values())
    for fila in filas:
        # Lo que cuesta y lo que se cobra son dos numeros distintos: el segundo
        # es el primero con el margen de esa organizacion encima.
        personas: dict = {}
        for persona in fila["usuarios"].values():
            nombre = nombres.get(persona["usuario_id"], persona["usuario_id"])
            # Quienes dan soporte van juntos en una fila: si solo se les
            # cambiara el nombre, saldrian tres filas llamadas igual.
            junta = nombre == cuentas.nombre_de_soporte()
            acumulado = personas.setdefault(nombre if junta else persona["usuario_id"], {
                "usuario_id": None if junta else persona["usuario_id"],
                "nombre": nombre, "consultas": 0, "tokens": 0, "costo": 0.0,
            })
            for clave in ("consultas", "tokens", "costo"):
                acumulado[clave] += persona[clave]

        for persona in personas.values():
            persona["cobrado"] = round(persona["costo"] * fila["markup"], 6)
            persona["costo"] = round(persona["costo"], 6)
        fila["usuarios"] = sorted(personas.values(), key=lambda p: p["costo"], reverse=True)
        fila["cobrado"] = round(fila["costo"] * fila["markup"], 6)
        fila["costo"] = round(fila["costo"], 6)
    return sorted(filas, key=lambda f: f["costo"], reverse=True)


def totalizar(registros: list[dict]) -> dict:
    consultas = [r for r in registros if r.get("modo") not in SIN_COSTO]
    segundos_voz = sum(
        r.get("segundos") or 0 for r in registros if r.get("modo") == "sesion"
    )
    costo_voz = sum(r.get("costo", 0.0) for r in consultas if r.get("modo") == "voz")
    minutos_voz = segundos_voz / 60

    return {
        "consultas": len(consultas),
        "tokens": sum(r.get("tokens", 0) for r in consultas),
        "costo": round(sum(r.get("costo", 0.0) for r in consultas), 6),
        "minutos_voz": round(minutos_voz, 2),
        "costo_voz": round(costo_voz, 6),
        "costo_por_minuto_voz": round(costo_voz / minutos_voz, 4) if minutos_voz else None,
        "tokens_por_minuto_voz": round(
            sum(r.get("tokens", 0) for r in consultas if r.get("modo") == "voz") / minutos_voz
        ) if minutos_voz else None,
    }


# --------------------------------------------------------------------------
# Por origen: cuanto gasta cada puente, y de que se compone
# --------------------------------------------------------------------------

# Cada origen es un 'dispositivo'. Las cotizaciones van aparte: las pide
# cualquiera, y lo que interesa es cuanto cuestan en total.
ORIGENES = {
    "navegador": "Web",
    "lentes": "Puente de los lentes",
    "reloj": "Puente del reloj",
}

# Un puente sin vincular es ese puente: se ve junto a los demas.
RELOJ_SIN_VINCULAR_A = _PUENTE_DE_LA_PISTA

# Lo que se cuenta en cada modo, para mostrar "30 min" y no "30 consultas".
UNIDADES = {
    "texto": "consultas",
    "voz": "respuestas",
    "transcripcion": "minutos",
    "tts": "respuestas leidas",
    "cotizacion": "cotizaciones",
}


def agrupar_por_origen(registros: list[dict]) -> list[dict]:
    """Una fila por origen con su total, y dentro, una linea por concepto.

    El total de cada origen es exactamente la suma de sus lineas, y el de todo
    Jarvis la suma de los origenes: el tablero muestra de donde sale cada
    numero. Ademas, por origen, las sesiones de voz que se abrieron contra las
    que informaron cuanto duraron: si no cuadran, alguien no esta informando.
    """
    from . import cuentas

    grupos: dict[str, dict] = {}

    def origen_de(registro: dict) -> str:
        if registro.get("modo") == "cotizacion":
            return "cotizaciones"
        dispositivo = registro.get("dispositivo") or "navegador"
        return RELOJ_SIN_VINCULAR_A.get(dispositivo, dispositivo)

    for registro in registros:
        clave = origen_de(registro)
        grupo = grupos.setdefault(clave, {
            "origen": clave,
            "nombre": "Cotizaciones (PDF.co)" if clave == "cotizaciones"
                      else ORIGENES.get(clave, clave),
            "costo": 0.0, "cobrado": 0.0,
            "conceptos": {},
            "sesiones_abiertas": 0, "sesiones_informadas": 0, "minutos_voz": 0.0,
        })
        modo = registro.get("modo", "?")

        if modo == "apertura":
            grupo["sesiones_abiertas"] += 1
            continue
        if modo == "sesion":
            grupo["sesiones_informadas"] += 1
            grupo["minutos_voz"] += (registro.get("segundos") or 0) / 60
            continue

        # Cobrado es lo que de verdad se descuenta en agentia: lo de quien no
        # tiene a quien cobrarle (el admin, el soporte) sale en cero.
        costo = registro.get("costo", 0.0)
        cobrado = costo * cuentas.markup(registro.get("organizacion_id")) \
            if _se_cobra(registro) else 0.0
        concepto = grupo["conceptos"].setdefault(modo, {
            "modo": modo, "unidad": UNIDADES.get(modo, "registros"),
            "cantidad": 0.0, "costo": 0.0, "cobrado": 0.0, "creditos": 0,
        })
        concepto["cantidad"] += (registro.get("segundos") or 0) / 60 \
            if modo == "transcripcion" else 1
        if modo == "cotizacion":
            concepto["creditos"] += registro.get("tokens", 0)
        concepto["costo"] += costo
        concepto["cobrado"] += cobrado
        grupo["costo"] += costo
        grupo["cobrado"] += cobrado

    filas = []
    for grupo in grupos.values():
        conceptos = sorted(grupo["conceptos"].values(), key=lambda c: c["costo"], reverse=True)
        for concepto in conceptos:
            concepto["cantidad"] = round(concepto["cantidad"], 2)
            concepto["costo"] = round(concepto["costo"], 6)
            concepto["cobrado"] = round(concepto["cobrado"], 6)
        grupo["conceptos"] = conceptos
        grupo["costo"] = round(grupo["costo"], 6)
        grupo["cobrado"] = round(grupo["cobrado"], 6)
        grupo["minutos_voz"] = round(grupo["minutos_voz"], 2)
        grupo["sesiones_sin_informar"] = max(
            0, grupo["sesiones_abiertas"] - grupo["sesiones_informadas"]
        )
        filas.append(grupo)
    return sorted(filas, key=lambda f: f["costo"], reverse=True)



def _se_cobra(registro: dict) -> bool:
    """Lo mismo que decide creditos.py: se cobra lo que tiene a quien."""
    from . import creditos

    return creditos.cliente_de(registro.get("organizacion_id")) is not None
