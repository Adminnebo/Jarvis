import json

import httpx
import pytest

from backend import evolution_wa


@pytest.fixture
def api(monkeypatch):
    """Evolution falso: `respuestas` es {(METODO, ruta): (status, json)}; anota cada pedido."""
    monkeypatch.setenv("EVOLUTION_URL", "https://evo.test/")
    monkeypatch.setenv("EVOLUTION_API_KEY", "clave-global")
    pedidos, respuestas = [], {}

    def manejar(pedido: httpx.Request):
        pedidos.append(pedido)
        status, cuerpo = respuestas.get((pedido.method, pedido.url.path), (404, {"message": "no existe"}))
        return httpx.Response(status, json=cuerpo)

    cliente = httpx.Client(transport=httpx.MockTransport(manejar))
    monkeypatch.setattr(evolution_wa, "_http", lambda: cliente)
    return pedidos, respuestas


def test_configurado(monkeypatch):
    monkeypatch.delenv("EVOLUTION_URL", raising=False)
    monkeypatch.delenv("EVOLUTION_API_KEY", raising=False)
    assert not evolution_wa.configurado()
    monkeypatch.setenv("EVOLUTION_URL", "https://evo")
    monkeypatch.setenv("EVOLUTION_API_KEY", "k")
    assert evolution_wa.configurado()


def test_nombre_de_instancia_es_seguro():
    assert evolution_wa.nombre_instancia("jorge") == "jarvis-jorge"
    assert evolution_wa.nombre_instancia("Ana María/1") == "jarvis-ana-mar-a-1"


def test_crear_configura_todo_y_devuelve_el_qr(api):
    pedidos, respuestas = api
    respuestas[("POST", "/instance/create")] = (201, {
        "instance": {"instanceName": "jarvis-u1"}, "hash": "tok",
        "qrcode": {"base64": "data:image/png;base64,AAA", "pairingCode": None, "code": "2@x"}})
    r = evolution_wa.crear("jarvis-u1", "https://jarvis/integraciones/whatsapp/evolution?clave=s")
    assert r == {"qr": "data:image/png;base64,AAA", "codigo": None}
    cuerpo = json.loads(pedidos[0].content)
    assert pedidos[0].headers["apikey"] == "clave-global"
    assert cuerpo["instanceName"] == "jarvis-u1" and cuerpo["qrcode"] is True
    assert cuerpo["integration"] == "WHATSAPP-BAILEYS"
    assert cuerpo["groupsIgnore"] is True and cuerpo["readMessages"] is False
    assert cuerpo["alwaysOnline"] is False and cuerpo["syncFullHistory"] is False
    gancho = cuerpo["webhook"]
    assert gancho["url"].endswith("clave=s") and gancho["enabled"] is True
    assert set(gancho["events"]) == {"MESSAGES_UPSERT", "CONNECTION_UPDATE", "QRCODE_UPDATED"}


def test_crear_con_numero_pide_codigo(api):
    pedidos, respuestas = api
    respuestas[("POST", "/instance/create")] = (201, {"qrcode": {"base64": "q", "pairingCode": "ABCD1234"}})
    assert evolution_wa.crear("jarvis-u1", "https://j", numero="18095551234")["codigo"] == "ABCD1234"
    assert json.loads(pedidos[0].content)["number"] == "18095551234"


def test_conectar_y_estado(api):
    pedidos, respuestas = api
    respuestas[("GET", "/instance/connect/jarvis-u1")] = (200, {"base64": "q2", "pairingCode": "WXYZ9876", "code": "c"})
    respuestas[("GET", "/instance/connectionState/jarvis-u1")] = (200, {"instance": {"instanceName": "jarvis-u1", "state": "open"}})
    assert evolution_wa.conectar("jarvis-u1", "18095551234") == {"qr": "q2", "codigo": "WXYZ9876"}
    assert pedidos[0].url.params["number"] == "18095551234"
    assert evolution_wa.estado("jarvis-u1") == "open"


def test_estado_de_instancia_que_no_existe(api):
    assert evolution_wa.estado("jarvis-nadie") is None


def test_numero_de_la_instancia(api):
    _, respuestas = api
    respuestas[("GET", "/instance/fetchInstances")] = (200, [
        {"name": "jarvis-u1", "ownerJid": "18095551234@s.whatsapp.net", "profileName": "Ana"}])
    assert evolution_wa.numero("jarvis-u1") == "18095551234"


def test_borrar_ignora_lo_que_ya_no_existe(api):
    pedidos, respuestas = api
    respuestas[("DELETE", "/instance/delete/jarvis-u1")] = (200, {"status": "SUCCESS"})
    evolution_wa.borrar("jarvis-u1")   # el logout da 404 y no importa
    assert [p.method + " " + p.url.path for p in pedidos] == [
        "DELETE /instance/logout/jarvis-u1", "DELETE /instance/delete/jarvis-u1"]


def test_errores_traen_el_status(api):
    _, respuestas = api
    respuestas[("POST", "/message/sendText/jarvis-u1")] = (400, {"response": {"message": ["no existe el numero"]}})
    with pytest.raises(evolution_wa.ErrorEvolution) as error:
        evolution_wa.enviar("jarvis-u1", "1809@s.whatsapp.net", "hola")
    assert error.value.status == 400 and "no existe el numero" in str(error.value)


def test_chats_sin_grupos_y_normalizados(api):
    _, respuestas = api
    respuestas[("POST", "/chat/findChats/jarvis-u1")] = (200, [
        {"remoteJid": "18097778888@s.whatsapp.net", "pushName": "Pedro", "updatedAt": "2026-11-19T10:00:00.000Z",
         "unreadCount": 2, "lastMessage": {"key": {"fromMe": False, "id": "m1"}, "pushName": "Pedro",
                                           "message": {"conversation": "y el pedido?"}, "messageTimestamp": 1700000000}},
        {"remoteJid": "1203@g.us", "pushName": "Grupo", "updatedAt": "2026-11-19T11:00:00.000Z"},
        {"remoteJid": "status@broadcast", "updatedAt": "2026-11-19T12:00:00.000Z"},
        {"remoteJid": "555@lid", "pushName": None, "updatedAt": "2026-11-18T09:00:00.000Z",
         "lastMessage": {"key": {"fromMe": True, "id": "m2", "remoteJidAlt": "18091112222@s.whatsapp.net"},
                         "message": {"extendedTextMessage": {"text": "ok"}}, "messageTimestamp": 1690000000}},
    ])
    chats = evolution_wa.chats("jarvis-u1")
    assert [c["id"] for c in chats] == ["18097778888@s.whatsapp.net", "555@lid"]
    pedro, otro = chats
    assert pedro["nombre"] == "Pedro" and pedro["telefono"] == "18097778888"
    assert pedro["ultimo"] == "y el pedido?" and pedro["no_leidos"] == 2 and not pedro["ultimo_mio"]
    assert pedro["ultimo_id"] == "m1"
    assert otro["telefono"] == "18091112222" and otro["ultimo_mio"] and otro["no_leidos"] == 0


def test_mensajes_en_orden_y_con_adjuntos(api):
    pedidos, respuestas = api
    respuestas[("POST", "/chat/findMessages/jarvis-u1")] = (200, {"messages": {"records": [
        {"key": {"id": "b", "fromMe": True}, "message": {"conversation": "va en camino"}, "messageTimestamp": 20},
        {"key": {"id": "a", "fromMe": False}, "pushName": "Pedro",
         "message": {"audioMessage": {"ptt": True}}, "messageTimestamp": 10},
    ]}})
    mensajes = evolution_wa.mensajes("jarvis-u1", "18097778888@s.whatsapp.net", 30)
    assert [m["id"] for m in mensajes] == ["a", "b"]
    assert mensajes[0]["texto"] == "[nota de voz]" and mensajes[0]["entrante"] and mensajes[0]["nombre"] == "Pedro"
    assert mensajes[1]["texto"] == "va en camino" and not mensajes[1]["entrante"]
    cuerpo = json.loads(pedidos[0].content)
    assert cuerpo["where"]["key"]["remoteJid"] == "18097778888@s.whatsapp.net" and cuerpo["limit"] == 30


@pytest.mark.parametrize("mensaje, texto", [
    ({"conversation": "hola"}, "hola"),
    ({"extendedTextMessage": {"text": "link"}}, "link"),
    ({"imageMessage": {"caption": "mira"}}, "[imagen] mira"),
    ({"imageMessage": {}}, "[imagen]"),
    ({"videoMessage": {}}, "[video]"),
    ({"audioMessage": {"ptt": False}}, "[audio]"),
    ({"documentMessage": {"fileName": "factura.pdf"}}, "[archivo: factura.pdf]"),
    ({"documentWithCaptionMessage": {"message": {"documentMessage": {"fileName": "x.pdf", "caption": "va"}}}},
     "[archivo: x.pdf] va"),
    ({"stickerMessage": {}}, ""),
    ({"reactionMessage": {"text": "👍"}}, ""),
    ({"protocolMessage": {}}, ""),
    (None, ""),
])
def test_texto_de_cada_tipo(mensaje, texto):
    assert evolution_wa.texto_de(mensaje) == texto


def test_telefono_con_lid():
    assert evolution_wa.telefono_de({"remoteJid": "18097778888@s.whatsapp.net"}) == "18097778888"
    assert evolution_wa.telefono_de({"remoteJid": "555@lid", "remoteJidAlt": "18091112222@s.whatsapp.net"}) == "18091112222"
    assert evolution_wa.telefono_de({"remoteJid": "555@lid"}) == ""
