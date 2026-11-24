"""Cada prueba corre sin variables BOT_MEET_ de la máquina."""
import os

import pytest


@pytest.fixture(autouse=True)
def entorno_limpio(monkeypatch):
    for nombre in list(os.environ):
        if nombre.startswith("BOT_MEET_"):
            monkeypatch.delenv(nombre, raising=False)
