import shutil
import subprocess

import pytest

from backend import reuniones_voces as rv


@pytest.fixture
def recortes(monkeypatch):
    hechos = []

    def recortar(origen, inicio, fin, destino):
        destino.write_bytes(b"WAV")
        hechos.append((destino.stem, inicio, fin))
        return True
    monkeypatch.setattr(rv, "recortar", recortar)
    return hechos


def seg(h, i, f, t="hola"):
    return {"inicio": i, "fin": f, "hablante": h, "texto": t}


def test_primer_pedazo_numera_voces_y_guarda_su_recorte(tmp_path, recortes):
    salida = rv.unificar("r1", tmp_path / "1.webm", [seg("A", 0, 1), seg("B", 1, 9), seg("A", 9, 30)])
    assert [s["hablante"] for s in salida] == ["Hablante 1", "Hablante 2", "Hablante 1"]
    # El tramo más largo de cada voz, cortado a 10 s.
    assert sorted(recortes) == [("Hablante 1", 9, 19), ("Hablante 2", 1, 9)]
    assert [n for n, _ in rv.cargar("r1")] == ["Hablante 1", "Hablante 2"]


def test_siguiente_pedazo_respeta_las_conocidas_y_numera_las_nuevas(tmp_path, recortes):
    rv.unificar("r1", tmp_path / "1.webm", [seg("A", 0, 5), seg("B", 5, 10)])
    salida = rv.unificar("r1", tmp_path / "2.webm", [seg("Hablante 2", 0, 4), seg("A", 4, 9)])
    assert [s["hablante"] for s in salida] == ["Hablante 2", "Hablante 3"]


def test_voz_sin_tramo_de_dos_segundos_queda_sin_recorte(tmp_path, recortes):
    rv.unificar("r1", tmp_path / "1.webm", [seg("A", 0, 1.5)])
    assert rv.cargar("r1") == [] and recortes == []


def test_como_mucho_cuatro_voces_conocidas(tmp_path, recortes):
    rv.unificar("r1", tmp_path / "1.webm", [seg(h, i * 5, i * 5 + 4) for i, h in enumerate("ABCDE")])
    assert len(rv.cargar("r1")) == 4


def test_sin_ffmpeg_no_rompe(tmp_path, monkeypatch):
    def sin_ffmpeg(*a, **k):
        raise FileNotFoundError("ffmpeg")
    monkeypatch.setattr(subprocess, "run", sin_ffmpeg)
    assert rv.recortar(tmp_path / "x.webm", 0, 3, tmp_path / "y.wav") is False


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="sin ffmpeg en esta máquina")
def test_recorte_real(tmp_path):
    origen = tmp_path / "tono.ogg"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=d=6", "-c:a", "libopus", str(origen)],
                   check=True)
    destino = tmp_path / "Hablante 1.wav"
    assert rv.recortar(origen, 1, 4, destino) and destino.stat().st_size > 1000
    assert rv.data_url(destino).startswith("data:audio/wav;base64,")
