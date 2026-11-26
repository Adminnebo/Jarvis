"""Reuniones grabadas por el bot de Meet: filas en la SQLite de Jarvis.

Estados de una reunion: propuesta (salio el aviso, nadie pidio grabar),
agendada, esperando, grabando, procesando, lista; o rechazada, fallida,
cancelada, sin_bot. `incompleta` marca una lista a la que le falta un trozo.
"""

import json
import uuid
from datetime import datetime, timezone

from . import basedatos

JSON = ("linea", "transcripcion", "puntos", "tareas", "nombres")
MAX_INTENTOS = 3


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fila(f) -> dict | None:
    if f is None:
        return None
    d = dict(f)
    for campo in JSON:
        if campo in d and d[campo] is not None:
            d[campo] = json.loads(d[campo])
    return d


def crear_o_obtener(clave: str, meet_url: str, titulo: str, inicio: str, fin: str) -> dict:
    with basedatos.conexion() as con:
        con.execute(
            "INSERT OR IGNORE INTO reuniones (id, clave, meet_url, titulo, inicio, fin, estado, creada) "
            "VALUES (?, ?, ?, ?, ?, ?, 'propuesta', ?)",
            (uuid.uuid4().hex, clave, meet_url, titulo[:200] or "Reunión", inicio, fin, _ahora()))
        return _fila(con.execute("SELECT * FROM reuniones WHERE clave = ?", (clave,)).fetchone())


def obtener(id_: str) -> dict | None:
    with basedatos.conexion() as con:
        return _fila(con.execute("SELECT * FROM reuniones WHERE id = ?", (id_,)).fetchone())


def actualizar(id_: str, **campos) -> None:
    if not campos:
        return
    valores = [json.dumps(v, ensure_ascii=False) if k in JSON and v is not None else v
               for k, v in campos.items()]
    asignaciones = ", ".join(f"{k} = ?" for k in campos)
    with basedatos.conexion() as con:
        con.execute(f"UPDATE reuniones SET {asignaciones} WHERE id = ?", (*valores, id_))


def interesar(reunion_id: str, usuario_id: str, quiere: bool) -> None:
    with basedatos.conexion() as con:
        con.execute(
            "INSERT INTO reunion_interesados (reunion_id, usuario_id, quiere) VALUES (?, ?, ?) "
            "ON CONFLICT (reunion_id, usuario_id) DO UPDATE SET quiere = excluded.quiere",
            (reunion_id, usuario_id, int(quiere)))


def interesados(reunion_id: str) -> list[str]:
    """Quienes pidieron grabar (y por eso la ven y reciben el resumen)."""
    with basedatos.conexion() as con:
        return [f[0] for f in con.execute(
            "SELECT usuario_id FROM reunion_interesados WHERE reunion_id = ? AND quiere = 1 "
            "ORDER BY rowid", (reunion_id,)).fetchall()]


def puede_ver(reunion_id: str, usuario_id: str) -> bool:
    return usuario_id in interesados(reunion_id)


def listar_de(usuario_id: str, limite: int = 100) -> list[dict]:
    with basedatos.conexion() as con:
        filas = con.execute(
            "SELECT r.* FROM reuniones r JOIN reunion_interesados i ON i.reunion_id = r.id "
            "WHERE i.usuario_id = ? AND i.quiere = 1 ORDER BY r.inicio DESC LIMIT ?",
            (usuario_id, limite)).fetchall()
    return [_fila(f) for f in filas]


EN_CURSO = ("agendada", "esperando", "grabando")


def en_curso_de(usuario_id: str) -> list[dict]:
    """Las que pidió y todavía no terminan: agendadas, esperando que lo admitan o grabando."""
    marcas = ", ".join("?" * len(EN_CURSO))
    with basedatos.conexion() as con:
        filas = con.execute(
            "SELECT r.* FROM reuniones r JOIN reunion_interesados i ON i.reunion_id = r.id "
            f"WHERE i.usuario_id = ? AND i.quiere = 1 AND r.estado IN ({marcas}) ORDER BY r.inicio",
            (usuario_id, *EN_CURSO)).fetchall()
    return [_fila(f) for f in filas]


def guardar_pedazo(reunion_id: str, n: int, formato: str = "ogg", inicio_s: int | None = None) -> bool:
    """True si es nuevo; el mismo pedazo dos veces no se guarda otra vez."""
    with basedatos.conexion() as con:
        cursor = con.execute(
            "INSERT OR IGNORE INTO reunion_pedazos (reunion_id, n, estado, formato, inicio_s) "
            "VALUES (?, ?, 'recibido', ?, ?)", (reunion_id, n, formato, inicio_s))
        return cursor.rowcount == 1


def pedazos(reunion_id: str) -> list[dict]:
    with basedatos.conexion() as con:
        filas = con.execute("SELECT * FROM reunion_pedazos WHERE reunion_id = ? ORDER BY n",
                            (reunion_id,)).fetchall()
    salida = []
    for f in filas:
        d = dict(f)
        d["segmentos"] = json.loads(d["segmentos"]) if d["segmentos"] else None
        salida.append(d)
    return salida


def marcar_pedazo(reunion_id: str, n: int, estado: str, segmentos=None, sumar_intento: bool = False) -> None:
    with basedatos.conexion() as con:
        con.execute(
            "UPDATE reunion_pedazos SET estado = ?, segmentos = COALESCE(?, segmentos), "
            "intentos = intentos + ? WHERE reunion_id = ? AND n = ?",
            (estado, json.dumps(segmentos, ensure_ascii=False) if segmentos is not None else None,
             int(sumar_intento), reunion_id, n))


def para_transcribir() -> list[tuple[str, int]]:
    with basedatos.conexion() as con:
        return [(f[0], f[1]) for f in con.execute(
            "SELECT reunion_id, n FROM reunion_pedazos WHERE estado = 'recibido' AND intentos < ? "
            "ORDER BY reunion_id, n", (MAX_INTENTOS,)).fetchall()]


def en_estado(estado: str) -> list[dict]:
    with basedatos.conexion() as con:
        return [_fila(f) for f in con.execute("SELECT * FROM reuniones WHERE estado = ?",
                                              (estado,)).fetchall()]


def con_audio_desde_antes(limite_iso: str) -> list[str]:
    with basedatos.conexion() as con:
        return [f[0] for f in con.execute(
            "SELECT id FROM reuniones WHERE audio_borrado = 0 AND estado = 'lista' AND inicio < ?",
            (limite_iso,)).fetchall()]


def grabar_siempre(usuario_id: str) -> bool:
    with basedatos.conexion() as con:
        f = con.execute("SELECT grabar_siempre FROM reuniones_preferencias WHERE usuario_id = ?",
                        (usuario_id,)).fetchone()
    return bool(f and f[0])


def poner_grabar_siempre(usuario_id: str, valor: bool) -> None:
    with basedatos.conexion() as con:
        con.execute(
            "INSERT INTO reuniones_preferencias (usuario_id, grabar_siempre) VALUES (?, ?) "
            "ON CONFLICT (usuario_id) DO UPDATE SET grabar_siempre = excluded.grabar_siempre",
            (usuario_id, int(valor)))


def buscar_texto(usuario_id: str, texto: str, desde: str = "", hasta: str = "", limite: int = 5) -> list[dict]:
    patron = f"%{texto.strip()}%"
    sql = ("SELECT r.* FROM reuniones r JOIN reunion_interesados i ON i.reunion_id = r.id "
           "WHERE i.usuario_id = ? AND i.quiere = 1 AND r.estado = 'lista' "
           "AND (r.titulo LIKE ? OR r.resumen LIKE ? OR r.transcripcion LIKE ? OR r.tareas LIKE ?)")
    args = [usuario_id, patron, patron, patron, patron]
    if desde:
        sql += " AND r.inicio >= ?"
        args.append(desde)
    if hasta:
        sql += " AND r.inicio <= ?"
        args.append(hasta)
    sql += " ORDER BY r.inicio DESC LIMIT ?"
    args.append(limite)
    with basedatos.conexion() as con:
        return [_fila(f) for f in con.execute(sql, args).fetchall()]
