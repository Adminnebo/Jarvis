"""Sala de una reunión presencial: cada participante entra con su teléfono y dice
cuándo habla.

Un solo aparato graba el audio (el de quien organiza). Los demás solo mandan cuánto
oye su micrófono, 4 veces por segundo: quien habla está cerca de su teléfono, así que
en cada segundo el micrófono que más oye (con margen sobre el segundo) dice quién
habla. Eso arma la misma `linea` [{t, nombres}] que manda el bot de Meet, y
`reuniones_ia.con_nombres` hace el resto.

Se entra con un link/QR (invitados, sin cuenta: escriben su nombre) o desde una
invitación de Jarvis (equipo: su nombre sale de la cuenta y les llega el resumen).
Ver docs/superpowers/specs/2026-11-26-reuniones-calibracion-y-sala-design.md.
"""

import hashlib
import hmac
import re
import secrets
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from . import basedatos
from . import reuniones_datos as rd

BASE = "https://asistente.neboaiconsulting.com"
CODIGO = re.compile(r"^[A-Za-z0-9_-]{12}$")
VENTANA_MS = 250          # cada nivel que manda un teléfono
MAX_NIVELES = 80          # por paquete (20 s): más es un error o un abuso
UMBRAL = 0.02             # nivel mínimo para decir que alguien habla
MARGEN = 1.5              # cuánto más fuerte que el segundo micrófono
EQUIPO_DIAS = 60


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def nuevo_codigo() -> str:
    return secrets.token_urlsafe(9)   # 12 caracteres


def link(codigo: str) -> str:
    return f"{BASE}/sala/{codigo}"


def por_codigo(codigo: str) -> dict | None:
    if not CODIGO.match(codigo or ""):
        return None
    with basedatos.conexion() as con:
        fila = con.execute("SELECT id FROM reuniones WHERE sala = ?", (codigo,)).fetchone()
    return rd.obtener(fila["id"]) if fila else None


def abierta(r: dict | None) -> bool:
    return bool(r and r.get("sala") and r["estado"] == "grabando")


# --------------------------------------------------------------------------
# Participantes
# --------------------------------------------------------------------------

def agregar(reunion_id: str, nombre: str, usuario_id: str | None = None) -> dict:
    """Un participante nuevo (o el mismo, si ya entró con su cuenta) con un token nuevo."""
    token = secrets.token_urlsafe(24)
    ahora = _ahora().isoformat(timespec="seconds")
    with basedatos.conexion() as con:
        previo = con.execute("SELECT id FROM reunion_participantes WHERE reunion_id = ? AND usuario_id = ?",
                             (reunion_id, usuario_id)).fetchone() if usuario_id else None
        if previo:
            pid = previo["id"]
            con.execute("UPDATE reunion_participantes SET token_hash = ?, nombre = ?, visto = ? WHERE id = ?",
                        (_hash(token), nombre, ahora, pid))
        else:
            pid = uuid.uuid4().hex[:12]
            con.execute("INSERT INTO reunion_participantes (id, reunion_id, nombre, usuario_id, token_hash, unido, visto) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)", (pid, reunion_id, nombre, usuario_id, _hash(token), ahora, ahora))
    return {"participante": pid, "token": token, "nombre": nombre,
            "ahora_ms": int(_ahora().timestamp() * 1000)}


def unirse(codigo: str, nombre: str, usuario=None) -> dict | str:
    """Entra a la sala. Con cuenta de Jarvis el nombre sale de la cuenta y la persona
    pasa a recibir el resumen. Devuelve el participante o el motivo ('cerrada', 'nombre')."""
    r = por_codigo(codigo)
    if not abierta(r):
        return "cerrada"
    nombre = (usuario.nombre if usuario else " ".join((nombre or "").split()))[:60]
    if not nombre:
        return "nombre"
    if usuario:
        rd.interesar(r["id"], usuario.id, True)
    return agregar(r["id"], nombre, usuario.id if usuario else None)


def _participante(reunion_id: str, pid: str, token: str) -> dict | None:
    with basedatos.conexion() as con:
        fila = con.execute("SELECT * FROM reunion_participantes WHERE id = ? AND reunion_id = ?",
                           (pid or "", reunion_id)).fetchone()
    if fila and token and hmac.compare_digest(fila["token_hash"], _hash(token)):
        return dict(fila)
    return None


def participantes(reunion_id: str) -> list[dict]:
    ahora = _ahora()
    with basedatos.conexion() as con:
        filas = con.execute("SELECT id, nombre, usuario_id, unido, visto FROM reunion_participantes "
                            "WHERE reunion_id = ? ORDER BY unido", (reunion_id,)).fetchall()
    salida = []
    for f in filas:
        visto = datetime.fromisoformat(f["visto"]) if f["visto"] else None
        salida.append({"id": f["id"], "nombre": f["nombre"], "equipo": bool(f["usuario_id"]),
                       "visto_hace_s": int((ahora - visto).total_seconds()) if visto else None})
    return salida


# --------------------------------------------------------------------------
# Niveles y quién habla
# --------------------------------------------------------------------------

def guardar_niveles(codigo: str, pid: str, token: str, desde_ms: int, niveles: list) -> bool | None:
    """None si el participante no vale; False si la sala ya no graba (el teléfono para);
    True si se guardaron. Se guarda el máximo de cada segundo de la reunión."""
    r = por_codigo(codigo)
    if r is None or _participante(r["id"], pid, token) is None:
        return None
    if not abierta(r) or not r.get("grabando_desde"):
        return False
    base_ms = datetime.fromisoformat(r["grabando_desde"]).timestamp() * 1000
    por_segundo: dict[int, float] = {}
    for i, v in enumerate(niveles[:MAX_NIVELES]):
        try:
            v = min(max(float(v), 0.0), 1.0)
        except (TypeError, ValueError):
            continue
        segundo = int((int(desde_ms) + i * VENTANA_MS - base_ms) // 1000)
        if segundo >= 0:
            por_segundo[segundo] = max(v, por_segundo.get(segundo, 0.0))
    with basedatos.conexion() as con:
        con.executemany(
            "INSERT INTO reunion_niveles (reunion_id, participante_id, segundo, nivel) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (reunion_id, participante_id, segundo) DO UPDATE SET nivel = MAX(nivel, excluded.nivel)",
            [(r["id"], pid, s, v) for s, v in por_segundo.items()])
        con.execute("UPDATE reunion_participantes SET visto = ? WHERE id = ?",
                    (_ahora().isoformat(timespec="seconds"), pid))
    return True


def linea(reunion_id: str) -> list[dict]:
    """[{t, nombres: [quien]}]: en cada segundo, el micrófono que más oyó, si oyó lo
    suficiente y bastante más que el segundo."""
    with basedatos.conexion() as con:
        nombres = {f["id"]: f["nombre"] for f in con.execute(
            "SELECT id, nombre FROM reunion_participantes WHERE reunion_id = ?", (reunion_id,))}
        filas = con.execute("SELECT participante_id, segundo, nivel FROM reunion_niveles WHERE reunion_id = ?",
                            (reunion_id,)).fetchall()
    por_segundo: dict[int, list[tuple[float, str]]] = defaultdict(list)
    for f in filas:
        if f["participante_id"] in nombres:
            por_segundo[f["segundo"]].append((f["nivel"], f["participante_id"]))
    salida = []
    for segundo in sorted(por_segundo):
        orden = sorted(por_segundo[segundo], reverse=True)
        mayor, quien = orden[0]
        segundo_mayor = orden[1][0] if len(orden) > 1 else 0.0
        if mayor >= UMBRAL and mayor >= MARGEN * segundo_mayor:
            salida.append({"t": segundo, "nombres": [nombres[quien]]})
    return salida


def borrar_niveles(reunion_id: str) -> None:
    with basedatos.conexion() as con:
        con.execute("DELETE FROM reunion_niveles WHERE reunion_id = ?", (reunion_id,))


# --------------------------------------------------------------------------
# Equipo e invitaciones
# --------------------------------------------------------------------------

def equipo(usuario) -> list[dict]:
    """A quién se puede invitar: quienes usaron Jarvis en la misma organización en los
    últimos 60 días, y los miembros de una cuenta de organización."""
    from . import acceso, asistente, cuentas
    organizacion = asistente.organizacion_de(usuario)
    ids: set[str] = set()
    if organizacion:
        desde = (_ahora() - timedelta(days=EQUIPO_DIAS)).isoformat()
        with basedatos.conexion() as con:
            ids |= {f[0] for f in con.execute(
                "SELECT DISTINCT usuario_id FROM consumo WHERE organizacion_id = ? AND cuando >= ? "
                "AND usuario_id IS NOT NULL", (organizacion, desde))}
    else:
        ids |= {u.id for u in acceso.usuarios()}
    if getattr(usuario, "organizacion_id", None):
        ids |= {f"{cuentas.PREFIJO}{m['id']}" for m in cuentas.miembros(usuario.organizacion_id)}
    ids = {i for i in ids if i and i != usuario.id and not cuentas.es_puente(i)}
    if not ids:
        return []
    nombres = cuentas.nombres_de_usuarios(ids)
    return sorted(({"id": i, "nombre": nombres.get(i) or i} for i in ids), key=lambda x: x["nombre"].lower())


def invitar(usuario, reunion_id: str, ids: list[str]) -> int:
    """Manda la invitación (campanita + WhatsApp) a los del equipo elegidos."""
    from . import avisos
    r = rd.obtener(reunion_id)
    if not abierta(r) or not rd.puede_ver(reunion_id, usuario.id):
        return 0
    validos = {x["id"] for x in equipo(usuario)}
    enviados = 0
    for uid in dict.fromkeys(ids):
        if uid not in validos:
            continue
        texto = (f"{usuario.nombre} te invitó a la reunión presencial «{r['titulo']}». "
                 "Entra desde tu teléfono y déjalo frente a ti: así se sabe cuándo hablas.")
        if avisos.crear(uid, f"sala:{reunion_id}", reunion_id, "Reuniones", link(r["sala"]), texto,
                        con_whatsapp=True, tipo="sala", app="reuniones"):
            enviados += 1
    return enviados
