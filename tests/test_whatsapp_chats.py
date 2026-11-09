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
