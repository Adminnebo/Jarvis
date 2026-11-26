import shutil
import subprocess

import pytest

from backend import reuniones_voces as rv


@pytest.fixture
def recortes(monkeypatch):
    """ffmpeg simulado: anota (archivo, inicio, fin) y deja un wav de mentira."""
    hechos = []

    def recortar(origen, inicio, fin, destino):
        destino.write_bytes(b"WAV")
        hechos.append((destino.name, inicio, fin))
        return True
    monkeypatch.setattr(rv, "recortar", recortar)
    return hechos


def seg(h, i, f, t="hola"):
    return {"inicio": i, "fin": f, "hablante": h, "texto": t}


def test_primer_pedazo_numera_voces_y_guarda_su_recorte(tmp_path, recortes):
    salida = rv.unificar("r1", tmp_path / "1.webm", [seg("A", 0, 1), seg("B", 1, 9), seg("A", 9, 30)])
    assert [s["hablante"] for s in salida] == ["Hablante 1", "Hablante 2", "Hablante 1"]
    # El tramo más largo de cada voz, cortado a 10 s.
    assert sorted(recortes) == [("voz-01.wav", 9, 19), ("voz-02.wav", 1, 9)]
    assert [n for n, _ in rv.cargar("r1")] == ["Hablante 1", "Hablante 2"]


def test_siguiente_pedazo_respeta_las_conocidas_y_numera_las_nuevas(tmp_path, recortes):
    rv.unificar("r1", tmp_path / "1.webm", [seg("A", 0, 5), seg("B", 5, 10)])
    salida = rv.unificar("r1", tmp_path / "2.webm", [seg("Hablante 2", 0, 4), seg("A", 4, 9)])
    assert [s["hablante"] for s in salida] == ["Hablante 2", "Hablante 3"]


def test_voz_sin_tramo_de_dos_segundos_queda_sin_recorte(tmp_path, recortes):
    rv.unificar("r1", tmp_path / "1.webm", [seg("A", 0, 1.5)])
    assert rv.cargar("r1") == [] and recortes == []


def test_como_mucho_cuatro_recortes_automaticos(tmp_path, recortes):
    rv.unificar("r1", tmp_path / "1.webm", [seg(h, i * 5, i * 5 + 4) for i, h in enumerate("ABCDE")])
    assert len(rv.cargar("r1")) == 4


def test_muestras_de_la_calibracion(recortes):
    assert rv.guardar_muestra("r1", "  Jorge  Salamanca ", b"W", "webm") is None
    assert rv.guardar_muestra("r1", "Edmond", b"W", "webm") is None
    assert rv.guardar_muestra("r1", "jorge salamanca", b"W", "webm") == "repetido"
    assert rv.guardar_muestra("r1", "   ", b"W", "webm") == "nombre"
    assert [n for n, _ in rv.cargar("r1")] == ["Jorge Salamanca", "Edmond"]
    assert recortes[0] == ("voz-01.wav", 0, rv.MAX_S)        # hasta 10 s de la muestra
    for i in range(8):
        assert rv.guardar_muestra("r1", f"P{i}", b"W", "webm") is None
    assert rv.guardar_muestra("r1", "Once", b"W", "webm") == "muchas"


def test_muestra_que_ffmpeg_no_lee(monkeypatch):
    monkeypatch.setattr(rv, "recortar", lambda *a: False)
    assert rv.guardar_muestra("r1", "Ana", b"basura", "webm") == "audio"
    assert rv.conocidas("r1") == []


def test_calibradas_y_nuevas_conviven(tmp_path, recortes):
    rv.guardar_muestra("r1", "Jorge", b"W", "webm")
    salida = rv.unificar("r1", tmp_path / "1.webm", [seg("Jorge", 0, 4), seg("A", 4, 9)])
    assert [s["hablante"] for s in salida] == ["Jorge", "Hablante 1"]
    assert rv.conocidas("r1") == ["Jorge", "Hablante 1"]


def test_grupos_parejos():
    assert [len(g) for g in rv.grupos(list("abcdefg"))] == [4, 3]
    assert [len(g) for g in rv.grupos(list("abcd"))] == [4]
    assert [len(g) for g in rv.grupos(list("abcdefghi"))] == [3, 3, 3]
    assert rv.grupos([]) == []
    assert sum(rv.grupos(list("abcdefghij")), []) == list("abcdefghij")


def test_unir_llamadas_por_grupo():
    conocidas = {"Ana", "Beto", "Caro", "Dani", "Eva"}
    primera = [seg("Ana", 0, 4), seg("A", 4, 9), seg("B", 9, 12)]       # Eva no estaba en este grupo
    segunda = [seg("A", 0, 4), seg("Eva", 4.5, 8.5)]
    assert [s["hablante"] for s in rv.unir([primera, segunda], conocidas)] == ["Ana", "Eva", "B"]


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
