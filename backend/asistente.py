"""El asistente de cada organizacion: como se llama y como se ve.

El nombre sale de la tabla `asistentes`; si la organizacion no lo configuro (o
la persona no tiene organizacion, como las contrasenas por variable), de
JARVIS_NOMBRE, y si tampoco esta, "Jarvis". Los archivos -la foto y los tres
videos del avatar- viven en datos/avatares/<organizacion>/. Solo el super admin
los cambia: lo controla acceso.exige_admin.
"""

import os
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
