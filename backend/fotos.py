"""Fotos que llegan de fuera: la app de los lentes, a traves del puente.

Aqui solo se decide si lo que llego es de verdad una imagen. Leerla es cosa de
cerebro.py y guardar la constancia, de memoria.py.
"""

import base64
import binascii

# Una foto de los lentes pesa ~240 KB. El tope deja margen y corta cualquier
# otra cosa antes de mandarsela a un modelo que cobra por token.
MAX_BYTES = 2 * 1024 * 1024

FIRMAS = {
    "image/jpeg": lambda b: b[:3] == b"\xff\xd8\xff",
    "image/png": lambda b: b[:8] == b"\x89PNG\r\n\x1a\n",
    "image/webp": lambda b: b[:4] == b"RIFF" and b[8:12] == b"WEBP",
}


def decodificar(mime: str, dato: str) -> bytes:
    """Los bytes de la foto, o ValueError con un motivo que se puede mostrar.

    Se mira la firma de los primeros bytes y no solo el mime: el mime lo
    escribe quien manda la foto.
    """
    firma = FIRMAS.get(mime or "")
    if firma is None:
        raise ValueError(f"Formato no admitido ({mime or 'sin mime'}).")

    # base64 ocupa 4/3 de lo que decodifica: se corta antes de decodificar.
    if len(dato or "") * 3 // 4 > MAX_BYTES + 3:
        raise ValueError(f"La foto pesa mas de {MAX_BYTES // 1024} KB.")

    try:
        datos = base64.b64decode(dato or "", validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("La foto no viene en base64 valido.") from None

    if not datos:
        raise ValueError("La foto llego vacia.")
    if len(datos) > MAX_BYTES:
        raise ValueError(f"La foto pesa mas de {MAX_BYTES // 1024} KB.")
    if not firma(datos):
        raise ValueError(f"El contenido no es {mime}.")
    return datos


def url_de_datos(mime: str, datos: bytes) -> str:
    return f"data:{mime};base64,{base64.b64encode(datos).decode('ascii')}"


def constancia(origen: str, motivo: str) -> str:
    """Lo que queda en el historial en lugar de la foto, que no se guarda."""
    de_donde = "de los lentes" if origen == "lentes" else "del telefono"
    return f"[Foto {de_donde}] {motivo}".strip()
