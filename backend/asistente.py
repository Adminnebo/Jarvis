"""El asistente de cada organizacion: como se llama y como se ve.

El nombre sale de la tabla `asistentes`; si la organizacion no lo configuro (o
la persona no tiene organizacion, como las contrasenas por variable), de
JARVIS_NOMBRE, y si tampoco esta, "Jarvis". Los archivos -la foto y los tres
videos del avatar- viven en datos/avatares/<organizacion>/. Solo el super admin
los cambia: lo controla acceso.exige_admin.
"""

import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import acceso, basedatos, higgsfield, rutas

ESTADOS = ("reposo", "escuchando", "hablando")
LARGO_MAXIMO = 40


class ErrorDeAsistente(ValueError):
    """Algo de lo que mando el super admin no sirve; el mensaje es para el."""


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def por_defecto() -> str:
    return os.getenv("JARVIS_NOMBRE", "").strip() or "Jarvis"


def organizacion_de(usuario: acceso.Usuario | None) -> str | None:
    """De que organizacion es el asistente que ve esta persona.

    La suya; y quien no tiene (el admin de la contrasena) ve el de los paneles,
    que es la empresa principal de esta instalacion (hoy JH).
    """
    from . import cuentas

    return getattr(usuario, "organizacion_id", None) or cuentas.organizacion_de_paneles()


def nombre(usuario: acceso.Usuario | None) -> str:
    organizacion_id = organizacion_de(usuario)
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


# ---------------------------------------------------------------------------
# Videos
# ---------------------------------------------------------------------------

# Para atrapar los rechazos de la API sin depender del modulo real en las pruebas.
higgsfield_error = higgsfield.ErrorDeHiggsfield

COMUN = ("same person as the image, head and shoulders, looking at the camera, "
         "plain dark background, soft studio light, static camera")
PROMPTS = {
    "reposo": f"{COMUN}. Breathing calmly, natural blinking, very slight head movement, mouth closed.",
    "escuchando": f"{COMUN}. Attentive expression, slight nod as if listening carefully, mouth closed.",
    "hablando": f"{COMUN}. Talking naturally as if explaining something, mouth moving, subtle head gestures.",
}
VENCE = timedelta(minutes=30)
CADA_SEGUNDOS = 15


def generar(organizacion_id: str, estados: list[str]) -> None:
    """Pide a Higgsfield un video por estado. El anterior sigue a la vista."""
    if not estados or any(e not in ESTADOS for e in estados):
        raise ErrorDeAsistente("Los videos son: reposo, escuchando y hablando.")
    if not higgsfield.configurado():
        raise ErrorDeAsistente("Falta la clave de Higgsfield en el servidor (HIGGSFIELD_API_KEY_ID/SECRET).")
    foto = configuracion(organizacion_id)["foto"]
    if not foto:
        raise ErrorDeAsistente("Primero subi una foto.")

    contenido = (carpeta(organizacion_id) / foto).read_bytes()
    url = higgsfield.subir_imagen(contenido, tipo_de_imagen(contenido)[1])
    for estado_ in dict.fromkeys(estados):
        try:
            rid, est, error = higgsfield.crear_video(url, PROMPTS[estado_]), "generando", None
        except higgsfield_error as fallo:
            rid, est, error = None, "error", str(fallo)
        with basedatos.conexion() as con:
            con.execute(
                "INSERT INTO asistente_videos "
                "(organizacion_id, estado, trabajo_id, trabajo_estado, trabajo_desde, error, actualizado) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (organizacion_id, estado) DO UPDATE SET trabajo_id = excluded.trabajo_id, "
                "trabajo_estado = excluded.trabajo_estado, trabajo_desde = excluded.trabajo_desde, "
                "error = excluded.error, actualizado = excluded.actualizado",
                (organizacion_id, estado_, rid, est, _ahora(), error, _ahora()),
            )


def _terminar(fila, nuevo: bytes) -> None:
    org, estado_ = fila["organizacion_id"], fila["estado"]
    archivo = f"{estado_}-{_marca()}.mp4"
    (carpeta(org) / archivo).write_bytes(nuevo)
    with basedatos.conexion() as con:
        con.execute(
            "UPDATE asistente_videos SET archivo = ?, trabajo_id = NULL, trabajo_estado = 'listo', "
            "error = NULL, actualizado = ? WHERE organizacion_id = ? AND estado = ?",
            (archivo, _ahora(), org, estado_),
        )
    if fila["archivo"]:
        (carpeta(org) / fila["archivo"]).unlink(missing_ok=True)


def _fallar(fila, motivo: str) -> None:
    with basedatos.conexion() as con:
        con.execute(
            "UPDATE asistente_videos SET trabajo_id = NULL, trabajo_estado = 'error', error = ?, "
            "actualizado = ? WHERE organizacion_id = ? AND estado = ?",
            (motivo[:300], _ahora(), fila["organizacion_id"], fila["estado"]),
        )


def revisar_trabajos() -> None:
    """Una pasada sobre los trabajos en curso. La llama el hilo de fondo."""
    with basedatos.conexion() as con:
        filas = con.execute(
            "SELECT organizacion_id, estado, archivo, trabajo_id, trabajo_desde "
            "FROM asistente_videos WHERE trabajo_estado = 'generando'"
        ).fetchall()
    ahora = datetime.now(timezone.utc)
    for fila in filas:
        if ahora - datetime.fromisoformat(fila["trabajo_desde"]) > VENCE:
            _fallar(fila, "Higgsfield no respondio en 30 minutos. Proba de nuevo.")
            continue
        try:
            resultado = higgsfield.estado(fila["trabajo_id"])
            if resultado["estado"] == "listo":
                _terminar(fila, higgsfield.descargar(resultado["url"]))
            elif resultado["estado"] == "error":
                _fallar(fila, resultado["error"] or "Fallo en Higgsfield.")
        except Exception as fallo:  # noqa: BLE001 - un corte de red no es un video fallado
            print(f"  Avatar: no se pudo revisar {fila['trabajo_id']} ({type(fallo).__name__}).")


def vigilar() -> None:
    """Hilo de fondo. Al arrancar retoma lo que quedo en 'generando'."""
    def bucle():
        while True:
            try:
                revisar_trabajos()
            except Exception as fallo:  # noqa: BLE001 - nunca debe matar el hilo
                print(f"  Avatar: fallo una revision ({type(fallo).__name__}).")
            time.sleep(CADA_SEGUNDOS)

    threading.Thread(target=bucle, name="avatar", daemon=True).start()


def costo_estimado(cuantos: int) -> float | None:
    valor = os.getenv("JARVIS_AVATAR_CREDITOS_POR_VIDEO", "").strip().replace(",", ".")
    try:
        return round(float(valor) * cuantos, 2) if valor else None
    except ValueError:
        return None
