"""Vinculacion de dispositivos (relojes) por codigo.

Cualquier Usuario ya logueado en Jarvis -por contrasena, por panel o por una
cuenta de organizacion- puede generar un codigo desde el navegador y
escribirlo en el reloj para vincularlo. El reloj lo canjea una sola vez por un
token propio, que manda como 'Authorization: Bearer <token>' en cada pedido;
no vuelve a pedir nada despues del primer vinculo.
"""

import hashlib
import secrets
import string
from datetime import datetime, timedelta, timezone

from . import acceso, basedatos, cuentas, supabase_sesion

VIGENCIA_CODIGO = timedelta(minutes=10)

# Sin 0/O ni 1/I/L: se escriben a mano en la pantalla chica de un reloj.
_ALFABETO = "".join(c for c in string.ascii_uppercase + string.digits if c not in "0O1IL")


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generar_codigo(usuario_id: str) -> dict:
    """Un codigo nuevo para esa persona. Reemplaza el anterior si tenia uno."""
    codigo = "".join(secrets.choice(_ALFABETO) for _ in range(6))
    expira = _ahora() + VIGENCIA_CODIGO

    with basedatos.conexion() as con:
        con.execute("DELETE FROM codigos_vinculo WHERE usuario_id = ?", (usuario_id,))
        con.execute(
            "INSERT INTO codigos_vinculo (codigo, usuario_id, expira) VALUES (?, ?, ?)",
            (codigo, usuario_id, expira.isoformat()),
        )

    return {"codigo": codigo, "vence_en": int(VIGENCIA_CODIGO.total_seconds())}


def vincular(codigo: str, nombre: str = "") -> tuple[str, str] | None:
    """Canjea un codigo por un token de dispositivo.

    De un solo uso: el codigo se borra al intentarlo, valga o no. Devuelve
    (usuario_id del dueno, token crudo) o None si no vale.
    """
    codigo = (codigo or "").strip().upper()
    if not codigo:
        return None

    with basedatos.conexion() as con:
        fila = con.execute(
            "SELECT usuario_id, expira FROM codigos_vinculo WHERE codigo = ?", (codigo,)
        ).fetchone()
        if fila is None:
            return None

        con.execute("DELETE FROM codigos_vinculo WHERE codigo = ?", (codigo,))

        if datetime.fromisoformat(fila["expira"]) < _ahora():
            return None

        usuario_id = fila["usuario_id"]
        token = secrets.token_urlsafe(32)
        con.execute(
            "INSERT INTO dispositivos (id, usuario_id, nombre, token_hash, creado) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                secrets.token_hex(8),
                usuario_id,
                (nombre or "").strip() or "Reloj",
                _hash_token(token),
                _ahora().isoformat(),
            ),
        )

    return usuario_id, token


def usuario_de_token(token: str) -> acceso.Usuario | None:
    """El dueno del reloj que manda este token, o None si no vale."""
    if not token:
        return None

    hash_token = _hash_token(token)
    with basedatos.conexion() as con:
        fila = con.execute(
            "SELECT usuario_id FROM dispositivos WHERE token_hash = ?", (hash_token,)
        ).fetchone()
        if fila is None:
            return None
        con.execute(
            "UPDATE dispositivos SET ultimo_uso = ? WHERE token_hash = ?",
            (_ahora().isoformat(), hash_token),
        )
        usuario_id = fila["usuario_id"]

    return _usuario_para(usuario_id)


def _usuario_para(usuario_id: str) -> acceso.Usuario | None:
    """Resuelve al dueno de un dispositivo, sea cual sea el origen de su cuenta.

    Si le quitaron el acceso (borraron la cuenta, la variable de entorno, el
    permiso del panel) esto devuelve None y el reloj queda sin servicio, igual
    que le pasaria a su cookie del navegador.
    """
    crudo = cuentas.id_crudo(usuario_id)
    if crudo is not None:
        return cuentas.usuario_de_id(crudo)

    if usuario_id.startswith(supabase_sesion.PREFIJO):
        uuid = usuario_id[len(supabase_sesion.PREFIJO):]
        perfil = supabase_sesion.perfil_cacheado(uuid)
        return supabase_sesion.usuario_de_perfil(perfil) if perfil else None

    return acceso.usuario_de_id(usuario_id)


def dispositivos_de(usuario_id: str) -> list[dict]:
    with basedatos.conexion() as con:
        filas = con.execute(
            "SELECT id, nombre, creado, ultimo_uso FROM dispositivos "
            "WHERE usuario_id = ? ORDER BY creado",
            (usuario_id,),
        ).fetchall()
    return [dict(fila) for fila in filas]


def revocar(usuario_id: str, id_dispositivo: str) -> bool:
    with basedatos.conexion() as con:
        cursor = con.execute(
            "DELETE FROM dispositivos WHERE id = ? AND usuario_id = ?",
            (id_dispositivo, usuario_id),
        )
    return cursor.rowcount > 0
