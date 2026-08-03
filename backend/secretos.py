"""Cifrado de credenciales en reposo.

Las contrasenas de tus bases no deben quedar legibles en un JSON. Aqui se
cifran con una clave local que se genera sola la primera vez.

Alcance honesto de esta proteccion: sirve para que el archivo de fuentes no
revele nada si se copia, se sincroniza a la nube o se comparte por error. NO
protege contra alguien que ya tenga acceso a tu usuario de Windows, porque la
clave vive en la misma maquina.
"""

import base64
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

DATA = Path(__file__).resolve().parent.parent / "data"
ARCHIVO_CLAVE = DATA / "clave.key"

MARCA = "cifrado:"

_motor: Fernet | None = None


def motor() -> Fernet:
    global _motor
    if _motor is None:
        _motor = Fernet(clave())
    return _motor


def clave() -> bytes:
    """Usa JARVIS_CLAVE_SECRETA si existe; si no, una generada en disco."""
    del_entorno = os.getenv("JARVIS_CLAVE_SECRETA", "").strip()
    if del_entorno:
        # Aceptamos cualquier texto: lo normalizamos al formato que pide Fernet.
        relleno = del_entorno.encode("utf-8").ljust(32, b"0")[:32]
        return base64.urlsafe_b64encode(relleno)

    DATA.mkdir(exist_ok=True)
    if not ARCHIVO_CLAVE.exists():
        ARCHIVO_CLAVE.write_bytes(Fernet.generate_key())
    return ARCHIVO_CLAVE.read_bytes()


def cifrar(texto: str) -> str:
    if not texto:
        return ""
    return MARCA + motor().encrypt(texto.encode("utf-8")).decode("ascii")


def descifrar(valor: str) -> str:
    """Descifra. Si el valor viene en claro lo devuelve tal cual.

    Esa tolerancia permite editar data/fuentes.json a mano cuando haga falta.
    """
    if not valor:
        return ""
    if not valor.startswith(MARCA):
        return valor
    try:
        return motor().decrypt(valor[len(MARCA):].encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return ""


def enmascarar(texto: str) -> str:
    """Lo que ve la interfaz: suficiente para reconocerlo, inutil para usarlo."""
    if not texto:
        return ""
    if len(texto) <= 4:
        return "•" * len(texto)
    return f"{texto[:2]}{'•' * min(8, len(texto) - 4)}{texto[-2:]}"
