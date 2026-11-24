"""Firma HMAC de los pedidos de Jarvis al bot.

firma = HMAC-SHA256(secreto, f"{tiempo}.{METODO}.{ruta}." + cuerpo), en hex.
Jarvis usa exactamente la misma cuenta (plan 2).
"""
import hashlib
import hmac
import time

VENTANA_S = 300


def firmar(secreto: str, tiempo: int, metodo: str, ruta: str, cuerpo: bytes) -> str:
    mensaje = f"{tiempo}.{metodo.upper()}.{ruta}.".encode() + cuerpo
    return hmac.new(secreto.encode(), mensaje, hashlib.sha256).hexdigest()


def verificar(secreto, tiempo_txt, firma, metodo, ruta, cuerpo, ahora=None) -> bool:
    try:
        tiempo = int(tiempo_txt)
    except (TypeError, ValueError):
        return False
    ahora = int(time.time()) if ahora is None else ahora
    if abs(ahora - tiempo) > VENTANA_S:
        return False
    esperada = firmar(secreto, tiempo, metodo, ruta, cuerpo)
    return hmac.compare_digest(esperada, firma or "")
