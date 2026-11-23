"""gmail.py: lo que usa la bandeja de /apps/correo (permisos, lectura y escritura)."""

import base64
import json

import httpx
import pytest

from backend import gmail


@pytest.fixture
def api(monkeypatch):
    """Google falso: `respuestas` es {(METODO, ruta): (status, json)}; anota cada pedido."""
    monkeypatch.setenv("GOOGLE_JARVIS_CLIENT_ID", "id")
    monkeypatch.setenv("GOOGLE_JARVIS_CLIENT_SECRET", "secreto")
    pedidos, respuestas = [], {}

    def manejar(pedido: httpx.Request):
        pedidos.append(pedido)
        ruta = pedido.url.path.removeprefix("/gmail/v1/users/me")
        status, cuerpo = respuestas.get((pedido.method, ruta), (404, {"error": {"message": "no existe"}}))
        return httpx.Response(status, json=cuerpo)

    cliente = httpx.Client(transport=httpx.MockTransport(manejar))
    monkeypatch.setattr(gmail, "_http", lambda: cliente)
    gmail._cache_tokens.clear()
    gmail._permisos.clear()
    return pedidos, respuestas


# --- permisos ---

def test_pide_modificar():
    assert gmail.MODIFICAR in gmail.PERMISOS


def test_permisos_salen_del_refresco(api):
    pedidos, respuestas = api
    respuestas[("POST", "/token")] = (200, {"access_token": "a", "expires_in": 3600,
                                            "scope": f"{gmail.LEER} {gmail.ENVIAR} {gmail.MODIFICAR}"})
    assert gmail.puede_modificar("r1")
    assert gmail.permisos("r1") == {gmail.LEER, gmail.ENVIAR, gmail.MODIFICAR}
    assert len([p for p in pedidos if p.url.path == "/token"]) == 1   # una sola vez


def test_sin_modificar(api):
    _, respuestas = api
    respuestas[("POST", "/token")] = (200, {"access_token": "a", "expires_in": 3600, "scope": f"{gmail.LEER} {gmail.ENVIAR}"})
    assert not gmail.puede_modificar("r2")


def test_el_canje_anota_los_permisos(api):
    _, respuestas = api
    respuestas[("POST", "/token")] = (200, {"access_token": "a", "refresh_token": "r3", "expires_in": 3600,
                                            "scope": f"{gmail.LEER} {gmail.ENVIAR} {gmail.MODIFICAR}"})
    gmail.canjear_codigo("c")
    assert gmail.puede_modificar("r3")


# --- lectura ---

def test_etiquetas_con_contadores(api):
    pedidos, respuestas = api
    respuestas[("GET", "/labels")] = (200, {"labels": [
        {"id": "INBOX", "name": "INBOX", "type": "system"},
        {"id": "Label_1", "name": "Clientes/JH", "type": "user", "color": {"backgroundColor": "#16a766"}},
        {"id": "CHAT", "name": "CHAT", "type": "system"}]})
    respuestas[("GET", "/labels/INBOX")] = (200, {"id": "INBOX", "threadsUnread": 4, "threadsTotal": 90})
    respuestas[("GET", "/labels/Label_1")] = (200, {"id": "Label_1", "threadsUnread": 1, "threadsTotal": 3})
    lista = gmail.etiquetas("t")
    assert {e["id"]: e["no_leidos"] for e in lista} == {"INBOX": 4, "Label_1": 1}
    jh = next(e for e in lista if e["id"] == "Label_1")
    assert jh["nombre"] == "Clientes/JH" and jh["propia"] and jh["color"] == "#16a766"
    assert pedidos[0].headers["authorization"] == "Bearer t"


def test_hilos_de_una_etiqueta_con_busqueda(api):
    pedidos, respuestas = api
    respuestas[("GET", "/threads")] = (200, {"threads": [{"id": "h1"}, {"id": "h2"}], "nextPageToken": "p2"})
    assert gmail.hilos("t", "INBOX", "from:pedro", "p1") == (["h1", "h2"], "p2")
    params = pedidos[0].url.params
    assert params.get_list("labelIds") == ["INBOX"] and params["q"] == "from:pedro"
    assert params["pageToken"] == "p1" and params["maxResults"] == "50"


def test_hilos_de_todos_sin_etiqueta(api):
    pedidos, respuestas = api
    respuestas[("GET", "/threads")] = (200, {})
    assert gmail.hilos("t", "", "", None) == ([], None)
    assert "labelIds" not in pedidos[0].url.params


def test_hilo_completo_y_metadatos(api):
    pedidos, respuestas = api
    respuestas[("GET", "/threads/h1")] = (200, {"id": "h1", "messages": [{"id": "m1"}]})
    assert gmail.hilo_completo("t", "h1")["messages"] == [{"id": "m1"}]
    assert pedidos[0].url.params["format"] == "full"
    gmail.hilo_completo("t", "h1", solo_cabeceras=True)
    assert pedidos[1].url.params["format"] == "metadata"
    assert set(pedidos[1].url.params.get_list("metadataHeaders")) >= {"From", "To", "Subject", "Date"}


def test_adjunto(api):
    _, respuestas = api
    respuestas[("GET", "/messages/m1/attachments/a1")] = (200, {"data": base64.urlsafe_b64encode(b"PDF").decode().rstrip("=")})
    assert gmail.adjunto("t", "m1", "a1") == b"PDF"


def test_cambios(api):
    pedidos, respuestas = api
    respuestas[("GET", "/history")] = (200, {"historyId": "900", "history": [
        {"messagesAdded": [{"message": {"id": "m1", "threadId": "h1"}}]},
        {"labelsRemoved": [{"message": {"id": "m2", "threadId": "h2"}, "labelIds": ["UNREAD"]}]},
        {"messagesDeleted": [{"message": {"id": "m3", "threadId": "h3"}}]}]})
    assert gmail.cambios("t", "800") == {"historyId": "900", "hilos": ["h1", "h2", "h3"]}
    assert pedidos[0].url.params["startHistoryId"] == "800"


# --- escritura ---

def test_modificar_hilos(api):
    pedidos, respuestas = api
    respuestas[("POST", "/threads/h1/modify")] = (200, {})
    respuestas[("POST", "/threads/h2/modify")] = (200, {})
    gmail.modificar_hilos("t", ["h1", "h2"], agregar=["STARRED"], quitar=["INBOX"])
    assert [json.loads(p.content) for p in pedidos] == [{"addLabelIds": ["STARRED"], "removeLabelIds": ["INBOX"]}] * 2


def test_papelera(api):
    pedidos, respuestas = api
    respuestas[("POST", "/threads/h1/trash")] = (200, {})
    gmail.papelera("t", ["h1"])
    assert pedidos[0].url.path.endswith("/threads/h1/trash")


def test_borradores(api):
    pedidos, respuestas = api
    respuestas[("POST", "/drafts")] = (200, {"id": "d1", "message": {"id": "m9", "threadId": "h9"}})
    respuestas[("PUT", "/drafts/d1")] = (200, {"id": "d1", "message": {"id": "m10"}})
    respuestas[("DELETE", "/drafts/d1")] = (204, {})
    respuestas[("POST", "/drafts/send")] = (200, {"id": "m11", "threadId": "h9"})
    assert gmail.guardar_borrador("t", b"RAW", None, "h9")["id"] == "d1"
    cuerpo = json.loads(pedidos[0].content)
    assert cuerpo == {"message": {"raw": base64.urlsafe_b64encode(b"RAW").decode().rstrip("="), "threadId": "h9"}}
    gmail.guardar_borrador("t", b"RAW2", "d1", None)
    assert pedidos[1].method == "PUT" and json.loads(pedidos[1].content)["id"] == "d1"
    gmail.borrar_borrador("t", "d1")
    assert gmail.enviar_borrador("t", "d1")["id"] == "m11"
    assert json.loads(pedidos[3].content) == {"id": "d1"}


def test_enviar_mime(api):
    pedidos, respuestas = api
    respuestas[("POST", "/messages/send")] = (200, {"id": "m5", "threadId": "h5"})
    assert gmail.enviar_mime("t", b"CRUDO", "h5") == {"id": "m5", "threadId": "h5"}
    cuerpo = json.loads(pedidos[0].content)
    assert cuerpo["threadId"] == "h5" and base64.urlsafe_b64decode(cuerpo["raw"] + "==") == b"CRUDO"
