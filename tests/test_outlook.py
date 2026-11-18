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
