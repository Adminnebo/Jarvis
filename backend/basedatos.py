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
        creada TEXT NOT NULL,
        -- Lo que se le cobra sobre el costo real de OpenAI. 1.0 es al costo.
        markup REAL NOT NULL DEFAULT 1.0
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
