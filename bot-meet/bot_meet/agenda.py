"""Sesiones agendadas, guardadas en un JSON para sobrevivir reinicios."""
import json
import re
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

PATRON_MEET = re.compile(r"^https://meet\.google\.com/[a-z]{3}-[a-z]{4}-[a-z]{3}(\?[\w=&.-]*)?$")
ANTES = timedelta(minutes=1)
DESPUES = timedelta(minutes=15)
TOPE = timedelta(hours=3)
OCUPAN = ("agendada", "en_curso")


class SinBotLibre(Exception):
    pass


class LinkInvalido(Exception):
    pass


class DatosInvalidos(Exception):
    pass


@dataclass
class Sesion:
    id: str
    meet_url: str
    inicio: datetime
    fin: datetime
    token_subida: str
    url_jarvis: str
    estado: str = "agendada"  # agendada | en_curso | terminada | cancelada | vencida

    def franja(self):
        return self.inicio - ANTES, min(self.fin + DESPUES, self.inicio + TOPE)

    def a_dict(self):
        d = asdict(self)
        d["inicio"], d["fin"] = self.inicio.isoformat(), self.fin.isoformat()
        return d

    @classmethod
    def de_dict(cls, d):
        return cls(**{**d, "inicio": datetime.fromisoformat(d["inicio"]),
                      "fin": datetime.fromisoformat(d["fin"])})


class Agenda:
    def __init__(self, archivo: Path, max_sesiones: int = 2):
        self._archivo = Path(archivo)
        self._max = max_sesiones
        self._lock = threading.RLock()
        self._sesiones: dict[str, Sesion] = {}
        if self._archivo.exists():
            for d in json.loads(self._archivo.read_text(encoding="utf-8")):
                s = Sesion.de_dict(d)
                if s.estado == "en_curso":  # el bot se reinició en medio: se retoma
                    s.estado = "agendada"
                self._sesiones[s.id] = s

    def _guardar(self):
        self._archivo.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._archivo.with_suffix(".tmp")
        tmp.write_text(json.dumps([s.a_dict() for s in self._sesiones.values()]), encoding="utf-8")
        tmp.replace(self._archivo)

    def agregar(self, s: Sesion) -> Sesion:
        if not PATRON_MEET.match(s.meet_url):
            raise LinkInvalido(s.meet_url)
        if s.inicio.tzinfo is None or s.fin.tzinfo is None or s.fin <= s.inicio:
            raise DatosInvalidos("fechas")
        with self._lock:
            if s.id in self._sesiones:
                return self._sesiones[s.id]
            a0, a1 = s.franja()
            cruces = 0
            for otra in self._sesiones.values():
                if otra.estado not in OCUPAN:
                    continue
                b0, b1 = otra.franja()
                if a0 < b1 and b0 < a1:
                    cruces += 1
            if cruces >= self._max:
                raise SinBotLibre(s.id)
            self._sesiones[s.id] = s
            self._guardar()
            return s

    def obtener(self, id_: str):
        return self._sesiones.get(id_)

    def todas(self):
        return list(self._sesiones.values())

    def marcar(self, id_: str, estado: str):
        with self._lock:
            self._sesiones[id_].estado = estado
            self._guardar()

    def cancelar(self, id_: str) -> bool:
        with self._lock:
            s = self._sesiones.get(id_)
            if s is None or s.estado not in OCUPAN:
                return False
            s.estado = "cancelada"
            self._guardar()
            return True

    def por_iniciar(self, ahora: datetime):
        return [s for s in self._sesiones.values()
                if s.estado == "agendada" and s.franja()[0] <= ahora < s.franja()[1]]

    def vencer(self, ahora: datetime):
        with self._lock:
            cambio = False
            for s in self._sesiones.values():
                if s.estado == "agendada" and s.franja()[1] <= ahora:
                    s.estado, cambio = "vencida", True
            if cambio:
                self._guardar()

    def activas(self) -> int:
        return sum(1 for s in self._sesiones.values() if s.estado == "en_curso")
