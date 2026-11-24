import json

import httpx
import pytest

from backend import bot_meet

S = "s" * 32


def test_firma_igual_que_el_bot():
    # Mismo vector que bot-meet/tests/test_firma.py.
    assert bot_meet.firmar(S, 1000, "POST", "/v1/sesiones", b'{"id":"r1"}') == (
        "48afd012f6332ff2f2e9e0835636f6a9b6d7f2085a983ab6068614d17d3520b9")


def test_sin_variables_no_esta_configurado(monkeypatch):
    monkeypatch.delenv("BOT_MEET_URL", raising=False)
    assert bot_meet.configurado() is False


def _cliente(monkeypatch, respuesta):
    monkeypatch.setenv("BOT_MEET_URL", "https://bot.test")
    monkeypatch.setenv("BOT_MEET_SECRETO", S)
    pedidos = []

    def manejar(req):
        pedidos.append(req)
        return respuesta
    monkeypatch.setattr(bot_meet, "_http", lambda: httpx.Client(transport=httpx.MockTransport(manejar)))
    return pedidos


def test_agendar_firma_y_manda_el_contrato(monkeypatch):
    pedidos = _cliente(monkeypatch, httpx.Response(202, json={"estado": "agendada"}))
    bot_meet.agendar("r1", "https://meet.google.com/abc-defg-hij", "2026-12-01T14:00:00-04:00",
                     "2026-12-01T15:00:00-04:00", "tok")
    req = pedidos[0]
    assert req.url.path == "/v1/sesiones"
    cuerpo = json.loads(req.content)
    assert cuerpo["url_jarvis"] == "https://asistente.neboaiconsulting.com" and cuerpo["token_subida"] == "tok"
    t = int(req.headers["X-Bot-Tiempo"])
    assert req.headers["X-Bot-Firma"] == bot_meet.firmar(S, t, "POST", "/v1/sesiones", req.content)


def test_sin_bot_libre(monkeypatch):
    _cliente(monkeypatch, httpx.Response(409, json={"error": "sin_bot_libre"}))
    with pytest.raises(bot_meet.SinBotLibre):
        bot_meet.agendar("r1", "https://meet.google.com/abc-defg-hij", "a", "b", "t")


def test_otro_error(monkeypatch):
    _cliente(monkeypatch, httpx.Response(500))
    with pytest.raises(bot_meet.ErrorBot):
        bot_meet.agendar("r1", "https://meet.google.com/abc-defg-hij", "a", "b", "t")


def test_cancelar(monkeypatch):
    pedidos = _cliente(monkeypatch, httpx.Response(200, json={"estado": "cancelada"}))
    assert bot_meet.cancelar("r1") is True
    assert pedidos[0].method == "DELETE" and pedidos[0].url.path == "/v1/sesiones/r1"
