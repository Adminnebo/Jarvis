import json
from types import SimpleNamespace as NS

from backend import cerebro, consumo, reuniones_ia


class OpenAIFalso:
    def __init__(self, segmentos=None, resumen=None):
        self.pedidos = []
        self.audio = NS(transcriptions=NS(create=self._transcribir))
        self.responses = NS(create=self._responder)
        self._seg, self._res = segmentos or [], resumen

    def _transcribir(self, **kw):
        self.pedidos.append(kw)
        return NS(segments=[NS(**s) for s in self._seg], duration=300.0, usage=None)

    def _responder(self, **kw):
        self.pedidos.append(kw)
        return NS(output_text=json.dumps(self._res), usage=None)


def test_transcribir_pide_hablantes_y_anota_consumo(monkeypatch, tmp_path):
    falso = OpenAIFalso([{"start": 0.5, "end": 3.0, "speaker": "A", "text": " Hola "}])
    monkeypatch.setattr(cerebro, "cliente", lambda: falso)
    anotado = []
    monkeypatch.setattr(consumo, "registrar", lambda *a, **k: anotado.append((a, k)))
    audio = tmp_path / "p.ogg"
    audio.write_bytes(b"OGG")
    segs = reuniones_ia.transcribir(audio, usuario=None)
    assert segs == [{"inicio": 0.5, "fin": 3.0, "hablante": "A", "texto": "Hola"}]
    kw = falso.pedidos[0]
    assert kw["model"] == "gpt-4o-transcribe-diarize" and kw["response_format"] == "diarized_json"
    assert kw["chunking_strategy"] == "auto"
    assert anotado[0][0][:3] == ("transcripcion", "gpt-4o-transcribe-diarize", {"type": "duration", "seconds": 300.0})


def test_transcribir_anota_los_tokens_reales_y_su_costo(monkeypatch, tmp_path):
    falso = OpenAIFalso([{"start": 0, "end": 1, "speaker": "A", "text": "hola"}])
    uso = {"type": "tokens", "input_tokens": 2782, "output_tokens": 4724, "total_tokens": 7506,
           "input_token_details": {"audio_tokens": 2628, "text_tokens": 154}}
    falso.audio = NS(transcriptions=NS(create=lambda **kw: NS(segments=[NS(start=0, end=1, speaker="A", text="hola")],
                                                              duration=300.0, usage=NS(model_dump=lambda: uso))))
    monkeypatch.setattr(cerebro, "cliente", lambda: falso)
    audio = tmp_path / "p.ogg"
    audio.write_bytes(b"OGG")
    reuniones_ia.transcribir(audio, usuario=None)
    fila = consumo.registrar("transcripcion", "gpt-4o-transcribe-diarize", uso)
    # 2628*6 + 154*2.5 + 4724*10 por millón = ~$0.063 cada 5 minutos.
    assert 0.06 < fila["costo"] < 0.07


def test_nombres_desde_la_linea():
    pedazos = {
        1: [{"inicio": 0, "fin": 4, "hablante": "A", "texto": "Buenas"},
            {"inicio": 5, "fin": 8, "hablante": "B", "texto": "Hola Ana"}],
        2: [{"inicio": 1, "fin": 3, "hablante": "A", "texto": "Seguimos"}],
    }
    linea = [{"t": t, "nombres": ["Ana"]} for t in range(0, 5)] + \
            [{"t": t, "nombres": ["Luis"]} for t in range(5, 9)]
    texto = reuniones_ia.con_nombres(pedazos, linea, pedazo_s=300)
    assert [(x["quien"], x["t"]) for x in texto] == [("Ana", 0), ("Luis", 5), ("Participante A", 301)]


def test_sin_linea_quedan_participantes():
    texto = reuniones_ia.con_nombres({1: [{"inicio": 0, "fin": 2, "hablante": "B", "texto": "x"}]}, [], 300)
    assert texto[0]["quien"] == "Participante B"


def test_resumir_devuelve_json_limpio(monkeypatch):
    falso = OpenAIFalso(resumen={"resumen": "Se acordó el precio.", "puntos_clave": ["precio"],
                                 "tareas": [{"quien": "Ana", "que": "enviar cotización", "cuando": "viernes"}]})
    monkeypatch.setattr(cerebro, "cliente", lambda: falso)
    monkeypatch.setattr(cerebro, "anotar_consumo", lambda *a, **k: None)
    r = reuniones_ia.resumir("Ventas", [{"t": 0, "quien": "Ana", "texto": "El precio queda en 10"}], usuario=None)
    assert r["resumen"] == "Se acordó el precio." and r["tareas"][0]["quien"] == "Ana"
    assert "Ana: El precio queda en 10" in falso.pedidos[0]["input"]


def test_resumir_si_el_modelo_no_da_json(monkeypatch):
    falso = OpenAIFalso()
    falso.responses = NS(create=lambda **kw: NS(output_text="no es json", usage=None))
    monkeypatch.setattr(cerebro, "cliente", lambda: falso)
    monkeypatch.setattr(cerebro, "anotar_consumo", lambda *a, **k: None)
    r = reuniones_ia.resumir("Ventas", [], usuario=None)
    assert r == {"resumen": "no es json", "puntos_clave": [], "tareas": []}


def test_precio_por_minuto_del_modelo():
    assert consumo.PRECIOS_POR_DEFECTO["gpt-4o-transcribe-diarize"]["minuto"] == 0.006
