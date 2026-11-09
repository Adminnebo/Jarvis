# tests/test_gmail.py
import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from backend import gmail

LEER = "https://www.googleapis.com/auth/gmail.readonly"
ENVIAR = "https://www.googleapis.com/auth/gmail.send"


@pytest.fixture
def google(monkeypatch):
    monkeypatch.setenv("GOOGLE_JARVIS_CLIENT_ID", "id-cliente")
    monkeypatch.setenv("GOOGLE_JARVIS_CLIENT_SECRET", "secreto")
    monkeypatch.setenv("JARVIS_CLAVE_SECRETA", "clave-de-pruebas-larga")
    gmail._cache_tokens.clear()
    gmail._usados.clear()
    pedidos = []
    respuestas = {}

    def manejar(pedido: httpx.Request):
        pedidos.append(pedido)
        clave = (pedido.method, pedido.url.path)
        estado, cuerpo = respuestas.get(clave, (404, {"error": {"message": "no hay"}}))
        return httpx.Response(estado, json=cuerpo)

    monkeypatch.setattr(gmail, "_http", lambda: httpx.Client(transport=httpx.MockTransport(manejar)))
    return respuestas, pedidos


def test_configurado_depende_de_las_variables(monkeypatch):
    monkeypatch.delenv("GOOGLE_JARVIS_CLIENT_ID", raising=False)
    assert not gmail.configurado()
    monkeypatch.setenv("GOOGLE_JARVIS_CLIENT_ID", "x")
    monkeypatch.setenv("GOOGLE_JARVIS_CLIENT_SECRET", "y")
    assert gmail.configurado()


def test_el_estado_devuelve_al_usuario_una_sola_vez(google):
    estado = gmail.crear_estado("org:ana")
    assert gmail.leer_estado(estado) == "org:ana"
    assert gmail.leer_estado(estado) is None


def test_un_estado_alterado_o_vencido_no_vale(google, monkeypatch):
    estado = gmail.crear_estado("org:ana")
    assert gmail.leer_estado(estado[:-2] + "xx") is None
    assert gmail.leer_estado("basura") is None
    monkeypatch.setattr(gmail, "VIGENCIA_ESTADO", -1)
    assert gmail.leer_estado(gmail.crear_estado("org:ana")) is None


def test_la_url_pide_leer_y_enviar_con_permiso_permanente(google):
    url = urlparse(gmail.url_de_autorizacion("org:ana"))
    q = parse_qs(url.query)
    assert url.netloc == "accounts.google.com"
    assert LEER in q["scope"][0] and ENVIAR in q["scope"][0]
    assert q["access_type"] == ["offline"] and q["prompt"] == ["consent"]
    assert q["redirect_uri"] == ["https://asistente.neboaiconsulting.com/integraciones/gmail/callback"]
    assert gmail.leer_estado(q["state"][0]) == "org:ana"


def test_canjear_exige_los_dos_permisos(google):
    respuestas, _ = google
    respuestas[("POST", "/token")] = (200, {"access_token": "a", "refresh_token": "r",
                                            "expires_in": 3600, "scope": f"openid {LEER}"})
    with pytest.raises(gmail.ErrorGmail, match="dos casillas"):
        gmail.canjear_codigo("codigo")


def test_canjear_bien_deja_el_token_en_cache(google):
    respuestas, pedidos = google
    respuestas[("POST", "/token")] = (200, {"access_token": "a", "refresh_token": "r",
                                            "expires_in": 3600, "scope": f"openid {LEER} {ENVIAR}"})
    datos = gmail.canjear_codigo("codigo")
    assert datos["refresh_token"] == "r"
    assert gmail.token_de_acceso("r") == "a"
    assert len(pedidos) == 1   # el segundo no fue a Google


def test_invalid_grant_es_revocado(google):
    respuestas, _ = google
    respuestas[("POST", "/token")] = (400, {"error": "invalid_grant"})
    with pytest.raises(gmail.ErrorGmail) as error:
        gmail.token_de_acceso("r-viejo")
    assert error.value.revocado


def test_revocar_no_falla_si_google_falla(google):
    gmail.revocar("r")   # 404 del mock: no lanza


import base64


def _b64(texto: str) -> str:
    return base64.urlsafe_b64encode(texto.encode()).decode().rstrip("=")


MENSAJE = {
    "id": "m1", "threadId": "h1", "labelIds": ["INBOX", "CATEGORY_PERSONAL"],
    "snippet": "Hola &amp; adios",
    "payload": {
        "mimeType": "multipart/alternative",
        "headers": [{"name": "From", "value": "Carlos <carlos@jh.com>"},
                    {"name": "To", "value": "ana@gmail.com"},
                    {"name": "Subject", "value": "Cotizacion"},
                    {"name": "Date", "value": "Mon, 9 Nov 2026 10:00:00 -0400"},
                    {"name": "Message-ID", "value": "<abc@jh.com>"}],
        "parts": [{"mimeType": "text/html", "body": {"data": _b64("<p>Hola <b>Ana</b></p>")}},
                  {"mimeType": "text/plain", "body": {"data": _b64("Hola Ana\nNecesito precio")}}],
    },
}


def test_perfil(google):
    respuestas, _ = google
    respuestas[("GET", "/gmail/v1/users/me/profile")] = (200, {"emailAddress": "ana@gmail.com", "historyId": 77})
    assert gmail.perfil("t") == {"email": "ana@gmail.com", "historyId": "77"}


def test_historial_junta_paginas_y_quita_repetidos(google, monkeypatch):
    paginas = iter([
        {"history": [{"messagesAdded": [{"message": {"id": "a"}}, {"message": {"id": "b"}}]}],
         "nextPageToken": "p2", "historyId": "90"},
        {"history": [{"messagesAdded": [{"message": {"id": "b"}}, {"message": {"id": "c"}}]}],
         "historyId": "95"},
    ])
    monkeypatch.setattr(gmail, "_api", lambda *a, **k: next(paginas))
    assert gmail.historial("t", "80") == (["a", "b", "c"], "95")


def test_historial_viejo_es_404(google):
    with pytest.raises(gmail.ErrorGmail) as error:
        gmail.historial("t", "1")
    assert error.value.status == 404


def test_401_de_gmail_es_revocado(google):
    respuestas, _ = google
    respuestas[("GET", "/gmail/v1/users/me/profile")] = (401, {"error": {"message": "x"}})
    with pytest.raises(gmail.ErrorGmail) as error:
        gmail.perfil("t")
    assert error.value.revocado


def test_resumen_prefiere_texto_plano(google):
    r = gmail.resumen_de(MENSAJE)
    assert r["de"] == "Carlos <carlos@jh.com>" and r["asunto"] == "Cotizacion"
    assert r["texto"] == "Hola Ana\nNecesito precio"
    assert r["fragmento"] == "Hola & adios"
    assert r["message_id"] == "<abc@jh.com>" and r["hilo"] == "h1"


def test_texto_plano_saca_el_html_si_no_hay_plano():
    parte = {"mimeType": "text/html", "body": {"data": _b64("<style>x{}</style><p>Uno</p><p>Dos &amp; tres</p>")}}
    assert gmail.texto_plano(parte) == "Uno\n Dos & tres"


def test_enviar_respuesta_va_en_el_hilo(google):
    respuestas, pedidos = google
    respuestas[("POST", "/gmail/v1/users/me/messages/send")] = (200, {"id": "nuevo"})
    nuevo = gmail.enviar("t", "ana@gmail.com", "carlos@jh.com", "Re: Cotizacion", "Va manana",
                         {"hilo": "h1", "message_id": "<abc@jh.com>", "referencias": ""})
    assert nuevo == "nuevo"
    cuerpo = json.loads(pedidos[-1].content)
    assert cuerpo["threadId"] == "h1"
    crudo = base64.urlsafe_b64decode(cuerpo["raw"] + "==").decode()
    assert "In-Reply-To: <abc@jh.com>" in crudo and "To: carlos@jh.com" in crudo
    assert pedidos[-1].headers["authorization"] == "Bearer t"
