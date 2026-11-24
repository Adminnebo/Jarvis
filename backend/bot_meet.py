"""Cliente del bot de Meet (EC2 bot-meet). Pedidos firmados con BOT_MEET_SECRETO.

firma = HMAC-SHA256(secreto, f"{tiempo}.{METODO}.{ruta}." + cuerpo), igual que
bot-meet/bot_meet/firma.py. Ver el contrato en
docs/superpowers/plans/2026-11-24-bot-meet-1-bot.md.
"""

import hashlib
import hmac
import json
import os
import time

import httpx

URL_JARVIS = "https://asistente.neboaiconsulting.com"


class ErrorBot(Exception):
    pass


class SinBotLibre(ErrorBot):
    pass


def configurado() -> bool:
    return bool(os.getenv("BOT_MEET_URL", "").strip() and os.getenv("BOT_MEET_SECRETO", "").strip())


def firmar(secreto: str, tiempo: int, metodo: str, ruta: str, cuerpo: bytes) -> str:
    mensaje = f"{tiempo}.{metodo.upper()}.{ruta}.".encode() + cuerpo
    return hmac.new(secreto.encode(), mensaje, hashlib.sha256).hexdigest()


def _http() -> httpx.Client:
    return httpx.Client(timeout=15)


def _pedir(metodo: str, ruta: str, cuerpo: bytes = b"") -> httpx.Response:
    t = int(time.time())
    cabeceras = {"X-Bot-Tiempo": str(t),
                 "X-Bot-Firma": firmar(os.environ["BOT_MEET_SECRETO"], t, metodo, ruta, cuerpo),
                 "Content-Type": "application/json"}
    base = os.environ["BOT_MEET_URL"].rstrip("/")
    try:
        with _http() as http:
            return http.request(metodo, base + ruta, content=cuerpo, headers=cabeceras)
    except httpx.HTTPError as error:
        raise ErrorBot(f"El bot no responde: {error}") from error


def agendar(id_: str, meet_url: str, inicio: str, fin: str, token_subida: str) -> None:
    cuerpo = json.dumps({"id": id_, "meet_url": meet_url, "inicio": inicio, "fin": fin,
                         "token_subida": token_subida, "url_jarvis": URL_JARVIS}).encode()
    r = _pedir("POST", "/v1/sesiones", cuerpo)
    if r.status_code == 409:
        raise SinBotLibre(id_)
    if r.status_code != 202:
        raise ErrorBot(f"El bot respondió {r.status_code}: {r.text[:200]}")


def cancelar(id_: str) -> bool:
    r = _pedir("DELETE", f"/v1/sesiones/{id_}")
    return r.status_code == 200
