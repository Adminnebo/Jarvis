"""Voz de la sala de juntas de la oficina 3D: texto -> MP3 con el TTS de OpenAI.

Cada agente de la oficina habla con su propia voz (la elige la oficina entre las de
OpenAI). Se pide con stream_format "sse" para que OpenAI devuelva el uso al final y
anotarlo en consumo como "tts" (lo mismo que hacen los puentes del reloj y los lentes).
"""
import base64
import json
import os
import urllib.error
import urllib.request

URL_VOZ = "https://api.openai.com/v1/audio/speech"
MODELO = os.getenv("JARVIS_SALA_TTS", "gpt-4o-mini-tts")
VOCES = {"alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer", "verse", "marin", "cedar"}
INSTRUCCIONES = ("Habla en español de República Dominicana, con un acento caribeño suave, natural, cálido y "
                 "profesional, como un colega en una reunión de trabajo. Ritmo normal, sin sonar a locutor.")


class ErrorVoz(Exception):
    pass


def leer_eventos(texto: str) -> tuple[bytes, dict | None]:
    """Junta el audio de los eventos speech.audio.delta y el uso de speech.audio.done."""
    trozos, uso = [], None
    for linea in texto.splitlines():
        if not linea.startswith("data:"):
            continue
        dato = linea[5:].strip()
        if not dato or dato == "[DONE]":
            continue
        try:
            evento = json.loads(dato)
        except ValueError:
            continue
        if evento.get("type") == "speech.audio.delta" and evento.get("audio"):
            trozos.append(base64.b64decode(evento["audio"]))
        elif evento.get("type") == "speech.audio.done":
            uso = evento.get("usage")
    if not trozos:
        raise ErrorVoz("OpenAI no devolvio audio.")
    return b"".join(trozos), uso


def sintetizar(texto: str, voz: str, clave: str, instrucciones: str = "") -> tuple[bytes, dict | None]:
    """Devuelve (mp3, uso). La voz que no existe cae en una conocida."""
    cuerpo = {
        "model": MODELO,
        "voice": voz if voz in VOCES else "alloy",
        "input": texto,
        "response_format": "mp3",
        "instructions": (instrucciones or INSTRUCCIONES)[:600],
        "stream_format": "sse",
    }
    pedido = urllib.request.Request(URL_VOZ, data=json.dumps(cuerpo).encode("utf-8"), method="POST",
                                    headers={"Authorization": f"Bearer {clave}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(pedido, timeout=60) as r:
            crudo = r.read()
            tipo = r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        raise ErrorVoz(f"OpenAI rechazo la voz ({e.code}): {e.read()[:200].decode('utf-8', 'replace')}") from e
    if "event-stream" not in tipo:
        return crudo, None
    return leer_eventos(crudo.decode("utf-8", "replace"))
