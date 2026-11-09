import pytest

from backend import avisos, basedatos, dispositivos, integraciones, whatsapp, whatsapp_chats, zernio


@pytest.fixture
def conectado(monkeypatch):
    """u1 con WhatsApp conectado (cuenta acc-1), reglas puestas y acceso a Jarvis."""
    monkeypatch.setenv("ZERNIO_API_KEY", "z")
    monkeypatch.setattr(zernio, "perfil_de", lambda u, n: "p1")
    monkeypatch.setattr(dispositivos, "usuario_para", lambda u: object() if u == "u1" else None)
    monkeypatch.setattr(whatsapp, "numeros_propios", lambda: {"18090000000"})
    integraciones.iniciar_whatsapp("u1", "Ana")
    integraciones.guardar_whatsapp("u1", "acc-1", "+1 809 555 1234")
    integraciones.guardar_reglas("u1", "clientes que reclaman", "8095551234", True)


def evento(tipo="message.received", cuenta="acc-1", texto="hola", wamid="wamid.1", conv="c1",
           telefono="+18097778888", direccion="incoming", **extra):
    return {"id": f"ev-{wamid}-{tipo}", "event": tipo, "account": {"accountId": cuenta},
            "message": {"id": f"z-{wamid}", "platformMessageId": wamid, "conversationId": conv,
                        "platform": "whatsapp", "direction": direccion, "text": texto, "attachments": [],
                        "sender": {"name": "Pedro", "phoneNumber": telefono}},
            **extra}


def pendientes():
    with basedatos.conexion() as con:
        return [dict(f) for f in con.execute("SELECT * FROM whatsapp_pendientes ORDER BY rowid")]


def test_mensaje_entrante_queda_pendiente(conectado):
    assert whatsapp_chats.recibir(evento()) == "pendiente"
    (p,) = pendientes()
    assert (p["usuario_id"], p["conversacion"], p["mensaje_id"]) == ("u1", "c1", "wamid.1")
    assert p["remitente"] == "Pedro" and p["telefono"] == "18097778888" and p["texto"] == "hola"


def test_cuenta_ajena_se_ignora(conectado):
    assert whatsapp_chats.recibir(evento(cuenta="acc-de-otro")) == "cuenta ajena"
    assert pendientes() == []


@pytest.mark.parametrize("cambio, motivo", [
    ({"telefono": "+1 809 000 0000"}, "aviso de jarvis"),
    ({"texto": ""}, "vacio"),
    ({"direccion": "outgoing"}, "sin accion"),
    ({"metadata": {"standby": True}}, "standby"),
])
def test_filtros(conectado, cambio, motivo):
    assert whatsapp_chats.recibir(evento(**cambio)) == motivo
    assert pendientes() == []


def test_sin_reglas_o_sin_acceso_no_guarda(conectado, monkeypatch):
    integraciones.guardar_reglas("u1", "", "", True)
    assert whatsapp_chats.recibir(evento()) == "sin reglas"
    integraciones.guardar_reglas("u1", "x", "", True)
    monkeypatch.setattr(dispositivos, "usuario_para", lambda u: None)
    assert whatsapp_chats.recibir(evento()) == "sin acceso"
    assert pendientes() == []


def test_nota_de_voz_y_archivo_se_describen(conectado):
    ev = evento(texto=None, wamid="w2")
    ev["message"]["attachments"] = [{"type": "audio", "payload": {"voice": True}},
                                    {"type": "file", "filename": "factura.pdf"}]
    whatsapp_chats.recibir(ev)
    assert pendientes()[0]["texto"] == "[nota de voz] [archivo: factura.pdf]"


def test_si_la_persona_contesta_se_descarta_el_chat(conectado):
    whatsapp_chats.recibir(evento(wamid="w1"))
    whatsapp_chats.recibir(evento(wamid="w2", conv="c2"))
    assert whatsapp_chats.recibir(evento("message.sent", wamid="w3", direccion="outgoing")) == "contestado"
    assert [p["conversacion"] for p in pendientes()] == ["c2"]
    assert avisos._resuelto("u1", "wa:w1")


def test_desconexion_avisa_una_vez(conectado):
    ev = {"id": "ev-d", "event": "account.disconnected", "account": {"accountId": "acc-1"}}
    whatsapp_chats.recibir(ev)
    whatsapp_chats.recibir({**ev, "id": "ev-d2"})
    assert integraciones.conexion("u1", "whatsapp")["estado"] == "desconectado"
    (aviso,) = avisos.listar("u1")
    assert aviso["tipo"] == "sistema" and aviso["app"] == "whatsapp"


def test_eventos_repetidos(conectado):
    assert not whatsapp_chats.ya_procesado("e1")
    assert whatsapp_chats.ya_procesado("e1")
    whatsapp_chats.olvidar_evento("e1")
    assert not whatsapp_chats.ya_procesado("e1")


def _envejecer(segundos):
    """Corre la hora de llegada de todos los pendientes hacia atras."""
    from datetime import datetime, timedelta, timezone

    with basedatos.conexion() as con:
        for f in con.execute("SELECT rowid, recibido FROM whatsapp_pendientes").fetchall():
            nueva = datetime.fromisoformat(f["recibido"]) - timedelta(seconds=segundos)
            con.execute("UPDATE whatsapp_pendientes SET recibido = ? WHERE rowid = ?",
                        (nueva.isoformat(timespec="seconds"), f["rowid"]))


@pytest.fixture
def ia(monkeypatch):
    vistos = []

    def clasificar(reglas, item, usuario, etiqueta="avisos-gmail"):
        vistos.append((item, etiqueta))
        return {"importante": "reclamo" in item["texto"], "resumen": "Pedro reclama"}

    monkeypatch.setattr(avisos, "clasificar", clasificar)
    return vistos


def test_espera_la_calma_y_clasifica_el_bloque_una_vez(conectado, ia):
    whatsapp_chats.recibir(evento(texto="hola", wamid="w1"))
    whatsapp_chats.recibir(evento(texto="tengo un reclamo", wamid="w2"))
    whatsapp_chats.agrupar()
    assert ia == []   # todavia no se calma
    _envejecer(130)
    whatsapp_chats.agrupar()
    ((item, etiqueta),) = ia
    assert etiqueta == "avisos-whatsapp"
    assert item["texto"] == "Pedro: hola\nPedro: tengo un reclamo"
    assert item["asunto"] == "WhatsApp de Pedro" and "18097778888" in item["de"]
    (aviso,) = avisos.listar("u1")
    assert (aviso["app"], aviso["ref"], aviso["hilo"]) == ("whatsapp", "w2", "c1")
    assert aviso["whatsapp"] == "pendiente"
    assert pendientes() == [] and avisos._resuelto("u1", "wa:w1")


def test_lo_que_no_importa_no_avisa(conectado, ia):
    whatsapp_chats.recibir(evento(texto="jaja ok"))
    _envejecer(130)
    whatsapp_chats.agrupar()
    assert avisos.listar("u1") == [] and pendientes() == []


def test_un_chat_que_no_para_se_clasifica_a_los_10_min(conectado, ia):
    whatsapp_chats.recibir(evento(texto="reclamo", wamid="w1"))
    _envejecer(700)
    whatsapp_chats.recibir(evento(texto="sigo", wamid="w2"))   # recien llegado
    whatsapp_chats.agrupar()
    assert len(ia) == 1


def test_bloque_largo_se_recorta(conectado, ia):
    for i in range(40):
        whatsapp_chats.recibir(evento(texto="x" * 100 + str(i), wamid=f"w{i}"))
    _envejecer(130)
    whatsapp_chats.agrupar()
    texto = ia[0][0]["texto"]
    assert len(texto) <= whatsapp_chats.MAX_BLOQUE + 20 and texto.endswith("39")


def test_si_la_ia_falla_reintenta_y_al_tercero_avisa(conectado, monkeypatch):
    def falla(*a, **k):
        raise RuntimeError("caida")

    monkeypatch.setattr(avisos, "clasificar", falla)
    whatsapp_chats.recibir(evento(texto="hola"))
    _envejecer(130)
    whatsapp_chats.agrupar()
    whatsapp_chats.agrupar()
    assert avisos.listar("u1") == [] and len(pendientes()) == 1
    whatsapp_chats.agrupar()
    assert len(avisos.listar("u1")) == 1 and pendientes() == []


def test_barrido_recupera_lo_que_no_llego(conectado, ia, monkeypatch):
    from datetime import datetime, timedelta, timezone

    ahora = datetime.now(timezone.utc)
    monkeypatch.setattr(zernio, "conversaciones", lambda cuenta, limite=50: ([
        {"id": "c1", "unreadCount": 1, "updatedTime": ahora.isoformat(), "participantName": "Pedro",
         "participantId": "18097778888"},
        {"id": "c2", "unreadCount": 0, "updatedTime": ahora.isoformat()},
    ], None))
    monkeypatch.setattr(zernio, "mensajes", lambda conv, cuenta, limite=30: [
        {"id": "w-viejo", "direction": "incoming", "message": "antes", "createdAt": (ahora - timedelta(hours=2)).isoformat()},
        {"id": "w-ya", "direction": "incoming", "message": "ya visto", "createdAt": ahora.isoformat()},
        {"id": "w-nuevo", "direction": "incoming", "message": "tengo un reclamo", "createdAt": ahora.isoformat(),
         "senderName": "Pedro"},
        {"id": "w-mio", "direction": "outgoing", "message": "ok", "createdAt": ahora.isoformat()},
    ])
    avisos._resolver("u1", "wa:w-ya")
    whatsapp_chats._ultimo_barrido["u1"] = (ahora - timedelta(hours=1)).timestamp()
    whatsapp_chats.barrer("u1")
    assert [p["mensaje_id"] for p in pendientes()] == ["w-nuevo"]
    assert pendientes()[0]["telefono"] == "18097778888"


def test_barrido_primera_vez_solo_marca(conectado, monkeypatch):
    monkeypatch.setattr(zernio, "conversaciones", lambda *a, **k: pytest.fail("no deberia llamar"))
    whatsapp_chats._ultimo_barrido.pop("u1", None)
    whatsapp_chats.barrer("u1")
    assert "u1" in whatsapp_chats._ultimo_barrido


def test_barrido_detecta_cuenta_caida(conectado, monkeypatch):
    monkeypatch.setattr(zernio, "conversaciones", lambda *a, **k: ([], "needs reconnection"))
    whatsapp_chats._ultimo_barrido["u1"] = 0.0
    whatsapp_chats.barrer("u1")
    assert integraciones.conexion("u1", "whatsapp")["estado"] == "desconectado"


def test_una_vuelta_no_se_cae_por_un_error(conectado, monkeypatch):
    monkeypatch.setattr(whatsapp_chats, "barrer", lambda u: (_ for _ in ()).throw(RuntimeError("x")))
    enviados = []
    monkeypatch.setattr(avisos, "mandar_pendientes", lambda: enviados.append(1))
    whatsapp_chats.una_vuelta()
    assert enviados == [1]
