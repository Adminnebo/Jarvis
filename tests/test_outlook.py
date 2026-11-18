import pytest

from backend import avisos, integraciones, outlook, zernio

HILO = {"id": "t1", "subject": "Pedido", "messages": [
    {"id": "m1", "from": {"email": "luis@x.com", "name": "Luis"}, "to": [{"email": "ana@contoso.com"}],
     "subject": "Pedido", "date": "2026-11-18T10:00:00Z", "text": "Quiero 10\n> viejo",
     "clean": {"text": "Quiero 10"}},
    {"id": "m2", "from": {"email": "ana@contoso.com"}, "to": [{"email": "luis@x.com"}],
     "subject": "Re: Pedido", "date": "2026-11-18T11:00:00Z", "text": "Van", "html": None},
]}


@pytest.fixture
def conectado(monkeypatch):
    monkeypatch.setenv("ZERNIO_API_KEY", "z")
    integraciones.guardar_outlook("u1", "acc-o1", "ana@contoso.com")
    estado = {"hilos": [], "hilo": HILO, "enviados": [], "error": None}

    def hilos(cuenta, **kw):
        if estado["error"]:
            raise estado["error"]
        estado["kw"] = kw
        return estado["hilos"]

    monkeypatch.setattr(zernio, "hilos", hilos)
    monkeypatch.setattr(zernio, "hilo", lambda h, c: estado["hilo"])
    monkeypatch.setattr(zernio, "enviar_correo", lambda *a: estado["enviados"].append(a) or "n1")
    return estado


def test_sin_outlook_lo_dice():
    with pytest.raises(outlook.ErrorOutlook, match="Integraciones"):
        outlook.buscar("nadie", "x", 10)


def test_buscar_marca_ids_con_o_y_pone_al_otro_como_remitente(conectado):
    conectado["hilos"] = [{"id": "t1", "subject": "Pedido", "snippet": "Quiero 10",
                           "latestMessageReceivedAt": "2026-11-18T10:00:00Z",
                           "participants": [{"email": "ana@contoso.com"}, {"email": "luis@x.com", "name": "Luis"}]}]
    (uno,) = outlook.buscar("u1", "pedido", 5)
    assert uno == {"id": "o:t1", "fecha": "2026-11-18 10:00", "de": "Luis <luis@x.com>",
                   "asunto": "Pedido", "fragmento": "Quiero 10"}
    assert conectado["kw"] == {"buscar": "pedido", "limite": 5}


def test_leer_usa_el_texto_limpio(conectado):
    mensajes = outlook.leer("u1", "t1")
    assert [m["texto"] for m in mensajes] == ["Quiero 10", "Van"]
    assert mensajes[0]["de"] == "Luis <luis@x.com>" and mensajes[0]["para"] == "ana@contoso.com"


def test_texto_sale_del_html_si_no_hay_otro():
    assert outlook._texto({"html": "<p>Hola&nbsp;<b>Ana</b></p>"}) == "Hola Ana"


def test_responder_va_al_ultimo_mensaje_ajeno(conectado):
    assert outlook.a_quien_responder("u1", "t1") == {"mensaje_id": "m1", "para": "luis@x.com",
                                                     "asunto": "Re: Pedido"}


def test_responder_respeta_reply_to(conectado):
    conectado["hilo"] = {"id": "t1", "messages": [{"id": "m1", "from": {"email": "no-reply@x.com"},
                                                   "replyTo": [{"email": "ventas@x.com"}], "subject": "Re: Hola"}]}
    datos = outlook.a_quien_responder("u1", "t1")
    assert datos["para"] == "ventas@x.com" and datos["asunto"] == "Re: Hola"


def test_enviar_pasa_la_clave_y_el_mensaje(conectado):
    outlook.enviar("u1", ["l@x.com"], "Re: Pedido", "Van", "k1", "m1")
    assert conectado["enviados"] == [("acc-o1", ["l@x.com"], "Re: Pedido", "Van", "k1", "m1")]


def test_permiso_perdido_desconecta_y_avisa_una_vez(conectado):
    conectado["error"] = zernio.ErrorZernio("falta", 412, "account_scope_missing")
    with pytest.raises(outlook.ErrorOutlook, match="reconectalo"):
        outlook.buscar("u1", "x", 10)
    with pytest.raises(outlook.ErrorOutlook, match="Integraciones"):
        outlook.buscar("u1", "x", 10)
    assert integraciones.conexion("u1", "outlook")["estado"] == "desconectado"
    assert [a["tipo"] for a in avisos.listar("u1")] == ["sistema"]


def test_limite_de_uso_no_desconecta(conectado):
    conectado["error"] = zernio.ErrorZernio("lento", 429)
    with pytest.raises(outlook.ErrorOutlook, match="momento"):
        outlook.buscar("u1", "x", 10)
    assert integraciones.cuenta_outlook("u1") == "acc-o1"


from backend import dispositivos


def _hilo_lista(id_, recibido):
    return {"id": id_, "subject": f"Asunto {id_}", "latestMessageReceivedAt": recibido}


@pytest.fixture
def buzon(conectado, monkeypatch):
    integraciones.guardar_reglas("u1", "clientes que piden precio", "8095551234", True)
    integraciones.mover_cursor("u1", "2026-11-18T09:00:00+00:00", app="outlook")
    monkeypatch.setattr(dispositivos, "usuario_para", lambda u: object() if u == "u1" else None)
    conectado["veredicto"], conectado["clasificados"] = True, []

    def clasificar(reglas, correo, usuario, etiqueta="avisos-gmail"):
        conectado["clasificados"].append((correo["asunto"], etiqueta))
        if isinstance(conectado["veredicto"], Exception):
            raise conectado["veredicto"]
        return {"importante": conectado["veredicto"], "resumen": "resumen de " + correo["asunto"]}

    monkeypatch.setattr(avisos, "clasificar", clasificar)
    outlook._por_revisar.clear()
    outlook._ultimo_barrido.clear()
    return conectado


def test_webhook_de_outlook_solo_anota(buzon):
    ev = {"event": "message.received", "account": {"accountId": "acc-o1", "platform": "microsoft"}}
    assert outlook.recibir(ev) == "por revisar" and "u1" in outlook._por_revisar
    assert outlook.recibir({**ev, "account": {"accountId": "otra"}}) == "cuenta ajena"


def test_webhook_de_desconexion(buzon):
    ev = {"event": "account.disconnected", "account": {"accountId": "acc-o1"}}
    assert outlook.recibir(ev) == "desconectado"
    assert integraciones.cuenta_outlook("u1") is None


def test_revisar_avisa_y_mueve_el_cursor(buzon):
    buzon["hilos"] = [_hilo_lista("t1", "2026-11-18T10:00:00Z")]
    outlook.revisar("u1")
    (aviso,) = avisos.listar("u1")
    assert aviso["app"] == "outlook" and aviso["hilo"] == "o:t1" and aviso["resumen"] == "resumen de Pedido"
    assert aviso["ref"] == "ol:t1:2026-11-18T10:00:00Z" and aviso["whatsapp"] == "pendiente"
    assert buzon["clasificados"] == [("Pedido", "avisos-outlook")]
    assert buzon["kw"] == {"despues": "2026-11-18T09:00:00+00:00", "limite": 21, "ascendente": True}
    assert integraciones.conexion("u1", "outlook")["cursor"] == "2026-11-18T10:00:00Z"


def test_revisar_salta_hilos_sin_correo_nuevo_y_lo_propio(buzon):
    buzon["hilos"] = [_hilo_lista("viejo", "2026-11-18T08:00:00Z"), _hilo_lista("t1", "2026-11-18T10:00:00Z")]
    buzon["hilo"] = {"id": "t1", "messages": [{"id": "m2", "from": {"email": "ana@contoso.com"}, "subject": "x"}]}
    outlook.revisar("u1")
    assert buzon["clasificados"] == [] and avisos.listar("u1") == []
    assert integraciones.conexion("u1", "outlook")["cursor"] == "2026-11-18T10:00:00Z"


def test_si_la_ia_falla_no_avanza_y_a_los_tres_avisa_igual(buzon):
    buzon["hilos"] = [_hilo_lista("t1", "2026-11-18T10:00:00Z")]
    buzon["veredicto"] = RuntimeError("caida")
    for _ in range(2):
        outlook.revisar("u1")
        assert integraciones.conexion("u1", "outlook")["cursor"] == "2026-11-18T09:00:00+00:00"
    outlook.revisar("u1")
    (aviso,) = avisos.listar("u1")
    assert aviso["resumen"] == "Pedido"


def test_sin_reglas_solo_mueve_el_cursor(buzon):
    integraciones.guardar_reglas("u1", "", "", True)
    buzon["hilos"] = [_hilo_lista("t1", "2026-11-18T10:00:00Z")]
    outlook.revisar("u1")
    assert buzon["clasificados"] == []
    assert integraciones.conexion("u1", "outlook")["cursor"] != "2026-11-18T09:00:00+00:00"


def test_una_vuelta_revisa_anotados_y_barre_cada_media_hora(buzon, monkeypatch):
    revisados = []
    monkeypatch.setattr(outlook, "revisar", revisados.append)
    monkeypatch.setattr(avisos, "mandar_pendientes", lambda: None)
    outlook.una_vuelta()                     # primera vez: barrido
    outlook.una_vuelta()                     # nada anotado y barrido reciente: no revisa
    outlook._por_revisar.add("u1")
    outlook.una_vuelta()                     # anotado por el webhook
    assert revisados == ["u1", "u1"]
