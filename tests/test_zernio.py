import hashlib
import hmac
import json

import httpx
import pytest

from backend import zernio


@pytest.fixture
def api(monkeypatch):
    """Zernio falso: `respuestas` es {(METODO, ruta): (status, json)}; anota cada pedido."""
    monkeypatch.setenv("ZERNIO_API_KEY", "clave-z")
    monkeypatch.setenv("ZERNIO_WEBHOOK_SECRET", "secreto-w")
    pedidos, respuestas = [], {}

    def manejar(pedido: httpx.Request):
        pedidos.append(pedido)
        ruta = pedido.url.path.removeprefix("/api/v1")
        status, cuerpo = respuestas.get((pedido.method, ruta), (404, {"error": "no existe"}))
        return httpx.Response(status, json=cuerpo)

    cliente = httpx.Client(transport=httpx.MockTransport(manejar))
    monkeypatch.setattr(zernio, "_http", lambda: cliente)
    return pedidos, respuestas


def test_configurado_depende_de_la_clave(monkeypatch):
    monkeypatch.delenv("ZERNIO_API_KEY", raising=False)
    assert not zernio.configurado()
    monkeypatch.setenv("ZERNIO_API_KEY", "x")
    assert zernio.configurado()


def test_sin_clave_no_llama(monkeypatch):
    monkeypatch.delenv("ZERNIO_API_KEY", raising=False)
    with pytest.raises(zernio.ErrorZernio):
        zernio.conversaciones("acc")


def test_perfil_existente_por_external_id(api):
    pedidos, respuestas = api
    respuestas[("GET", "/profiles")] = (200, {"profiles": [
        {"_id": "otro", "externalId": "jarvis:u2"}, {"_id": "p1", "externalId": "jarvis:u1"}]})
    assert zernio.perfil_de("u1", "Ana") == "p1"
    assert pedidos[0].url.params["externalId"] == "jarvis:u1"
    assert pedidos[0].headers["authorization"] == "Bearer clave-z"
    assert len(pedidos) == 1


def test_perfil_nuevo_se_crea_con_external_id(api):
    pedidos, respuestas = api
    respuestas[("GET", "/profiles")] = (200, {"profiles": []})
    respuestas[("POST", "/profiles")] = (201, {"profile": {"_id": "p9"}})
    assert zernio.perfil_de("u1", "Ana") == "p9"
    cuerpo = json.loads(pedidos[1].content)
    assert cuerpo["externalId"] == "jarvis:u1" and cuerpo["name"] == "Jarvis · Ana"


def test_perfil_con_nombre_repetido_agrega_el_id(monkeypatch):
    monkeypatch.setenv("ZERNIO_API_KEY", "clave-z")
    nombres = []

    def manejar(pedido: httpx.Request):
        if pedido.method == "GET":
            return httpx.Response(200, json={"profiles": []})
        nombres.append(json.loads(pedido.content)["name"])
        if len(nombres) == 1:
            return httpx.Response(409, json={"error": "ya existe", "code": "profile_name_conflict"})
        return httpx.Response(201, json={"profile": {"_id": "p2"}})

    cliente = httpx.Client(transport=httpx.MockTransport(manejar))
    monkeypatch.setattr(zernio, "_http", lambda: cliente)
    assert zernio.perfil_de("usuario-largo-1", "Ana") == "p2"
    assert nombres == ["Jarvis · Ana", "Jarvis · Ana · usuario-"]


def test_url_de_conexion_en_coexistencia(api):
    pedidos, respuestas = api
    respuestas[("GET", "/connect/whatsapp")] = (200, {"authUrl": "https://meta/x", "state": "s"})
    assert zernio.url_conexion("p1", "https://j/cb?estado=e") == "https://meta/x"
    params = pedidos[0].url.params
    assert params["profileId"] == "p1" and params["onboarding"] == "business_app"
    assert params["redirect_url"] == "https://j/cb?estado=e" and params["language"] == "es"


def test_error_trae_status_y_codigo(api):
    _, respuestas = api
    respuestas[("GET", "/inbox/conversations")] = (403, {"error": "Inbox addon required", "code": "addon_required"})
    with pytest.raises(zernio.ErrorZernio) as error:
        zernio.conversaciones("acc")
    assert error.value.status == 403 and error.value.codigo == "addon_required"
    assert "Inbox" in str(error.value)


def test_conversaciones_y_mensajes(api):
    pedidos, respuestas = api
    respuestas[("GET", "/inbox/conversations")] = (200, {
        "data": [{"id": "c1"}], "pagination": {"nextCursor": None},
        "meta": {"failedAccounts": [{"accountId": "acc", "error": "token vencido"}]}})
    respuestas[("GET", "/inbox/conversations/c1/messages")] = (200, {
        "messages": [{"id": "m2"}, {"id": "m1"}]})
    lista, fallo = zernio.conversaciones("acc", limite=15)
    assert lista == [{"id": "c1"}] and fallo == "token vencido"
    assert pedidos[0].url.params["accountId"] == "acc" and pedidos[0].url.params["limit"] == "15"
    assert [m["id"] for m in zernio.mensajes("c1", "acc", 10)] == ["m1", "m2"]   # en orden
    assert pedidos[1].url.params["sortOrder"] == "desc"


def test_enviar_con_clave_de_idempotencia(api):
    pedidos, respuestas = api
    respuestas[("POST", "/inbox/conversations/c1/messages")] = (200, {"success": True, "data": {"messageId": "wamid.1"}})
    assert zernio.enviar("c1", "acc", "hola", "b-123") == "wamid.1"
    assert json.loads(pedidos[0].content) == {"accountId": "acc", "message": "hola"}
    assert pedidos[0].headers["idempotency-key"] == "b-123"


def test_firma_del_webhook(monkeypatch):
    monkeypatch.setenv("ZERNIO_WEBHOOK_SECRET", "secreto-w")
    cuerpo = b'{"id":"e1"}'
    firma = hmac.new(b"secreto-w", cuerpo, hashlib.sha256).hexdigest()
    assert zernio.firma_valida(cuerpo, firma)
    assert not zernio.firma_valida(cuerpo, "0" * 64)
    assert not zernio.firma_valida(cuerpo, "")
    monkeypatch.delenv("ZERNIO_WEBHOOK_SECRET")
    assert not zernio.firma_valida(cuerpo, firma)


def test_asegurar_webhook_crea_el_suyo_y_no_toca_ajenos(api):
    pedidos, respuestas = api
    url = "https://asistente.neboaiconsulting.com/integraciones/whatsapp/webhook"
    respuestas[("GET", "/webhooks/settings")] = (200, {"webhooks": [
        {"_id": "w-ajeno", "name": "Marketing JDL", "url": url}]})
    respuestas[("POST", "/webhooks/settings")] = (200, {"webhook": {"_id": "w-nuevo"}})
    assert zernio.asegurar_webhook(url) == "w-nuevo"
    cuerpo = json.loads(pedidos[1].content)
    assert cuerpo["name"] == "Jarvis asistente.neboaiconsulting.com"
    assert cuerpo["secret"] == "secreto-w" and "message.received" in cuerpo["events"]
    assert all(p.method != "DELETE" for p in pedidos)


def test_asegurar_webhook_actualiza_el_propio(api):
    pedidos, respuestas = api
    url = "https://asistente.neboaiconsulting.com/integraciones/whatsapp/webhook"
    respuestas[("GET", "/webhooks/settings")] = (200, {"webhooks": [
        {"_id": "w1", "name": "Jarvis asistente.neboaiconsulting.com", "url": url}]})
    respuestas[("PUT", "/webhooks/settings")] = (200, {"webhook": {"_id": "w1"}})
    assert zernio.asegurar_webhook(url) == "w1"
    assert json.loads(pedidos[1].content)["_id"] == "w1"
