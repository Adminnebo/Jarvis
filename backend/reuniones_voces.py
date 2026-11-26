"""Voces de una reunión presencial: que cada persona salga con el mismo nombre en
toda la reunión.

El modelo separa voces dentro de cada pedazo (A, B, ...) pero no entre pedazos. Las
voces conocidas se le pasan con su nombre en cada pedazo:

- las de la **calibración**: antes de grabar, cada persona dice su nombre y lee una
  frase (`guardar_muestra`);
- las que aparecen solas: del pedazo en que aparece una voz nueva se recorta su tramo
  más largo (2-10 s) y pasa a ser «Hablante N» (hasta 4 recortes automáticos).

El modelo acepta 4 voces conocidas por llamada: con más, el pedazo se transcribe una
vez por grupo (`grupos`) y se une (`unir`). Los archivos viven junto a los pedazos
locales y se borran con ellos al cerrar la reunión.
"""

import base64
import json
import math
import re
import subprocess
from pathlib import Path

from . import rutas

MAX_VOCES = 4          # por llamada al modelo, y recortes automáticos
MAX_MUESTRAS = 10      # personas en la calibración
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


def _archivo(reunion_id: str, i: int) -> Path:
    """El recorte de la voz i (por posición: los nombres pueden traer cualquier cosa)."""
    return carpeta(reunion_id) / f"voz-{i + 1:02d}.wav"


def conocidas(reunion_id: str) -> list[str]:
    return list(_estado(reunion_id)["nombres"])


def cargar(reunion_id: str) -> list[tuple[str, Path]]:
    """[(nombre, recorte.wav)] de las voces que tienen recorte, en orden."""
    return [(n, _archivo(reunion_id, i)) for i, n in enumerate(_estado(reunion_id)["nombres"])
            if _archivo(reunion_id, i).exists()]


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


def guardar_muestra(reunion_id: str, nombre: str, datos: bytes, formato: str) -> str | None:
    """La muestra de la calibración como voz conocida. None si quedó; si no, por qué:
    'nombre', 'repetido', 'muchas' o 'audio'."""
    nombre = " ".join((nombre or "").split())[:60]
    if not nombre:
        return "nombre"
    estado = _estado(reunion_id)
    if nombre.casefold() in {n.casefold() for n in estado["nombres"]}:
        return "repetido"
    if len(estado["nombres"]) >= MAX_MUESTRAS:
        return "muchas"
    crudo = carpeta(reunion_id) / f"muestra.{formato}"
    crudo.write_bytes(datos)
    destino = _archivo(reunion_id, len(estado["nombres"]))
    ok = recortar(crudo, 0, MAX_S, destino)
    crudo.unlink(missing_ok=True)
    if not ok:
        return "audio"
    estado["nombres"].append(nombre)
    _guardar(reunion_id, estado)
    return None


def grupos(voces: list) -> list[list]:
    """En grupos de hasta MAX_VOCES, parejos (7 → 4 + 3; 9 → 3 + 3 + 3)."""
    if len(voces) <= MAX_VOCES:
        return [list(voces)] if voces else []
    k = math.ceil(len(voces) / MAX_VOCES)
    tam, sobra = divmod(len(voces), k)
    salida, i = [], 0
    for g in range(k):
        n = tam + (1 if g < sobra else 0)
        salida.append(list(voces[i:i + n]))
        i += n
    return salida


def unir(llamadas: list[list[dict]], conocidas_: set[str]) -> list[dict]:
    """Une las transcripciones del mismo pedazo hechas por grupos de voces: valen los
    segmentos de la primera; si uno quedó con letra, toma el nombre conocido del
    segmento que más se le cruza en el tiempo en las otras llamadas."""
    if not llamadas:
        return []
    otras = [s for llamada in llamadas[1:] for s in llamada if s["hablante"] in conocidas_]
    salida = []
    for s in llamadas[0]:
        if s["hablante"] not in conocidas_:
            mejor, cruce = None, 0.0
            for o in otras:
                c = min(s["fin"], o["fin"]) - max(s["inicio"], o["inicio"])
                if c > cruce:
                    mejor, cruce = o["hablante"], c
            if mejor:
                s = {**s, "hablante": mejor}
        salida.append(s)
    return salida


def _mejor_tramo(segmentos: list[dict]) -> tuple[float, float] | None:
    largo = max(segmentos, key=lambda s: s["fin"] - s["inicio"], default=None)
    if largo is None or largo["fin"] - largo["inicio"] < MIN_S:
        return None
    return largo["inicio"], min(largo["fin"], largo["inicio"] + MAX_S)


def unificar(reunion_id: str, ruta_audio: Path, segmentos: list[dict]) -> list[dict]:
    """Cambia las letras del modelo por «Hablante N» (las conocidas ya vienen con su
    nombre) y guarda el recorte de las voces nuevas mientras haya lugar."""
    estado = _estado(reunion_id)
    sabidas = set(estado["nombres"])
    nuevas: dict[str, str] = {}
    for s in segmentos:
        h = s["hablante"]
        if h not in sabidas and h not in nuevas:
            numero = sum(1 for n in estado["nombres"] if ETIQUETA.match(n)) + 1
            estado["nombres"].append(f"Hablante {numero}")
            nuevas[h] = estado["nombres"][-1]
    _guardar(reunion_id, estado)
    salida = [{**s, "hablante": nuevas.get(s["hablante"], s["hablante"])} for s in segmentos]
    recortes = sum(1 for n, _ in cargar(reunion_id) if ETIQUETA.match(n))
    for nombre in nuevas.values():
        if recortes >= MAX_VOCES:
            break
        tramo = _mejor_tramo([s for s in salida if s["hablante"] == nombre])
        if tramo and recortar(ruta_audio, *tramo, _archivo(reunion_id, estado["nombres"].index(nombre))):
            recortes += 1
    return salida
