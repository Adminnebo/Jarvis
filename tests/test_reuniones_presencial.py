from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend import bot_meet, main, reuniones, reuniones_trabajo
from backend import reuniones_datos as rd


@pytest.fixture
def entrar(monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setenv("JARVIS_PASSWORD_ANA", "la-de-ana")

    def con(clave):
        c = TestClient(main.app)
        c.post("/acceso", data={"clave": clave}, follow_redirects=False)
        return c
    return con


def test_crear_y_subir_con_su_token(entrar):
    c = entrar("la-del-admin")
    x = c.post("/api/reuniones/presencial", json={"titulo": "Con Lucas"}).json()
    assert len(x["id"]) == 32 and x["token"] and x["pedazo_s"] == 300 and x["max_s"] == 4 * 3600
    r = rd.obtener(x["id"])
    assert r["tipo"] == "presencial" and r["estado"] == "grabando" and r["grabando_desde"]
    assert r["titulo"] == "Con Lucas" and r["meet_url"] == ""
    afuera = TestClient(main.app)    # sin sesión, solo con el token
    cab = {"Authorization": f"Bearer {x['token']}", "Content-Type": "audio/webm"}
    assert afuera.post(f"/api/reuniones/{x['id']}/audio?n=1&inicio_s=0", content=b"W", headers=cab).json()["parar"] is False
    (e,) = c.get("/api/reuniones/en-curso").json()["reuniones"]
    assert e["id"] == x["id"] and e["tipo"] == "presencial"
    assert entrar("la-de-ana").get("/api/reuniones/en-curso").json()["reuniones"] == []


def test_titulo_por_defecto(entrar):
    x = entrar("la-del-admin").post("/api/reuniones/presencial", json={}).json()
    assert rd.obtener(x["id"])["titulo"].startswith("Reunión presencial de las ")


def test_terminar_desde_el_aparato_no_espera_hablantes(entrar):
    x = entrar("la-del-admin").post("/api/reuniones/presencial", json={}).json()
    reuniones.recibir_evento(x["id"], {"tipo": "terminado", "motivo": "usuario"})
    r = rd.obtener(x["id"])
    assert r["estado"] == "procesando" and r["linea"] == [] and r["terminada"]


def test_sacar_una_presencial_no_llama_al_bot(entrar, monkeypatch):
    monkeypatch.setattr(bot_meet, "cancelar", lambda r: pytest.fail("no hay bot"))
    c = entrar("la-del-admin")
    x = c.post("/api/reuniones/presencial", json={}).json()
    m = c.post(f"/api/reuniones/{x['id']}/sacar").json()["mensaje"]
    assert m.startswith("Listo, terminé la grabación")
    r = rd.obtener(x["id"])
    assert r["estado"] == "procesando" and r["motivo"] == "sacada" and r["linea"] is None   # 120 s de gracia
    # El "terminado" que manda el aparato después no le cambia la hora, solo acorta la espera.
    terminada = r["terminada"]
    reuniones.recibir_evento(x["id"], {"tipo": "terminado", "motivo": "sacada"})
    r = rd.obtener(x["id"])
    assert r["terminada"] == terminada and r["linea"] == []


def test_un_terminado_tarde_no_reabre_una_lista(entrar):
    x = entrar("la-del-admin").post("/api/reuniones/presencial", json={}).json()
    rd.actualizar(x["id"], estado="lista")
    reuniones.recibir_evento(x["id"], {"tipo": "terminado", "motivo": "usuario"})
    assert rd.obtener(x["id"])["estado"] == "lista"


def test_tope_de_cuatro_horas():
    x = reuniones.crear_presencial("admin", "Larga")
    hace = (datetime.now(timezone.utc) - timedelta(hours=4, minutes=11)).isoformat(timespec="seconds")
    rd.actualizar(x["id"], grabando_desde=hace)
    reuniones_trabajo.vencer_presenciales()
    r = rd.obtener(x["id"])
    assert r["estado"] == "procesando" and r["motivo"] == "maximo" and r["linea"] == []
