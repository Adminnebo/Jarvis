"""Que version esta corriendo.

Sirve para responder de un vistazo la pregunta mas molesta despues de cada
despliegue: "¿estoy viendo el codigo nuevo o el navegador me guarda el viejo?"
"""

import hashlib
import os
import subprocess
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

# Se calcula una vez al arrancar: dentro de un mismo proceso no cambia.
_version: str | None = None
_arranque = datetime.now()


def _de_railway() -> str:
    return os.getenv("RAILWAY_GIT_COMMIT_SHA", "").strip()


def _de_git() -> str:
    """El commit actual. En el servidor puede no existir .git."""
    try:
        resultado = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=RAIZ, capture_output=True, text=True, timeout=5,
        )
        return resultado.stdout.strip() if resultado.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _de_los_archivos() -> str:
    """Ultimo recurso: huella del contenido del codigo."""
    huella = hashlib.sha256()
    for carpeta in ("backend", "web"):
        ruta = RAIZ / carpeta
        if not ruta.is_dir():
            continue
        for archivo in sorted(ruta.rglob("*")):
            if archivo.is_file() and archivo.suffix in (".py", ".js", ".css", ".html"):
                huella.update(archivo.name.encode())
                huella.update(str(archivo.stat().st_mtime_ns).encode())
    return huella.hexdigest()


def actual() -> str:
    global _version
    if _version is None:
        _version = _de_railway() or _de_git() or _de_los_archivos()
    return _version


def info() -> dict:
    completa = actual()
    return {
        "version": completa[:7],
        "completa": completa,
        "arrancado": _arranque.isoformat(timespec="seconds"),
    }
