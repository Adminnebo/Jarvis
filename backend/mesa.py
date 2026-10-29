"""La mesa de cotizaciones de cada persona.

En la mesa hay a la vez:
- la ORIGINAL: la cotizacion que se trajo con buscar_cotizacion (de JH o JV),
  con los precios con que se cotizo. Es de solo lectura.
- las VARIANTES: borradores sin emitir (de preparar_cotizacion o sacados de la
  original), cada uno con un nombre corto ("a costo", "costo + 50%", "P5").

Se guarda en SQLite: cada despliegue reinicia Jarvis y en memoria se perdia lo
que alguien estaba armando. Vence a las 2 horas sin uso.

Forma de la mesa (dict, se guarda como JSON):
    {"original": {...} | None, "variantes": [{...}], "piso": float | None,
     "ultima": "original" | nombre de variante | None}
"""

import json
import threading
import time

from . import basedatos

VIGENCIA = 2 * 3600
MAX_VARIANTES = 5

# Un cambio de la mesa es leer-modificar-guardar: con dos herramientas en
# paralelo para la misma persona, sin esto una pisaria a la otra.
candado = threading.RLock()


def vacia() -> dict:
    return {"original": None, "variantes": [], "piso": None, "ultima": None}


def cargar(usuario: str) -> dict:
    """La mesa de esa persona, o una vacia si no tiene o ya vencio."""
    with basedatos.conexion() as con:
        fila = con.execute(
            "SELECT datos, actualizado FROM mesas_cotizacion WHERE usuario_id = ?", (usuario,)
        ).fetchone()
    if fila is None or time.time() - fila["actualizado"] > VIGENCIA:
        return vacia()
    return {**vacia(), **json.loads(fila["datos"])}


def guardar(usuario: str, mesa: dict) -> None:
    """Guarda la mesa y renueva su vigencia. Una mesa sin nada se borra."""
    with basedatos.conexion() as con:
        if not mesa.get("original") and not mesa.get("variantes"):
            con.execute("DELETE FROM mesas_cotizacion WHERE usuario_id = ?", (usuario,))
            return
        con.execute(
            "INSERT INTO mesas_cotizacion (usuario_id, datos, actualizado) VALUES (?, ?, ?) "
            "ON CONFLICT(usuario_id) DO UPDATE SET datos = excluded.datos, "
            "actualizado = excluded.actualizado",
            (usuario, json.dumps(mesa, ensure_ascii=False), time.time()),
        )


def envejecer(usuario: str, segundos: float) -> None:
    """Para las pruebas: hace como si la mesa se hubiera tocado hace un rato."""
    with basedatos.conexion() as con:
        con.execute(
            "UPDATE mesas_cotizacion SET actualizado = actualizado - ? WHERE usuario_id = ?",
            (segundos, usuario),
        )


def variante(mesa: dict, nombre: str) -> dict | None:
    return next((v for v in mesa["variantes"] if v["nombre"] == nombre), None)


def poner_variante(mesa: dict, nueva: dict) -> None:
    """Agrega la variante, o reemplaza la que tenga el mismo nombre."""
    mesa["variantes"] = [v for v in mesa["variantes"] if v["nombre"] != nueva["nombre"]]
    mesa["variantes"].append(nueva)
    mesa["ultima"] = nueva["nombre"]


def activa(mesa: dict) -> dict | None:
    """La variante con la que se esta trabajando: la ultima tocada, o la mas
    reciente si lo ultimo que se toco fue la original."""
    elegida = variante(mesa, mesa.get("ultima") or "")
    if elegida is None and mesa["variantes"]:
        elegida = mesa["variantes"][-1]
    return elegida
