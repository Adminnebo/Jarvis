import base64

import pytest
from fastapi.testclient import TestClient

# Arriba del todo por lo mismo que en test_permisos.py: main carga el .env real.
from backend import cerebro, fotos, memoria
from backend.main import app

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 60


def _b64(datos: bytes) -> str:
    return base64.b64encode(datos).decode("ascii")


@pytest.fixture
def cliente(entorno_limpio, monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setenv("JARVIS_CLAVE_SECRETA", "clave-de-pruebas-larga")
    cliente = TestClient(app)
    respuesta = cliente.post("/acceso", data={"clave": "la-del-admin"}, follow_redirects=False)
    assert respuesta.status_code == 303
    return cliente


def test_una_foto_valida_se_decodifica():
    assert fotos.decodificar("image/jpeg", _b64(JPEG)) == JPEG


@pytest.mark.parametrize("mime, dato, motivo", [
    ("image/gif", _b64(JPEG), "no admitido"),
    ("image/jpeg", "esto no es base64!!", "base64"),
    ("image/jpeg", "", "base64|vacia"),
    ("image/png", _b64(JPEG), "no es image/png"),
])
def test_lo_que_no_es_una_foto_se_rechaza(mime, dato, motivo):
    with pytest.raises(ValueError, match=motivo):
        fotos.decodificar(mime, dato)


def test_una_foto_demasiado_grande_se_corta_antes_de_decodificar():
    enorme = "A" * (fotos.MAX_BYTES * 2)
    with pytest.raises(ValueError, match="pesa mas"):
        fotos.decodificar("image/jpeg", enorme)


def test_sin_sesion_no_se_puede_mandar_una_foto(entorno_limpio, monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    respuesta = TestClient(app).post("/api/fotos", json={"mime": "image/jpeg", "dato": _b64(JPEG)})
    assert respuesta.status_code == 401


def test_la_foto_se_lee_y_queda_constancia_en_el_historial(cliente, monkeypatch):
    vistas = []

    def leer_falso(url, motivo, usuario):
        vistas.append((url, motivo, usuario.id))
        return "Es una taza azul."

    monkeypatch.setattr(cerebro, "leer_foto", leer_falso)

    respuesta = cliente.post("/api/fotos", json={
        "mime": "image/jpeg", "dato": _b64(JPEG),
        "motivo": "que es esto", "origen": "telefono",
    })

    assert respuesta.status_code == 200
    assert respuesta.json() == {"lectura": "Es una taza azul."}
    assert vistas[0][0].startswith("data:image/jpeg;base64,")
    assert vistas[0][1:] == ("que es esto", "admin")
    assert memoria.cargar_conversacion("admin")[-2:] == [
        {"role": "user", "content": "[Foto del telefono] que es esto"},
        {"role": "assistant", "content": "Es una taza azul."},
    ]


def test_una_foto_invalida_no_llega_al_modelo(cliente, monkeypatch):
    monkeypatch.setattr(cerebro, "leer_foto", lambda *a: pytest.fail("no debia leerla"))

    respuesta = cliente.post("/api/fotos", json={"mime": "image/jpeg", "dato": _b64(b"hola")})

    assert respuesta.status_code == 400
    assert memoria.cargar_conversacion("admin") == []


def test_si_el_modelo_falla_responde_502_y_no_ensucia_el_historial(cliente, monkeypatch):
    def falla(*a):
        raise RuntimeError("sin cuota")

    monkeypatch.setattr(cerebro, "leer_foto", falla)

    respuesta = cliente.post("/api/fotos", json={"mime": "image/jpeg", "dato": _b64(JPEG)})

    assert respuesta.status_code == 502
    assert "sin cuota" in respuesta.json()["error"]
    assert memoria.cargar_conversacion("admin") == []
