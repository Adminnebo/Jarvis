"""Graba el monitor de PulseAudio en pedazos Opus mono 16 kHz 24 kbps."""
import signal
import subprocess
from pathlib import Path


class Grabador:
    def __init__(self, carpeta: Path, pedazo_s: int = 300, fuente: str = "grabacion.monitor",
                 popen=None):
        self._dir = Path(carpeta)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._pedazo_s = pedazo_s
        self._fuente = fuente
        self._popen = popen or (lambda args: subprocess.Popen(args))
        self._proc = None
        self._siguiente = 1

    def comando(self, inicio: int) -> list[str]:
        return ["ffmpeg", "-nostdin", "-loglevel", "error",
                "-f", "pulse", "-i", self._fuente,
                "-ac", "1", "-ar", "16000",
                "-c:a", "libopus", "-b:a", "24k", "-application", "voip",
                "-f", "segment", "-segment_time", str(self._pedazo_s),
                "-segment_start_number", str(inicio), "-reset_timestamps", "1",
                str(self._dir / "pedazo-%05d.ogg")]

    def _archivos(self):
        return sorted((int(p.stem.split("-")[1]), p) for p in self._dir.glob("pedazo-*.ogg"))

    def iniciar(self):
        self._proc = self._popen(self.comando(self._siguiente))

    def detener(self):
        if self._proc is None:
            return
        self._proc.send_signal(signal.SIGINT)
        try:
            self._proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._proc.kill()
        self._proc = None
        archivos = self._archivos()
        if archivos:
            self._siguiente = max(self._siguiente, archivos[-1][0] + 1)

    def pedazos_listos(self, todos: bool = False):
        """[(n, ruta)] cerrados. Mientras graba, el último se está escribiendo."""
        archivos = self._archivos()
        if archivos:
            self._siguiente = max(self._siguiente, archivos[-1][0] + 1)
        if self._proc is not None and not todos:
            archivos = archivos[:-1]
        return archivos
