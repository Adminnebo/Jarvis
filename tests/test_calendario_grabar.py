from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from backend import avisos, bot_meet, calendario
from backend import reuniones_datos as rd

RD = ZoneInfo("America/Santo_Domingo")


@pytest.fixture
def entorno(monkeypatch):
    monkeypatch.setenv("JARVIS_CLAVE_SECRETA", "x" * 40)
    monkeypatch.setattr(bot_meet, "configurado", lambda: True)
    agendadas = []
    monkeypatch.setattr(bot_meet, "agendar", lambda *a: agendadas.append(a))
    creados = []
    monkeypatch.setattr(avisos, "crear", lambda *a, **k: creados.append((a, k)) or True)
    monkeypatch.setattr(avisos, "existe", lambda *a: False)
    monkeypatch.setattr(calendario, "_resumen_invitados", lambda *a: "")
    return agendadas, creados


def evento(ahora):
    return {"id": "e1", "title": "Ventas", "start": (ahora + timedelta(minutes=10)).isoformat(),
            "end": (ahora + timedelta(minutes=70)).isoformat(), "participants": [],
            "conferencing": {"url": "https://meet.google.com/abc-defg-hij"}}


def avisar(ahora):
    calendario._avisar(None, "u1", "google", evento(ahora), ahora, RD, {"whatsapp": "1809", "activo": True})


def test_sin_grabar_siempre_el_aviso_ofrece_grabar(entorno):
    agendadas, creados = entorno
    avisar(datetime.now(RD))
    (args, kw), = creados
    rid = args[2]   # hilo = id de la reunión
    assert rd.obtener(rid)["estado"] == "propuesta" and agendadas == []
    assert "Grabar: https://asistente.neboaiconsulting.com/reuniones/accion?" in args[5]


def test_con_grabar_siempre_agenda_y_ofrece_no_grabar(entorno):
    agendadas, creados = entorno
    rd.poner_grabar_siempre("u1", True)
    avisar(datetime.now(RD))
    (args, kw), = creados
    assert len(agendadas) == 1 and rd.obtener(args[2])["estado"] == "agendada"
    assert "voy a grabar" in args[5] and "No grabar: " in args[5]


def test_el_enlace_llega_entero_aunque_haya_resumen_de_invitados(monkeypatch):
    # Con el avisos.crear de verdad: antes guardaba 300 caracteres y cortaba el enlace.
    monkeypatch.setenv("JARVIS_CLAVE_SECRETA", "x" * 40)
    monkeypatch.setattr(bot_meet, "configurado", lambda: True)
    monkeypatch.setattr(calendario, "_resumen_invitados", lambda *a: "R" * 240)
    ahora = datetime.now(RD)
    e = {**evento(ahora), "participants": [{"email": "ana@x.com", "name": "Ana"}]}
    calendario._avisar(None, "u1", "google", e, ahora, RD, {"whatsapp": None, "activo": True})
    aviso, = avisos.listar("u1")
    enlace = aviso["resumen"].split("Grabar: ")[1]
    from urllib.parse import parse_qs, urlparse
    from backend import reuniones
    q = {k: v[0] for k, v in parse_qs(urlparse(enlace).query).items()}
    assert reuniones.verificar_enlace(q["u"], q["r"], q["a"], q["f"])


def test_sin_bot_el_aviso_sale_como_antes(entorno, monkeypatch):
    _, creados = entorno
    monkeypatch.setattr(bot_meet, "configurado", lambda: False)
    avisar(datetime.now(RD))
    (args, kw), = creados
    assert args[2] is None and "Grabar" not in args[5]
