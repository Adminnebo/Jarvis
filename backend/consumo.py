"""Cuanto gasta Jarvis: tokens y dolares, por turno.

Guarda un registro por respuesta y otro por sesion de voz. Con eso se puede
responder lo que de verdad importa: cuanto cuesta un minuto hablando.

Los precios viven en data/precios.json, que se crea solo la primera vez. Si
OpenAI los cambia, se editan ahi sin tocar codigo.
"""

import json
import threading
from datetime import datetime, timedelta

from . import rutas

_candado = threading.Lock()

MAXIMO_REGISTROS = 5000


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
}


def precios() -> dict:
    ruta = archivo_precios()
    if not ruta.exists():
        ruta.write_text(
            json.dumps(PRECIOS_POR_DEFECTO, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return dict(PRECIOS_POR_DEFECTO)
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return dict(PRECIOS_POR_DEFECTO)


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
    """Separa el uso en las seis casillas que se cobran distinto.

    Realtime usa 'input_token_details' y Responses 'input_tokens_details'.
    Ademas los tokens cacheados vienen DENTRO de los de entrada, asi que hay
    que restarlos para no cobrarlos dos veces.
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
    cacheados = int(entrada.get("cached_tokens") or 0)

    cache_texto = int(cache.get("text_tokens") or 0)
    cache_audio = int(cache.get("audio_tokens") or 0)

    # Si no hay desglose del cache, se atribuye todo al texto: es lo que pasa
    # en el modo texto, donde no hay audio.
    if cacheados and not (cache_texto or cache_audio):
        cache_texto = cacheados

    # Sin desglose por modalidad (modo texto), todo lo de entrada es texto.
    if not (entrada_texto or entrada_audio):
        entrada_texto = total_entrada

    salida_texto = int(salida.get("text_tokens") or 0)
    salida_audio = int(salida.get("audio_tokens") or 0)
    if not (salida_texto or salida_audio):
        salida_texto = total_salida

    return {
        "entrada_texto": max(0, entrada_texto - cache_texto),
        "entrada_audio": max(0, entrada_audio - cache_audio),
        "cache_texto": cache_texto,
        "cache_audio": cache_audio,
        "salida_texto": salida_texto,
        "salida_audio": salida_audio,
    }


def casillas_vacias() -> dict:
    return {
        "entrada_texto": 0, "entrada_audio": 0,
        "cache_texto": 0, "cache_audio": 0,
        "salida_texto": 0, "salida_audio": 0,
    }


def calcular_costo(modelo: str, casillas: dict) -> float:
    tarifa = precio_de(modelo)
    total = (
        casillas["entrada_texto"] * tarifa["texto_entrada"]
        + casillas["cache_texto"] * tarifa["texto_cache"]
        + casillas["salida_texto"] * tarifa["texto_salida"]
        + casillas["entrada_audio"] * tarifa["audio_entrada"]
        + casillas["cache_audio"] * tarifa["audio_cache"]
        + casillas["salida_audio"] * tarifa["audio_salida"]
    )
    return total / 1_000_000


# --------------------------------------------------------------------------
# Registro
# --------------------------------------------------------------------------

def registrar(modo: str, modelo: str, uso: dict,
              segundos: float | None = None) -> dict:
    """Anota una respuesta. `modo` es 'voz' o 'texto'."""
    casillas = desglosar(uso)
    registro = {
        "cuando": datetime.now().isoformat(timespec="seconds"),
        "modo": modo,
        "modelo": modelo,
        **casillas,
        "tokens": sum(casillas.values()),
        "segundos": round(segundos, 2) if segundos else None,
        "costo": round(calcular_costo(modelo, casillas), 6),
    }

    with _candado:
        with archivo().open("a", encoding="utf-8") as salida:
            salida.write(json.dumps(registro, ensure_ascii=False) + "\n")

    return registro


def registrar_sesion(modelo: str, segundos: float) -> dict:
    """Anota cuanto duro una sesion de voz, para el costo por minuto."""
    registro = {
        "cuando": datetime.now().isoformat(timespec="seconds"),
        "modo": "sesion",
        "modelo": modelo,
        "segundos": round(segundos, 2),
        "tokens": 0,
        "costo": 0.0,
        **casillas_vacias(),
    }
    with _candado:
        with archivo().open("a", encoding="utf-8") as salida:
            salida.write(json.dumps(registro, ensure_ascii=False) + "\n")
    return registro


def todos() -> list[dict]:
    ruta = archivo()
    if not ruta.exists():
        return []
    registros = []
    with ruta.open(encoding="utf-8") as entrada:
        for linea in entrada:
            linea = linea.strip()
            if not linea:
                continue
            try:
                registros.append(json.loads(linea))
            except json.JSONDecodeError:
                continue
    return registros[-MAXIMO_REGISTROS:]


def borrar() -> None:
    with _candado:
        ruta = archivo()
        if ruta.exists():
            ruta.unlink()


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


def consultar(periodo: str = "7d", modo: str = "todos",
              modelo: str = "todos") -> dict:
    """Resumen y detalle, con los filtros que pida la interfaz."""
    desde = PERIODOS.get(periodo, PERIODOS["7d"])()

    registros = []
    for registro in todos():
        try:
            cuando = datetime.fromisoformat(registro["cuando"])
        except (KeyError, ValueError):
            continue
        if cuando < desde:
            continue
        if modo != "todos" and registro.get("modo") != modo:
            continue
        if modelo != "todos" and registro.get("modelo") != modelo:
            continue
        registros.append(registro)

    return {
        "periodo": periodo,
        "registros": list(reversed(registros[-200:])),
        "por_modelo": agrupar(registros),
        "totales": totalizar(registros),
        "modelos": sorted({r.get("modelo", "?") for r in todos()}),
        "precios": precios(),
    }


def agrupar(registros: list[dict]) -> list[dict]:
    """Una fila por modelo y modo, con sus ritmos por segundo y por minuto."""
    grupos: dict[tuple, dict] = {}

    for registro in registros:
        modo = registro.get("modo", "?")
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


def totalizar(registros: list[dict]) -> dict:
    consultas = [r for r in registros if r.get("modo") != "sesion"]
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
