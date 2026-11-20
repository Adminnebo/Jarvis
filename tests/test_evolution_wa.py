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
    assert set(gancho["events"]) == {"MESSAGES_UPSERT", "MESSAGES_UPDATE", "SEND_MESSAGE", "CONNECTION_UPDATE", "QRCODE_UPDATED"}


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
    assert mensajes[0]["descripcion"] == "[nota de voz]" and mensajes[0]["entrante"] and mensajes[0]["nombre"] == "Pedro"
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


# --- mensajes con todos sus detalles (vista de WhatsApp) ---

def registro(tipo, contenido, desde_mi=False, actualizaciones=(), contexto=None, id_="m1", jid="18097778888@s.whatsapp.net"):
    return {"key": {"id": id_, "fromMe": desde_mi, "remoteJid": jid}, "pushName": "Pedro",
            "messageType": tipo, "message": {tipo: contenido} if tipo != "conversation" else {"conversation": contenido},
            "messageTimestamp": 1795179971, "contextInfo": contexto,
            "MessageUpdate": [{"status": s} for s in actualizaciones]}


def test_normalizar_texto_con_estado_y_cita():
    m = evolution_wa.normalizar_mensaje(registro(
        "conversation", "va en camino", desde_mi=True, actualizaciones=["SERVER_ACK", "READ", "DELIVERY_ACK"],
        contexto={"stanzaId": "m0", "quotedMessage": {"conversation": "y el pedido?"}}))
    assert m["id"] == "m1" and m["jid"] == "18097778888@s.whatsapp.net" and not m["entrante"]
    assert m["tipo"] == "texto" and m["texto"] == "va en camino" and m["estado"] == "leido"
    assert m["cita"] == {"id": "m0", "texto": "y el pedido?"} and m["momento"] == 1795179971
    assert m["archivo"] is None


def test_normalizar_estados():
    def estado(*a):
        return evolution_wa.normalizar_mensaje(registro("conversation", "x", desde_mi=True, actualizaciones=a))["estado"]
    assert estado() == "enviado" and estado("DELIVERY_ACK") == "entregado" and estado("PLAYED") == "leido"
    assert evolution_wa.normalizar_mensaje(registro("conversation", "x"))["estado"] is None   # entrante


def test_normalizar_imagen_con_miniatura():
    m = evolution_wa.normalizar_mensaje(registro("imageMessage", {
        "caption": "mira", "mimetype": "image/jpeg", "fileLength": {"low": 2048, "high": 0},
        "jpegThumbnail": "QUJD", "width": 800, "height": 600}))
    assert m["tipo"] == "imagen" and m["texto"] == "mira"
    assert m["archivo"] == {"mime": "image/jpeg", "nombre": None, "tamano": 2048, "segundos": None,
                            "miniatura": "data:image/jpeg;base64,QUJD", "ancho": 800, "alto": 600}


@pytest.mark.parametrize("tipo, contenido, esperado, texto", [
    ("audioMessage", {"ptt": True, "seconds": 7, "mimetype": "audio/ogg; codecs=opus"}, "nota", ""),
    ("audioMessage", {"ptt": False, "seconds": 70, "mimetype": "audio/mpeg"}, "audio", ""),
    ("videoMessage", {"caption": "", "seconds": 12, "mimetype": "video/mp4"}, "video", ""),
    ("documentMessage", {"fileName": "factura.pdf", "mimetype": "application/pdf", "caption": "la factura"},
     "documento", "la factura"),
    ("stickerMessage", {"mimetype": "image/webp"}, "sticker", ""),
    ("extendedTextMessage", {"text": "un link"}, "texto", "un link"),
])
def test_normalizar_tipos(tipo, contenido, esperado, texto):
    m = evolution_wa.normalizar_mensaje(registro(tipo, contenido))
    assert m["tipo"] == esperado and m["texto"] == texto
    if esperado in ("nota", "audio", "video"):
        assert m["archivo"]["segundos"] == contenido["seconds"]
    if esperado == "documento":
        assert m["archivo"]["nombre"] == "factura.pdf"


def test_documento_con_pie_viene_envuelto():
    m = evolution_wa.normalizar_mensaje(registro("documentWithCaptionMessage", {"message": {
        "documentMessage": {"fileName": "x.pdf", "caption": "va", "mimetype": "application/pdf"}}}))
    assert m["tipo"] == "documento" and m["archivo"]["nombre"] == "x.pdf" and m["texto"] == "va"


def test_reacciones_y_protocolo_no_son_mensajes():
    assert evolution_wa.normalizar_mensaje(registro("reactionMessage", {"text": "👍"})) is None
    assert evolution_wa.normalizar_mensaje(registro("protocolMessage", {})) is None


def test_mensajes_con_pagina(api):
    pedidos, respuestas = api
    respuestas[("POST", "/chat/findMessages/jarvis-u1")] = (200, {"messages": {"records": [
        registro("conversation", "nuevo", id_="b") | {"messageTimestamp": 20},
        registro("reactionMessage", {"text": "x"}, id_="r") | {"messageTimestamp": 15},
        registro("conversation", "viejo", id_="a") | {"messageTimestamp": 10}]}})
    lista = evolution_wa.mensajes("jarvis-u1", "18097778888@s.whatsapp.net", 30, pagina=2)
    assert [m["id"] for m in lista] == ["a", "b"]
    assert json.loads(pedidos[0].content)["page"] == 2


def test_chats_traen_estado_y_tipo_del_ultimo(api):
    _, respuestas = api
    respuestas[("POST", "/chat/findChats/jarvis-u1")] = (200, [
        {"remoteJid": "18097778888@s.whatsapp.net", "updatedAt": "2026-11-19T10:00:00.000Z",
         "lastMessage": {"key": {"fromMe": True, "id": "m1"}, "messageType": "imageMessage",
                         "message": {"imageMessage": {"caption": ""}}, "MessageUpdate": [{"status": "READ"}],
                         "messageTimestamp": 1700000000}}])
    (chat,) = evolution_wa.chats("jarvis-u1")
    assert chat["ultimo_estado"] == "leido" and chat["ultimo_tipo"] == "imagen"


# --- acciones de la vista ---

def test_archivo_de_un_mensaje(api):
    pedidos, respuestas = api
    respuestas[("POST", "/chat/getBase64FromMediaMessage/jarvis-u1")] = (200, {
        "mimetype": "image/jpeg", "fileName": "foto.jpg", "base64": "QUJD"})
    assert evolution_wa.archivo("jarvis-u1", "m1") == {"mime": "image/jpeg", "nombre": "foto.jpg", "base64": "QUJD"}
    assert json.loads(pedidos[0].content) == {"message": {"key": {"id": "m1"}}, "convertToMp4": False}


def test_foto_de_perfil(api):
    pedidos, respuestas = api
    respuestas[("POST", "/chat/fetchProfilePictureUrl/jarvis-u1")] = (200, {"profilePictureUrl": "https://pps/x.jpg"})
    assert evolution_wa.foto_perfil("jarvis-u1", "18097778888@s.whatsapp.net") == "https://pps/x.jpg"
    assert json.loads(pedidos[0].content) == {"number": "18097778888@s.whatsapp.net"}
    respuestas[("POST", "/chat/fetchProfilePictureUrl/jarvis-u1")] = (200, {"profilePictureUrl": None})
    assert evolution_wa.foto_perfil("jarvis-u1", "x@s.whatsapp.net") is None


def test_marcar_leido(api):
    pedidos, respuestas = api
    respuestas[("POST", "/chat/markMessageAsRead/jarvis-u1")] = (200, {"message": "Read messages"})
    evolution_wa.marcar_leido("jarvis-u1", "1809@s.whatsapp.net", ["a", "b"])
    assert json.loads(pedidos[0].content) == {"readMessages": [
        {"remoteJid": "1809@s.whatsapp.net", "fromMe": False, "id": "a"},
        {"remoteJid": "1809@s.whatsapp.net", "fromMe": False, "id": "b"}]}
    evolution_wa.marcar_leido("jarvis-u1", "1809@s.whatsapp.net", [])
    assert len(pedidos) == 1   # sin ids no llama


def test_enviar_con_cita(api):
    pedidos, respuestas = api
    respuestas[("POST", "/message/sendText/jarvis-u1")] = (201, {"key": {"id": "nuevo"}})
    assert evolution_wa.enviar("jarvis-u1", "18097778888@s.whatsapp.net", "si", cita={"id": "m0", "texto": "va?"}) == "nuevo"
    cuerpo = json.loads(pedidos[0].content)
    assert cuerpo["number"] == "18097778888" and cuerpo["text"] == "si"
    assert cuerpo["quoted"] == {"key": {"id": "m0"}, "message": {"conversation": "va?"}}


def test_enviar_archivo_y_nota(api):
    pedidos, respuestas = api
    respuestas[("POST", "/message/sendMedia/jarvis-u1")] = (201, {"key": {"id": "f1"}})
    respuestas[("POST", "/message/sendWhatsAppAudio/jarvis-u1")] = (201, {"key": {"id": "n1"}})
    assert evolution_wa.enviar_archivo("jarvis-u1", "18097778888@s.whatsapp.net", "application/pdf",
                                       "factura.pdf", "QUJD", "la factura") == "f1"
    cuerpo = json.loads(pedidos[0].content)
    assert cuerpo == {"number": "18097778888", "mediatype": "document", "mimetype": "application/pdf",
                      "fileName": "factura.pdf", "media": "QUJD", "caption": "la factura"}
    evolution_wa.enviar_archivo("jarvis-u1", "1@s.whatsapp.net", "image/png", "a.png", "X", "")
    assert json.loads(pedidos[1].content)["mediatype"] == "image"
    assert evolution_wa.enviar_nota("jarvis-u1", "18097778888@s.whatsapp.net", "T0dH", cita={"id": "m0", "texto": "x"}) == "n1"
    nota = json.loads(pedidos[2].content)
    assert nota["audio"] == "T0dH" and nota["number"] == "18097778888" and nota["quoted"]["key"]["id"] == "m0"


def test_asegurar_eventos(api):
    pedidos, respuestas = api
    respuestas[("POST", "/webhook/set/jarvis-u1")] = (201, {})
    evolution_wa.asegurar_eventos("jarvis-u1", "https://j/w?clave=s")
    gancho = json.loads(pedidos[0].content)["webhook"]
    assert gancho["url"] == "https://j/w?clave=s" and gancho["enabled"] is True
    assert {"MESSAGES_UPDATE", "SEND_MESSAGE", "MESSAGES_UPSERT"} <= set(gancho["events"])
