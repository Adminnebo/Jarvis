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


from backend import avisos, dispositivos


@pytest.fixture
def con_reunion(conectado, monkeypatch):
    monkeypatch.setattr(dispositivos, "usuario_para", lambda u: object() if u == "u1" else None)
    integraciones.guardar_reglas("u1", "x", "8095551234", True)
    inicio = (datetime.now(RD) + timedelta(minutes=10)).replace(second=0, microsecond=0)
    conectado["inicio"] = inicio
    conectado["eventos"] = [{
        "id": "e1", "title": "Revision", "start": inicio.isoformat(), "end": (inicio + timedelta(minutes=30)).isoformat(),
        "participants": [{"email": "ana@contoso.com", "self": True, "status": "accepted"},
                         {"email": "p@x.com", "name": "Pedro"}],
        "conferencing": {"url": "https://teams/x"}, "status": "confirmed"}]
    resumenes = []
    monkeypatch.setattr(calendario, "_resumen_invitados",
                        lambda usuario, u, invitados: resumenes.append(invitados) or "Pedro pidio precio")
    conectado["resumenes"] = resumenes
    return conectado


def test_aviso_previo_sale_una_vez(con_reunion):
    calendario.revisar("u1")
    calendario.revisar("u1")
    (aviso,) = avisos.listar("u1")
    assert aviso["tipo"] == "reunion" and aviso["asunto"] == "https://teams/x" and aviso["whatsapp"] == "pendiente"
    assert aviso["resumen"] == f"{con_reunion['inicio']:%H:%M} · Revision. Pedro pidio precio"
    assert con_reunion["resumenes"] == [[{"email": "p@x.com", "name": "Pedro"}]]


def test_si_la_reunion_se_mueve_avisa_otra_vez(con_reunion):
    calendario.revisar("u1")
    nuevo = con_reunion["inicio"] + timedelta(minutes=2)
    con_reunion["eventos"][0]["start"] = nuevo.isoformat()
    calendario.revisar("u1")
    assert len(avisos.listar("u1")) == 2


@pytest.mark.parametrize("cambio", [
    {"allDay": True},
    {"status": "cancelled"},
    {"participants": [{"email": "ana@contoso.com", "self": True, "status": "declined"}]},
])
def test_no_avisa_de_todo_el_dia_cancelada_o_rechazada(con_reunion, cambio):
    con_reunion["eventos"][0].update(cambio)
    calendario.revisar("u1")
    assert avisos.listar("u1") == []


def test_no_avisa_si_falta_mucho(con_reunion):
    lejos = datetime.now(RD) + timedelta(minutes=25)
    con_reunion["eventos"][0]["start"] = lejos.isoformat()
    calendario.revisar("u1")
    assert avisos.listar("u1") == []


def test_si_el_resumen_falla_avisa_igual(con_reunion, monkeypatch):
    def falla(*a):
        raise RuntimeError("ia caida")

    monkeypatch.setattr(calendario, "_resumen_invitados", falla)
    calendario.revisar("u1")
    (aviso,) = avisos.listar("u1")
    assert aviso["resumen"] == f"{con_reunion['inicio']:%H:%M} · Revision"


def test_resumen_invitados_junta_correo_y_chats(monkeypatch):
    from backend import correo, whatsapp_chats

    monkeypatch.setattr(correo, "buscar", lambda u, q, n: f"correos con {q}")
    monkeypatch.setattr(whatsapp_chats, "buscar", lambda u, t: f"chats con {t}")
    vistos = []
    monkeypatch.setattr(calendario, "_resumir", lambda usuario, texto: vistos.append(texto) or "listo")
    assert calendario._resumen_invitados(object(), "u1", [{"email": "p@x.com", "name": "Pedro"}]) == "listo"
    assert "INVITADO: Pedro" in vistos[0] and "correos con p@x.com" in vistos[0] and "chats con Pedro" in vistos[0]
    assert calendario._resumen_invitados(object(), "u1", []) == ""
