"""La vista de WhatsApp dentro de Jarvis: canal en vivo, fotos, instancia (apps_whatsapp.py)."""

import asyncio
import time

import pytest

from backend import apps_whatsapp, evolution_wa, integraciones, whatsapp_chats


@pytest.fixture
def conectado(monkeypatch):
    monkeypatch.setenv("EVOLUTION_URL", "https://evo")
    monkeypatch.setenv("EVOLUTION_API_KEY", "k")
    apps_whatsapp._eventos_listos.clear()
    apps_whatsapp._fotos.clear()
    fila = integraciones.preparar_evolution("u1")
    integraciones.conectar_evolution("u1", "18095551234")
    return fila


def test_publicar_llega_solo_al_dueno():
    async def prueba():
        mia, ajena = apps_whatsapp.suscribir("u1"), apps_whatsapp.suscribir("u2")
        apps_whatsapp.publicar("u1", {"tipo": "mensaje", "x": 1})
        await asyncio.sleep(0)
        assert mia.get_nowait() == {"tipo": "mensaje", "x": 1}
        assert ajena.empty()
        apps_whatsapp.desuscribir("u1", mia)
        apps_whatsapp.desuscribir("u2", ajena)
        apps_whatsapp.publicar("u1", {"tipo": "otro"})   # nadie escucha: no falla
        assert apps_whatsapp._suscritos.get("u1") in (None, [])

    asyncio.run(prueba())


def test_publicar_desde_otro_hilo():
    import threading

    async def prueba():
        cola = apps_whatsapp.suscribir("u1")
        threading.Thread(target=apps_whatsapp.publicar, args=("u1", {"tipo": "estado"})).start()
        assert await asyncio.wait_for(cola.get(), 2) == {"tipo": "estado"}
        apps_whatsapp.desuscribir("u1", cola)

    asyncio.run(prueba())


def test_sin_whatsapp_conectado(monkeypatch):
    with pytest.raises(apps_whatsapp.SinWhatsApp):
        apps_whatsapp.instancia_de("nadie")


def test_instancia_asegura_los_eventos_una_vez(conectado, monkeypatch):
    llamadas = []
    monkeypatch.setattr(evolution_wa, "asegurar_eventos", lambda inst, url: llamadas.append((inst, url)))
    assert apps_whatsapp.instancia_de("u1") == "jarvis-u1"
    assert apps_whatsapp.instancia_de("u1") == "jarvis-u1"
    assert llamadas == [("jarvis-u1", whatsapp_chats.url_webhook_evolution(conectado["clave"]))]


def test_foto_con_cache(conectado, monkeypatch):
    pedidas = []
    monkeypatch.setattr(evolution_wa, "foto_perfil", lambda inst, jid: pedidas.append(jid) or "https://pps/x.jpg")
    assert apps_whatsapp.foto("jarvis-u1", "1@s.whatsapp.net") == "https://pps/x.jpg"
    assert apps_whatsapp.foto("jarvis-u1", "1@s.whatsapp.net") == "https://pps/x.jpg"
    assert pedidas == ["1@s.whatsapp.net"]
    apps_whatsapp._fotos[("jarvis-u1", "1@s.whatsapp.net")] = ("viejo", time.time() - 90000)
    assert apps_whatsapp.foto("jarvis-u1", "1@s.whatsapp.net") == "https://pps/x.jpg" and len(pedidas) == 2


@pytest.mark.parametrize("texto, jid", [
    ("18097778888@s.whatsapp.net", "18097778888@s.whatsapp.net"),
    ("555@lid", "555@lid"),
    ("809 777 8888", "18097778888@s.whatsapp.net"),
])
def test_jid_de(texto, jid):
    assert apps_whatsapp.jid_de(texto) == jid


@pytest.mark.parametrize("texto", ["1203@g.us", "status@broadcast", "123", ""])
def test_jid_invalido(texto):
    with pytest.raises(ValueError):
        apps_whatsapp.jid_de(texto)


# --- el webhook publica lo que ve la vista ---

def _webhook(evento, clave, monkeypatch):
    vistos = []
    monkeypatch.setattr(apps_whatsapp, "publicar", lambda u, ev: vistos.append((u, ev)))
    whatsapp_chats.recibir_evolution(evento, clave)
    return vistos


def test_mensaje_nuevo_se_publica(conectado, monkeypatch):
    ev = {"event": "messages.upsert", "instance": "jarvis-u1", "data": {
        "key": {"remoteJid": "18097778888@s.whatsapp.net", "fromMe": False, "id": "m1"},
        "pushName": "Pedro", "message": {"conversation": "hola"}, "messageTimestamp": int(time.time())}}
    ((usuario, publicado),) = _webhook(ev, conectado["clave"], monkeypatch)
    assert usuario == "u1" and publicado["tipo"] == "mensaje"
    assert publicado["mensaje"]["id"] == "m1" and publicado["mensaje"]["texto"] == "hola"


def test_mensaje_de_grupo_no_se_publica(conectado, monkeypatch):
    ev = {"event": "messages.upsert", "instance": "jarvis-u1", "data": {
        "key": {"remoteJid": "1203@g.us", "fromMe": False, "id": "g1"}, "message": {"conversation": "x"}}}
    assert _webhook(ev, conectado["clave"], monkeypatch) == []


def test_lo_enviado_por_jarvis_se_publica(conectado, monkeypatch):
    ev = {"event": "send.message", "instance": "jarvis-u1", "data": {
        "key": {"remoteJid": "18097778888@s.whatsapp.net", "fromMe": True, "id": "s1"},
        "message": {"conversation": "va"}, "messageTimestamp": int(time.time()), "status": "PENDING"}}
    ((_, publicado),) = _webhook(ev, conectado["clave"], monkeypatch)
    assert publicado["mensaje"]["id"] == "s1" and not publicado["mensaje"]["entrante"]


def test_cambio_de_checks_se_publica(conectado, monkeypatch):
    ev = {"event": "messages.update", "instance": "jarvis-u1", "data": {
        "keyId": "s1", "messageId": "db-9", "remoteJid": "18097778888@s.whatsapp.net", "fromMe": True,
        "status": "READ"}}
    ((_, publicado),) = _webhook(ev, conectado["clave"], monkeypatch)
    assert publicado == {"tipo": "estado", "id": "s1", "jid": "18097778888@s.whatsapp.net", "estado": "leido"}


def test_conexion_se_publica(conectado, monkeypatch):
    ev = {"event": "connection.update", "instance": "jarvis-u1", "data": {"state": "connecting"}}
    ((_, publicado),) = _webhook(ev, conectado["clave"], monkeypatch)
    assert publicado == {"tipo": "conexion", "estado": "connecting"}
