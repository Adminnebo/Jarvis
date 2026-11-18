from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from backend import avisos, calendario, dispositivos, gmail, integraciones, zernio
from backend import google_calendario as gc

RD = ZoneInfo("America/Santo_Domingo")


def _manana(hora: int, minuto: int = 0) -> datetime:
    return (datetime.now(RD) + timedelta(days=1)).replace(hour=hora, minute=minuto, second=0, microsecond=0)


@pytest.fixture
def google(monkeypatch):
    monkeypatch.setenv("GOOGLE_JARVIS_CLIENT_ID", "x")
    monkeypatch.setenv("GOOGLE_JARVIS_CLIENT_SECRET", "y")
    monkeypatch.setattr(gmail, "canjear_codigo", lambda c: {
        "access_token": "a", "refresh_token": "r", "scope": gmail.CALENDARIO})
    monkeypatch.setattr(gmail, "perfil", lambda t: {"email": "ana@gmail.com", "historyId": "1"})
    monkeypatch.setattr(gmail, "revocar", lambda t: None)
    monkeypatch.setattr(gmail, "token_de_acceso", lambda r: "tok")
    integraciones.conectar_gmail("u1", "c")
    estado = {"eventos": [], "ocupado": [], "creados": [], "error": None}

    def eventos(token, desde, hasta, zona):
        if estado["error"]:
            raise estado["error"]
        return estado["eventos"]

    def ocupado(token, desde, hasta):
        return estado["ocupado"]

    def crear(token, titulo, inicio, fin, zona, invitados, notas):
        estado["creados"].append((titulo, inicio, fin, zona, invitados))
        return {"id": "g9", "conferencing": {"url": "https://meet.google.com/abc"}}

    monkeypatch.setattr(gc, "eventos", eventos)
    monkeypatch.setattr(gc, "ocupado", ocupado)
    monkeypatch.setattr(gc, "crear_evento", crear)
    calendario._borradores.clear()
    return estado


@pytest.fixture
def con_outlook(google, monkeypatch):
    monkeypatch.setenv("ZERNIO_API_KEY", "z")
    integraciones.guardar_outlook("u1", "acc-o1", "ana@contoso.com")
    google["eventos_outlook"], google["huecos_outlook"], google["creados_outlook"] = [], [], []
    monkeypatch.setattr(zernio, "eventos", lambda c, d, h, z: google["eventos_outlook"])
    monkeypatch.setattr(zernio, "huecos", lambda c, d, h, m, hor: google["huecos_outlook"])
    monkeypatch.setattr(zernio, "crear_evento",
                        lambda *a: google["creados_outlook"].append(a) or {"conferencing": {"url": "https://teams/x"}})
    return google


def _evento(id_, inicio: datetime, titulo="Revision", minutos=30):
    return {"id": id_, "title": titulo, "start": inicio.isoformat(),
            "end": (inicio + timedelta(minutes=minutos)).isoformat(), "status": "confirmed",
            "participants": [], "conferencing": None}


def test_solo_google_lee_la_agenda(google):
    google["eventos"] = [_evento("g1", _manana(15))]
    texto = calendario.ver_agenda("u1")
    assert "1 evento(s)" in texto and "15:00-15:30 · Revision" in texto and "[Google]" not in texto


def test_sin_permiso_del_calendario_lo_dice(google):
    integraciones.quitar_calendario_google("u1")
    with pytest.raises(calendario.ErrorCalendario, match="Integraciones"):
        calendario.ver_agenda("u1")


def test_google_sin_permiso_real_quita_la_marca_y_explica(google):
    google["error"] = gc.ErrorGoogleCalendario("Insufficient Permission", 403, sin_permiso=True)
    with pytest.raises(calendario.ErrorCalendario, match="casilla del calendario"):
        calendario.ver_agenda("u1")
    assert not integraciones.calendario_google("u1")


def test_huecos_de_google_respetan_horario_y_ocupado(google):
    integraciones.guardar_horario("u1", "09:00", "11:00", [1, 2, 3, 4, 5, 6, 7], "America/Santo_Domingo")
    dia = _manana(9).date().isoformat()
    google["ocupado"] = [(_manana(9, 30).isoformat(), _manana(10).isoformat())]
    texto = calendario.ver_disponibilidad("u1", dia, dia, "30")
    assert "09:00 a 09:30" in texto and "10:00 a 10:30" in texto and "10:30 a 11:00" in texto
    assert "09:30 a 10:00" not in texto


def test_huecos_locales_saltan_dias_fuera_del_horario():
    horario = {"inicio": "09:00", "fin": "10:00", "dias": [1], "zona": "America/Santo_Domingo"}
    lunes = datetime(2026, 11, 23, tzinfo=RD)
    huecos = calendario._huecos_locales([], lunes - timedelta(days=1), lunes + timedelta(days=2), 30, horario)
    assert [(a.isoformat(), b.isoformat()) for a, b in huecos] == [
        ("2026-11-23T09:00:00-04:00", "2026-11-23T09:30:00-04:00"),
        ("2026-11-23T09:30:00-04:00", "2026-11-23T10:00:00-04:00")]


def test_reunion_en_google_con_meet(google):
    inicio = _manana(15)
    texto = calendario.preparar("u1", "Revision", inicio.strftime("%Y-%m-%d %H:%M"), "30", "p@x.com")
    assert "con Meet" in texto
    assert "https://meet.google.com/abc" in calendario.confirmar("u1")
    ((titulo, desde, hasta, zona, invitados),) = google["creados"]
    assert (titulo, desde, zona, invitados) == ("Revision", inicio.isoformat(), "America/Santo_Domingo", ["p@x.com"])


def test_con_los_dos_la_agenda_junta_y_marca(con_outlook):
    con_outlook["eventos"] = [_evento("g1", _manana(15), "De Google")]
    con_outlook["eventos_outlook"] = [_evento("o1", _manana(9), "De Outlook")]
    texto = calendario.ver_agenda("u1")
    assert "2 evento(s)" in texto
    assert texto.index("De Outlook") < texto.index("De Google")
    assert "De Outlook · Outlook" in texto and "De Google · Google" in texto


def test_con_los_dos_un_hueco_tiene_que_estar_libre_en_ambos(con_outlook):
    a, b = _manana(9), _manana(10)
    con_outlook["huecos_outlook"] = [{"from": a.isoformat(), "to": (a + timedelta(minutes=30)).isoformat()},
                                     {"from": b.isoformat(), "to": (b + timedelta(minutes=30)).isoformat()}]
    con_outlook["ocupado"] = [(b.isoformat(), (b + timedelta(hours=1)).isoformat())]
    texto = calendario.ver_disponibilidad("u1", a.date().isoformat(), a.date().isoformat())
    assert "09:00 a 09:30" in texto and "10:00 a 10:30" not in texto


def test_con_los_dos_la_reunion_pregunta_en_cual(con_outlook):
    inicio = _manana(15).strftime("%Y-%m-%d %H:%M")
    with pytest.raises(calendario.ErrorCalendario, match="desde"):
        calendario.preparar("u1", "X", inicio)
    assert "con Teams" in calendario.preparar("u1", "X", inicio, desde="outlook")
    calendario.confirmar("u1")
    assert len(con_outlook["creados_outlook"]) == 1 and con_outlook["creados"] == []
    assert "con Meet" in calendario.preparar("u1", "X", inicio, desde="google")


def test_aviso_previo_tambien_para_google(google, monkeypatch):
    monkeypatch.setattr(dispositivos, "usuario_para", lambda u: object())
    integraciones.guardar_reglas("u1", "x", "", True)
    inicio = (datetime.now(RD) + timedelta(minutes=10)).replace(second=0, microsecond=0)
    evento = _evento("g1", inicio)
    evento["conferencing"] = {"url": "https://meet.google.com/abc"}
    google["eventos"] = [evento]
    calendario.revisar("u1")
    calendario.revisar("u1")
    (aviso,) = avisos.listar("u1")
    assert aviso["tipo"] == "reunion" and aviso["app"] == "gmail" and aviso["asunto"] == "https://meet.google.com/abc"
    assert avisos._texto_whatsapp(aviso).endswith("Meet: https://meet.google.com/abc")


def test_una_vuelta_incluye_a_quien_tiene_solo_google(google, monkeypatch):
    revisados = []
    monkeypatch.setattr(calendario, "revisar", revisados.append)
    monkeypatch.setattr(avisos, "mandar_pendientes", lambda: None)
    calendario.una_vuelta()
    assert revisados == ["u1"]
