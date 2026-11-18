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


def test_conectar_outlook_pide_correo_y_calendario(api):
    pedidos, respuestas = api
    respuestas[("GET", "/connect/microsoft")] = (200, {"authUrl": "https://login.microsoftonline.com/x"})
    assert zernio.url_conexion_microsoft("p1", "https://j/cb?estado=e") == "https://login.microsoftonline.com/x"
    p = pedidos[0].url.params
    assert p["profileId"] == "p1" and p["scopes"] == "email,calendar" and p["redirect_url"] == "https://j/cb?estado=e"


def test_conectar_outlook_sin_enlace_es_error(api):
    _, respuestas = api
    respuestas[("GET", "/connect/microsoft")] = (200, {})
    with pytest.raises(zernio.ErrorZernio):
        zernio.url_conexion_microsoft("p1", "https://j/cb")


def test_hilos_busca_con_kql_o_desde_el_cursor(api):
    pedidos, respuestas = api
    respuestas[("GET", "/email/threads")] = (200, {"data": [{"id": "t1"}]})
    assert zernio.hilos("acc", buscar="from:carlos") == [{"id": "t1"}]
    zernio.hilos("acc", despues="2026-11-18T10:00:00+00:00", limite=20, ascendente=True)
    a, b = pedidos[0].url.params, pedidos[1].url.params
    assert a["searchQueryNative"] == "from:carlos" and "after" not in a and a["accountId"] == "acc"
    assert a["sortOrder"] == "desc"
    assert b["after"] == "2026-11-18T10:00:00+00:00" and b["limit"] == "20" and b["sortOrder"] == "asc"
    assert "searchQueryNative" not in b


def test_hilo_codifica_el_id_y_pide_texto_limpio(api):
    pedidos, respuestas = api
    respuestas[("GET", "/email/threads/AAQk/x=")] = (200, {"data": {"id": "AAQk/x=", "messages": []}})
    assert zernio.hilo("AAQk/x=", "acc")["id"] == "AAQk/x="
    assert b"/email/threads/AAQk%2Fx%3D" in pedidos[0].url.raw_path
    assert pedidos[0].url.params["clean"] == "true" and pedidos[0].url.params["accountId"] == "acc"


def test_enviar_correo_nuevo_y_respuesta(api):
    pedidos, respuestas = api
    respuestas[("POST", "/email/messages")] = (201, {"data": {"id": "n1"}})
    respuestas[("POST", "/email/messages/m9/reply")] = (201, {"data": {"id": "n2"}})
    assert zernio.enviar_correo("acc", ["c@jh.com"], "Hola", "Texto", "clave-1") == "n1"
    assert zernio.enviar_correo("acc", ["c@jh.com"], "Re: Hola", "Va", "clave-2", responder_a="m9") == "n2"
    nuevo, respuesta = json.loads(pedidos[0].content), json.loads(pedidos[1].content)
    assert nuevo == {"accountId": "acc", "to": [{"email": "c@jh.com"}], "subject": "Hola", "text": "Texto"}
    assert respuesta["subject"] == "Re: Hola" and respuesta["to"] == [{"email": "c@jh.com"}]
    assert pedidos[0].headers["idempotency-key"] == "clave-1"


def test_eventos_sigue_el_cursor_y_no_repite(api, monkeypatch):
    paginas = [
        {"data": [{"id": "e2", "start": "2026-11-18T15:00:00-04:00"}, {"id": "e1", "start": "2026-11-18T09:00:00-04:00"}],
         "pagination": {"hasMore": True, "nextCursor": "c2"}},
        {"data": [{"id": "e1", "start": "2026-11-18T09:00:00-04:00"}], "pagination": {"hasMore": False, "nextCursor": None}},
    ]
    pedidos = []

    def manejar(pedido):
        pedidos.append(pedido)
        return httpx.Response(200, json=paginas[len(pedidos) - 1])

    monkeypatch.setattr(zernio, "_http", lambda: httpx.Client(transport=httpx.MockTransport(manejar)))
    eventos = zernio.eventos("acc", "2026-11-18T00:00:00-04:00", "2026-11-19T00:00:00-04:00", "America/Santo_Domingo")
    assert [e["id"] for e in eventos] == ["e1", "e2"]
    assert pedidos[0].url.params["timezone"] == "America/Santo_Domingo"
    assert pedidos[1].url.params["cursor"] == "c2"


def test_huecos_manda_el_horario_con_domingo_cero(api):
    pedidos, respuestas = api
    respuestas[("POST", "/calendar/availability")] = (200, {"data": {"timeSlots": [{"from": "a", "to": "b"}]}})
    horario = {"inicio": "08:00", "fin": "18:00", "dias": [1, 2, 7], "zona": "America/Santo_Domingo"}
    assert zernio.huecos("acc", "2026-11-18T08:00:00-04:00", "2026-11-25T00:00:00-04:00", 30, horario) == [
        {"from": "a", "to": "b"}]
    cuerpo = json.loads(pedidos[0].content)
    (participante,) = cuerpo["participants"]
    assert participante["accountId"] == "acc"
    assert participante["openHours"] == [{"days": [0, 1, 2], "timezone": "America/Santo_Domingo",
                                          "start": "08:00", "end": "18:00"}]
    assert cuerpo["durationMinutes"] == 30


def test_crear_evento_con_teams(api):
    pedidos, respuestas = api
    respuestas[("POST", "/calendar/events")] = (201, {"data": {"id": "ev1", "conferencing": {"url": "https://teams/x"}}})
    evento = zernio.crear_evento("acc", "Revision", "2026-11-20T15:00:00-04:00", "2026-11-20T15:30:00-04:00",
                                 "America/Santo_Domingo", ["p@x.com"], "Traer <contrato>")
    assert evento["conferencing"]["url"] == "https://teams/x"
    cuerpo = json.loads(pedidos[0].content)
    assert cuerpo["conferencing"] == "teams" and cuerpo["participants"] == [{"email": "p@x.com"}]
    assert cuerpo["timezone"] == "America/Santo_Domingo" and cuerpo["title"] == "Revision"
    assert cuerpo["description"] == "Traer &lt;contrato&gt;"
