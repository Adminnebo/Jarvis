"""Aislamiento de las pruebas.

Cada prueba corre contra una carpeta de datos vacia y sin ninguna variable
JARVIS_ heredada de la maquina. Sin esto, la contrasena real del desarrollador
se colaria en las pruebas de acceso y los resultados cambiarian segun quien las
corra.
"""

import os

import pytest


@pytest.fixture(autouse=True)
def entorno_limpio(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))
    for nombre in list(os.environ):
        if nombre.startswith("JARVIS_PASSWORD"):
            monkeypatch.delenv(nombre, raising=False)
    for nombre in ("JARVIS_CLAVE_SECRETA", "JARVIS_USUARIO"):
        monkeypatch.delenv(nombre, raising=False)
    return tmp_path
