"""Accesos directos: preguntas frecuentes con su consulta ya escrita, por fuente.

Existen por velocidad y por acierto, como el catalogo de consultas.py, pero los
carga el super admin desde la interfaz (asistido por redactor.py). Las variables
viajan como parametros del driver (%(nombre)s): nunca se pegan en el SQL.
"""

import json
import re
import time
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


# (id, valores) -> (momento, filas). Se vacia al guardar.
_cache: dict = {}


VIGENCIA = 30  # segundos


def _valores(acceso: dict, recibidos: dict) -> dict:
    valores = {}
    for nombre, spec in acceso["parametros"].items():
        crudo = recibidos.get(nombre, spec.get("por_defecto"))
        if crudo is None:
            raise ErrorDeAcceso(f"Falta la variable {nombre}: {spec.get('descripcion', '')}.")
        valores[nombre] = valor(spec, crudo)
    return valores


def _anotar_error(id_acceso: str, texto: str | None) -> None:
    with basedatos.conexion() as con:
        con.execute("UPDATE accesos_directos SET ultimo_error = ? WHERE id = ?",
                    (texto[:300] if texto else None, id_acceso))


def ejecutar(id_acceso: str, recibidos: dict | None = None, limite: int = 100) -> dict:
    """{'filas': [...]} o {'error': texto para el modelo}."""
    acceso = obtener(id_acceso)
    if not acceso or not acceso["activo"]:
        return {"error": f"No hay un acceso directo activo llamado '{id_acceso}'. Usa consultar_fuente."}
    try:
        valores = _valores(acceso, recibidos or {})
    except ErrorDeAcceso as error:
        return {"error": str(error)}
    clave = (id_acceso, json.dumps(valores, sort_keys=True))
    guardado = _cache.get(clave)
    if guardado and time.monotonic() - guardado[0] < VIGENCIA:
        return {"filas": guardado[1]}
    try:
        filas = fuentes.consultar(acceso["fuente_id"], acceso["sql"], limite, parametros=valores or None)
    except Exception as error:  # noqa: BLE001 - p. ej. cambio la vista
        explicacion = fuentes.explicar(error)
        _anotar_error(id_acceso, explicacion)
        return {"error": f"El acceso directo fallo ({explicacion}). Responde con consultar_fuente."}
    if acceso["ultimo_error"]:
        _anotar_error(id_acceso, None)
    _cache[clave] = (time.monotonic(), filas)
    return {"filas": filas}


def catalogo_para_prompt() -> str:
    """Una linea por acceso activo de una fuente activa. Prefijo fijo: el puente lo busca."""
    ids_activas = {f["id"] for f in fuentes.activas()}
    lineas = []
    for a in listar():
        if a["activo"] and a["fuente_id"] in ids_activas:
            variables = ", ".join(a["parametros"])
            lineas.append(f"- acceso {a['id']}({variables}) [fuente {a['fuente_id']}]: {a['descripcion']}")
    return "\n".join(lineas)
