"""Memoria persistente de Jarvis.

Dos cosas viven aqui:
  - hechos: cosas que Jarvis debe recordar para siempre (guardadas en JSON)
  - conversacion: el historial de mensajes de la sesion actual

Se guarda en archivos planos a proposito: es facil de inspeccionar, de
respaldar y de editar a mano cuando Jarvis recuerde algo mal.
"""

import json
import uuid
from datetime import datetime
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
DATA.mkdir(exist_ok=True)

ARCHIVO_HECHOS = DATA / "hechos.json"
ARCHIVO_CONVERSACION = DATA / "conversacion.json"


def _leer(archivo: Path, por_defecto):
    if not archivo.exists():
        return por_defecto
    try:
        return json.loads(archivo.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return por_defecto


def _escribir(archivo: Path, datos):
    archivo.write_text(
        json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# --------------------------------------------------------------------------
# Hechos
# --------------------------------------------------------------------------

def todos_los_hechos() -> list[dict]:
    return _leer(ARCHIVO_HECHOS, [])


def recordar(contenido: str, categoria: str = "general") -> dict:
    """Guarda un hecho nuevo. Si ya existe uno casi identico, no lo duplica."""
    hechos = todos_los_hechos()

    normalizado = contenido.strip().lower()
    for hecho in hechos:
        if hecho["contenido"].strip().lower() == normalizado:
            return hecho

    hecho = {
        "id": uuid.uuid4().hex[:8],
        "contenido": contenido.strip(),
        "categoria": categoria,
        "creado": datetime.now().isoformat(timespec="seconds"),
    }
    hechos.append(hecho)
    _escribir(ARCHIVO_HECHOS, hechos)
    return hecho


def olvidar(id_hecho: str) -> bool:
    hechos = todos_los_hechos()
    quedan = [h for h in hechos if h["id"] != id_hecho]
    if len(quedan) == len(hechos):
        return False
    _escribir(ARCHIVO_HECHOS, quedan)
    return True


def buscar(consulta: str, limite: int = 10) -> list[dict]:
    """Busqueda por palabras. Suficiente para cientos de hechos.

    Si algun dia esto crece a miles, aqui es donde entra un embedding.
    """
    palabras = [p for p in consulta.lower().split() if len(p) > 2]
    if not palabras:
        return todos_los_hechos()[:limite]

    puntuados = []
    for hecho in todos_los_hechos():
        texto = f"{hecho['contenido']} {hecho['categoria']}".lower()
        puntos = sum(1 for p in palabras if p in texto)
        if puntos:
            puntuados.append((puntos, hecho))

    puntuados.sort(key=lambda par: par[0], reverse=True)
    return [hecho for _, hecho in puntuados[:limite]]


def resumen_para_prompt(maximo: int = 60) -> str:
    """Los hechos formateados para inyectarlos en el system prompt."""
    hechos = todos_los_hechos()[-maximo:]
    if not hechos:
        return "(Todavia no recuerdas nada sobre el usuario.)"

    por_categoria: dict[str, list[str]] = {}
    for hecho in hechos:
        por_categoria.setdefault(hecho["categoria"], []).append(hecho["contenido"])

    lineas = []
    for categoria, contenidos in por_categoria.items():
        lineas.append(f"[{categoria}]")
        lineas.extend(f"  - {c}" for c in contenidos)
    return "\n".join(lineas)


# --------------------------------------------------------------------------
# Conversacion
# --------------------------------------------------------------------------

def cargar_conversacion() -> list[dict]:
    return _leer(ARCHIVO_CONVERSACION, [])


def guardar_conversacion(mensajes: list[dict], maximo: int = 40) -> None:
    """Guarda solo los ultimos mensajes para que el archivo no crezca sin fin."""
    _escribir(ARCHIVO_CONVERSACION, mensajes[-maximo:])


def borrar_conversacion() -> None:
    _escribir(ARCHIVO_CONVERSACION, [])
