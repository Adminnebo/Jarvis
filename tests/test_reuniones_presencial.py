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


def lista_con_transcripcion(usuario="admin"):
    x = reuniones.crear_presencial(usuario, "Con Lucas")
    rd.actualizar(x["id"], estado="lista", resumen="Hablante 2 presenta. Hablante 10 calla.",
                  puntos=["Hablante 2 trae números"], tareas=[{"quien": "Hablante 2", "que": "mandar a Hablante 1"}],
                  transcripcion=[{"t": 0, "quien": "Hablante 1", "texto": "hola Lucas"},
                                 {"t": 5, "quien": "Hablante 2", "texto": "hola"}],
                  nombres={"Hablante 1": "Jorge"})
    return x["id"]


def test_detalle_con_nombres_puestos_y_renombrar(entrar):
    rid = lista_con_transcripcion()
    c = entrar("la-del-admin")
    d = c.get(f"/api/reuniones/{rid}").json()
    assert d["tipo"] == "presencial"
    assert d["hablantes"] == [{"etiqueta": "Hablante 1", "nombre": "Jorge"},
                              {"etiqueta": "Hablante 2", "nombre": "Hablante 2"}]
    assert d["transcripcion"][0]["quien"] == "Jorge"
    d = c.put(f"/api/reuniones/{rid}/nombres", json={"de": "Hablante 2", "a": "Lucas"}).json()
    assert d["resumen"] == "Lucas presenta. Hablante 10 calla."      # Hablante 10 no es Hablante 1
    assert d["puntos"] == ["Lucas trae números"]
    assert d["tareas"] == [{"quien": "Lucas", "que": "mandar a Jorge"}]
    assert [x["quien"] for x in d["transcripcion"]] == ["Jorge", "Lucas"]
    # Vacío = vuelve a la etiqueta; una etiqueta que no está = 400; otra persona = 404.
    d = c.put(f"/api/reuniones/{rid}/nombres", json={"de": "Hablante 1", "a": ""}).json()
    assert d["transcripcion"][0]["quien"] == "Hablante 1"
    assert c.put(f"/api/reuniones/{rid}/nombres", json={"de": "Hablante 7", "a": "X"}).status_code == 400
    assert entrar("la-de-ana").put(f"/api/reuniones/{rid}/nombres", json={"de": "Hablante 1", "a": "X"}).status_code == 404
    assert rd.obtener(rid)["transcripcion"][0]["quien"] == "Hablante 1"   # en la base quedan las etiquetas


def test_buscar_reuniones_con_los_nombres_puestos():
    from backend import herramientas
    rid = lista_con_transcripcion()
    texto = herramientas._buscar_reuniones("presenta", "", "", "admin")
    assert "Con Lucas" in texto and "Hablante 2 presenta" in texto
    reuniones.renombrar("admin", rid, "Hablante 2", "Lucas")
    assert "Lucas presenta" in herramientas._buscar_reuniones("presenta", "", "", "admin")


def test_muestras_de_voz(entrar, monkeypatch):
    from backend import reuniones_voces
    monkeypatch.setattr(reuniones_voces, "recortar", lambda o, i, f, d: d.write_bytes(b"WAV") or True)
    x = entrar("la-del-admin").post("/api/reuniones/presencial", json={}).json()
    afuera = TestClient(main.app)
    cab = {"Authorization": f"Bearer {x['token']}", "Content-Type": "audio/webm"}
    r = afuera.post(f"/api/reuniones/{x['id']}/voces?nombre=Jorge", content=b"W", headers=cab)
    assert r.status_code == 200 and r.json()["voces"] == ["Jorge"]
    r = afuera.post(f"/api/reuniones/{x['id']}/voces?nombre=jorge", content=b"W", headers=cab)
    assert r.status_code == 400 and "ya está" in r.json()["error"]
    assert afuera.post(f"/api/reuniones/{x['id']}/voces?nombre=Ana", content=b"W",
                       headers={**cab, "Content-Type": "text/plain"}).status_code == 415
    assert afuera.post(f"/api/reuniones/{x['id']}/voces?nombre=Ana", content=b"W",
                       headers={"Authorization": "Bearer otro", "Content-Type": "audio/webm"}).status_code == 401
