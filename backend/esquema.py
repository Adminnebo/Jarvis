"""Cliente MCP minimo y cache del esquema de la base de datos.

Sin esto, para cualquier pregunta sobre los datos el modelo tiene que pedir
primero la lista de tablas: un viaje extra y una respuesta enorme. En texto se
nota; en voz es silencio incomodo y el modelo lo rellena diciendo que "va a
buscarlo". Cacheando el esquema puede ir directo al SQL.
"""

import json
import os
import re
import threading
from datetime import datetime, timedelta
from pathlib import Path

import httpx

from . import conectores, rutas

VIGENCIA = timedelta(hours=12)


def CACHE() -> Path:
    return rutas.archivo("esquema.json")

_candado = threading.Lock()

SQL_ESQUEMA = """
select c.relname as tabla,
       coalesce(s.n_live_tup, 0) as filas,
       string_agg(a.attname || ' ' || format_type(a.atttypid, null),
                  ', ' order by a.attnum) as columnas
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
join pg_attribute a on a.attrelid = c.oid and a.attnum > 0 and not a.attisdropped
left join pg_stat_user_tables s on s.relname = c.relname and s.schemaname = 'public'
where n.nspname = 'public' and c.relkind = 'r'
group by c.relname, s.n_live_tup
order by coalesce(s.n_live_tup, 0) desc;
"""


def consultar(sql: str) -> list[dict]:
    """Ejecuta SQL de solo lectura por la via mas rapida disponible.

    Con SUPABASE_DB_URL configurada va directo a Postgres (decimas de segundo).
    Sin ella cae al MCP, que funciona igual pero cuesta ~2s por viaje porque
    pasa por los servidores de OpenAI y de Supabase.
    """
    if os.getenv("SUPABASE_DB_URL", "").strip():
        return consultar_directo(sql)
    return consultar_por_mcp(sql)


def consultar_directo(sql: str) -> list[dict]:
    """Conexion directa a Postgres, siempre en transaccion de solo lectura."""
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(os.environ["SUPABASE_DB_URL"], connect_timeout=10) as conexion:
        # read_only a nivel de transaccion: aunque la credencial tenga
        # permisos de escritura, por aqui no se puede escribir.
        conexion.read_only = True
        with conexion.cursor(row_factory=dict_row) as cursor:
            cursor.execute(sql)
            return [dict(fila) for fila in cursor.fetchall()]


def consultar_por_mcp(sql: str) -> list[dict]:
    """Ejecuta SQL contra el MCP de Supabase configurado en .env."""
    conector = conectores.supabase()
    if conector is None:
        raise RuntimeError("Supabase no esta configurado.")
    return _mcp(conector["authorization"], conector["server_url"], sql)


def consultar_por_mcp_con(token: str, referencia: str, sql: str) -> list[dict]:
    """Igual, pero con las credenciales de una fuente guardada."""
    if not token or not referencia:
        raise RuntimeError("Faltan el token o la referencia del proyecto.")
    url = f"{conectores.URL_SUPABASE}?project_ref={referencia}&read_only=true"
    return _mcp(token, url, sql)


def _mcp(token: str, url: str, sql: str) -> list[dict]:
    """Cliente JSON-RPC minimo contra un servidor MCP de Supabase."""
    cabeceras = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    with httpx.Client(timeout=45, headers=cabeceras) as http:
        inicio = http.post(url, json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "jarvis", "version": "1.0"},
            },
        })
        inicio.raise_for_status()

        sesion = inicio.headers.get("mcp-session-id")
        if sesion:
            http.headers["Mcp-Session-Id"] = sesion
        http.post(url, json={"jsonrpc": "2.0", "method": "notifications/initialized"})

        respuesta = http.post(url, json={
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "execute_sql", "arguments": {"query": sql}},
        })
        respuesta.raise_for_status()

    return filas_de(cuerpo(respuesta))


def cuerpo(respuesta: httpx.Response) -> dict:
    """El servidor contesta JSON plano o un evento SSE segun el momento."""
    texto = respuesta.text
    if texto.lstrip().startswith(("event:", "data:")) or "\ndata: " in texto:
        for linea in texto.splitlines():
            if linea.startswith("data: "):
                return json.loads(linea[6:])
    return respuesta.json()


def mensaje_de_error(resultado: dict) -> str:
    """Saca el texto util del envoltorio de error del MCP.

    Sin esto, un simple 'tabla no existe' llega como un muro de JSON anidado.
    """
    try:
        texto = resultado["content"][0]["text"]
        interior = json.loads(texto)
        crudo = interior.get("error", {}).get("message", texto)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        crudo = json.dumps(resultado)

    # Postgres antepone 'Failed to run sql query: ERROR: 42P01: '
    limpio = re.sub(r"^Failed to run sql query:\s*", "", str(crudo)).strip()
    limpio = re.sub(r"^ERROR:\s*\w+:\s*", "", limpio).strip()
    return limpio[:300] or "La consulta fallo."


def filas_de(sobre: dict) -> list[dict]:
    """Saca las filas del envoltorio del MCP.

    Supabase rodea los datos con marcas <untrusted-data-...> para que un
    registro no pueda inyectar instrucciones al modelo. Aqui las quitamos.
    """
    resultado = sobre.get("result", sobre)
    if resultado.get("isError"):
        raise RuntimeError(mensaje_de_error(resultado))

    texto = resultado["content"][0]["text"]
    interior = json.loads(texto).get("result", "")

    abre = interior.find("[")
    cierra = interior.rfind("]") + 1
    if abre == -1 or cierra <= abre:
        return []
    return json.loads(interior[abre:cierra])


# --------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------

def leer_cache() -> dict | None:
    ruta = CACHE()
    if not ruta.exists():
        return None
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def vigente(cache: dict | None) -> bool:
    if not cache:
        return False
    try:
        creado = datetime.fromisoformat(cache["creado"])
    except (KeyError, ValueError):
        return False
    return datetime.now() - creado < VIGENCIA


def refrescar() -> dict | None:
    """Vuelve a leer el esquema y lo guarda. Devuelve None si no se pudo."""
    if conectores.supabase() is None:
        return None

    with _candado:
        try:
            tablas = consultar(SQL_ESQUEMA)
        except Exception:  # noqa: BLE001 - sin esquema Jarvis sigue funcionando
            return None

        cache = {"creado": datetime.now().isoformat(timespec="seconds"), "tablas": tablas}
        CACHE().write_text(
            json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return cache


def refrescar_en_segundo_plano() -> None:
    """Actualiza el esquema sin bloquear el arranque del servidor."""
    if conectores.supabase() is None or vigente(leer_cache()):
        return
    threading.Thread(target=refrescar, daemon=True).start()


def resumen() -> str:
    """Esquema completo con columnas. Pesa; no va en el prompt."""
    cache = leer_cache()
    if not vigente(cache):
        refrescar_en_segundo_plano()
    if not cache:
        return ""

    lineas = []
    for tabla in cache["tablas"]:
        lineas.append(f"{tabla['tabla']} ({tabla['filas']} filas): {tabla['columnas']}")
    return "\n".join(lineas)


def indice() -> str:
    """Solo nombres y tamanos: lo que si cabe en el prompt.

    Volcar todas las columnas costaba ~1600 tokens y duplicaba el tiempo que
    tarda el modelo en decidir que hacer. Con el catalogo de consultas cubriendo
    lo habitual, basta con que sepa que tablas existen.
    """
    cache = leer_cache()
    if not vigente(cache):
        refrescar_en_segundo_plano()
    if not cache:
        return ""

    return ", ".join(
        f"{t['tabla']}({t['filas']})" for t in cache["tablas"]
    )


def columnas_de(tabla: str) -> str:
    cache = leer_cache()
    if not cache:
        return "No tengo el esquema cargado."

    for entrada in cache["tablas"]:
        if entrada["tabla"].lower() == tabla.strip().lower():
            return f"{entrada['tabla']} ({entrada['filas']} filas): {entrada['columnas']}"

    nombres = ", ".join(t["tabla"] for t in cache["tablas"])
    return f"No existe la tabla '{tabla}'. Las que hay: {nombres}"


def info() -> dict:
    cache = leer_cache()
    return {
        "tablas": len(cache["tablas"]) if cache else 0,
        "creado": cache.get("creado") if cache else None,
    }
