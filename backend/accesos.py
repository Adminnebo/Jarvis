"""Accesos directos: preguntas frecuentes con su consulta ya escrita, por fuente.

Existen por velocidad y por acierto, como el catalogo de consultas.py, pero los
carga el super admin desde la interfaz (asistido por redactor.py). Las variables
viajan como parametros del driver (%(nombre)s): nunca se pegan en el SQL.
"""

import json
import re
from datetime import date, datetime, timezone

from . import basedatos, fuentes

NOMBRE = re.compile(r"^[a-z][a-z0-9_]{2,59}$")
PLACEHOLDER = re.compile(r"%\((\w+)\)s")
TIPOS = ("fecha", "entero", "texto")


class ErrorDeAcceso(ValueError):
    """Algo del acceso directo no sirve. El mensaje es para quien lo carga."""


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def valor(spec: dict, crudo):
    """Convierte y valida el valor de una variable segun su tipo."""
    tipo = spec.get("tipo")
    if tipo == "fecha":
        try:
            return date.fromisoformat(str(crudo)).isoformat()
        except ValueError:
            raise ErrorDeAcceso(f"'{crudo}' no es una fecha AAAA-MM-DD.") from None
    if tipo == "entero":
        try:
            numero = int(crudo)
        except (TypeError, ValueError):
            raise ErrorDeAcceso(f"'{crudo}' no es un numero entero.") from None
        minimo, maximo = int(spec.get("minimo", 1)), int(spec.get("maximo", 500))
        if not minimo <= numero <= maximo:
            raise ErrorDeAcceso(f"{numero} esta fuera de {minimo}-{maximo}.")
        return numero
    if tipo == "texto":
        texto = str(crudo or "").strip()
        if len(texto) > 100:
            raise ErrorDeAcceso("El texto puede tener hasta 100 caracteres.")
        return texto
    raise ErrorDeAcceso(f"Tipo de variable desconocido: {tipo}.")


def validar(datos: dict) -> dict:
    """Lo que se guarda, ya limpio. Lanza ErrorDeAcceso si algo no sirve."""
    nombre = str(datos.get("id") or "").strip()
    if not NOMBRE.match(nombre):
        raise ErrorDeAcceso("El nombre va en minusculas, con guiones bajos, sin espacios (p. ej. ventas_por_periodo).")
    sql = str(datos.get("sql") or "").strip().rstrip(";")
    try:
        fuentes.validar_solo_lectura(sql)
    except ValueError as error:
        raise ErrorDeAcceso(f"La consulta tiene que ser de solo lectura: {error}") from None
    parametros = datos.get("parametros") or {}
    usados, declarados = set(PLACEHOLDER.findall(sql)), set(parametros)
    if usados != declarados:
        faltan = sorted(usados ^ declarados)
        raise ErrorDeAcceso(f"Las variables de la consulta y las declaradas no coinciden: {', '.join(faltan)}.")
    for nombre_p, spec in parametros.items():
        if spec.get("tipo") not in TIPOS:
            raise ErrorDeAcceso(f"La variable {nombre_p} tiene un tipo invalido.")
        if spec.get("por_defecto") is not None:
            valor(spec, spec["por_defecto"])
    descripcion = " ".join(str(datos.get("descripcion") or "").split())
    if not descripcion:
        raise ErrorDeAcceso("Falta la descripcion de que responde.")
    return {"id": nombre, "pregunta": str(datos.get("pregunta") or "").strip()[:300],
            "descripcion": descripcion[:400], "sql": sql, "parametros": parametros}


def guardar(fuente_id: str, datos: dict) -> dict:
    limpio = validar(datos)
    with basedatos.conexion() as con:
        con.execute(
            "INSERT INTO accesos_directos (id, fuente_id, pregunta, descripcion, sql, parametros, "
            "creado, actualizado) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (id) DO UPDATE SET fuente_id = excluded.fuente_id, pregunta = excluded.pregunta, "
            "descripcion = excluded.descripcion, sql = excluded.sql, parametros = excluded.parametros, "
            "ultimo_error = NULL, actualizado = excluded.actualizado",
            (limpio["id"], fuente_id, limpio["pregunta"], limpio["descripcion"], limpio["sql"],
             json.dumps(limpio["parametros"], ensure_ascii=False), _ahora(), _ahora()),
        )
    _cache.clear()
    return obtener(limpio["id"])


def _fila(f) -> dict:
    return {"id": f["id"], "fuente_id": f["fuente_id"], "pregunta": f["pregunta"],
            "descripcion": f["descripcion"], "sql": f["sql"], "parametros": json.loads(f["parametros"]),
            "activo": bool(f["activo"]), "ultimo_error": f["ultimo_error"]}


def obtener(id_acceso: str) -> dict | None:
    with basedatos.conexion() as con:
        f = con.execute("SELECT * FROM accesos_directos WHERE id = ?", (id_acceso,)).fetchone()
    return _fila(f) if f else None


def listar(fuente_id: str | None = None) -> list[dict]:
    with basedatos.conexion() as con:
        filas = con.execute(
            "SELECT * FROM accesos_directos" + (" WHERE fuente_id = ?" if fuente_id else "") + " ORDER BY id",
            (fuente_id,) if fuente_id else (),
        ).fetchall()
    return [_fila(f) for f in filas]


def activar(id_acceso: str, activo: bool) -> None:
    with basedatos.conexion() as con:
        con.execute("UPDATE accesos_directos SET activo = ?, actualizado = ? WHERE id = ?",
                    (1 if activo else 0, _ahora(), id_acceso))


def borrar(id_acceso: str) -> bool:
    with basedatos.conexion() as con:
        return con.execute("DELETE FROM accesos_directos WHERE id = ?", (id_acceso,)).rowcount > 0


def borrar_de_fuente(fuente_id: str) -> None:
    with basedatos.conexion() as con:
        con.execute("DELETE FROM accesos_directos WHERE fuente_id = ?", (fuente_id,))


_cache: dict = {}
