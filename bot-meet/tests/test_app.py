import json
import time

from fastapi.testclient import TestClient

from bot_meet.agenda import Agenda
from bot_meet.app import crear_app
from bot_meet.config import Config
from bot_meet.firma import firmar

S = "s" * 32
CUERPO = {"id": "r1", "meet_url": "https://meet.google.com/abc-defg-hij",
          "inicio": "2026-12-01T14:00:00+00:00", "fin": "2026-12-01T15:00:00+00:00",
          "token_subida": "tok", "url_jarvis": "https://asistente.neboaiconsulting.com"}


def cliente(tmp_path, max_sesiones=2):
    config = Config(secreto=S, datos=tmp_path, max_sesiones=max_sesiones)
    agenda = Agenda(tmp_path / "agenda.json", max_sesiones=max_sesiones)
    return TestClient(crear_app(config, agenda, lanzador=None)), agenda


def firmado(metodo, ruta, cuerpo=b""):
    t = int(time.time())
    return {"X-Bot-Tiempo": str(t), "X-Bot-Firma": firmar(S, t, metodo, ruta, cuerpo)}


def post(c, cuerpo):
    datos = json.dumps(cuerpo).encode()
    return c.post("/v1/sesiones", content=datos,
                  headers={**firmado("POST", "/v1/sesiones", datos), "Content-Type": "application/json"})


def test_agenda_una_sesion(tmp_path):
    c, agenda = cliente(tmp_path)
    r = post(c, CUERPO)
    assert r.status_code == 202 and r.json() == {"estado": "agendada"}
    assert agenda.obtener("r1").token_subida == "tok"


def test_sin_firma_401(tmp_path):
    c, _ = cliente(tmp_path)
    assert c.post("/v1/sesiones", json=CUERPO).status_code == 401


def test_link_invalido_400(tmp_path):
    c, _ = cliente(tmp_path)
    r = post(c, {**CUERPO, "meet_url": "https://zoom.us/j/1"})
    assert r.status_code == 400 and r.json() == {"error": "link_invalido"}


def test_datos_invalidos_400(tmp_path):
    c, _ = cliente(tmp_path)
    assert post(c, {"id": "r1"}).json() == {"error": "datos_invalidos"}
    assert post(c, {**CUERPO, "url_jarvis": "ftp://x"}).json() == {"error": "datos_invalidos"}


def test_sin_bot_libre_409(tmp_path):
    c, _ = cliente(tmp_path, max_sesiones=1)
    post(c, CUERPO)
    r = post(c, {**CUERPO, "id": "r2"})
    assert r.status_code == 409 and r.json() == {"error": "sin_bot_libre"}


def test_cancelar(tmp_path):
    c, agenda = cliente(tmp_path)
    post(c, CUERPO)
    r = c.delete("/v1/sesiones/r1", headers=firmado("DELETE", "/v1/sesiones/r1"))
    assert r.status_code == 200 and agenda.obtener("r1").estado == "cancelada"
    assert c.delete("/v1/sesiones/r9", headers=firmado("DELETE", "/v1/sesiones/r9")).status_code == 404


def test_salud_sin_firma(tmp_path):
    c, _ = cliente(tmp_path)
    post(c, CUERPO)
    d = c.get("/v1/salud").json()
    assert d["ok"] is True and d["agendadas"] == 1 and d["activas"] == 0
    assert "memoria_libre_mb" in d and "carga" in d
