"""Fuentes de datos: PostgreSQL, SQL Server y Supabase.

Cada fuente se guarda con sus credenciales cifradas, se puede probar antes de
usarla, y expone su esquema para que Jarvis sepa que hay dentro.

La definicion de campos de CATALOGO_TIPOS es la unica fuente de verdad: la
interfaz web dibuja los formularios a partir de ella, asi que agregar un motor
nuevo no obliga a tocar el frontend.
"""

import json
import re
import threading
import time
import uuid
from pathlib import Path

from . import rutas, secretos

_candado = threading.Lock()


def ARCHIVO() -> Path:
    return rutas.archivo("fuentes.json")


# --------------------------------------------------------------------------
# Que campos pide cada motor
# --------------------------------------------------------------------------

def campo(nombre, etiqueta, tipo="texto", requerido=False, por_defecto="",
          ayuda="", ejemplo=""):
    return {
        "nombre": nombre, "etiqueta": etiqueta, "tipo": tipo,
        "requerido": requerido, "por_defecto": por_defecto,
        "ayuda": ayuda, "ejemplo": ejemplo,
    }


CATALOGO_TIPOS = {
    "postgres": {
        "etiqueta": "PostgreSQL",
        "descripcion": "Cualquier Postgres accesible por red: propio, RDS, Neon, Railway.",
        "campos": [
            campo("url", "Cadena de conexion", "secreto", ayuda=
                  "Si la pones, se ignoran los campos de abajo.",
                  ejemplo="postgresql://usuario:clave@servidor:5432/basededatos"),
            campo("host", "Servidor", ejemplo="db.midominio.com"),
            campo("puerto", "Puerto", "numero", por_defecto="5432"),
            campo("base", "Base de datos", ejemplo="postgres"),
            campo("usuario", "Usuario", ejemplo="postgres"),
            campo("password", "Contrasena", "secreto"),
            campo("ssl", "Exigir SSL", "booleano", por_defecto=True),
        ],
    },
    "mssql": {
        "etiqueta": "Microsoft SQL Server",
        "descripcion": "SQL Server local o en Azure. Se conecta por TDS, sin ODBC.",
        "campos": [
            campo("host", "Servidor", requerido=True,
                  ayuda="Solo el host. La instancia va en su propio campo.",
                  ejemplo="192.168.1.10 o miservidor.database.windows.net"),
            campo("puerto", "Puerto", "numero", por_defecto="1433"),
            campo("instancia", "Instancia", ayuda="Opcional.", ejemplo="SQLEXPRESS"),
            campo("base", "Base de datos", requerido=True, ejemplo="Contabilidad"),
            campo("usuario", "Usuario", requerido=True, ejemplo="sa"),
            campo("password", "Contrasena", "secreto", requerido=True),
        ],
    },
    "supabase": {
        "etiqueta": "Supabase",
        "descripcion": "Consulta por MCP, o directo a Postgres si das la cadena.",
        "campos": [
            campo("project_ref", "Referencia del proyecto", requerido=True,
                  ayuda="El id que aparece en la URL del dashboard.",
                  ejemplo="abcdefghijklmnopqrst"),
            campo("access_token", "Personal Access Token", "secreto", requerido=True,
                  ayuda="Empieza con sbp_. No sirven las llaves de proyecto.",
                  ejemplo="sbp_..."),
            campo("url", "Cadena de conexion directa", "secreto", ayuda=
                  "Opcional, pero baja cada consulta de ~1.2s a ~0.15s. "
                  "Dashboard > Database > Connection string > Transaction pooler.",
                  ejemplo="postgresql://postgres.abc:clave@...pooler.supabase.com:6543/postgres"),
        ],
    },
}

CAMPOS_SECRETOS = {"password", "access_token", "url"}


def tipos_para_interfaz() -> dict:
    return CATALOGO_TIPOS


# --------------------------------------------------------------------------
# Persistencia
# --------------------------------------------------------------------------

def _leer() -> list[dict]:
    ruta = ARCHIVO()
    if not ruta.exists():
        return []
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _escribir(fuentes: list[dict]) -> None:
    ARCHIVO().write_text(
        json.dumps(fuentes, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def todas() -> list[dict]:
    """Las fuentes con sus secretos ya descifrados. Solo para uso interno."""
    fuentes = []
    for guardada in _leer():
        fuente = dict(guardada)
        fuente["config"] = {
            clave: secretos.descifrar(valor) if clave in CAMPOS_SECRETOS else valor
            for clave, valor in guardada.get("config", {}).items()
        }
        fuentes.append(fuente)
    return fuentes


def obtener(id_fuente: str) -> dict | None:
    return next((f for f in todas() if f["id"] == id_fuente), None)


def activas() -> list[dict]:
    return [f for f in todas() if f.get("activa", True)]


def para_interfaz() -> list[dict]:
    """Version segura: los secretos salen enmascarados, nunca completos."""
    publicas = []
    for fuente in todas():
        config = {}
        for clave, valor in fuente["config"].items():
            config[clave] = secretos.enmascarar(valor) if clave in CAMPOS_SECRETOS else valor
        publicas.append({**fuente, "config": config, "tiene_secretos": True})
    return publicas


def guardar(datos: dict) -> dict:
    """Crea o actualiza una fuente. Cifra los secretos antes de escribir."""
    tipo = datos.get("tipo")
    if tipo not in CATALOGO_TIPOS:
        raise ValueError(f"Tipo desconocido: {tipo}")

    nombre = (datos.get("nombre") or "").strip()
    if not nombre:
        raise ValueError("La fuente necesita un nombre.")

    id_fuente = datos.get("id") or uuid.uuid4().hex[:8]
    entrantes = datos.get("config") or {}

    with _candado:
        guardadas = _leer()
        previa = next((f for f in guardadas if f["id"] == id_fuente), None)
        config_previa = (previa or {}).get("config", {})

        config = {}
        for definicion in CATALOGO_TIPOS[tipo]["campos"]:
            clave = definicion["nombre"]
            valor = entrantes.get(clave, "")

            if clave in CAMPOS_SECRETOS:
                # Un secreto vacio al editar significa "dejalo como estaba".
                # Sin esto, guardar el formulario borraria la contrasena, que
                # llega enmascarada desde la interfaz.
                if valor in ("", None):
                    config[clave] = config_previa.get(clave, "")
                else:
                    config[clave] = secretos.cifrar(str(valor))
            elif definicion["tipo"] == "booleano":
                config[clave] = bool(valor)
            else:
                config[clave] = str(valor).strip()

        fuente = {
            "id": id_fuente,
            "nombre": nombre,
            "tipo": tipo,
            "config": config,
            "solo_lectura": bool(datos.get("solo_lectura", True)),
            "activa": bool(datos.get("activa", True)),
            "notas": (datos.get("notas") or "").strip(),
        }

        if previa:
            guardadas = [fuente if f["id"] == id_fuente else f for f in guardadas]
        else:
            guardadas.append(fuente)

        _escribir(guardadas)

    return {"id": id_fuente}


def borrar(id_fuente: str) -> bool:
    with _candado:
        guardadas = _leer()
        quedan = [f for f in guardadas if f["id"] != id_fuente]
        if len(quedan) == len(guardadas):
            return False
        _escribir(quedan)
    return True


# --------------------------------------------------------------------------
# Guardia de solo lectura
# --------------------------------------------------------------------------

PROHIBIDAS = re.compile(
    r"\b(insert|update|delete|drop|truncate|alter|create|grant|revoke|"
    r"merge|exec|execute|call|copy|vacuum|reindex|comment|"
    r"sp_\w+|xp_\w+)\b",
    re.IGNORECASE,
)


def validar_solo_lectura(sql: str) -> None:
    """Rechaza cualquier cosa que no sea una consulta.

    Postgres tiene transacciones de solo lectura y ahi esta la garantia real.
    SQL Server no tiene un equivalente igual de limpio, asi que este filtro es
    la primera linea. Se aplica a todos los motores por igual.
    """
    limpio = re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql, flags=re.DOTALL).strip()

    if not limpio:
        raise ValueError("La consulta esta vacia.")

    if not re.match(r"^\s*(select|with)\b", limpio, re.IGNORECASE):
        raise ValueError("Solo se permiten consultas SELECT.")

    # Punto y coma intermedio: alguien intenta encadenar una segunda sentencia.
    if ";" in limpio.rstrip().rstrip(";"):
        raise ValueError("No se permite mas de una sentencia.")

    encontrada = PROHIBIDAS.search(limpio)
    if encontrada:
        raise ValueError(
            f"La palabra '{encontrada.group()}' no se permite en modo solo lectura."
        )


# --------------------------------------------------------------------------
# Conexion y consulta por motor
# --------------------------------------------------------------------------

def url_postgres(config: dict) -> str:
    if config.get("url"):
        return config["url"]

    faltan = [c for c in ("host", "base", "usuario") if not config.get(c)]
    if faltan:
        raise ValueError(f"Faltan datos de conexion: {', '.join(faltan)}.")

    from urllib.parse import quote

    usuario = quote(config["usuario"], safe="")
    clave = quote(config.get("password", ""), safe="")
    puerto = config.get("puerto") or "5432"
    ssl = "?sslmode=require" if config.get("ssl") else ""

    return f"postgresql://{usuario}:{clave}@{config['host']}:{puerto}/{config['base']}{ssl}"


def consultar_postgres(config: dict, sql: str, limite: int) -> list[dict]:
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(url_postgres(config), connect_timeout=15) as conexion:
        conexion.read_only = True   # la garantia real, a nivel de transaccion
        with conexion.cursor(row_factory=dict_row) as cursor:
            cursor.execute(sql)
            return [dict(f) for f in cursor.fetchmany(limite)]


def consultar_mssql(config: dict, sql: str, limite: int) -> list[dict]:
    import pymssql

    servidor = config["host"]
    if config.get("instancia"):
        servidor = f"{servidor}\\{config['instancia']}"

    conexion = pymssql.connect(
        server=servidor,
        port=str(config.get("puerto") or 1433),
        user=config["usuario"],
        password=config.get("password", ""),
        database=config["base"],
        timeout=30,
        login_timeout=15,
        as_dict=True,
    )
    try:
        with conexion.cursor(as_dict=True) as cursor:
            # Evita bloquear al resto de la base mientras leemos.
            cursor.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;")
            cursor.execute(sql)
            return [dict(f) for f in cursor.fetchmany(limite)]
    finally:
        conexion.close()


def consultar_supabase(config: dict, sql: str, limite: int) -> list[dict]:
    # Con cadena directa vamos por Postgres, que es mucho mas rapido.
    if config.get("url"):
        return consultar_postgres({"url": config["url"]}, sql, limite)

    from . import esquema

    filas = esquema.consultar_por_mcp_con(
        config["access_token"], config["project_ref"], sql
    )
    return filas[:limite]


MOTORES = {
    "postgres": consultar_postgres,
    "mssql": consultar_mssql,
    "supabase": consultar_supabase,
}


def consultar(id_fuente: str, sql: str, limite: int = 200) -> list[dict]:
    fuente = obtener(id_fuente)
    if fuente is None:
        raise ValueError(f"No existe la fuente '{id_fuente}'.")
    if not fuente.get("activa", True):
        raise ValueError(f"La fuente '{fuente['nombre']}' esta desactivada.")

    if fuente.get("solo_lectura", True):
        validar_solo_lectura(sql)

    return MOTORES[fuente["tipo"]](fuente["config"], sql, limite)


# --------------------------------------------------------------------------
# Prueba de conexion
# --------------------------------------------------------------------------

SQL_PRUEBA = {
    "postgres": "select current_database() as base, version() as version;",
    "supabase": "select current_database() as base, version() as version;",
    "mssql": "select db_name() as base, @@version as version;",
}


def probar(datos: dict) -> dict:
    """Intenta conectar y contar tablas. Nunca lanza: devuelve el diagnostico."""
    tipo = datos.get("tipo")
    if tipo not in CATALOGO_TIPOS:
        return {"ok": False, "mensaje": f"Tipo desconocido: {tipo}"}

    # Al probar una fuente ya guardada, la interfaz manda solo el id: partimos
    # de lo guardado y encima ponemos lo que venga en el formulario. Los
    # secretos vacios significan "usa el que ya tenias", porque llegan
    # enmascarados y no se pueden reenviar.
    config = {}
    if datos.get("id"):
        previa = obtener(datos["id"])
        if previa:
            config = dict(previa["config"])

    for clave, valor in (datos.get("config") or {}).items():
        if clave in CAMPOS_SECRETOS and not valor:
            continue
        config[clave] = valor

    inicio = time.perf_counter()
    try:
        filas = MOTORES[tipo](config, SQL_PRUEBA[tipo], 1)
        latencia = round((time.perf_counter() - inicio) * 1000)

        info = filas[0] if filas else {}
        version = str(info.get("version", ""))

        tablas = None
        try:
            tablas = len(MOTORES[tipo](config, SQL_TABLAS[tipo], 500))
        except Exception:  # noqa: BLE001 - el conteo es un extra
            pass

        return {
            "ok": True,
            "mensaje": "Conexion correcta.",
            "base": info.get("base"),
            "version": version.split("\n")[0][:90],
            "latencia_ms": latencia,
            "tablas": tablas,
        }
    except Exception as error:  # noqa: BLE001 - el error es el resultado
        return {
            "ok": False,
            "mensaje": explicar(error),
            "latencia_ms": round((time.perf_counter() - inicio) * 1000),
        }


def explicar(error: Exception) -> str:
    """Traduce los fallos tipicos a algo accionable."""
    crudo = str(error)
    bajo = crudo.lower()

    if "password authentication failed" in bajo or "login failed" in bajo:
        return "Usuario o contrasena incorrectos."
    if "could not translate host name" in bajo or "getaddrinfo" in bajo:
        return "No se encuentra el servidor. Revisa el nombre o la IP."
    if "timeout" in bajo or "timed out" in bajo:
        return ("No responde. Puede ser un firewall, o que el servidor no "
                "acepte conexiones desde esta red.")
    if "does not exist" in bajo and "database" in bajo:
        return "Esa base de datos no existe en el servidor."
    if "connection refused" in bajo:
        return "El servidor rechazo la conexion. Revisa el puerto."
    if "ssl" in bajo:
        return "Problema de SSL. Prueba desactivando 'Exigir SSL'."
    if "20009" in crudo:
        return ("No se pudo conectar. En SQL Server revisa que TCP/IP este "
                "habilitado y que el puerto sea el correcto.")
    return crudo[:220]


# --------------------------------------------------------------------------
# Esquema por motor
# --------------------------------------------------------------------------

SQL_TABLAS = {
    "postgres": """
        select table_schema as esquema, table_name as tabla
        from information_schema.tables
        where table_type = 'BASE TABLE'
          and table_schema not in ('pg_catalog', 'information_schema')
        order by table_schema, table_name;
    """,
    "supabase": """
        select table_schema as esquema, table_name as tabla
        from information_schema.tables
        where table_type = 'BASE TABLE'
          and table_schema not in (
            'pg_catalog', 'information_schema', 'auth', 'storage', 'realtime',
            'vault', 'extensions', 'graphql', 'graphql_public', 'pgbouncer',
            'net', 'cron', 'supabase_migrations', 'supabase_functions'
          )
        order by table_schema, table_name;
    """,
    "mssql": """
        select table_schema as esquema, table_name as tabla
        from information_schema.tables
        where table_type = 'BASE TABLE'
        order by table_schema, table_name;
    """,
}

SQL_COLUMNAS = {
    "postgres": """
        select table_schema as esquema, table_name as tabla,
               column_name as columna, data_type as tipo
        from information_schema.columns
        where table_schema not in ('pg_catalog', 'information_schema')
        order by table_schema, table_name, ordinal_position;
    """,
    # En Supabase filtramos los esquemas del propio servicio: sin esto salen
    # 68 tablas de auth, storage y realtime que tapan las tuyas.
    "supabase": """
        select table_schema as esquema, table_name as tabla,
               column_name as columna, data_type as tipo
        from information_schema.columns
        where table_schema not in (
            'pg_catalog', 'information_schema', 'auth', 'storage', 'realtime',
            'vault', 'extensions', 'graphql', 'graphql_public', 'pgbouncer',
            'net', 'cron', 'supabase_migrations', 'supabase_functions'
        )
        order by table_schema, table_name, ordinal_position;
    """,
    "mssql": """
        select table_schema as esquema, table_name as tabla,
               column_name as columna, data_type as tipo
        from information_schema.columns
        order by table_schema, table_name, ordinal_position;
    """,
}


def esquema_de(id_fuente: str) -> dict:
    """Tablas y columnas de una fuente, agrupadas."""
    fuente = obtener(id_fuente)
    if fuente is None:
        raise ValueError(f"No existe la fuente '{id_fuente}'.")

    filas = MOTORES[fuente["tipo"]](
        fuente["config"], SQL_COLUMNAS[fuente["tipo"]], 5000
    )

    tablas: dict[str, list[str]] = {}
    for fila in filas:
        nombre = fila["tabla"] if fila["esquema"] in ("public", "dbo") \
            else f"{fila['esquema']}.{fila['tabla']}"
        tablas.setdefault(nombre, []).append(f"{fila['columna']} {fila['tipo']}")

    return {
        "fuente": fuente["nombre"],
        "tipo": fuente["tipo"],
        "tablas": [
            {"tabla": nombre, "columnas": ", ".join(columnas)}
            for nombre, columnas in tablas.items()
        ],
    }


def resumen_para_prompt() -> str:
    """Lo que Jarvis necesita saber para elegir fuente sin preguntar."""
    lista = activas()
    if not lista:
        return ""

    lineas = []
    for fuente in lista:
        etiqueta = CATALOGO_TIPOS[fuente["tipo"]]["etiqueta"]
        permiso = "solo lectura" if fuente.get("solo_lectura", True) else "lectura y escritura"
        nota = f" — {fuente['notas']}" if fuente.get("notas") else ""
        lineas.append(f'- id "{fuente["id"]}": {fuente["nombre"]} ({etiqueta}, {permiso}){nota}')
    return "\n".join(lineas)
