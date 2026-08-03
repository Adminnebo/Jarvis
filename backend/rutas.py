"""Donde vive lo que Jarvis guarda.

En local es la carpeta data/ del proyecto. En un servidor conviene apuntarla a
un volumen persistente con JARVIS_DATA_DIR: el disco de Railway se borra en
cada despliegue, y con el se irian tus recuerdos, el cache del esquema y —lo
mas molesto— la clave que descifra las credenciales de tus fuentes.
"""

import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def datos() -> Path:
    configurada = os.getenv("JARVIS_DATA_DIR", "").strip()
    carpeta = Path(configurada) if configurada else RAIZ / "data"
    carpeta.mkdir(parents=True, exist_ok=True)
    return carpeta


def archivo(nombre: str) -> Path:
    return datos() / nombre


def hospedado() -> bool:
    """True si esto corre en un servidor y no en la maquina de casa.

    Sirve para no dejar abierto en internet algo pensado para localhost.
    """
    señales = (
        "RAILWAY_ENVIRONMENT", "RAILWAY_PROJECT_ID", "RAILWAY_SERVICE_ID",
        "RENDER", "FLY_APP_NAME", "DYNO", "KUBERNETES_SERVICE_HOST",
        "WEBSITE_INSTANCE_ID", "GOOGLE_CLOUD_PROJECT",
    )
    return any(os.getenv(nombre) for nombre in señales)
