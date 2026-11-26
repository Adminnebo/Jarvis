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


def _agendada(bot):
    r = reuniones.proponer("u1", EVENTO)
    reuniones.pedir("u1", r["id"])
    return r["id"]


def test_eventos_cambian_el_estado(bot, monkeypatch):
    avisos_creados = []
    monkeypatch.setattr(reuniones, "_avisar", lambda rid, texto: avisos_creados.append(texto))
    rid = _agendada(bot)
    reuniones.recibir_evento(rid, {"tipo": "esperando"})
    assert rd.obtener(rid)["estado"] == "esperando"
    reuniones.recibir_evento(rid, {"tipo": "admitido"})
    assert rd.obtener(rid)["estado"] == "grabando"
    reuniones.recibir_evento(rid, {"tipo": "terminado", "motivo": "solo", "incompleta": True})
    fila = rd.obtener(rid)
    assert fila["estado"] == "procesando" and fila["incompleta"] == 1 and fila["terminada"]
    assert avisos_creados == []


def test_rechazado_y_fallo_avisan(bot, monkeypatch):
    avisos_creados = []
    monkeypatch.setattr(reuniones, "_avisar", lambda rid, texto: avisos_creados.append(texto))
    rid = _agendada(bot)
    reuniones.recibir_evento(rid, {"tipo": "rechazado", "motivo": "sin_respuesta"})
    assert rd.obtener(rid)["estado"] == "rechazada"
    assert "No me dejaron entrar" in avisos_creados[0]
    reuniones.recibir_evento(rid, {"tipo": "fallo", "motivo": "sesion_google"})
    assert rd.obtener(rid)["estado"] == "fallida" and "No pude entrar" in avisos_creados[1]


def test_audio_se_guarda_una_vez(bot):
    rid = _agendada(bot)
    assert reuniones.recibir_audio(rid, 1, b"OGG1") is True
    assert reuniones.recibir_audio(rid, 1, b"OGG1") is False
    assert reuniones.ruta_pedazo(rid, 1).read_bytes() == b"OGG1"


def test_hablantes(bot):
    rid = _agendada(bot)
    reuniones.recibir_hablantes(rid, [{"t": 3, "nombres": ["Ana"]}])
    assert rd.obtener(rid)["linea"] == [{"t": 3, "nombres": ["Ana"]}]


def test_herramienta_buscar_reuniones(bot):
    from backend import herramientas
    r = reuniones.proponer("u1", EVENTO)
    reuniones.pedir("u1", r["id"])
    rd.actualizar(r["id"], estado="lista", resumen="Se acordó bajar el precio del alambre.",
                  tareas=[{"quien": "Ana", "que": "mandar cotización", "cuando": "viernes"}])
    texto = herramientas.ejecutar("buscar_reuniones", '{"texto": "alambre"}', "u1")
    assert "Ventas" in texto and "bajar el precio" in texto and "Ana: mandar cotización (viernes)" in texto
    assert "No encontré" in herramientas.ejecutar("buscar_reuniones", '{"texto": "alambre"}', "u2")


def test_grabar_por_link_sin_calendario(bot):
    texto = reuniones.grabar_link("u1", "https://meet.google.com/pnp-gtkn-yer?pli=1&authuser=2", "Con Pedro")
    assert "voy a grabar «Con Pedro»" in texto
    (rid, url, ini, fin, _), = bot["agendadas"]
    assert url == "https://meet.google.com/pnp-gtkn-yer"
    assert rd.obtener(rid)["estado"] == "agendada" and rd.interesados(rid) == ["u1"]
    from datetime import datetime
    assert (datetime.fromisoformat(fin) - datetime.fromisoformat(ini)).total_seconds() == 2 * 3600


def test_grabar_por_link_sin_titulo_y_link_malo(bot):
    assert "«Meet" in reuniones.grabar_link("u1", "meet.google.com/abc-defg-hij")
    assert "no es un link de Google Meet" in reuniones.grabar_link("u1", "https://zoom.us/j/123")
    assert len(bot["agendadas"]) == 1


def test_grabar_por_link_sin_bot(bot, monkeypatch):
    monkeypatch.setattr(bot_meet, "configurado", lambda: False)
    assert "no está configurado" in reuniones.grabar_link("u1", "https://meet.google.com/abc-defg-hij")


def test_herramienta_grabar_meet(bot):
    from backend import herramientas
    texto = herramientas.ejecutar("grabar_meet", '{"link": "https://meet.google.com/abc-defg-hij"}', "u1")
    assert "voy a grabar" in texto and len(bot["agendadas"]) == 1


def test_en_curso_con_la_hora_en_que_entro(bot):
    rid = _agendada(bot)
    assert [(x["id"], x["estado"], x["grabando_desde"]) for x in reuniones.en_curso("u1")] == [(rid, "agendada", None)]
    reuniones.recibir_evento(rid, {"tipo": "admitido"})
    (x,) = reuniones.en_curso("u1")
    assert x["estado"] == "grabando" and x["grabando_desde"]
    assert reuniones.en_curso("u2") == []          # solo las de quien la pidió
    reuniones.recibir_evento(rid, {"tipo": "terminado", "motivo": "solo", "incompleta": False})
    assert reuniones.en_curso("u1") == []          # procesando ya no está "en curso"


def test_en_curso_primero_lo_que_graba_y_sin_agendadas_vencidas(bot):
    from datetime import datetime, timedelta
    ahora = datetime.now(reuniones.ZONA).replace(microsecond=0)
    vieja = {**EVENTO, "conferencing": {"url": "https://meet.google.com/aaa-bbbb-ccc"},
             "start": (ahora - timedelta(hours=3)).isoformat(), "end": (ahora - timedelta(hours=2)).isoformat()}
    futura = {**EVENTO, "conferencing": {"url": "https://meet.google.com/ddd-eeee-fff"},
              "start": (ahora + timedelta(hours=1)).isoformat(), "end": (ahora + timedelta(hours=2)).isoformat()}
    viva = {**EVENTO, "conferencing": {"url": "https://meet.google.com/ggg-hhhh-iii"},
            "start": (ahora + timedelta(hours=2)).isoformat(), "end": (ahora + timedelta(hours=3)).isoformat()}
    ids = {}
    for nombre, e in (("vieja", vieja), ("futura", futura), ("viva", viva)):
        r = reuniones.proponer("u1", e)
        reuniones.pedir("u1", r["id"])
        ids[nombre] = r["id"]
    reuniones.recibir_evento(ids["viva"], {"tipo": "admitido"})
    assert [x["id"] for x in reuniones.en_curso("u1")] == [ids["viva"], ids["futura"]]


def test_sacar_al_bot_mientras_graba(bot):
    rid = _agendada(bot)
    reuniones.recibir_evento(rid, {"tipo": "admitido"})
    assert "saco al bot" in reuniones.sacar("u1", rid)
    assert bot["canceladas"] == [rid]
    assert rd.obtener(rid)["estado"] == "grabando"   # lo grabado llega con el "terminado" del bot


def test_sacar_antes_de_que_entre_lo_cancela(bot):
    rid = _agendada(bot)
    reuniones.sacar("u1", rid)
    assert rd.obtener(rid)["estado"] == "cancelada"


def test_sacarlo_en_la_sala_de_espera_no_avisa_como_rechazo(bot, monkeypatch):
    avisos_creados = []
    monkeypatch.setattr(reuniones, "_avisar", lambda rid, texto: avisos_creados.append(texto))
    rid = _agendada(bot)
    reuniones.recibir_evento(rid, {"tipo": "esperando"})
    reuniones.sacar("u1", rid)
    reuniones.recibir_evento(rid, {"tipo": "rechazado", "motivo": "cancelada"})
    assert rd.obtener(rid)["estado"] == "cancelada" and avisos_creados == []


def test_sacar_solo_quien_la_pidio(bot):
    rid = _agendada(bot)
    assert "No encontré" in reuniones.sacar("u2", rid) and bot["canceladas"] == []


def test_enlace_firmado(bot, monkeypatch):
    monkeypatch.setenv("JARVIS_CLAVE_SECRETA", "x" * 40)
    r = reuniones.proponer("u1", EVENTO)
    url = reuniones.enlace("u1", r["id"], "grabar")
    assert url.startswith("https://asistente.neboaiconsulting.com/reuniones/accion?")
    from urllib.parse import parse_qs, urlparse
    q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    assert reuniones.verificar_enlace(q["u"], q["r"], q["a"], q["f"]) is True
    assert reuniones.verificar_enlace("u2", q["r"], q["a"], q["f"]) is False
