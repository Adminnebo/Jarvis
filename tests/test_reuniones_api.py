import pytest
from fastapi.testclient import TestClient

from backend import bot_meet, main, reuniones
from backend import reuniones_datos as rd

EVENTO = {"id": "e1", "title": "Ventas", "start": "2026-12-01T14:00:00-04:00",
          "end": "2026-12-01T15:00:00-04:00", "conferencing": {"url": "https://meet.google.com/abc-defg-hij"}}


@pytest.fixture
def reunion(monkeypatch):
    monkeypatch.setenv("JARVIS_CLAVE_SECRETA", "x" * 40)
    monkeypatch.setattr(bot_meet, "configurado", lambda: True)
    tokens = []
    monkeypatch.setattr(bot_meet, "agendar", lambda rid, u, i, f, tok: tokens.append(tok))
    r = reuniones.proponer("u1", EVENTO)
    reuniones.pedir("u1", r["id"])
    return r["id"], tokens[0]


def test_el_bot_entra_con_su_token(reunion):
    rid, token = reunion
    c = TestClient(main.app)
    cab = {"Authorization": f"Bearer {token}"}
    assert c.post(f"/api/reuniones/{rid}/eventos", json={"tipo": "admitido"}, headers=cab).status_code == 200
    assert rd.obtener(rid)["estado"] == "grabando"
    assert c.post(f"/api/reuniones/{rid}/audio?n=1", content=b"OGG", headers=cab).status_code == 200
    assert c.post(f"/api/reuniones/{rid}/audio?n=1", content=b"OGG", headers=cab).status_code == 409
    assert c.post(f"/api/reuniones/{rid}/hablantes", json={"linea": []}, headers=cab).status_code == 200


def test_sin_token_o_con_otro_no_entra(reunion):
    rid, _ = reunion
    c = TestClient(main.app)
    assert c.post(f"/api/reuniones/{rid}/eventos", json={"tipo": "admitido"}).status_code == 401
    assert c.post(f"/api/reuniones/{rid}/eventos", json={"tipo": "admitido"},
                  headers={"Authorization": "Bearer otro"}).status_code == 401


def test_audio_demasiado_grande(reunion):
    rid, token = reunion
    c = TestClient(main.app)
    grande = b"x" * (20 * 1024 * 1024 + 1)
    r = c.post(f"/api/reuniones/{rid}/audio?n=1", content=grande, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 413


def test_enlace_de_whatsapp_muestra_y_confirma(reunion, monkeypatch):
    rid, _ = reunion
    llamadas = []
    monkeypatch.setattr(reuniones, "no_grabar", lambda u, r: llamadas.append((u, r)) or "Listo, no grabo «Ventas».")
    url = reuniones.enlace("u1", rid, "no_grabar").replace("https://asistente.neboaiconsulting.com", "")
    c = TestClient(main.app)
    pagina = c.get(url)   # WhatsApp abre la vista previa con GET: no debe hacer nada
    assert pagina.status_code == 200 and "<form" in pagina.text and llamadas == []
    r = c.post(url)
    assert r.status_code == 200 and "no grabo" in r.text and llamadas == [("u1", rid)]
    assert c.post(url.replace("f=", "f=00")).status_code == 403


@pytest.fixture
def entrar(monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setenv("JARVIS_PASSWORD_ANA", "la-de-ana")

    def con(clave):
        c = TestClient(main.app)
        c.post("/acceso", data={"clave": clave}, follow_redirects=False)
        return c
    return con


def test_lista_detalle_y_preferencias(reunion, entrar):
    rid, _ = reunion
    reuniones.pedir("admin", rid)
    c = entrar("la-del-admin")
    assert [x["id"] for x in c.get("/api/reuniones").json()["reuniones"]] == [rid]
    assert c.get(f"/api/reuniones/{rid}").json()["titulo"] == "Ventas"
    assert c.put("/api/reuniones/preferencias", json={"grabar_siempre": True}).json() == {"grabar_siempre": True}
    assert c.get("/api/reuniones/preferencias").json() == {"grabar_siempre": True, "disponible": True}
    assert entrar("la-de-ana").get(f"/api/reuniones/{rid}").status_code == 404


def test_grabar_un_link_desde_la_vista(reunion, entrar):
    c = entrar("la-de-ana")
    r = c.post("/api/reuniones/grabar-link", json={"url": "https://meet.google.com/xyz-abcd-efg", "titulo": ""})
    assert r.status_code == 200 and "voy a grabar" in r.json()["mensaje"]
    assert [x["meet_url"] for x in c.get("/api/reuniones").json()["reuniones"]] == ["https://meet.google.com/xyz-abcd-efg"]
    malo = c.post("/api/reuniones/grabar-link", json={"url": "https://zoom.us/j/1"})
    assert malo.status_code == 400


def test_en_curso_y_sacar_desde_la_vista(reunion, entrar, monkeypatch):
    rid, _ = reunion
    canceladas = []
    monkeypatch.setattr(bot_meet, "cancelar", lambda r: canceladas.append(r) or True)
    reuniones.pedir("admin", rid)
    c = entrar("la-del-admin")
    (x,) = c.get("/api/reuniones/en-curso").json()["reuniones"]
    assert x["id"] == rid and x["estado"] == "agendada" and "grabando_desde" in x
    assert "no va a entrar" in c.post(f"/api/reuniones/{rid}/sacar").json()["mensaje"]   # aún no había entrado
    assert canceladas == [rid]
    assert c.get("/api/reuniones/en-curso").json()["reuniones"] == []
    assert entrar("la-de-ana").post(f"/api/reuniones/{rid}/sacar").json()["mensaje"].startswith("No encontré")


def test_grabar_desde_la_campanita(reunion, entrar):
    rid, _ = reunion
    c = entrar("la-de-ana")
    assert "grabar" in c.post(f"/api/reuniones/{rid}/grabar").json()["mensaje"].lower()
    assert "ana" in rd.interesados(rid)


def test_audio_con_formato_y_parar(reunion):
    rid, token = reunion
    c = TestClient(main.app)
    cab = {"Authorization": f"Bearer {token}"}
    c.post(f"/api/reuniones/{rid}/eventos", json={"tipo": "admitido"}, headers=cab)
    r = c.post(f"/api/reuniones/{rid}/audio?n=1&inicio_s=0", content=b"W",
               headers={**cab, "Content-Type": "audio/webm;codecs=opus"})
    assert r.status_code == 200 and r.json() == {"ok": True, "parar": False}
    (p,) = rd.pedazos(rid)
    assert p["formato"] == "webm" and p["inicio_s"] == 0
    assert reuniones.ruta_pedazo(rid, 1, "webm").read_bytes() == b"W"
    malo = c.post(f"/api/reuniones/{rid}/audio?n=2", content=b"X", headers={**cab, "Content-Type": "video/avi"})
    assert malo.status_code == 415
    rd.actualizar(rid, estado="procesando")
    r = c.post(f"/api/reuniones/{rid}/audio?n=2", content=b"O", headers={**cab, "Content-Type": "audio/ogg"})
    assert r.json()["parar"] is True     # lo sacaron: el aparato deja de grabar
    rd.actualizar(rid, estado="lista")
    r = c.post(f"/api/reuniones/{rid}/audio?n=3", content=b"O", headers={**cab, "Content-Type": "audio/ogg"})
    assert r.status_code == 200 and r.json()["parar"] is True and len(rd.pedazos(rid)) == 2   # ya cerrada: no se guarda
