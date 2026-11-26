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

    -- WhatsApp por Zernio (ver whatsapp_chats.py). El perfil de Zernio de cada
    -- persona (uno por numero, lo exige Zernio) y la cuenta conectada en el.
    CREATE TABLE IF NOT EXISTS zernio_cuentas (
        usuario_id TEXT PRIMARY KEY,
        perfil_id TEXT NOT NULL,
        cuenta_id TEXT,
        actualizado TEXT NOT NULL
    );

    CREATE UNIQUE INDEX IF NOT EXISTS idx_zernio_cuenta ON zernio_cuentas (cuenta_id);

    -- Eventos de webhook ya procesados: Zernio entrega "al menos una vez".
    CREATE TABLE IF NOT EXISTS zernio_eventos (
        id TEXT PRIMARY KEY,
        recibido TEXT NOT NULL
    );

    -- Mensajes entrantes esperando a que su chat se calme para clasificarlos.
    -- Se borran al clasificarlos: Jarvis no guarda copia de los chats.
    CREATE TABLE IF NOT EXISTS whatsapp_pendientes (
        usuario_id TEXT NOT NULL,
        conversacion TEXT NOT NULL,
        mensaje_id TEXT NOT NULL,
        remitente TEXT,
        telefono TEXT,
        texto TEXT,
        recibido TEXT NOT NULL,
        PRIMARY KEY (usuario_id, mensaje_id)
    );

    -- WhatsApp por Evolution (ver evolution_wa.py): la instancia de cada persona
    -- y el secreto que lleva su webhook (?clave=), que dice de quien es cada evento.
    CREATE TABLE IF NOT EXISTS evolution_instancias (
        usuario_id TEXT PRIMARY KEY,
        instancia TEXT NOT NULL UNIQUE,
        clave TEXT NOT NULL UNIQUE,
        numero TEXT,
        actualizado TEXT NOT NULL
    );

    -- Outlook por Zernio (ver outlook.py): la cuenta de Microsoft de cada
    -- persona, en el mismo perfil de Zernio que su WhatsApp. El accountId va en
    -- claro: sin la clave de Zernio no sirve, y hace falta para saber de quien
    -- es un webhook.
    CREATE TABLE IF NOT EXISTS outlook_cuentas (
        usuario_id TEXT PRIMARY KEY,
        cuenta_id TEXT NOT NULL UNIQUE,
        actualizado TEXT NOT NULL
    );

    -- Quien dio permiso al calendario de Google al conectar Gmail (la casilla
    -- es opcional). Ver google_calendario.py.
    CREATE TABLE IF NOT EXISTS google_calendario (
        usuario_id TEXT PRIMARY KEY,
        concedido TEXT NOT NULL
    );

    -- Horario laboral para los huecos libres (ver calendario.py). Sin fila =
    -- lunes a viernes de 8 a 6 en Santo Domingo. dias: 1 = lunes ... 7 = domingo.
    CREATE TABLE IF NOT EXISTS horario_laboral (
        usuario_id TEXT PRIMARY KEY,
        inicio TEXT NOT NULL,
        fin TEXT NOT NULL,
        dias TEXT NOT NULL,
        zona TEXT NOT NULL
    );

    -- Reuniones de Meet que graba el bot (docs/superpowers/specs/2026-11-24-bot-grabacion-meet-design.md).
    CREATE TABLE IF NOT EXISTS reuniones (
        id TEXT PRIMARY KEY,
        clave TEXT NOT NULL UNIQUE,
        meet_url TEXT NOT NULL,
        titulo TEXT NOT NULL,
        inicio TEXT NOT NULL,
        fin TEXT NOT NULL,
        estado TEXT NOT NULL,
        motivo TEXT,
        token_hash TEXT,
        linea TEXT,
        transcripcion TEXT,
        resumen TEXT,
        puntos TEXT,
        tareas TEXT,
        duracion_s INTEGER,
        terminada TEXT,
        incompleta INTEGER NOT NULL DEFAULT 0,
        audio_borrado INTEGER NOT NULL DEFAULT 0,
        creada TEXT NOT NULL,
        grabando_desde TEXT,
        tipo TEXT,
        nombres TEXT,
        sala TEXT
    );

    CREATE TABLE IF NOT EXISTS reunion_interesados (
        reunion_id TEXT NOT NULL REFERENCES reuniones (id) ON DELETE CASCADE,
        usuario_id TEXT NOT NULL,
        quiere INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (reunion_id, usuario_id)
    );

    CREATE TABLE IF NOT EXISTS reunion_pedazos (
        reunion_id TEXT NOT NULL REFERENCES reuniones (id) ON DELETE CASCADE,
        n INTEGER NOT NULL,
        estado TEXT NOT NULL,
        intentos INTEGER NOT NULL DEFAULT 0,
        segmentos TEXT,
        formato TEXT,
        inicio_s INTEGER,
        PRIMARY KEY (reunion_id, n)
    );

    -- Sala de una presencial (salas.py): quién entró con su teléfono y cuánto oyó
    -- su micrófono en cada segundo (para saber quién habla). Los niveles se borran
    -- al cerrar la reunión.
    CREATE TABLE IF NOT EXISTS reunion_participantes (
        id TEXT PRIMARY KEY,
        reunion_id TEXT NOT NULL REFERENCES reuniones (id) ON DELETE CASCADE,
        nombre TEXT NOT NULL,
        usuario_id TEXT,
        token_hash TEXT NOT NULL,
        unido TEXT NOT NULL,
        visto TEXT
    );

    CREATE TABLE IF NOT EXISTS reunion_niveles (
        reunion_id TEXT NOT NULL,
        participante_id TEXT NOT NULL,
        segundo INTEGER NOT NULL,
        nivel REAL NOT NULL,
        PRIMARY KEY (reunion_id, participante_id, segundo)
    );

    CREATE TABLE IF NOT EXISTS reuniones_preferencias (
        usuario_id TEXT PRIMARY KEY,
        grabar_siempre INTEGER NOT NULL DEFAULT 0
    );
"""


# Columnas que llegaron después de crear su tabla: CREATE TABLE IF NOT EXISTS no
# las agrega a una base que ya existía, así que se agregan aquí una sola vez.
_COLUMNAS_NUEVAS = (
    ("reuniones", "grabando_desde", "TEXT"),   # cuándo entró el bot (para "lleva 12 min")
    ("reuniones", "tipo", "TEXT"),             # NULL = Meet; 'presencial'
    ("reuniones", "nombres", "TEXT"),          # JSON {"Hablante 1": "Jorge"} (IA + persona)
    ("reunion_pedazos", "formato", "TEXT"),    # ogg / webm / mp4 (NULL = ogg, el del bot)
    ("reunion_pedazos", "inicio_s", "INTEGER"),  # segundo de la reunión en que empieza
    ("reuniones", "sala", "TEXT"),             # código de la sala de una presencial (salas.py)
)


def _agregar_columnas(con) -> None:
    for tabla, columna, tipo in _COLUMNAS_NUEVAS:
        existentes = {f[1] for f in con.execute(f"PRAGMA table_info({tabla})")}
        if existentes and columna not in existentes:
            con.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {tipo}")


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
            _agregar_columnas(con)
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
