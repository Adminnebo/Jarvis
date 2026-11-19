"""Las apps que cada persona conecta a Jarvis: Gmail, WhatsApp y Outlook (Zernio).

Guarda la conexion (el refresh token cifrado de Gmail, la cuenta de Zernio de
WhatsApp y de Outlook), las reglas de aviso y el horario laboral. No habla con
Google ni con Microsoft: eso es gmail.py, outlook.py y calendario.py. Agregar
otra app = otra entrada en _APPS y su propio modulo.
"""

import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import basedatos, evolution_wa, gmail, secretos, whatsapp, zernio

_APPS = [
    {"app": "gmail", "nombre": "Gmail",
     "descripcion": "Correo y calendario de Google. Jarvis busca, lee y envia tus correos, te avisa "
                    "de los importantes y, si das permiso, mira tu agenda y agenda reuniones con Meet.",
     "configurado": gmail.configurado},
    {"app": "whatsapp", "nombre": "WhatsApp",
     "descripcion": "Conecta tu WhatsApp Business y sigue usando la app en tu telefono. "
                    "Jarvis lee tus chats, responde con tu permiso y te avisa de lo importante.",
     "configurado": lambda: evolution_wa.configurado() or zernio.configurado()},
    {"app": "outlook", "nombre": "Outlook",
     "descripcion": "Correo y calendario de Microsoft 365 / Outlook.com. Jarvis lee y responde "
                    "tus correos, mira tu agenda, agenda reuniones con Teams y te avisa antes de cada una.",
     "configurado": zernio.configurado},
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
        if app == "gmail":
            con.execute("DELETE FROM google_calendario WHERE usuario_id = ?", (usuario_id,))
    return actual["token"]


def conectar_gmail(usuario_id: str, codigo: str) -> str:
    """Termina el OAuth: guarda la conexion desde el historyId de hoy. Devuelve el email."""
    datos = gmail.canjear_codigo(codigo)
    cuenta = gmail.perfil(datos["access_token"])
    anterior = guardar_gmail(usuario_id, cuenta["email"], datos["refresh_token"], cuenta["historyId"])
    with basedatos.conexion() as con:
        if gmail.tiene_calendario(datos):
            con.execute("INSERT INTO google_calendario (usuario_id, concedido) VALUES (?, ?) "
                        "ON CONFLICT (usuario_id) DO UPDATE SET concedido = excluded.concedido",
                        (usuario_id, _ahora()))
        else:
            con.execute("DELETE FROM google_calendario WHERE usuario_id = ?", (usuario_id,))
    if anterior:
        gmail.revocar(anterior)
    return cuenta["email"]


def quitar_calendario_google(usuario_id: str) -> None:
    """Google dijo que no hay permiso: hasta que reconecte, no se le pregunta."""
    with basedatos.conexion() as con:
        con.execute("DELETE FROM google_calendario WHERE usuario_id = ?", (usuario_id,))


def calendario_google(usuario_id: str) -> bool:
    """Si la persona tiene Gmail conectado y dio permiso al calendario."""
    with basedatos.conexion() as con:
        fila = con.execute(
            "SELECT 1 FROM google_calendario g JOIN integraciones i "
            "ON i.usuario_id = g.usuario_id AND i.app = 'gmail' "
            "WHERE g.usuario_id = ? AND i.estado = 'conectado'", (usuario_id,)).fetchone()
    return fila is not None


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
            "calendario": calendario_google(usuario_id) if app["app"] == "gmail" else None,
        })
        if app["app"] == "whatsapp" and evolution_wa.configurado():
            # Con Evolution se vincula como WhatsApp Web: QR o codigo, sin Facebook.
            salida[-1]["vincular"] = True
            salida[-1]["descripcion"] = DESCRIPCION_EVOLUTION
    return salida


DESCRIPCION_EVOLUTION = ("Vincula tu WhatsApp escaneando un codigo QR, como WhatsApp Web. Sirve con "
                         "WhatsApp normal o Business. Jarvis lee tus chats, responde con tu permiso "
                         "y te avisa de lo importante.")


# --------------------------------------------------------------------------
# WhatsApp (Zernio): perfil propio de cada persona y la cuenta conectada
# --------------------------------------------------------------------------

def cuenta_zernio(usuario_id: str) -> dict | None:
    with basedatos.conexion() as con:
        fila = con.execute("SELECT * FROM zernio_cuentas WHERE usuario_id = ?", (usuario_id,)).fetchone()
    return dict(fila) if fila else None


def usuario_de_cuenta(cuenta_id: str) -> str | None:
    with basedatos.conexion() as con:
        fila = con.execute("SELECT usuario_id FROM zernio_cuentas WHERE cuenta_id = ?", (cuenta_id,)).fetchone()
    return fila["usuario_id"] if fila else None


def iniciar_whatsapp(usuario_id: str, nombre: str) -> str:
    return perfil_zernio(usuario_id, nombre)


def perfil_zernio(usuario_id: str, nombre: str) -> str:
    """El perfil de Zernio de la persona (lo crea la primera vez). Lo comparten
    WhatsApp y Outlook. Lanza zernio.ErrorZernio."""
    actual = cuenta_zernio(usuario_id)
    if actual:
        return actual["perfil_id"]
    perfil = zernio.perfil_de(usuario_id, nombre)
    with basedatos.conexion() as con:
        con.execute("INSERT INTO zernio_cuentas (usuario_id, perfil_id, actualizado) VALUES (?, ?, ?) "
                    "ON CONFLICT (usuario_id) DO UPDATE SET perfil_id = excluded.perfil_id, "
                    "actualizado = excluded.actualizado", (usuario_id, perfil, _ahora()))
    return perfil


def guardar_whatsapp(usuario_id: str, cuenta_id: str, cuenta: str) -> None:
    with basedatos.conexion() as con:
        # Un numero que se conecta en otra persona deja de ser del anterior.
        con.execute("UPDATE zernio_cuentas SET cuenta_id = NULL WHERE cuenta_id = ? AND usuario_id != ?",
                    (cuenta_id, usuario_id))
        con.execute("UPDATE zernio_cuentas SET cuenta_id = ?, actualizado = ? WHERE usuario_id = ?",
                    (cuenta_id, _ahora(), usuario_id))
        con.execute(
            "INSERT INTO integraciones (usuario_id, app, cuenta, token, cursor, estado, error, conectado) "
            "VALUES (?, 'whatsapp', ?, NULL, NULL, 'conectado', NULL, ?) "
            "ON CONFLICT (usuario_id, app) DO UPDATE SET cuenta = excluded.cuenta, "
            "estado = 'conectado', error = NULL, conectado = excluded.conectado",
            (usuario_id, cuenta, _ahora()))


def desconectar_whatsapp(usuario_id: str) -> str | None:
    """Suelta la cuenta y devuelve su id (para borrarla en Zernio). El perfil se conserva."""
    actual = cuenta_zernio(usuario_id)
    if not actual or not actual["cuenta_id"]:
        return None
    with basedatos.conexion() as con:
        con.execute("UPDATE zernio_cuentas SET cuenta_id = NULL, actualizado = ? WHERE usuario_id = ?",
                    (_ahora(), usuario_id))
        con.execute("UPDATE integraciones SET estado = 'desconectado', error = NULL "
                    "WHERE usuario_id = ? AND app = 'whatsapp'", (usuario_id,))
    return actual["cuenta_id"]


# --------------------------------------------------------------------------
# Outlook (Zernio): la cuenta de Microsoft de cada persona
# --------------------------------------------------------------------------

def guardar_outlook(usuario_id: str, cuenta_id: str, correo: str) -> None:
    """Conecta la cuenta. El cursor arranca ahora: no se avisa de correo viejo."""
    ahora = _ahora()
    with basedatos.conexion() as con:
        # Una cuenta que se conecta en otra persona deja de ser de la anterior.
        for fila in con.execute("SELECT usuario_id FROM outlook_cuentas WHERE cuenta_id = ? "
                                "AND usuario_id != ?", (cuenta_id, usuario_id)).fetchall():
            con.execute("UPDATE integraciones SET estado = 'desconectado', error = NULL "
                        "WHERE usuario_id = ? AND app = 'outlook'", (fila["usuario_id"],))
        con.execute("DELETE FROM outlook_cuentas WHERE cuenta_id = ? AND usuario_id != ?",
                    (cuenta_id, usuario_id))
        con.execute("INSERT INTO outlook_cuentas (usuario_id, cuenta_id, actualizado) VALUES (?, ?, ?) "
                    "ON CONFLICT (usuario_id) DO UPDATE SET cuenta_id = excluded.cuenta_id, "
                    "actualizado = excluded.actualizado", (usuario_id, cuenta_id, ahora))
        con.execute(
            "INSERT INTO integraciones (usuario_id, app, cuenta, token, cursor, estado, error, conectado) "
            "VALUES (?, 'outlook', ?, NULL, ?, 'conectado', NULL, ?) "
            "ON CONFLICT (usuario_id, app) DO UPDATE SET cuenta = excluded.cuenta, "
            "cursor = excluded.cursor, estado = 'conectado', error = NULL, conectado = excluded.conectado",
            (usuario_id, correo, ahora, ahora))


def cuenta_outlook(usuario_id: str) -> str | None:
    """El accountId de Zernio, solo si la conexion esta en pie."""
    with basedatos.conexion() as con:
        fila = con.execute(
            "SELECT o.cuenta_id FROM outlook_cuentas o JOIN integraciones i "
            "ON i.usuario_id = o.usuario_id AND i.app = 'outlook' "
            "WHERE o.usuario_id = ? AND i.estado = 'conectado'", (usuario_id,)).fetchone()
    return fila["cuenta_id"] if fila else None


def usuario_de_outlook(cuenta_id: str) -> str | None:
    """De quien es una cuenta (aunque este desconectada: el webhook la necesita)."""
    with basedatos.conexion() as con:
        fila = con.execute("SELECT usuario_id FROM outlook_cuentas WHERE cuenta_id = ?",
                           (cuenta_id,)).fetchone()
    return fila["usuario_id"] if fila else None


def desconectar_outlook(usuario_id: str) -> str | None:
    """Suelta la cuenta y devuelve su id (para borrarla en Zernio). El perfil se conserva."""
    with basedatos.conexion() as con:
        fila = con.execute("SELECT cuenta_id FROM outlook_cuentas WHERE usuario_id = ?",
                           (usuario_id,)).fetchone()
        if not fila:
            return None
        con.execute("DELETE FROM outlook_cuentas WHERE usuario_id = ?", (usuario_id,))
        con.execute("UPDATE integraciones SET estado = 'desconectado', error = NULL "
                    "WHERE usuario_id = ? AND app = 'outlook'", (usuario_id,))
    return fila["cuenta_id"]


# --------------------------------------------------------------------------
# Horario laboral (para los huecos libres del calendario)
# --------------------------------------------------------------------------

HORARIO_DEFECTO = {"inicio": "08:00", "fin": "18:00", "dias": [1, 2, 3, 4, 5],
                   "zona": "America/Santo_Domingo"}
_HORA = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def horario(usuario_id: str) -> dict:
    with basedatos.conexion() as con:
        fila = con.execute("SELECT * FROM horario_laboral WHERE usuario_id = ?", (usuario_id,)).fetchone()
    if not fila:
        return {**HORARIO_DEFECTO, "dias": list(HORARIO_DEFECTO["dias"])}
    return {"inicio": fila["inicio"], "fin": fila["fin"],
            "dias": [int(d) for d in fila["dias"].split(",") if d], "zona": fila["zona"]}


def guardar_horario(usuario_id: str, inicio: str, fin: str, dias, zona: str) -> dict:
    """Lanza ValueError con un mensaje para la persona si algo no cuadra."""
    inicio, fin = (inicio or "").strip(), (fin or "").strip()
    zona = (zona or "").strip() or HORARIO_DEFECTO["zona"]
    if not _HORA.match(inicio) or not _HORA.match(fin):
        raise ValueError("Las horas van como 08:00.")
    if inicio >= fin:
        raise ValueError("La hora de salida tiene que ser despues de la de entrada.")
    try:
        lista = sorted({int(d) for d in dias})
    except (TypeError, ValueError):
        raise ValueError("Los dias van del 1 (lunes) al 7 (domingo).") from None
    if not lista or any(d < 1 or d > 7 for d in lista):
        raise ValueError("Marca al menos un dia, del 1 (lunes) al 7 (domingo).")
    try:
        ZoneInfo(zona)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"No conozco la zona horaria {zona}.") from None
    with basedatos.conexion() as con:
        con.execute("INSERT INTO horario_laboral (usuario_id, inicio, fin, dias, zona) VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT (usuario_id) DO UPDATE SET inicio = excluded.inicio, fin = excluded.fin, "
                    "dias = excluded.dias, zona = excluded.zona",
                    (usuario_id, inicio, fin, ",".join(str(d) for d in lista), zona))
    return horario(usuario_id)


# --------------------------------------------------------------------------
# WhatsApp (Evolution): la instancia de cada persona
# --------------------------------------------------------------------------

def instancia_evolution(usuario_id: str) -> dict | None:
    with basedatos.conexion() as con:
        fila = con.execute("SELECT * FROM evolution_instancias WHERE usuario_id = ?", (usuario_id,)).fetchone()
    return dict(fila) if fila else None


def preparar_evolution(usuario_id: str) -> dict:
    """La instancia de la persona (nombre y secreto del webhook); la anota la primera vez."""
    import secrets as _secrets

    actual = instancia_evolution(usuario_id)
    if actual:
        return actual
    with basedatos.conexion() as con:
        con.execute("INSERT INTO evolution_instancias (usuario_id, instancia, clave, actualizado) "
                    "VALUES (?, ?, ?, ?)",
                    (usuario_id, evolution_wa.nombre_instancia(usuario_id), _secrets.token_urlsafe(32), _ahora()))
    return instancia_evolution(usuario_id)


def usuario_de_clave(clave: str) -> tuple[str, str] | None:
    """(usuario_id, instancia) del webhook que trae esta clave."""
    if not clave:
        return None
    with basedatos.conexion() as con:
        fila = con.execute("SELECT usuario_id, instancia FROM evolution_instancias WHERE clave = ?",
                           (clave,)).fetchone()
    return (fila["usuario_id"], fila["instancia"]) if fila else None


def conectar_evolution(usuario_id: str, numero: str) -> None:
    cuenta = whatsapp.legible(numero) if numero else "tu WhatsApp"
    with basedatos.conexion() as con:
        con.execute("UPDATE evolution_instancias SET numero = ?, actualizado = ? WHERE usuario_id = ?",
                    (numero or None, _ahora(), usuario_id))
        con.execute(
            "INSERT INTO integraciones (usuario_id, app, cuenta, token, cursor, estado, error, conectado) "
            "VALUES (?, 'whatsapp', ?, NULL, NULL, 'conectado', NULL, ?) "
            "ON CONFLICT (usuario_id, app) DO UPDATE SET cuenta = excluded.cuenta, "
            "estado = 'conectado', error = NULL, conectado = excluded.conectado",
            (usuario_id, cuenta, _ahora()))


def borrar_evolution(usuario_id: str) -> str | None:
    """Olvida la instancia y devuelve su nombre (para borrarla en Evolution)."""
    actual = instancia_evolution(usuario_id)
    if not actual:
        return None
    with basedatos.conexion() as con:
        con.execute("DELETE FROM evolution_instancias WHERE usuario_id = ?", (usuario_id,))
        con.execute("UPDATE integraciones SET estado = 'desconectado', error = NULL "
                    "WHERE usuario_id = ? AND app = 'whatsapp'", (usuario_id,))
    return actual["instancia"]
