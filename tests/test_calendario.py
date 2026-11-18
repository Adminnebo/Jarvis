from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from backend import calendario, integraciones, zernio

RD = ZoneInfo("America/Santo_Domingo")


@pytest.fixture
def conectado(monkeypatch):
    monkeypatch.setenv("ZERNIO_API_KEY", "z")
    integraciones.guardar_outlook("u1", "acc-o1", "ana@contoso.com")
    estado = {"eventos": [], "huecos": [], "creados": [], "pedidos": []}

    def eventos(cuenta, desde, hasta, zona):
        estado["pedidos"].append((cuenta, desde, hasta, zona))
        return estado["eventos"]

    def huecos(cuenta, desde, hasta, minutos, horario):
        estado["pedidos"].append((cuenta, desde, hasta, minutos, horario))
        return estado["huecos"]

    def crear(cuenta, titulo, inicio, fin, zona, invitados, notas):
        estado["creados"].append((cuenta, titulo, inicio, fin, zona, invitados, notas))
        return estado.get("respuesta", {"id": "ev1", "conferencing": {"url": "https://teams/x"}})

    monkeypatch.setattr(zernio, "eventos", eventos)
    monkeypatch.setattr(zernio, "huecos", huecos)
    monkeypatch.setattr(zernio, "crear_evento", crear)
    calendario._borradores.clear()
    return estado


def test_sin_outlook_lo_dice():
    with pytest.raises(calendario.ErrorCalendario, match="Integraciones"):
        calendario.ver_agenda("nadie")


def test_momento_acepta_fecha_y_fecha_con_hora():
    assert calendario._momento("2026-11-20", RD) == datetime(2026, 11, 20, tzinfo=RD)
    assert calendario._momento("2026-11-20", RD, fin_de_dia=True) == datetime(2026, 11, 21, tzinfo=RD)
    assert calendario._momento("2026-11-20 15:30", RD) == datetime(2026, 11, 20, 15, 30, tzinfo=RD)
    with pytest.raises(calendario.ErrorCalendario, match="AAAA-MM-DD"):
        calendario._momento("el jueves", RD)


def test_agenda_lista_hora_invitados_y_teams(conectado):
    conectado["eventos"] = [
        {"id": "e1", "title": "Revision", "start": "2026-11-20T15:00:00-04:00", "end": "2026-11-20T15:30:00-04:00",
         "participants": [{"email": "ana@contoso.com", "self": True}, {"email": "p@x.com", "name": "Pedro"}],
         "conferencing": {"url": "https://teams/x"}, "status": "confirmed"},
        {"id": "e2", "title": "Feriado", "start": "2026-11-21", "end": "2026-11-22", "allDay": True},
        {"id": "e3", "title": "Cancelada", "start": "2026-11-20T09:00:00-04:00", "end": "2026-11-20T10:00:00-04:00",
         "status": "cancelled"},
    ]
    texto = calendario.ver_agenda("u1", "2026-11-20", "2026-11-21")
    assert "2 evento(s)" in texto and "viernes 20/11 15:00-15:30 · Revision · con Pedro · Teams: https://teams/x" in texto
    assert "2026-11-21 (todo el dia)" in texto and "Cancelada" not in texto
    (_, desde, hasta, zona) = conectado["pedidos"][0]
    assert desde == "2026-11-20T00:00:00-04:00" and hasta == "2026-11-22T00:00:00-04:00"
    assert zona == "America/Santo_Domingo"


def test_agenda_vacia(conectado):
    assert "No tienes nada" in calendario.ver_agenda("u1", "2026-11-20", "2026-11-20")


def test_disponibilidad_usa_el_horario_y_lista_huecos(conectado):
    integraciones.guardar_horario("u1", "09:00", "17:00", [1, 2, 3, 4, 5], "America/Santo_Domingo")
    manana = (datetime.now(RD) + timedelta(days=1)).date().isoformat()
    conectado["huecos"] = [{"from": f"{manana}T13:00:00Z", "to": f"{manana}T13:30:00Z"}]
    texto = calendario.ver_disponibilidad("u1", manana, manana, "30")
    assert "Huecos libres de 30 min" in texto and "09:00 a 09:30" in texto
    (_, _, _, minutos, horario) = conectado["pedidos"][0]
    assert minutos == 30 and horario["inicio"] == "09:00"


def test_disponibilidad_sin_huecos_y_duracion_mala(conectado):
    assert "No encontre huecos" in calendario.ver_disponibilidad("u1")
    with pytest.raises(calendario.ErrorCalendario, match="minutos"):
        calendario.ver_disponibilidad("u1", duracion="media hora")


def test_preparar_no_crea_y_confirmar_si(conectado):
    inicio = (datetime.now(RD) + timedelta(days=1)).replace(hour=15, minute=0, second=0, microsecond=0)
    texto = calendario.preparar("u1", "Revision", inicio.strftime("%Y-%m-%d %H:%M"), "30", "Pedro <p@x.com>", "Traer contrato")
    assert "confirmar_reunion" in texto and "p@x.com" in texto and conectado["creados"] == []
    assert "https://teams/x" in calendario.confirmar("u1")
    ((cuenta, titulo, desde, hasta, zona, invitados, notas),) = conectado["creados"]
    assert (cuenta, titulo, zona, invitados, notas) == ("acc-o1", "Revision", "America/Santo_Domingo",
                                                         ["p@x.com"], "Traer contrato")
    assert desde == inicio.isoformat() and hasta == (inicio + timedelta(minutes=30)).isoformat()


def test_confirmar_sin_borrador_o_vencido_no_crea(conectado, monkeypatch):
    with pytest.raises(calendario.ErrorCalendario, match="pendiente"):
        calendario.confirmar("u1")
    inicio = (datetime.now(RD) + timedelta(days=1)).strftime("%Y-%m-%d 10:00")
    calendario.preparar("u1", "X", inicio)
    calendario._borradores["u1"].creado -= calendario.VIGENCIA + 1
    with pytest.raises(calendario.ErrorCalendario, match="pendiente"):
        calendario.confirmar("u1")
    assert conectado["creados"] == []


def test_sin_teams_lo_dice(conectado):
    conectado["respuesta"] = {"id": "ev1", "conferencing": None}
    calendario.preparar("u1", "X", (datetime.now(RD) + timedelta(days=1)).strftime("%Y-%m-%d 10:00"))
    assert "sin enlace de Teams" in calendario.confirmar("u1")


@pytest.mark.parametrize("titulo, inicio, invitados, motivo", [
    ("", "2030-01-01 10:00", "", "titulo"),
    ("X", "2030-01-01", "", "hora"),
    ("X", "2020-01-01 10:00", "", "paso"),
    ("X", "2030-01-01 10:00", "pedro", "correos"),
])
def test_preparar_valida(conectado, titulo, inicio, invitados, motivo):
    with pytest.raises(calendario.ErrorCalendario, match=motivo):
        calendario.preparar("u1", titulo, inicio, "30", invitados)
