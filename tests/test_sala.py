"""Sala de juntas de la oficina 3D: /api/sala contesta en el papel de un agente y no guarda."""
import pytest
from fastapi.testclient import TestClient

from backend import cerebro, memoria
from backend.main import app


@pytest.fixture
def cliente_admin(monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setenv("JARVIS_CLAVE_SECRETA", "clave-de-pruebas-larga")
    cliente = TestClient(app)
    respuesta = cliente.post("/acceso", data={"clave": "la-del-admin"}, follow_redirects=False)
    assert respuesta.status_code == 303
    return cliente


def _falso(vistos, eventos):
    def responder(mensajes, usuario, extra="", dispositivo="navegador", guardar=True):
        vistos.append({"mensajes": mensajes, "extra": extra, "dispositivo": dispositivo, "guardar": guardar})
        return iter(eventos)
    return responder


def test_contesta_el_agente_en_su_papel(cliente_admin, monkeypatch):
    vistos = []
    monkeypatch.setattr(cerebro, "responder", _falso(vistos, [
        {"tipo": "herramienta", "dato": "consultar_fuente"},
        {"tipo": "texto", "dato": "Llevamos unos 239 millones "},
        {"tipo": "texto", "dato": "facturados en el mes."},
    ]))
    r = cliente_admin.post("/api/sala", json={
        "nombre": "Ventas", "area": "Análisis", "rol": "Mide lo facturado",
        "datos": "Facturado del mes RD$ 239M", "pregunta": "¿Cómo vamos este mes?",
        "historial": [{"quien": "Jorge", "texto": "Empecemos"}, {"quien": "Llamadas", "texto": "La deuda bajó"}],
        "presentes": ["Ventas", "Llamadas"],
    })
    assert r.status_code == 200
    assert r.json() == {"texto": "Llevamos unos 239 millones facturados en el mes.", "herramientas": ["consultar_fuente"]}

    [v] = vistos
    assert v["guardar"] is False and v["dispositivo"] == "oficina"
    assert "eres Ventas" in v["extra"] and "NO hablas como Jarvis" in v["extra"]
    assert "RD$ 239M" in v["extra"]
    assert "Llamadas" in v["extra"]                 # los otros presentes, para derivar preguntas
    [mensaje] = v["mensajes"]
    assert "Llamadas: La deuda bajó" in mensaje["content"] and "¿Cómo vamos este mes?" in mensaje["content"]


def test_no_toca_la_conversacion_de_la_persona(cliente_admin, monkeypatch):
    antes = memoria.cargar_conversacion("admin")
    monkeypatch.setattr(cerebro, "responder", _falso([], [{"tipo": "texto", "dato": "Hola."}]))
    cliente_admin.post("/api/sala", json={"nombre": "Jarvis", "pregunta": "¿Qué hay?"})
    assert memoria.cargar_conversacion("admin") == antes


def test_sin_pregunta_o_sin_respuesta(cliente_admin, monkeypatch):
    assert cliente_admin.post("/api/sala", json={"nombre": "Ventas", "pregunta": "  "}).status_code == 400
    monkeypatch.setattr(cerebro, "responder", _falso([], [{"tipo": "error", "dato": "sin cuota"}]))
    r = cliente_admin.post("/api/sala", json={"nombre": "Ventas", "pregunta": "¿Y?"})
    assert r.status_code == 502 and r.json()["error"] == "sin cuota"



# --------------------------------------------------------------------------
# La voz natural de la sala (/api/sala/voz)
# --------------------------------------------------------------------------

def test_la_voz_devuelve_el_mp3_y_anota_el_consumo(cliente_admin, monkeypatch):
    import base64
    import json

    from backend import consumo, sala_voz

    pedidos = []

    class Resp:
        headers = {"Content-Type": "text/event-stream"}

        def __init__(self, cuerpo):
            self.cuerpo = cuerpo

        def read(self):
            return self.cuerpo

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen_falso(pedido, timeout=0):
        pedidos.append(json.loads(pedido.data))
        eventos = [
            {"type": "speech.audio.delta", "audio": base64.b64encode(b"ID3-uno").decode()},
            {"type": "speech.audio.delta", "audio": base64.b64encode(b"-dos").decode()},
            {"type": "speech.audio.done", "usage": {"input_tokens": 20, "output_tokens": 250}},
        ]
        return Resp("\n\n".join("data: " + json.dumps(e) for e in eventos).encode())

    monkeypatch.setattr(sala_voz.urllib.request, "urlopen", urlopen_falso)
    monkeypatch.setattr(cerebro, "clave_openai", lambda: "sk-prueba")

    r = cliente_admin.post("/api/sala/voz", json={"texto": "Llevamos  239 millones.", "voz": "verse"})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg"
    assert r.content == b"ID3-uno-dos"
    [p] = pedidos
    assert p["voice"] == "verse" and p["input"] == "Llevamos 239 millones." and p["stream_format"] == "sse"
    assert "República Dominicana" in p["instructions"]
    [registro] = [x for x in consumo.todos() if x["modo"] == "tts"]
    assert registro["dispositivo"] == "oficina"


def test_la_voz_desconocida_cae_en_una_valida_y_sin_texto_es_400(cliente_admin, monkeypatch):
    from backend import sala_voz

    vistos = []
    monkeypatch.setattr(sala_voz, "sintetizar", lambda texto, voz, clave, instr="": (vistos.append(voz), (b"mp3", None))[1])
    monkeypatch.setattr(cerebro, "clave_openai", lambda: "sk-prueba")
    assert cliente_admin.post("/api/sala/voz", json={"texto": "  "}).status_code == 400
    assert cliente_admin.post("/api/sala/voz", json={"texto": "Hola", "voz": "inventada"}).status_code == 200
    # la validación de la voz la hace sintetizar (cae en "alloy" si no existe)
    assert vistos == ["inventada"] and "alloy" in sala_voz.VOCES
