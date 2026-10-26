"""El asistente de cada organizacion: como se llama y como se ve.

El nombre sale de la tabla `asistentes`; si la organizacion no lo configuro (o
la persona no tiene organizacion, como las contrasenas por variable), de
JARVIS_NOMBRE, y si tampoco esta, "Jarvis". Los archivos -la foto y los tres
videos del avatar- viven en datos/avatares/<organizacion>/. Solo el super admin
los cambia: lo controla acceso.exige_admin.
"""

import os
import time
from datetime import datetime, timezone
from pathlib import Path

from . import acceso, basedatos, rutas

ESTADOS = ("reposo", "escuchando", "hablando")
LARGO_MAXIMO = 40


class ErrorDeAsistente(ValueError):
    """Algo de lo que mando el super admin no sirve; el mensaje es para el."""


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def por_defecto() -> str:
    return os.getenv("JARVIS_NOMBRE", "").strip() or "Jarvis"


def nombre(usuario: acceso.Usuario | None) -> str:
    organizacion_id = getattr(usuario, "organizacion_id", None)
    if organizacion_id:
        with basedatos.conexion() as con:
            fila = con.execute(
                "SELECT nombre FROM asistentes WHERE organizacion_id = ?", (organizacion_id,)
            ).fetchone()
        if fila and fila["nombre"]:
            return fila["nombre"]
    return por_defecto()


def _asegurar_fila(con, organizacion_id: str) -> None:
    con.execute(
        "INSERT OR IGNORE INTO asistentes (organizacion_id, actualizado) VALUES (?, ?)",
        (organizacion_id, _ahora()),
    )


def guardar_nombre(organizacion_id: str, valor: str) -> None:
    limpio = " ".join((valor or "").split())
    if len(limpio) > LARGO_MAXIMO:
        raise ErrorDeAsistente(f"El nombre puede tener hasta {LARGO_MAXIMO} letras.")
    with basedatos.conexion() as con:
        _asegurar_fila(con, organizacion_id)
        con.execute(
            "UPDATE asistentes SET nombre = ?, actualizado = ? WHERE organizacion_id = ?",
            (limpio or None, _ahora(), organizacion_id),
        )


def carpeta(organizacion_id: str) -> Path:
    destino = rutas.datos() / "avatares" / organizacion_id
    destino.mkdir(parents=True, exist_ok=True)
    return destino


def configuracion(organizacion_id: str) -> dict:
    with basedatos.conexion() as con:
        fila = con.execute(
            "SELECT nombre, foto FROM asistentes WHERE organizacion_id = ?", (organizacion_id,)
        ).fetchone()
        videos = {
            v["estado"]: v for v in con.execute(
                "SELECT estado, archivo, trabajo_estado, error FROM asistente_videos "
                "WHERE organizacion_id = ?", (organizacion_id,)
            )
        }
    return {
        "organizacion_id": organizacion_id,
        "nombre": fila["nombre"] if fila else None,
        "foto": fila["foto"] if fila else None,
        "videos": {
            e: {
                "archivo": videos[e]["archivo"] if e in videos else None,
                "trabajo_estado": videos[e]["trabajo_estado"] if e in videos else None,
                "error": videos[e]["error"] if e in videos else None,
            }
            for e in ESTADOS
        },
    }


# ---------------------------------------------------------------------------
# Foto
# ---------------------------------------------------------------------------

MAXIMO_FOTO = 8 * 1024 * 1024
# Por la firma del archivo, no por lo que diga el navegador.
FIRMAS = ((b"\xff\xd8\xff", "jpg", "image/jpeg"), (b"\x89PNG", "png", "image/png"))


def tipo_de_imagen(contenido: bytes) -> tuple[str, str] | None:
    """(extension, content type) o None si no es una imagen aceptada."""
    for firma, extension, tipo in FIRMAS:
        if contenido.startswith(firma):
            return extension, tipo
    if contenido[:4] == b"RIFF" and contenido[8:12] == b"WEBP":
        return "webp", "image/webp"
    return None


def _marca() -> str:
    return str(int(time.time() * 1000))


def guardar_foto(organizacion_id: str, contenido: bytes) -> str:
    if len(contenido) > MAXIMO_FOTO:
        raise ErrorDeAsistente("La foto puede pesar hasta 8 MB.")
    tipo = tipo_de_imagen(contenido)
    if not tipo:
        raise ErrorDeAsistente("La foto tiene que ser JPG, PNG o WEBP.")
    archivo = f"foto-{_marca()}.{tipo[0]}"
    (carpeta(organizacion_id) / archivo).write_bytes(contenido)
    with basedatos.conexion() as con:
        _asegurar_fila(con, organizacion_id)
        vieja = con.execute(
            "SELECT foto FROM asistentes WHERE organizacion_id = ?", (organizacion_id,)
        ).fetchone()["foto"]
        con.execute(
            "UPDATE asistentes SET foto = ?, actualizado = ? WHERE organizacion_id = ?",
            (archivo, _ahora(), organizacion_id),
        )
    if vieja and vieja != archivo:
        (carpeta(organizacion_id) / vieja).unlink(missing_ok=True)
    return archivo
