"""Conexion SQLite compartida para cuentas, organizaciones y dispositivos.

Todo lo demas en el proyecto vive en JSON plano bajo data/ (fuentes.json,
esquema.json...), pero aqui hay relaciones reales -organizacion -> usuarios ->
dispositivos- y una restriccion real (email unico), asi que conviene una base
de datos de verdad en vez de otro catalogo plano. sqlite3 es de la libreria
estandar: no agrega dependencias.
"""

import sqlite3
import threading
from contextlib import contextmanager

from . import rutas

# Bases a las que ya se les aplico el esquema en este proceso. Sin esto, cada
# conexion volvia a correr el script entero: son ocho sentencias por cada
# respuesta anotada, y se notaba.
_preparadas: set[str] = set()
_candado = threading.Lock()


_ESQUEMA = """
    CREATE TABLE IF NOT EXISTS organizaciones (
        id TEXT PRIMARY KEY,
        nombre TEXT NOT NULL,
        creada TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS usuarios (
        id TEXT PRIMARY KEY,
        organizacion_id TEXT NOT NULL REFERENCES organizaciones(id),
        nombre TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        es_admin_org INTEGER NOT NULL DEFAULT 0,
        creado TEXT NOT NULL
    );

    -- usuario_id no lleva llave foranea: el dueno de un dispositivo puede ser
    -- una cuenta de organizacion (tabla usuarios) o una persona de
    -- JARVIS_PASSWORD_<NOMBRE> / un panel de Supabase, que no viven aqui.
    CREATE TABLE IF NOT EXISTS dispositivos (
        id TEXT PRIMARY KEY,
        usuario_id TEXT NOT NULL,
        nombre TEXT NOT NULL,
        token_hash TEXT NOT NULL UNIQUE,
        creado TEXT NOT NULL,
        ultimo_uso TEXT
    );

    CREATE TABLE IF NOT EXISTS codigos_vinculo (
        codigo TEXT PRIMARY KEY,
        usuario_id TEXT NOT NULL,
        expira TEXT NOT NULL
    );

    -- El gasto, que antes vivia en consumo.jsonl. Aqui porque de esto sale la
    -- factura: un archivo plano en un disco efimero no es base para cobrar.
    CREATE TABLE IF NOT EXISTS consumo (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cuando TEXT NOT NULL,
        modo TEXT NOT NULL,
        modelo TEXT NOT NULL,
        usuario_id TEXT,
        organizacion_id TEXT,
        dispositivo TEXT,
        entrada_texto INTEGER NOT NULL DEFAULT 0,
        entrada_audio INTEGER NOT NULL DEFAULT 0,
        entrada_imagen INTEGER NOT NULL DEFAULT 0,
        cache_texto INTEGER NOT NULL DEFAULT 0,
        cache_audio INTEGER NOT NULL DEFAULT 0,
        cache_imagen INTEGER NOT NULL DEFAULT 0,
        salida_texto INTEGER NOT NULL DEFAULT 0,
        salida_audio INTEGER NOT NULL DEFAULT 0,
        tokens INTEGER NOT NULL DEFAULT 0,
        segundos REAL,
        costo REAL NOT NULL DEFAULT 0
    );

    CREATE INDEX IF NOT EXISTS idx_consumo_organizacion
        ON consumo (organizacion_id, cuando);

    -- Cobro en agentia (creditos.py). Hasta donde ya se miro el consumo, lo
    -- que cada persona debe y todavia no llega a un centavo, y cada envio con
    -- su referencia: se anota antes de mandarlo, asi un reintento no cobra
    -- dos veces.
    CREATE TABLE IF NOT EXISTS creditos_estado (
        clave TEXT PRIMARY KEY,
        valor TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS creditos_pendientes (
        organizacion_id TEXT NOT NULL,
        usuario_id TEXT NOT NULL,
        pendiente REAL NOT NULL DEFAULT 0,
        PRIMARY KEY (organizacion_id, usuario_id)
    );

    CREATE TABLE IF NOT EXISTS creditos_envios (
        referencia TEXT PRIMARY KEY,
        cliente_id INTEGER NOT NULL,
        organizacion_id TEXT NOT NULL,
        usuario_id TEXT NOT NULL,
        monto REAL NOT NULL,
        nota TEXT,
        creado TEXT NOT NULL,
        enviado TEXT,
        ultimo_error TEXT
    );

    -- El asistente de cada organizacion: su nombre y su foto. Sin fila, o con
    -- nombre NULL, se usa JARVIS_NOMBRE. Ver asistente.py.
    CREATE TABLE IF NOT EXISTS asistentes (
        organizacion_id TEXT PRIMARY KEY REFERENCES organizaciones(id) ON DELETE CASCADE,
        nombre TEXT,
        foto TEXT,
        actualizado TEXT NOT NULL
    );

    -- Los tres videos del avatar. `archivo` es el que se muestra; `trabajo_*`
    -- el que se esta generando en Higgsfield (el viejo sigue a la vista hasta
    -- que el nuevo termina bien).
    CREATE TABLE IF NOT EXISTS asistente_videos (
        organizacion_id TEXT NOT NULL REFERENCES organizaciones(id) ON DELETE CASCADE,
        estado TEXT NOT NULL CHECK (estado IN ('reposo', 'escuchando', 'hablando')),
        archivo TEXT,
        trabajo_id TEXT,
        trabajo_estado TEXT CHECK (trabajo_estado IN ('generando', 'listo', 'error')),
        trabajo_desde TEXT,
        error TEXT,
        actualizado TEXT NOT NULL,
        PRIMARY KEY (organizacion_id, estado)
    );

    -- Accesos directos: preguntas frecuentes con su consulta lista, por fuente.
    -- fuente_id apunta a fuentes.json (no a una tabla). Ver accesos.py.
    CREATE TABLE IF NOT EXISTS accesos_directos (
        id TEXT PRIMARY KEY,
        fuente_id TEXT NOT NULL,
        pregunta TEXT NOT NULL,
        descripcion TEXT NOT NULL,
        sql TEXT NOT NULL,
        parametros TEXT NOT NULL,
        activo INTEGER NOT NULL DEFAULT 1,
        ultimo_error TEXT,
        creado TEXT NOT NULL,
        actualizado TEXT NOT NULL
    );

    -- La mesa de cotizaciones de cada persona (original + variantes sin
    -- emitir), en JSON. Aqui y no en memoria: cada despliegue reinicia Jarvis
    -- y se perdia lo que alguien estaba armando. Ver mesa.py.
    CREATE TABLE IF NOT EXISTS mesas_cotizacion (
        usuario_id TEXT PRIMARY KEY,
        datos TEXT NOT NULL,
        actualizado REAL NOT NULL
    );

    -- Apps que cada persona conecta (hoy solo Gmail). `token` es el refresh
    -- token cifrado con secretos.cifrar; `cursor`, el ultimo historyId de Gmail
    -- ya revisado. Ver integraciones.py.
    CREATE TABLE IF NOT EXISTS integraciones (
        usuario_id TEXT NOT NULL,
        app TEXT NOT NULL,
        cuenta TEXT,
        token TEXT,
        cursor TEXT,
        estado TEXT NOT NULL CHECK (estado IN ('conectado', 'desconectado')),
        error TEXT,
        conectado TEXT NOT NULL,
        PRIMARY KEY (usuario_id, app)
    );

    -- Que correos le importan a cada persona (texto libre para la IA) y a que
    -- WhatsApp avisarle. Ver avisos.py.
    CREATE TABLE IF NOT EXISTS reglas_aviso (
        usuario_id TEXT PRIMARY KEY,
        reglas TEXT NOT NULL DEFAULT '',
        whatsapp TEXT,
        activo INTEGER NOT NULL DEFAULT 1
    );

    -- Los avisos de la campanita. UNIQUE evita avisar dos veces del mismo correo.
    CREATE TABLE IF NOT EXISTS avisos (
        id TEXT PRIMARY KEY,
        usuario_id TEXT NOT NULL,
        app TEXT NOT NULL,
        ref TEXT NOT NULL,
        hilo TEXT,
        remitente TEXT,
        asunto TEXT,
        resumen TEXT,
        tipo TEXT NOT NULL DEFAULT 'correo',
        creado TEXT NOT NULL,
        visto INTEGER NOT NULL DEFAULT 0,
        whatsapp TEXT NOT NULL DEFAULT 'no_aplica',
        enviado TEXT,
        intentos INTEGER NOT NULL DEFAULT 0,
        UNIQUE (usuario_id, app, ref)
    );

    CREATE INDEX IF NOT EXISTS idx_avisos_usuario ON avisos (usuario_id, visto, creado);

    -- Correos que el revisor ya resolvio (o lleva intentando), para no volver
    -- a pagar la IA por el mismo correo si el cursor no avanzo.
    CREATE TABLE IF NOT EXISTS correos_vistos (
        usuario_id TEXT NOT NULL,
        ref TEXT NOT NULL,
        intentos INTEGER NOT NULL DEFAULT 0,
        resuelto INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (usuario_id, ref)
    );
"""


def archivo():
    return rutas.archivo("jarvis.db")


@contextmanager
def conexion():
    """Una conexion lista para usar, con las tablas ya creadas.

    Se asegura el esquema en cada apertura (CREATE TABLE IF NOT EXISTS es
    barato) en vez de depender de que alguien haya llamado a crear_tablas() en
    el arranque: el TestClient de las pruebas no dispara el evento de
    arranque salvo que se use como context manager, y este modulo no puede
    asumir que ya paso por ahi.
    """
    ruta = archivo()
    con = sqlite3.connect(ruta, timeout=10)
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA foreign_keys=ON;")
    con.row_factory = sqlite3.Row

    with _candado:
        if str(ruta) not in _preparadas:
            con.executescript(_ESQUEMA)
            con.commit()
            _preparadas.add(str(ruta))

    try:
        yield con
        con.commit()
    finally:
        con.close()


def crear_tablas() -> None:
    """Se llama al arrancar el servidor de verdad, para que el primer pedido
    no pague el costo de crear el esquema."""
    with conexion():
        pass
