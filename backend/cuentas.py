"""Cuentas de organizacion: una organizacion, sus usuarios y su contrasena.

Traduce credenciales (alta o login) en un acceso.Usuario, con el mismo
criterio que supabase_sesion.py: este modulo no sabe de HTTP ni de cookies,
solo de "credencial -> Usuario o None / error".
"""

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
from datetime import datetime, timezone

from . import acceso, basedatos

PREFIJO = "u-"

_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_ITERACIONES = 200_000


class ErrorDeCuenta(ValueError):
    """Algo en lo que escribio la persona no sirve; el mensaje es para ella."""


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hashear(password: str) -> str:
    sal = secrets.token_hex(16)
    derivado = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(sal), _ITERACIONES
    )
    return f"{sal}${derivado.hex()}"


def _verificar(password: str, guardado: str) -> bool:
    try:
        sal, derivado = guardado.split("$", 1)
    except ValueError:
        return False
    calculado = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(sal), _ITERACIONES
    ).hex()
    return hmac.compare_digest(calculado, derivado)


def _validar_alta(nombre: str, email: str, password: str) -> None:
    if not nombre.strip():
        raise ErrorDeCuenta("Falta el nombre.")
    if not _CORREO.match(email):
        raise ErrorDeCuenta("El correo no es valido.")
    if len(password or "") < 8:
        raise ErrorDeCuenta("La contrasena necesita al menos 8 caracteres.")


def _usuario_de_fila(fila: sqlite3.Row) -> acceso.Usuario:
    return acceso.Usuario(
        f"{PREFIJO}{fila['id']}", fila["nombre"], "usuario",
        organizacion_id=fila["organizacion_id"],
    )


def id_crudo(id_usuario: str) -> str | None:
    """El id de la tabla usuarios (sin el prefijo). None si no es de aqui."""
    if not id_usuario.startswith(PREFIJO):
        return None
    return id_usuario[len(PREFIJO):]


def crear_organizacion(
    nombre_organizacion: str, nombre: str, email: str, password: str
) -> acceso.Usuario:
    """Crea la organizacion y su primera cuenta, que la administra."""
    nombre_organizacion = (nombre_organizacion or "").strip()
    nombre = (nombre or "").strip()
    email = (email or "").strip().lower()

    if not nombre_organizacion:
        raise ErrorDeCuenta("Falta el nombre de la organizacion.")
    _validar_alta(nombre, email, password)

    id_org = secrets.token_hex(8)
    id_usuario = secrets.token_hex(8)

    with basedatos.conexion() as con:
        con.execute(
            "INSERT INTO organizaciones (id, nombre, creada) VALUES (?, ?, ?)",
            (id_org, nombre_organizacion, _ahora()),
        )
        try:
            con.execute(
                "INSERT INTO usuarios "
                "(id, organizacion_id, nombre, email, password_hash, es_admin_org, creado) "
                "VALUES (?, ?, ?, ?, ?, 1, ?)",
                (id_usuario, id_org, nombre, email, _hashear(password), _ahora()),
            )
        except sqlite3.IntegrityError:
            raise ErrorDeCuenta("Ya existe una cuenta con ese correo.")

    return acceso.Usuario(f"{PREFIJO}{id_usuario}", nombre, "usuario", organizacion_id=id_org)


def agregar_usuario(organizacion_id: str, nombre: str, email: str, password: str) -> acceso.Usuario:
    """Suma una persona mas a una organizacion que ya existe."""
    nombre = (nombre or "").strip()
    email = (email or "").strip().lower()
    _validar_alta(nombre, email, password)

    id_usuario = secrets.token_hex(8)

    with basedatos.conexion() as con:
        existe = con.execute(
            "SELECT 1 FROM organizaciones WHERE id = ?", (organizacion_id,)
        ).fetchone()
        if existe is None:
            raise ErrorDeCuenta("La organizacion no existe.")
        try:
            con.execute(
                "INSERT INTO usuarios "
                "(id, organizacion_id, nombre, email, password_hash, es_admin_org, creado) "
                "VALUES (?, ?, ?, ?, ?, 0, ?)",
                (id_usuario, organizacion_id, nombre, email, _hashear(password), _ahora()),
            )
        except sqlite3.IntegrityError:
            raise ErrorDeCuenta("Ya existe una cuenta con ese correo.")

    return acceso.Usuario(
        f"{PREFIJO}{id_usuario}", nombre, "usuario", organizacion_id=organizacion_id
    )


def entrar(email: str, password: str) -> acceso.Usuario | None:
    email = (email or "").strip().lower()
    if not email or not password:
        return None

    with basedatos.conexion() as con:
        fila = con.execute("SELECT * FROM usuarios WHERE email = ?", (email,)).fetchone()

    if fila is None or not _verificar(password, fila["password_hash"]):
        return None
    return _usuario_de_fila(fila)


def usuario_de_id(id_sin_prefijo: str) -> acceso.Usuario | None:
    with basedatos.conexion() as con:
        fila = con.execute(
            "SELECT * FROM usuarios WHERE id = ?", (id_sin_prefijo,)
        ).fetchone()
    return _usuario_de_fila(fila) if fila else None


def es_admin_org(id_usuario: str) -> bool:
    """`id_usuario` con su prefijo `u-`, tal como llega en acceso.Usuario.id."""
    crudo = id_crudo(id_usuario)
    if crudo is None:
        return False
    with basedatos.conexion() as con:
        fila = con.execute(
            "SELECT es_admin_org FROM usuarios WHERE id = ?", (crudo,)
        ).fetchone()
    return bool(fila and fila["es_admin_org"])


def miembros(organizacion_id: str) -> list[dict]:
    with basedatos.conexion() as con:
        filas = con.execute(
            "SELECT id, nombre, email, es_admin_org, creado FROM usuarios "
            "WHERE organizacion_id = ? ORDER BY creado",
            (organizacion_id,),
        ).fetchall()
    return [dict(fila) for fila in filas]


# --------------------------------------------------------------------------
# La organizacion de quienes entran desde los paneles de Supabase
# --------------------------------------------------------------------------

ORGANIZACION_PANELES = "JARVIS_ORGANIZACION_PANELES"

# Id fijo, no sale de token_hex como las de /registro: asi nadie que se
# registre con el mismo nombre puede quedarse con esta organizacion, y el id
# sobrevive si cambia el nombre en la variable.
ID_PANELES = "paneles"


def organizacion_de_paneles() -> str | None:
    """A que organizacion pertenece quien entra desde un panel, o None.

    Los paneles comparten un solo directorio de Supabase, el de una sola
    empresa, asi que todos sus usuarios son de la misma organizacion.
    """
    return ID_PANELES if os.getenv(ORGANIZACION_PANELES, "").strip() else None


def asegurar_organizacion_de_paneles() -> None:
    """Se llama al arrancar: crea la organizacion, o le actualiza el nombre."""
    nombre = os.getenv(ORGANIZACION_PANELES, "").strip()
    if not nombre:
        return

    with basedatos.conexion() as con:
        fila = con.execute(
            "SELECT nombre FROM organizaciones WHERE id = ?", (ID_PANELES,)
        ).fetchone()
        if fila is None:
            con.execute(
                "INSERT INTO organizaciones (id, nombre, creada) VALUES (?, ?, ?)",
                (ID_PANELES, nombre, _ahora()),
            )
            print(f"  Organizacion de los paneles creada: {nombre}")
        elif fila["nombre"] != nombre:
            con.execute(
                "UPDATE organizaciones SET nombre = ? WHERE id = ?", (nombre, ID_PANELES)
            )


def nombre_organizacion(organizacion_id: str | None) -> str | None:
    if not organizacion_id:
        return None
    with basedatos.conexion() as con:
        fila = con.execute(
            "SELECT nombre FROM organizaciones WHERE id = ?", (organizacion_id,)
        ).fetchone()
    return fila["nombre"] if fila else None


# --------------------------------------------------------------------------
# Cuanto lleva consumido cada organizacion
# --------------------------------------------------------------------------

MARGEN = "JARVIS_MARGEN"
PREFIJO_MARGEN = "JARVIS_MARGEN_"


def _porcentaje(valor: str | None) -> float | None:
    """'30', '30%' o '12,5' -> el numero. None si no es un porcentaje valido.

    Negativo tampoco vale: cobrar por debajo del costo no es un margen, y un
    signo menos de mas es mas probable que un descuento a proposito.
    """
    try:
        numero = float((valor or "").strip().rstrip("%").replace(",", "."))
    except ValueError:
        return None
    return numero if numero >= 0 else None


def margen(organizacion_id: str | None) -> float:
    """El porcentaje que se cobra sobre lo que cobra OpenAI. 30 es 30% mas.

    JARVIS_MARGEN_<id> pisa a JARVIS_MARGEN para esa organizacion. Quien no
    tiene organizacion es de la casa: no se le cobra margen.
    """
    if not organizacion_id:
        return 0.0

    for variable, valor in os.environ.items():
        sufijo = variable[len(PREFIJO_MARGEN):] if variable.startswith(PREFIJO_MARGEN) else None
        if sufijo and sufijo.lower() == organizacion_id:
            propio = _porcentaje(valor)
            if propio is not None:
                return propio

    return _porcentaje(os.getenv(MARGEN)) or 0.0


def markup(organizacion_id: str | None) -> float:
    """El multiplicador que sale del margen: 30% es 1.3."""
    return 1 + margen(organizacion_id) / 100


def avisar_de_margenes_invalidos() -> None:
    """Se llama al arrancar. Un margen mal escrito se ignora, y callarlo haria
    que alguien se quede cobrando al costo sin saberlo."""
    with basedatos.conexion() as con:
        existentes = {fila["id"] for fila in con.execute("SELECT id FROM organizaciones")}

    for variable, valor in sorted(os.environ.items()):
        if variable != MARGEN and not variable.startswith(PREFIJO_MARGEN):
            continue

        if _porcentaje(valor) is None:
            print(f"  AVISO: se ignora {variable}={valor!r}: tiene que ser un "
                  "porcentaje de 0 en adelante, como 30.")
            continue

        sufijo = variable[len(PREFIJO_MARGEN):].lower()
        if variable != MARGEN and sufijo not in existentes:
            print(f"  AVISO: {variable} no corresponde a ninguna organizacion. "
                  "El id sale en el tablero de Consumo.")


def consumido(organizacion_id: str | None) -> dict:
    """Lo que lleva gastado una organizacion desde siempre.

    `costo` es lo que cuesta en OpenAI y `cobrado` lo que se le factura: el
    mismo numero con su margen encima. Son dos cifras distintas a proposito.
    """
    if not organizacion_id:
        return {"consultas": 0, "tokens": 0, "costo": 0.0, "cobrado": 0.0,
                "margen": 0.0, "markup": 1.0}

    with basedatos.conexion() as con:
        fila = con.execute(
            "SELECT COUNT(*) AS consultas, COALESCE(SUM(tokens), 0) AS tokens, "
            "COALESCE(SUM(costo), 0) AS costo FROM consumo "
            "WHERE organizacion_id = ? AND modo != 'sesion'",
            (organizacion_id,),
        ).fetchone()

    tarifa = markup(organizacion_id)
    return {
        "consultas": fila["consultas"],
        "tokens": fila["tokens"],
        "costo": round(fila["costo"], 6),
        "cobrado": round(fila["costo"] * tarifa, 6),
        "margen": margen(organizacion_id),
        "markup": tarifa,
    }


def organizaciones() -> list[dict]:
    """Todas, con lo que llevan consumido. Para quien administra Jarvis."""
    with basedatos.conexion() as con:
        filas = con.execute(
            "SELECT id, nombre, creada FROM organizaciones ORDER BY creada"
        ).fetchall()
    return [{**dict(fila), **consumido(fila["id"])} for fila in filas]
