from datetime import datetime, timedelta, timezone

import pytest

from bot_meet.agenda import Agenda, LinkInvalido, Sesion, SinBotLibre, DatosInvalidos

T0 = datetime(2026, 12, 1, 14, 0, tzinfo=timezone.utc)
URL = "https://meet.google.com/abc-defg-hij"


def sesion(id_="r1", inicio=T0, minutos=60, url=URL):
    return Sesion(id=id_, meet_url=url, inicio=inicio, fin=inicio + timedelta(minutes=minutos),
                  token_subida="tok", url_jarvis="https://asistente.neboaiconsulting.com")


def test_agrega_y_guarda(tmp_path):
    a = Agenda(tmp_path / "agenda.json")
    a.agregar(sesion())
    otra = Agenda(tmp_path / "agenda.json")
    assert otra.obtener("r1").meet_url == URL
    assert otra.obtener("r1").estado == "agendada"


def test_mismo_id_no_duplica(tmp_path):
    a = Agenda(tmp_path / "agenda.json", max_sesiones=1)
    a.agregar(sesion())
    a.agregar(sesion())  # Jarvis reintentó: no cuenta como segunda
    assert len(a.todas()) == 1


@pytest.mark.parametrize("url", [
    "https://meet.google.com/abc-defg-hi",
    "http://meet.google.com/abc-defg-hij",
    "https://evil.com/abc-defg-hij",
    "https://meet.google.com/abc-defg-hij/../x",
])
def test_link_invalido(tmp_path, url):
    with pytest.raises(LinkInvalido):
        Agenda(tmp_path / "a.json").agregar(sesion(url=url))


def test_link_con_parametros_vale(tmp_path):
    Agenda(tmp_path / "a.json").agregar(sesion(url=URL + "?authuser=0"))


def test_fin_antes_de_inicio(tmp_path):
    with pytest.raises(DatosInvalidos):
        Agenda(tmp_path / "a.json").agregar(sesion(minutos=0))


def test_fechas_sin_zona(tmp_path):
    with pytest.raises(DatosInvalidos):
        Agenda(tmp_path / "a.json").agregar(sesion(inicio=T0.replace(tzinfo=None)))


def test_limite_de_bots_a_la_vez(tmp_path):
    a = Agenda(tmp_path / "a.json", max_sesiones=2)
    a.agregar(sesion("r1"))
    a.agregar(sesion("r2", inicio=T0 + timedelta(minutes=30)))
    with pytest.raises(SinBotLibre):
        a.agregar(sesion("r3", inicio=T0 + timedelta(minutes=45)))


def test_sin_cruce_si_alcanza(tmp_path):
    a = Agenda(tmp_path / "a.json", max_sesiones=1)
    a.agregar(sesion("r1"))  # franja 13:59 a 15:15
    a.agregar(sesion("r2", inicio=T0 + timedelta(minutes=80)))  # 15:19, ya no se cruza


def test_canceladas_no_ocupan_lugar(tmp_path):
    a = Agenda(tmp_path / "a.json", max_sesiones=1)
    a.agregar(sesion("r1"))
    assert a.cancelar("r1") is True
    a.agregar(sesion("r2"))
    assert a.cancelar("nada") is False


def test_por_iniciar_y_vencidas(tmp_path):
    a = Agenda(tmp_path / "a.json")
    a.agregar(sesion("r1"))
    assert a.por_iniciar(T0 - timedelta(minutes=2)) == []
    assert [s.id for s in a.por_iniciar(T0 - timedelta(seconds=59))] == ["r1"]
    a.vencer(T0 + timedelta(hours=2))  # pasó la franja (fin + 15 min)
    assert a.obtener("r1").estado == "vencida"
    assert a.por_iniciar(T0 + timedelta(hours=2)) == []


def test_en_curso_se_retoma_al_reiniciar(tmp_path):
    a = Agenda(tmp_path / "a.json")
    a.agregar(sesion("r1"))
    a.marcar("r1", "en_curso")
    assert a.activas() == 1
    otra = Agenda(tmp_path / "a.json")
    assert otra.obtener("r1").estado == "agendada"
