from backend import reuniones_datos as rd

INI, FIN = "2026-12-01T14:00:00-04:00", "2026-12-01T15:00:00-04:00"


def nueva(clave="abc-defg-hij@2026-12-01T14:00"):
    return rd.crear_o_obtener(clave, "https://meet.google.com/abc-defg-hij", "Ventas", INI, FIN)


def test_crear_es_idempotente_por_clave():
    a = nueva()
    b = nueva()
    assert a["id"] == b["id"] and a["estado"] == "propuesta"
    assert rd.obtener(a["id"])["titulo"] == "Ventas"


def test_actualizar_guarda_json():
    r = nueva()
    rd.actualizar(r["id"], estado="lista", tareas=[{"quien": "Ana", "que": "cotizar"}], linea=[])
    r2 = rd.obtener(r["id"])
    assert r2["estado"] == "lista" and r2["tareas"][0]["quien"] == "Ana" and r2["linea"] == []


def test_interesados_y_quien_puede_ver():
    r = nueva()
    rd.interesar(r["id"], "u1", True)
    rd.interesar(r["id"], "u2", False)
    assert rd.interesados(r["id"]) == ["u1"]
    assert rd.puede_ver(r["id"], "u1") and not rd.puede_ver(r["id"], "u2")
    rd.interesar(r["id"], "u2", True)
    assert sorted(rd.interesados(r["id"])) == ["u1", "u2"]
    assert [x["id"] for x in rd.listar_de("u2")] == [r["id"]]


def test_pedazos_sin_repetir():
    r = nueva()
    assert rd.guardar_pedazo(r["id"], 1) is True
    assert rd.guardar_pedazo(r["id"], 1) is False
    rd.guardar_pedazo(r["id"], 2)
    rd.marcar_pedazo(r["id"], 1, "transcrito", segmentos=[{"texto": "hola"}])
    rd.marcar_pedazo(r["id"], 2, "recibido", sumar_intento=True)
    ps = rd.pedazos(r["id"])
    assert [(p["n"], p["estado"]) for p in ps] == [(1, "transcrito"), (2, "recibido")]
    assert ps[0]["segmentos"] == [{"texto": "hola"}] and ps[1]["intentos"] == 1
    assert rd.para_transcribir() == [(r["id"], 2)]


def test_agrega_grabando_desde_a_una_base_vieja(tmp_path, monkeypatch):
    # Una base creada antes de la columna: al abrirla se agrega sola.
    import sqlite3
    from backend import basedatos
    ruta = basedatos.archivo()
    basedatos._preparadas.discard(str(ruta))
    ruta.unlink(missing_ok=True)
    con = sqlite3.connect(ruta)
    con.execute("CREATE TABLE reuniones (id TEXT PRIMARY KEY, clave TEXT NOT NULL UNIQUE, meet_url TEXT NOT NULL, "
                "titulo TEXT NOT NULL, inicio TEXT NOT NULL, fin TEXT NOT NULL, estado TEXT NOT NULL, motivo TEXT, "
                "token_hash TEXT, linea TEXT, transcripcion TEXT, resumen TEXT, puntos TEXT, tareas TEXT, "
                "duracion_s INTEGER, terminada TEXT, incompleta INTEGER NOT NULL DEFAULT 0, "
                "audio_borrado INTEGER NOT NULL DEFAULT 0, creada TEXT NOT NULL)")
    con.commit()
    con.close()
    r = nueva()
    rd.actualizar(r["id"], grabando_desde="2026-11-26T14:00:00+00:00")
    assert rd.obtener(r["id"])["grabando_desde"] == "2026-11-26T14:00:00+00:00"


def test_grabar_siempre():
    assert rd.grabar_siempre("u1") is False
    rd.poner_grabar_siempre("u1", True)
    assert rd.grabar_siempre("u1") is True


def test_buscar_texto_solo_las_suyas():
    r = nueva()
    rd.interesar(r["id"], "u1", True)
    rd.actualizar(r["id"], estado="lista", resumen="Se habló del precio del alambre")
    assert [x["id"] for x in rd.buscar_texto("u1", "alambre")] == [r["id"]]
    assert rd.buscar_texto("u2", "alambre") == []
