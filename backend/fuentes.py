"""Fuentes de datos: PostgreSQL, SQL Server y Supabase.

Cada fuente se guarda con sus credenciales cifradas, se puede probar antes de
usarla, y expone su esquema para que Jarvis sepa que hay dentro.

La definicion de campos de CATALOGO_TIPOS es la unica fuente de verdad: la
interfaz web dibuja los formularios a partir de ella, asi que agregar un motor
nuevo no obliga a tocar el frontend.
"""

import json
import os
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
            # Activacion y leyenda por tabla. Al editar la fuente se conserva lo
            # que ya habia: se administra aparte, en el panel de tablas.
            "tablas": datos.get("tablas") if "tablas" in datos
                      else (previa or {}).get("tablas", {}),
        }

        if previa:
            guardadas = [fuente if f["id"] == id_fuente else f for f in guardadas]
        else:
            guardadas.append(fuente)

        _escribir(guardadas)

    # Las credenciales pueden haber cambiado: la conexion viva ya no vale.
    soltar_conexion(id_fuente)
    olvidar_esquema(id_fuente)

    return {"id": id_fuente}


def sembrar_desde_entorno() -> list[str]:
    """Crea las fuentes definidas en JARVIS_FUENTES si todavia no existen.

    En un servidor el disco se borra en cada despliegue y con el se van las
    fuentes, asi que configurarlas por la interfaz no basta: al segundo
    despliegue no habria base de productos y Jarvis se quedaria sin precios.
    Definidas como variable de entorno vuelven solas cada vez que arranca.

    Solo crea lo que falta. Si editas una fuente desde la interfaz, tu cambio
    manda mientras el disco aguante.
    """
    crudo = os.getenv("JARVIS_FUENTES", "").strip()
    if not crudo:
        return []

    try:
        definidas = json.loads(crudo)
    except json.JSONDecodeError as error:
        print(f"  AVISO: JARVIS_FUENTES no es JSON valido ({error}). Se ignora.")
        return []

    if not isinstance(definidas, list):
        print("  AVISO: JARVIS_FUENTES debe ser una lista. Se ignora.")
        return []

    existentes = {f["id"] for f in todas()}
    creadas = []

    for definicion in definidas:
        id_fuente = (definicion.get("id") or "").strip()
        if not id_fuente:
            print("  AVISO: una fuente de JARVIS_FUENTES no tiene id. Se salta.")
            continue
        if id_fuente in existentes:
            continue
        try:
            guardar({**definicion, "id": id_fuente})
            creadas.append(definicion.get("nombre", id_fuente))
        except ValueError as error:
            print(f"  AVISO: no pude crear la fuente '{id_fuente}': {error}")

    return creadas


def borrar(id_fuente: str) -> bool:
    with _candado:
        guardadas = _leer()
        quedan = [f for f in guardadas if f["id"] != id_fuente]
        if len(quedan) == len(guardadas):
            return False
        _escribir(quedan)

    soltar_conexion(id_fuente)
    olvidar_esquema(id_fuente)
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


# --------------------------------------------------------------------------
# Conexiones reutilizadas
# --------------------------------------------------------------------------

# Abrir una conexion a SQL Server cuesta ~0.9s y ejecutar la consulta ~0.1s:
# reconectar en cada pregunta era casi todo el tiempo de respuesta. Aqui se
# guarda una conexion viva por fuente. Si se cae, se reabre y se reintenta.
_conexiones: dict[str, object] = {}
_candado_conexiones = threading.Lock()


def soltar_conexion(id_fuente: str) -> None:
    """Cierra y olvida la conexion guardada. Al editar una fuente hay que
    llamarlo, si no seguiriamos usando las credenciales viejas."""
    with _candado_conexiones:
        conexion = _conexiones.pop(id_fuente, None)
    if conexion is not None:
        try:
            conexion.close()
        except Exception:  # noqa: BLE001 - ya la estabamos descartando
            pass


def _con_reintento(id_fuente: str | None, abrir, ejecutar):
    """Ejecuta reusando la conexion; si esta muerta, reabre y reintenta una vez."""
    if id_fuente is None:
        conexion = abrir()
        try:
            return ejecutar(conexion)
        finally:
            try:
                conexion.close()
            except Exception:  # noqa: BLE001
                pass

    with _candado_conexiones:
        conexion = _conexiones.get(id_fuente)

    if conexion is not None:
        try:
            return ejecutar(conexion)
        except Exception:  # noqa: BLE001 - puede ser solo la conexion caida
            soltar_conexion(id_fuente)

    conexion = abrir()
    with _candado_conexiones:
        _conexiones[id_fuente] = conexion
    return ejecutar(conexion)


def consultar_postgres(config: dict, sql: str, limite: int,
                       id_fuente: str | None = None) -> list[dict]:
    import psycopg
    from psycopg.rows import dict_row

    def abrir():
        conexion = psycopg.connect(url_postgres(config), connect_timeout=15,
                                   autocommit=True)
        conexion.read_only = True   # la garantia real, a nivel de transaccion
        return conexion

    def ejecutar(conexion):
        with conexion.cursor(row_factory=dict_row) as cursor:
            cursor.execute(sql)
            return [dict(f) for f in cursor.fetchmany(limite)]

    return _con_reintento(id_fuente, abrir, ejecutar)


def consultar_mssql(config: dict, sql: str, limite: int,
                    id_fuente: str | None = None) -> list[dict]:
    import pymssql

    def abrir():
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
        cursor = conexion.cursor()
        # Evita bloquear al resto de la base mientras leemos.
        cursor.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;")
        cursor.close()
        return conexion

    def ejecutar(conexion):
        with conexion.cursor(as_dict=True) as cursor:
            cursor.execute(sql)
            return [dict(f) for f in cursor.fetchmany(limite)]

    return _con_reintento(id_fuente, abrir, ejecutar)


def consultar_supabase(config: dict, sql: str, limite: int,
                       id_fuente: str | None = None) -> list[dict]:
    # Con cadena directa vamos por Postgres, que es mucho mas rapido.
    if config.get("url"):
        return consultar_postgres({"url": config["url"]}, sql, limite, id_fuente)

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

    return MOTORES[fuente["tipo"]](fuente["config"], sql, limite, id_fuente)


# --------------------------------------------------------------------------
# Busqueda por texto
# --------------------------------------------------------------------------

TIPOS_TEXTO = ("char", "varchar", "nvarchar", "nchar", "text", "ntext", "citext")


def columnas_de_texto(id_fuente: str, tabla: str) -> tuple[str, list[str]]:
    """Nombre real de la tabla y sus columnas de texto, sin distinguir mayusculas."""
    esquema_fuente = esquema_de(id_fuente)
    buscada = tabla.strip().lower()

    for entrada in esquema_fuente["tablas"]:
        if entrada["tabla"].lower() != buscada:
            continue
        columnas = []
        for definicion in entrada["columnas"].split(", "):
            partes = definicion.rsplit(" ", 1)
            if len(partes) == 2 and partes[1].lower() in TIPOS_TEXTO:
                columnas.append(partes[0])
        return entrada["tabla"], columnas

    disponibles = ", ".join(t["tabla"] for t in esquema_fuente["tablas"])
    raise ValueError(f"No existe la tabla '{tabla}'. Las que hay: {disponibles}")


def limpiar_termino(termino: str) -> str:
    """Deja solo lo que puede aparecer en una descripcion o una referencia.

    Las referencias llevan barras, puntos y guiones ('ACV-14/3', '6.0MM'), asi
    que se conservan; lo que se va es todo lo que podria cerrar la cadena SQL.
    """
    return re.sub(r"[^\w\sáéíóúüñÁÉÍÓÚÜÑ./-]", "", termino)[:40]


# Palabras que aparecen en cualquier frase y no distinguen nada.
VACIAS = {
    "de", "la", "el", "los", "las", "un", "una", "unos", "unas", "del", "al",
    "para", "con", "por", "que", "en", "lo", "su", "sus", "es", "hay", "me",
    "te", "se", "y", "o", "tiene", "tienes", "dame", "busca", "buscame",
    "cuanto", "cuesta", "precio", "producto", "productos",
}

# Como se dice frente a como esta escrito. En un catalogo de materiales las
# medidas se guardan en cifras y el usuario las dice en palabras: sin esto,
# "tres cuartos" jamas encuentra 3/4.
EQUIVALENCIAS = [
    ("tres cuartos", "3/4"), ("un cuarto", "1/4"), ("dos cuartos", "1/2"),
    ("tres octavos", "3/8"), ("cinco octavos", "5/8"), ("siete octavos", "7/8"),
    ("un octavo", "1/8"), ("media pulgada", "1/2"), ("medio", "1/2"),
    ("pulgada y media", "1.5"), ("una pulgada", "1"),
    ("milimetros", "mm"), ("milimetro", "mm"), ("pulgadas", ""), ("pulgada", ""),
    ("cero", "0"), ("uno", "1"), ("dos", "2"), ("tres", "3"), ("cuatro", "4"),
    ("cinco", "5"), ("seis", "6"), ("siete", "7"), ("ocho", "8"),
    ("nueve", "9"), ("diez", "10"), ("doce", "12"), ("catorce", "14"),
    ("dieciseis", "16"), ("veinte", "20"),
]


def unir_medidas(frase: str) -> str:
    """Pega el numero a su unidad: '6 milimetros' -> '6.0mm'.

    Separados pierden la relacion y el '6' suelto coincide con '16.0MM' o con
    el calibre '(6)'. El catalogo guarda '6.0MM', asi que se canoniza a eso.
    """
    def canonico(coincidencia: re.Match) -> str:
        numero = coincidencia.group(1)
        return f" {numero}mm " if "." in numero else f" {numero}.0mm "

    return re.sub(r"\b(\d+(?:\.\d+)?)\s*(?:milimetros?|mm)\b", canonico, frase)


def terminos_de(texto: str) -> list[str]:
    """Convierte lo que se dijo en terminos buscables."""
    frase = texto.lower()
    for hablado, escrito in EQUIVALENCIAS:
        frase = re.sub(rf"\b{re.escape(hablado)}\b", f" {escrito} ", frase)
    frase = unir_medidas(frase)

    vistos: list[str] = []
    for palabra in frase.split():
        limpio = limpiar_termino(palabra).strip(".-/")
        if not limpio or limpio in VACIAS or limpio in vistos:
            continue
        # Un solo caracter solo sirve si es una cifra: en un catalogo de
        # materiales los calibres son "6", "8", "4", y perderlos hace que
        # "alambre 6 negro" devuelva el de 4.
        if len(limpio) < 2 and not limpio.isdigit():
            continue
        vistos.append(limpio)
    return vistos


DESCRIPTIVAS = ("descripcion", "description", "nombre", "name", "titulo", "title")


def columna_descriptiva(columnas: list[str]) -> str:
    """La columna donde vive el nombre de la cosa.

    Importa para puntuar: coincidir en la descripcion vale mucho mas que
    coincidir en un codigo. Antes se usaba la primera columna de texto sin
    mirar, que en la tabla de productos es 'Codigo' —un numero— asi que la
    descripcion, que es justo lo que la gente dice al hablar, puntuaba menos.
    """
    for pista in DESCRIPTIVAS:
        for columna in columnas:
            if pista in columna.lower():
                return columna
    return columnas[0]


# Donde la gente escribe como llama a las cosas, mas alla del nombre oficial:
# sinonimos, usos, notas. Es donde vive el lenguaje hablado.
ALTERNATIVAS = ("alterna", "alternativa", "sinonimo", "uso", "comun",
                "observacion", "nota", "comentario", "etiqueta", "tag")

# Identificadores. Coinciden por accidente y gastan cupo de busqueda.
IDENTIFICADORAS = ("codigo", "code", "codbar", "barra", "barcode", "ean", "upc",
                   "sku", "referencia", "ref", "unidad", "und", "um")

# Nombres cortos que serian identificadores pero no contienen ninguna pista
# larga: 'id' esta dentro de demasiadas palabras para buscarlo como fragmento
# ('humedad', 'medida'), asi que van por coincidencia exacta.
IDENTIFICADORAS_EXACTAS = ("id", "pk", "no", "num", "nro")


def ordenar_por_utilidad(columnas: list[str]) -> list[str]:
    """Primero donde vive el lenguaje, al final los codigos.

    El recorte a ocho columnas era por orden de tabla, no por utilidad. En un
    catalogo de productos las ocho primeras se iban en Codigo, Referencia,
    CodBar y Und, y dejaban fuera DescripcionAlterna —justo la columna donde
    estan las palabras que usa la gente: 'cable de goma', 'alambre italiano'.
    Buscar por como se dice no encontraba nada.
    """
    def peso(columna: str) -> int:
        bajo = columna.lower()
        if any(p in bajo for p in DESCRIPTIVAS):
            return 0
        if any(p in bajo for p in ALTERNATIVAS):
            return 1
        if bajo in IDENTIFICADORAS_EXACTAS or any(p in bajo for p in IDENTIFICADORAS):
            return 3
        return 2

    # sorted es estable: dentro de cada grupo se respeta el orden de la tabla.
    return sorted(columnas, key=peso)


def buscar_en_tabla(id_fuente: str, tabla: str, texto: str,
                    limite: int = 8) -> list[dict]:
    """Busca por texto y devuelve las mejores coincidencias primero.

    No exige que aparezcan todas las palabras: puntua cada fila por cuantas
    encuentra y ordena por esa puntuacion. Exigirlas todas era demasiado
    estricto —'letra LB tres cuartos' no encontraba 'LETRA LB IMC 3/4'— y
    exigir una sola devuelve basura. Puntuar da lo mejor de ambas.
    """
    fuente = obtener(id_fuente)
    if fuente is None:
        raise ValueError(f"No existe la fuente '{id_fuente}'.")

    nombre_real, columnas = columnas_de_texto(id_fuente, tabla)
    if not columnas:
        raise ValueError(f"La tabla '{nombre_real}' no tiene columnas de texto.")

    # En tablas enormes el LIKE escanea millones de filas y cuelga la sesion.
    # Cortamos antes y le decimos al modelo que cambie a SQL con filtro.
    n = contar_filas(id_fuente, nombre_real)
    if n is not None and n > UMBRAL_TABLA_GRANDE:
        raise ValueError(
            f"'{nombre_real}' tiene {n:,} filas: demasiadas para buscar por "
            "texto. Usa consultar_fuente con SQL, filtrando con WHERE (por fecha, "
            "codigo o vendedor) y agrupando con SUM/GROUP BY. No la escanees entera."
        )

    terminos = terminos_de(texto)
    if not terminos:
        raise ValueError("Hace falta algo que buscar.")

    # Muchas columnas de texto disparan la consulta sin mejorar el resultado;
    # ordenarlas antes evita gastar el cupo en codigos y perder las utiles.
    columnas = ordenar_por_utilidad(columnas)[:8]
    principal = columna_descriptiva(columnas)

    def patron(columna: str, termino: str) -> str:
        # Un termino que empieza por cifra debe empezar tambien palabra: si no,
        # '6.0mm' coincide dentro de '16.0MM' y da el calibre equivocado.
        if termino[0].isdigit():
            return f"({columna} like '% {termino}%' or {columna} like '{termino}%')"
        return f"{columna} like '%{termino}%'"

    def en_alguna(termino: str) -> str:
        return "(" + " or ".join(patron(c, termino) for c in columnas) + ")"

    # Coincidir en la descripcion vale el triple: el producto que se llama asi
    # gana al que solo lo menciona de pasada en una nota larga.
    puntuacion = " + ".join(
        f"case when {patron(principal, t)} then 3 else 0 end + "
        f"case when {en_alguna(t)} then 1 else 0 end"
        for t in terminos
    )

    donde = " or ".join(en_alguna(t) for t in terminos)

    if fuente["tipo"] == "mssql":
        sql = (f"select top {limite} *, ({puntuacion}) as _relevancia "
               f"from {nombre_real} where {donde} order by _relevancia desc")
    else:
        sql = (f"select *, ({puntuacion}) as _relevancia "
               f"from {nombre_real} where {donde} "
               f"order by _relevancia desc limit {limite}")

    return MOTORES[fuente["tipo"]](fuente["config"], sql, limite, id_fuente)


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


# --------------------------------------------------------------------------
# Salud de las conexiones
# --------------------------------------------------------------------------

VIGENCIA_SALUD = 60   # segundos

_salud: dict | None = None
_salud_en = 0.0
_candado_salud = threading.Lock()


def salud(refrescar: bool = False) -> dict:
    """Estado de todas las fuentes activas, cacheado.

    Sin cache, cada carga de la pagina abriria conexiones a todas las bases.
    """
    global _salud, _salud_en

    ahora = time.monotonic()
    if not refrescar and _salud and ahora - _salud_en < VIGENCIA_SALUD:
        return _salud

    with _candado_salud:
        # Otro hilo pudo refrescarlo mientras esperabamos.
        if not refrescar and _salud and time.monotonic() - _salud_en < VIGENCIA_SALUD:
            return _salud

        detalle = []
        for fuente in activas():
            resultado = probar({"id": fuente["id"], "tipo": fuente["tipo"], "config": {}})
            detalle.append({
                "id": fuente["id"],
                "nombre": fuente["nombre"],
                "tipo": fuente["tipo"],
                "ok": resultado["ok"],
                "mensaje": resultado["mensaje"],
                "latencia_ms": resultado.get("latencia_ms"),
                "tablas": resultado.get("tablas"),
            })

        _salud = {
            "fuentes": detalle,
            "total": len(detalle),
            "conectadas": sum(1 for f in detalle if f["ok"]),
            "todas_ok": bool(detalle) and all(f["ok"] for f in detalle),
        }
        _salud_en = time.monotonic()

    return _salud


def mantener_vivas() -> None:
    """Consulta trivial a cada fuente activa para que la conexion no muera.

    Sin esto, la primera pregunta despues de un rato paga el reconectar entero
    —casi un segundo contra SQL Server— y hablando eso se nota. El servidor de
    la base tambien cierra las conexiones ociosas por su cuenta.
    """
    for fuente in activas():
        try:
            consultar(fuente["id"], "select 1 as vivo", limite=1)
        except Exception:  # noqa: BLE001 - si falla, la proxima reconecta
            soltar_conexion(fuente["id"])


def vigilar_conexiones(cada_segundos: int = 120) -> None:
    """Hilo de fondo que mantiene las conexiones calientes."""
    def bucle():
        while True:
            time.sleep(cada_segundos)
            try:
                mantener_vivas()
            except Exception:  # noqa: BLE001 - nunca debe matar el hilo
                pass

    threading.Thread(target=bucle, daemon=True).start()


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


# El esquema de una fuente no cambia entre preguntas, pero leerlo cuesta un
# viaje entero a la base. Se cachea en memoria y se tira al editar la fuente.
_esquemas: dict[str, dict] = {}

# Numero de filas por tabla (fuente, tabla) -> filas. Se llena a demanda y se
# usa para no escanear por texto tablas enormes y para avisar su tamano en el
# prompt.
_conteos: dict[tuple[str, str], int] = {}

# A partir de aqui una tabla es demasiado grande para buscar por texto (LIKE
# escanea todo). Encima de esto hay que consultar con SQL: filtro y agregacion.
UMBRAL_TABLA_GRANDE = 50000


def olvidar_esquema(id_fuente: str) -> None:
    _esquemas.pop(id_fuente, None)
    for clave in [k for k in _conteos if k[0] == id_fuente]:
        _conteos.pop(clave, None)


def contar_filas(id_fuente: str, tabla: str) -> int | None:
    """Filas de una tabla, cacheado. None si no se pudo contar.

    COUNT(*) usa el indice y es rapido incluso con millones de filas; lo
    guardamos para no repetirlo en cada pregunta.
    """
    clave = (id_fuente, tabla)
    if clave in _conteos:
        return _conteos[clave]
    fuente = obtener(id_fuente)
    if fuente is None:
        return None

    n = None
    try:
        if fuente["tipo"] == "mssql":
            # Metadata del indice: instantaneo, NO escanea (clave con millones de
            # filas). Las vistas no tienen filas aqui: caen al COUNT de abajo.
            filas = MOTORES["mssql"](
                fuente["config"],
                "SELECT SUM(p.rows) AS n FROM sys.partitions p "
                f"WHERE p.object_id = OBJECT_ID('{tabla}') AND p.index_id IN (0, 1)",
                1, id_fuente,
            )
            crudo = filas[0].get("n") if filas else None
            n = int(crudo) if crudo is not None else None
        if n is None:
            filas = MOTORES[fuente["tipo"]](
                fuente["config"], f"SELECT COUNT(*) AS n FROM {tabla}", 1, id_fuente
            )
            n = int(next(iter(filas[0].values()))) if filas else 0
    except Exception:  # noqa: BLE001 - si no se puede contar, seguimos sin el dato
        return None

    _conteos[clave] = n
    return n


def guardar_config_tablas(id_fuente: str, config_tablas: dict) -> dict:
    """Activa/desactiva tablas y guarda su leyenda, sin tocar el resto.

    La leyenda es una pista en lenguaje natural (p. ej. "saldos y deudas de
    clientes") que va al prompt para que el modelo sepa en que tabla buscar.
    Las desactivadas no aparecen en el prompt.
    """
    limpio = {}
    for nombre, cfg in (config_tablas or {}).items():
        cfg = cfg or {}
        limpio[str(nombre)] = {
            "activa": bool(cfg.get("activa", True)),
            "leyenda": (cfg.get("leyenda") or "").strip(),
        }

    with _candado:
        guardadas = _leer()
        fuente = next((f for f in guardadas if f["id"] == id_fuente), None)
        if fuente is None:
            raise ValueError(f"No existe la fuente '{id_fuente}'.")
        fuente["tablas"] = limpio
        _escribir(guardadas)

    return {"ok": True, "tablas": limpio}


def esquema_con_estado(id_fuente: str) -> dict:
    """El esquema de la fuente, con el estado (activa/leyenda) de cada tabla.

    Es lo que consume el panel de tablas: combina el esquema real de la base
    con la config que guardo el usuario, sin ensuciar el cache de esquema_de.
    """
    esq = esquema_de(id_fuente)
    config_tablas = (obtener(id_fuente) or {}).get("tablas", {})
    tablas = []
    for t in esq["tablas"]:
        cfg = config_tablas.get(t["tabla"], {})
        tablas.append({
            "tabla": t["tabla"],
            "columnas": t["columnas"],
            "activa": bool(cfg.get("activa", True)),
            "leyenda": cfg.get("leyenda", ""),
            "filas": contar_filas(id_fuente, t["tabla"]),
        })
    return {"fuente": esq["fuente"], "tipo": esq["tipo"], "tablas": tablas}


def esquema_de(id_fuente: str, refrescar: bool = False) -> dict:
    """Tablas y columnas de una fuente, agrupadas."""
    if not refrescar and id_fuente in _esquemas:
        return _esquemas[id_fuente]

    fuente = obtener(id_fuente)
    if fuente is None:
        raise ValueError(f"No existe la fuente '{id_fuente}'.")

    filas = MOTORES[fuente["tipo"]](
        fuente["config"], SQL_COLUMNAS[fuente["tipo"]], 5000, id_fuente
    )

    tablas: dict[str, list[str]] = {}
    for fila in filas:
        nombre = fila["tabla"] if fila["esquema"] in ("public", "dbo") \
            else f"{fila['esquema']}.{fila['tabla']}"
        tablas.setdefault(nombre, []).append(f"{fila['columna']} {fila['tipo']}")

    resultado = {
        "fuente": fuente["nombre"],
        "tipo": fuente["tipo"],
        "tablas": [
            {"tabla": nombre, "columnas": ", ".join(columnas)}
            for nombre, columnas in tablas.items()
        ],
    }
    _esquemas[id_fuente] = resultado
    return resultado


# Cuanto esquema cabe en el prompt antes de que pese mas de lo que ayuda.
TOPE_ESQUEMA_EN_PROMPT = 6000


def resumen_para_prompt() -> str:
    """Fuentes y sus columnas, para que Jarvis no gaste un viaje preguntandolas.

    Incluir el esquema aqui ahorra la llamada a `ver_esquema_fuente` en cada
    pregunta, que era un viaje completo al modelo y a la base. Si una fuente es
    demasiado grande solo van los nombres de tabla y el modelo pide el detalle.
    """
    lista = activas()
    if not lista:
        return ""

    bloques = []
    for fuente in lista:
        etiqueta = CATALOGO_TIPOS[fuente["tipo"]]["etiqueta"]
        permiso = "solo lectura" if fuente.get("solo_lectura", True) else "lectura y escritura"
        nota = f" — {fuente['notas']}" if fuente.get("notas") else ""
        cabecera = f'- id "{fuente["id"]}": {fuente["nombre"]} ({etiqueta}, {permiso}){nota}'

        # La base principal ya va documentada aparte, con su catalogo.
        if fuente["tipo"] == "supabase" and not fuente.get("notas", "").strip():
            bloques.append(cabecera)
            continue

        try:
            esquema_fuente = esquema_de(fuente["id"])
        except Exception:  # noqa: BLE001 - sin esquema seguimos, solo mas lento
            bloques.append(cabecera)
            continue

        # Solo las tablas activas van al prompt, con su leyenda como pista de
        # cuando usarlas. La leyenda la pone el usuario en el panel de tablas.
        config_tablas = fuente.get("tablas", {})
        tablas_activas = [
            t for t in esquema_fuente["tablas"]
            if config_tablas.get(t["tabla"], {}).get("activa", True)
        ]

        def con_leyenda(nombre: str, cfg=config_tablas, fid=fuente["id"]) -> str:
            ley = cfg.get(nombre, {}).get("leyenda", "")
            n = contar_filas(fid, nombre)
            partes = [nombre]
            if n and n > UMBRAL_TABLA_GRANDE:
                partes.append(f"[{n:,} filas: NO buscar por texto, consulta con SQL agregado y filtro de fecha]")
            elif n and n > 10000:
                partes.append(f"[{n:,} filas]")
            if ley:
                partes.append(f"({ley})")
            return " ".join(partes)

        detalle = "\n".join(
            f"    {con_leyenda(t['tabla'])}: {t['columnas']}" for t in tablas_activas
        )
        if len(detalle) > TOPE_ESQUEMA_EN_PROMPT:
            detalle = "    tablas: " + ", ".join(
                con_leyenda(t["tabla"]) for t in tablas_activas
            ) + "\n    (usa ver_esquema_fuente para las columnas)"

        bloques.append(f"{cabecera}\n{detalle}")

    return "\n".join(bloques)
