"""Las apps que cada persona conecta a Jarvis. Hoy: Gmail.

Guarda la conexion (el refresh token cifrado) y las reglas de aviso. No habla
con Google: eso es gmail.py. Agregar otra app = otra entrada en _APPS y su
propio modulo.
"""

from datetime import datetime, timezone

from . import basedatos, gmail, secretos, whatsapp

_APPS = [
    {"app": "gmail", "nombre": "Gmail",
     "descripcion": "Jarvis busca, lee y envia tus correos, y te avisa de los importantes.",
     "configurado": gmail.configurado},
]


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fila(fila) -> dict | None:
    if fila is None:
        return None
    datos = dict(fila)
    datos["token"] = secretos.descifrar(datos["token"]) if datos["token"] else None
    return datos


def conexion(usuario_id: str, app: str = "gmail") -> dict | None:
    with basedatos.conexion() as con:
        return _fila(con.execute(
            "SELECT * FROM integraciones WHERE usuario_id = ? AND app = ?", (usuario_id, app)).fetchone())


def conectados(app: str = "gmail") -> list[dict]:
    with basedatos.conexion() as con:
        filas = con.execute(
            "SELECT * FROM integraciones WHERE app = ? AND estado = 'conectado' "
            "ORDER BY conectado, usuario_id",
            (app,)).fetchall()
    return [_fila(f) for f in filas]


def guardar_gmail(usuario_id: str, cuenta: str, refresh: str, cursor: str) -> str | None:
    """Guarda la conexion nueva. Devuelve el refresh token anterior (para revocarlo), si habia."""
    anterior = conexion(usuario_id)
    with basedatos.conexion() as con:
        con.execute(
            "INSERT INTO integraciones (usuario_id, app, cuenta, token, cursor, estado, error, conectado) "
            "VALUES (?, 'gmail', ?, ?, ?, 'conectado', NULL, ?) "
            "ON CONFLICT (usuario_id, app) DO UPDATE SET cuenta = excluded.cuenta, "
            "token = excluded.token, cursor = excluded.cursor, estado = 'conectado', "
            "error = NULL, conectado = excluded.conectado",
            (usuario_id, cuenta, secretos.cifrar(refresh), cursor, _ahora()))
    return anterior["token"] if anterior and anterior["token"] != refresh else None


def mover_cursor(usuario_id: str, cursor: str, app: str = "gmail") -> None:
    with basedatos.conexion() as con:
        con.execute("UPDATE integraciones SET cursor = ? WHERE usuario_id = ? AND app = ?",
                    (cursor, usuario_id, app))


def marcar_desconectado(usuario_id: str, motivo: str, app: str = "gmail") -> None:
    with basedatos.conexion() as con:
        con.execute("UPDATE integraciones SET estado = 'desconectado', error = ? "
                    "WHERE usuario_id = ? AND app = ?", (motivo, usuario_id, app))


def desconectar(usuario_id: str, app: str = "gmail") -> str | None:
    """Borra el token y devuelve el que habia, para revocarlo en Google."""
    actual = conexion(usuario_id, app)
    if not actual or not actual["token"]:
        return None
    with basedatos.conexion() as con:
        con.execute("UPDATE integraciones SET token = NULL, estado = 'desconectado', error = NULL "
                    "WHERE usuario_id = ? AND app = ?", (usuario_id, app))
    return actual["token"]


def conectar_gmail(usuario_id: str, codigo: str) -> str:
    """Termina el OAuth: guarda la conexion desde el historyId de hoy. Devuelve el email."""
    datos = gmail.canjear_codigo(codigo)
    cuenta = gmail.perfil(datos["access_token"])
    anterior = guardar_gmail(usuario_id, cuenta["email"], datos["refresh_token"], cuenta["historyId"])
    if anterior:
        gmail.revocar(anterior)
    return cuenta["email"]


def reglas(usuario_id: str) -> dict:
    with basedatos.conexion() as con:
        fila = con.execute("SELECT * FROM reglas_aviso WHERE usuario_id = ?", (usuario_id,)).fetchone()
    if fila is None:
        return {"reglas": "", "whatsapp": None, "activo": True}
    return {"reglas": fila["reglas"], "whatsapp": fila["whatsapp"], "activo": bool(fila["activo"])}


def guardar_reglas(usuario_id: str, texto: str, numero: str, activo: bool) -> dict:
    """Lanza ValueError si el numero de WhatsApp no es valido."""
    normalizado = None
    if (numero or "").strip():
        try:
            normalizado = whatsapp.normalizar_numero(numero)
        except whatsapp.ErrorEnvio as error:
            raise ValueError(str(error)) from error
    with basedatos.conexion() as con:
        con.execute(
            "INSERT INTO reglas_aviso (usuario_id, reglas, whatsapp, activo) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (usuario_id) DO UPDATE SET reglas = excluded.reglas, "
            "whatsapp = excluded.whatsapp, activo = excluded.activo",
            (usuario_id, (texto or "").strip()[:2000], normalizado, int(bool(activo))))
    return reglas(usuario_id)


def catalogo(usuario_id: str) -> list[dict]:
    salida = []
    for app in _APPS:
        actual = conexion(usuario_id, app["app"])
        salida.append({
            "app": app["app"], "nombre": app["nombre"], "descripcion": app["descripcion"],
            "disponible": app["configurado"](),
            "estado": actual["estado"] if actual else "sin_conectar",
            "cuenta": actual["cuenta"] if actual else None,
            "error": actual["error"] if actual else None,
        })
    return salida
