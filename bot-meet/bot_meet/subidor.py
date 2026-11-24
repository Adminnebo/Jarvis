"""Cola en disco de lo que va a Jarvis: eventos, pedazos de audio, hablantes.

Cada cosa es un archivo numerado; se envían en orden y se borran solo cuando
Jarvis responde 2xx (o 409, ya lo tenía). Si Jarvis no contesta, se espera
ESPERA_S antes de volver a intentar. Lo que pasa de 24 h se descarta.
"""
import json
import shutil
import time
from pathlib import Path

import httpx

ESPERA_S = 30
VIDA_MAX_S = 24 * 3600


class Subidor:
    def __init__(self, carpeta: Path, url_jarvis: str, id_reunion: str, token: str,
                 cliente: httpx.Client | None = None, reloj=time.time):
        self._dir = Path(carpeta)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._base = f"{url_jarvis.rstrip('/')}/api/reuniones/{id_reunion}"
        self._cabeceras = {"Authorization": f"Bearer {token}"}
        self._cliente = cliente or httpx.Client(timeout=60)
        self._reloj = reloj
        self._proximo_intento = 0.0
        existentes = sorted(self._dir.glob("*.json"))
        self._seq = int(existentes[-1].stem) if existentes else 0

    def _encolar(self, meta: dict, archivo: Path | None = None):
        self._seq += 1
        nombre = f"{self._seq:06d}"
        if archivo is not None:
            shutil.move(str(archivo), self._dir / f"{nombre}.ogg")
            meta["archivo"] = f"{nombre}.ogg"
        meta["creado"] = self._reloj()
        tmp = self._dir / f"{nombre}.tmp"
        tmp.write_text(json.dumps(meta), encoding="utf-8")
        tmp.replace(self._dir / f"{nombre}.json")

    def evento(self, tipo: str, **datos):
        self._encolar({"tipo": "evento", "datos": {"tipo": tipo, **datos}})

    def audio(self, n: int, ruta: Path):
        self._encolar({"tipo": "audio", "n": n}, archivo=Path(ruta))

    def hablantes(self, linea: list):
        self._encolar({"tipo": "hablantes", "datos": {"linea": linea}})

    def _enviar(self, meta: dict) -> httpx.Response:
        if meta["tipo"] == "evento":
            return self._cliente.post(f"{self._base}/eventos", json=meta["datos"], headers=self._cabeceras)
        if meta["tipo"] == "hablantes":
            return self._cliente.post(f"{self._base}/hablantes", json=meta["datos"], headers=self._cabeceras)
        cuerpo = (self._dir / meta["archivo"]).read_bytes()
        return self._cliente.post(f"{self._base}/audio", params={"n": meta["n"]}, content=cuerpo,
                                  headers={**self._cabeceras, "Content-Type": "audio/ogg"})

    def _borrar(self, ruta_json: Path, meta: dict):
        if meta.get("archivo"):
            (self._dir / meta["archivo"]).unlink(missing_ok=True)
        ruta_json.unlink(missing_ok=True)

    def pendientes(self) -> int:
        return len(list(self._dir.glob("*.json")))

    def vaciar(self) -> int:
        """Envía lo que pueda, en orden. Devuelve cuántos quedan pendientes."""
        ahora = self._reloj()
        if ahora < self._proximo_intento:
            return self.pendientes()
        for ruta in sorted(self._dir.glob("*.json")):
            meta = json.loads(ruta.read_text(encoding="utf-8"))
            if ahora - meta["creado"] > VIDA_MAX_S:
                print(f"[subidor] descarto {ruta.name}: más de 24 h sin poder enviarlo")
                self._borrar(ruta, meta)
                continue
            try:
                r = self._enviar(meta)
            except httpx.HTTPError as error:
                print(f"[subidor] Jarvis no responde ({error}); reintento en {ESPERA_S} s")
                self._proximo_intento = ahora + ESPERA_S
                break
            if r.is_success or r.status_code == 409:
                self._borrar(ruta, meta)
            elif 400 <= r.status_code < 500 and r.status_code not in (408, 429):
                print(f"[subidor] Jarvis rechazó {ruta.name} con {r.status_code}; lo descarto")
                self._borrar(ruta, meta)
            else:
                self._proximo_intento = ahora + ESPERA_S
                break
        return self.pendientes()
