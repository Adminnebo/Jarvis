"""Voces de una reunión presencial: que «Hablante 2» siga siendo la misma persona
de un pedazo de 5 min al siguiente.

El modelo separa voces dentro de cada pedazo (A, B, ...) pero no entre pedazos. Del
pedazo en que aparece cada voz se recorta su tramo más largo (2-10 s) y en los
pedazos siguientes se le pasa al modelo como voz conocida con su nombre «Hablante N»
(hasta 4, el límite del modelo). Los recortes viven junto a los pedazos locales y se
borran con ellos al cerrar la reunión.
"""

import base64
import json
import re
import subprocess
from pathlib import Path

from . import rutas

MAX_VOCES = 4
MIN_S, MAX_S = 2.0, 10.0
ETIQUETA = re.compile(r"^Hablante \d+$")


def carpeta(reunion_id: str) -> Path:
    c = Path(rutas.archivo(f"reuniones/{reunion_id}/voces"))
    c.mkdir(parents=True, exist_ok=True)
    return c


def _estado(reunion_id: str) -> dict:
    f = carpeta(reunion_id) / "voces.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"nombres": []}


def _guardar(reunion_id: str, estado: dict) -> None:
    (carpeta(reunion_id) / "voces.json").write_text(json.dumps(estado, ensure_ascii=False), encoding="utf-8")


def cargar(reunion_id: str) -> list[tuple[str, Path]]:
    """[(«Hablante N», recorte.wav)] de las voces con recorte, en orden."""
    c = carpeta(reunion_id)
    salida = [(n, c / f"{n}.wav") for n in _estado(reunion_id)["nombres"] if (c / f"{n}.wav").exists()]
    return salida[:MAX_VOCES]


def recortar(origen: Path, inicio: float, fin: float, destino: Path) -> bool:
    try:
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{inicio:.2f}", "-t", f"{fin - inicio:.2f}",
                            "-i", str(origen), "-ac", "1", "-ar", "16000", str(destino)],
                           capture_output=True, timeout=60)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0 and destino.exists() and destino.stat().st_size > 0


def data_url(ruta: Path) -> str:
    return "data:audio/wav;base64," + base64.b64encode(Path(ruta).read_bytes()).decode()


def _mejor_tramo(segmentos: list[dict]) -> tuple[float, float] | None:
    largo = max(segmentos, key=lambda s: s["fin"] - s["inicio"], default=None)
    if largo is None or largo["fin"] - largo["inicio"] < MIN_S:
        return None
    return largo["inicio"], min(largo["fin"], largo["inicio"] + MAX_S)


def unificar(reunion_id: str, ruta_audio: Path, segmentos: list[dict]) -> list[dict]:
    """Cambia las letras del modelo por «Hablante N» (las conocidas ya vienen con su
    nombre) y guarda el recorte de las voces nuevas mientras haya lugar."""
    estado = _estado(reunion_id)
    nuevas: dict[str, str] = {}
    for s in segmentos:
        h = s["hablante"]
        if not ETIQUETA.match(h) and h not in nuevas:
            estado["nombres"].append(f"Hablante {len(estado['nombres']) + 1}")
            nuevas[h] = estado["nombres"][-1]
    _guardar(reunion_id, estado)
    salida = [{**s, "hablante": nuevas.get(s["hablante"], s["hablante"])} for s in segmentos]
    con_voz = len(cargar(reunion_id))
    for nombre in nuevas.values():
        if con_voz >= MAX_VOCES:
            break
        tramo = _mejor_tramo([s for s in salida if s["hablante"] == nombre])
        if tramo and recortar(ruta_audio, *tramo, carpeta(reunion_id) / f"{nombre}.wav"):
            con_voz += 1
    return salida
