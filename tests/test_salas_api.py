from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from backend import avisos, main, salas
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


@pytest.fixture
def sala(entrar):
    c = entrar("la-del-admin")
    x = c.post("/api/reuniones/presencial", json={"titulo": "Con el equipo", "sala": True}).json()
    return c, x


def test_crear_sala_y_ver_quien_esta(sala):
    c, x = sala
    assert x["link"].endswith("/sala/" + x["sala"]) and x["participante_token"]
    d = c.get(f"/api/reuniones/{x['id']}/sala").json()
    (yo,) = d["participantes"]                       # quien organiza, con su cuenta
    assert d["abierta"] and yo["equipo"] and yo["nombre"]
    svg = c.get(f"/api/reuniones/{x['id']}/sala/qr.svg")
    assert svg.status_code == 200 and svg.headers["content-type"].startswith("image/svg+xml") and b"<svg" in svg.content


def test_invitado_entra_sin_cuenta_y_manda_niveles(sala):
    c, x = sala
    afuera = TestClient(main.app)
    assert afuera.get(f"/sala/{x['sala']}").status_code == 200                       # la página
    assert afuera.get("/apps/sala.js").status_code == 200 and afuera.get("/apps/niveles.js").status_code == 200
    e = afuera.get(f"/api/salas/{x['sala']}").json()
    assert e == {"titulo": "Con el equipo", "abierta": True, "nombre": ""}
    assert afuera.post(f"/api/salas/{x['sala']}/unirse", json={"nombre": " "}).status_code == 400
    p = afuera.post(f"/api/salas/{x['sala']}/unirse", json={"nombre": "Lucas"}).json()
    base = int(datetime.fromisoformat(rd.obtener(x["id"])["grabando_desde"]).timestamp() * 1000)
    cuerpo = {"participante": p["participante"], "token": p["token"], "desde_ms": base + 2000, "niveles": [0.3, 0.1]}
    assert afuera.post(f"/api/salas/{x['sala']}/niveles", json=cuerpo).json() == {"seguir": True}
    assert afuera.post(f"/api/salas/{x['sala']}/niveles", json={**cuerpo, "token": "malo"}).status_code == 401
    # Cuando quien organiza termina, los teléfonos se enteran y paran.
    c.post(f"/api/reuniones/{x['id']}/sacar")
    assert afuera.post(f"/api/salas/{x['sala']}/niveles", json=cuerpo).json() == {"seguir": False}
    assert afuera.post(f"/api/salas/{x['sala']}/unirse", json={"nombre": "Tarde"}).status_code == 409


def test_con_cuenta_el_nombre_sale_de_la_sesion(sala, entrar):
    _, x = sala
    ana = entrar("la-de-ana")
    assert ana.get(f"/api/salas/{x['sala']}").json()["nombre"] == "Ana"
    p = ana.post(f"/api/salas/{x['sala']}/unirse", json={"nombre": "otra cosa"}).json()
    assert p["nombre"] == "Ana"
    assert any(u.startswith("ana") or u == "ana" for u in rd.interesados(x["id"]))


def test_sala_que_no_existe_y_rutas_de_otro(sala, entrar):
    _, x = sala
    afuera = TestClient(main.app)
    assert afuera.get("/api/salas/AAAAAAAAAAAA").status_code == 404
    assert afuera.get("/api/salas/corto").status_code in (401, 404)                 # ni siquiera es libre
    assert afuera.get(f"/api/reuniones/{x['id']}/sala").status_code == 401           # sin sesión
    assert entrar("la-de-ana").get(f"/api/reuniones/{x['id']}/sala").status_code == 404


def test_equipo_e_invitar(sala, monkeypatch):
    c, x = sala
    monkeypatch.setattr(salas, "equipo", lambda u: [{"id": "sb-1", "nombre": "Edmond"}])
    creados = []
    monkeypatch.setattr(avisos, "crear", lambda *a, **k: creados.append(a) or True)
    assert c.get("/api/reuniones/equipo").json() == {"equipo": [{"id": "sb-1", "nombre": "Edmond"}]}
    assert c.post(f"/api/reuniones/{x['id']}/invitar", json={"usuarios": ["sb-1"]}).json() == {"enviadas": 1}
    assert creados[0][0] == "sb-1"
