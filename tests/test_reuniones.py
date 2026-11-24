import pytest

from backend import bot_meet, reuniones
from backend import reuniones_datos as rd

EVENTO = {"id": "e1", "title": "Ventas", "start": "2026-12-01T14:00:00-04:00",
          "end": "2026-12-01T15:00:00-04:00",
          "conferencing": {"url": "https://meet.google.com/abc-defg-hij"}}


@pytest.fixture
def bot(monkeypatch):
    estado = {"agendadas": [], "canceladas": [], "falla": None}

    def agendar(id_, url, ini, fin, token):
        if estado["falla"]:
            raise estado["falla"]
        estado["agendadas"].append((id_, url, ini, fin, token))

    monkeypatch.setattr(bot_meet, "configurado", lambda: True)
    monkeypatch.setattr(bot_meet, "agendar", agendar)
    monkeypatch.setattr(bot_meet, "cancelar", lambda id_: estado["canceladas"].append(id_) or True)
    return estado


@pytest.mark.parametrize("evento,esperado", [
    (EVENTO, "https://meet.google.com/abc-defg-hij"),
    ({"conferencing": None, "location": "meet.google.com/abc-defg-hij"}, "https://meet.google.com/abc-defg-hij"),
    ({"description": "Entrar: https://meet.google.com/xyz-abcd-efg?authuser=0"}, "https://meet.google.com/xyz-abcd-efg"),
    ({"conferencing": {"url": "https://teams.microsoft.com/l/x"}}, None),
])
def test_link_de_meet(evento, esperado):
    assert reuniones.link_meet(evento) == esperado


def test_proponer_crea_una_sola_por_reunion(bot):
    a = reuniones.proponer("u1", EVENTO)
    b = reuniones.proponer("u2", EVENTO)
    assert a["id"] == b["id"] and a["estado"] == "propuesta"


def test_proponer_sin_bot_o_sin_meet(bot, monkeypatch):
    assert reuniones.proponer("u1", {**EVENTO, "conferencing": None}) is None
    monkeypatch.setattr(bot_meet, "configurado", lambda: False)
    assert reuniones.proponer("u1", EVENTO) is None


def test_pedir_agenda_al_bot_una_sola_vez(bot):
    r = reuniones.proponer("u1", EVENTO)
    assert "grabar" in reuniones.pedir("u1", r["id"]).lower()
    reuniones.pedir("u2", r["id"])
    assert len(bot["agendadas"]) == 1
    fila = rd.obtener(r["id"])
    assert fila["estado"] == "agendada"
    assert sorted(rd.interesados(r["id"])) == ["u1", "u2"]
    token = bot["agendadas"][0][4]
    assert reuniones.token_valido(r["id"], token) and not reuniones.token_valido(r["id"], "otro")


def test_pedir_sin_bot_libre(bot):
    bot["falla"] = bot_meet.SinBotLibre("r")
    r = reuniones.proponer("u1", EVENTO)
    assert "no hay bot libre" in reuniones.pedir("u1", r["id"]).lower()
    assert rd.obtener(r["id"])["estado"] == "sin_bot"


def test_no_grabar_cancela_si_nadie_mas_quiere(bot):
    r = reuniones.proponer("u1", EVENTO)
    reuniones.pedir("u1", r["id"])
    reuniones.pedir("u2", r["id"])
    reuniones.no_grabar("u1", r["id"])
    assert bot["canceladas"] == []
    reuniones.no_grabar("u2", r["id"])
    assert bot["canceladas"] == [r["id"]] and rd.obtener(r["id"])["estado"] == "cancelada"


def test_enlace_firmado(bot, monkeypatch):
    monkeypatch.setenv("JARVIS_CLAVE_SECRETA", "x" * 40)
    r = reuniones.proponer("u1", EVENTO)
    url = reuniones.enlace("u1", r["id"], "grabar")
    assert url.startswith("https://asistente.neboaiconsulting.com/reuniones/accion?")
    from urllib.parse import parse_qs, urlparse
    q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    assert reuniones.verificar_enlace(q["u"], q["r"], q["a"], q["f"]) is True
    assert reuniones.verificar_enlace("u2", q["r"], q["a"], q["f"]) is False
