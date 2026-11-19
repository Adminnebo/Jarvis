"""WhatsApp por Evolution: vincular, webhook y herramientas (whatsapp_chats.py)."""

import time

import pytest

from backend import avisos, basedatos, dispositivos, evolution_wa, integraciones, whatsapp, whatsapp_chats


@pytest.fixture
def evo(monkeypatch):
    """u1 con instancia de Evolution preparada, reglas y acceso. Devuelve la fila."""
    monkeypatch.setenv("EVOLUTION_URL", "https://evo")
    monkeypatch.setenv("EVOLUTION_API_KEY", "k")
    monkeypatch.setattr(dispositivos, "usuario_para", lambda u: object() if u == "u1" else None)
    monkeypatch.setattr(whatsapp, "numeros_propios", lambda: {"18090000000"})
    integraciones.guardar_reglas("u1", "clientes que reclaman", "8095551234", True)
    whatsapp_chats._qr.clear()
    return integraciones.preparar_evolution("u1")


@pytest.fixture
def conectado(evo):
    integraciones.conectar_evolution("u1", "18095551234")
    return evo


def upsert(clave, texto="hola", id_="m1", jid="18097778888@s.whatsapp.net", desde_mi=False,
           instancia="jarvis-u1", hace=0, **clave_extra):
    return {"event": "messages.upsert", "instance": instancia, "data": {
        "key": {"remoteJid": jid, "fromMe": desde_mi, "id": id_, **clave_extra},
        "pushName": "Pedro", "message": {"conversation": texto} if texto is not None else {"stickerMessage": {}},
        "messageTimestamp": int(time.time()) - hace}}


def pendientes():
    with basedatos.conexion() as con:
        return [dict(f) for f in con.execute("SELECT * FROM whatsapp_pendientes ORDER BY rowid")]


# --- webhook ---

def test_mensaje_entrante_queda_pendiente(conectado):
    assert whatsapp_chats.recibir_evolution(upsert(conectado["clave"]), conectado["clave"]) == "pendiente"
    (p,) = pendientes()
    assert (p["conversacion"], p["mensaje_id"], p["remitente"], p["telefono"], p["texto"]) == (
        "18097778888@s.whatsapp.net", "m1", "Pedro", "18097778888", "hola")


def test_clave_desconocida_o_instancia_cambiada(conectado):
    assert whatsapp_chats.recibir_evolution(upsert("x"), "x") == "clave desconocida"
    assert whatsapp_chats.recibir_evolution(upsert("", instancia="otra"), conectado["clave"]) == "otra instancia"
    assert pendientes() == []


@pytest.mark.parametrize("cambio, motivo", [
    ({"jid": "1203@g.us"}, "grupo"),
    ({"texto": None}, "vacio"),
    ({"jid": "18090000000@s.whatsapp.net"}, "aviso de jarvis"),
    ({"hace": 3600}, "viejo"),
])
def test_filtros(conectado, cambio, motivo):
    assert whatsapp_chats.recibir_evolution(upsert(conectado["clave"], **cambio), conectado["clave"]) == motivo
    assert pendientes() == []


def test_con_lid_saca_el_numero_de_remote_jid_alt(conectado):
    ev = upsert(conectado["clave"], jid="555@lid", remoteJidAlt="18097778888@s.whatsapp.net")
    whatsapp_chats.recibir_evolution(ev, conectado["clave"])
    assert pendientes()[0]["telefono"] == "18097778888" and pendientes()[0]["conversacion"] == "555@lid"


def test_si_contesta_desde_el_telefono_se_descarta(conectado):
    clave = conectado["clave"]
    whatsapp_chats.recibir_evolution(upsert(clave, id_="m1"), clave)
    assert whatsapp_chats.recibir_evolution(upsert(clave, id_="m2", desde_mi=True), clave) == "contestado"
    assert pendientes() == [] and avisos._resuelto("u1", "wa:m1")


def test_qr_nuevo_por_webhook(evo):
    ev = {"event": "qrcode.updated", "instance": "jarvis-u1",
          "data": {"qrcode": {"base64": "data:image/png;base64,NUEVO", "pairingCode": None}}}
    assert whatsapp_chats.recibir_evolution(ev, evo["clave"]) == "qr"
    assert whatsapp_chats._qr["u1"]["qr"].endswith("NUEVO")


def test_conexion_abierta_conecta(evo, monkeypatch):
    monkeypatch.setattr(evolution_wa, "numero", lambda inst: "18095551234")
    ev = {"event": "connection.update", "instance": "jarvis-u1", "data": {"state": "open"}}
    assert whatsapp_chats.recibir_evolution(ev, evo["clave"]) == "conectado"
    assert integraciones.conexion("u1", "whatsapp")["cuenta"] == "+1 809-555-1234"


def test_cierre_de_sesion_avisa_y_un_corte_normal_no(conectado):
    clave = conectado["clave"]
    corte = {"event": "connection.update", "instance": "jarvis-u1", "data": {"state": "close", "statusReason": 428}}
    assert whatsapp_chats.recibir_evolution(corte, clave) == "sin accion"
    assert integraciones.conexion("u1", "whatsapp")["estado"] == "conectado"
    fuera = {"event": "connection.update", "instance": "jarvis-u1", "data": {"state": "close", "statusReason": 401}}
    assert whatsapp_chats.recibir_evolution(fuera, clave) == "desconectado"
    assert integraciones.conexion("u1", "whatsapp")["estado"] == "desconectado"
    (aviso,) = avisos.listar("u1")
    assert aviso["tipo"] == "sistema"


# --- vincular ---

def test_vincular_crea_la_instancia_con_su_webhook(evo, monkeypatch):
    creadas = []
    monkeypatch.setattr(evolution_wa, "estado", lambda inst: None)
    monkeypatch.setattr(evolution_wa, "crear", lambda inst, url, numero="": creadas.append((inst, url, numero))
                        or {"qr": "QR1", "codigo": None})
    r = whatsapp_chats.vincular("u1")
    assert r == {"estado": "esperando", "qr": "QR1", "codigo": None}
    ((inst, url, numero),) = creadas
    assert inst == "jarvis-u1" and numero == ""
    assert url == f"https://asistente.neboaiconsulting.com/integraciones/whatsapp/evolution?clave={evo['clave']}"


def test_vincular_con_numero_da_codigo_y_reusa_la_instancia(evo, monkeypatch):
    monkeypatch.setattr(evolution_wa, "estado", lambda inst: "connecting")
    pedidos = []
    monkeypatch.setattr(evolution_wa, "conectar", lambda inst, numero="": pedidos.append(numero)
                        or {"qr": "Q", "codigo": "ABCD1234"})
    assert whatsapp_chats.vincular("u1", "809 555 1234")["codigo"] == "ABCD1234"
    assert pedidos == ["18095551234"]


def test_vincular_con_numero_malo(evo):
    with pytest.raises(whatsapp_chats.ErrorChat):
        whatsapp_chats.vincular("u1", "123")


def test_estado_del_vinculo(evo, monkeypatch):
    estados = iter(["connecting", "open"])
    monkeypatch.setattr(evolution_wa, "estado", lambda inst: next(estados))
    monkeypatch.setattr(evolution_wa, "numero", lambda inst: "18095551234")
    whatsapp_chats._qr["u1"] = {"qr": "Q", "codigo": None, "numero": "", "cuando": time.time()}
    assert whatsapp_chats.estado_vinculo("u1") == {"estado": "esperando", "qr": "Q", "codigo": None}
    assert whatsapp_chats.estado_vinculo("u1") == {"estado": "conectado", "cuenta": "+1 809-555-1234"}


def test_estado_del_vinculo_renueva_un_qr_viejo(evo, monkeypatch):
    monkeypatch.setattr(evolution_wa, "estado", lambda inst: "connecting")
    monkeypatch.setattr(evolution_wa, "conectar", lambda inst, numero="": {"qr": "NUEVO", "codigo": None})
    whatsapp_chats._qr["u1"] = {"qr": "VIEJO", "codigo": None, "numero": "", "cuando": time.time() - 120}
    assert whatsapp_chats.estado_vinculo("u1")["qr"] == "NUEVO"


def test_desvincular_borra_en_evolution(conectado, monkeypatch):
    borradas = []
    monkeypatch.setattr(evolution_wa, "borrar", borradas.append)
    whatsapp_chats.desvincular("u1")
    assert borradas == ["jarvis-u1"] and integraciones.instancia_evolution("u1") is None


# --- herramientas ---

CHATS = [
    {"id": "18097778888@s.whatsapp.net", "nombre": "Pedro Gomez", "telefono": "18097778888",
     "ultimo": "y el pedido?", "ultimo_id": "m9", "ultimo_mio": False, "no_leidos": 2, "actualizado": time.time()},
    {"id": "18091112222@s.whatsapp.net", "nombre": "Maria", "telefono": "18091112222",
     "ultimo": "gracias", "ultimo_id": "m8", "ultimo_mio": True, "no_leidos": 0, "actualizado": time.time() - 99999},
]


def test_buscar_y_leer(conectado, monkeypatch):
    monkeypatch.setattr(evolution_wa, "chats", lambda inst, limite=50: CHATS)
    monkeypatch.setattr(evolution_wa, "mensajes", lambda inst, jid, limite=30: [
        {"id": "a", "entrante": True, "nombre": "Pedro", "texto": "y el pedido?", "momento": 1700000000},
        {"id": "b", "entrante": False, "nombre": None, "texto": "va en camino", "momento": 1700000300}])
    resultado = whatsapp_chats.buscar("u1", "pedro")
    assert "chat id 18097778888@s.whatsapp.net" in resultado and "2 sin leer" in resultado and "Maria" not in resultado
    assert "Maria" in whatsapp_chats.buscar("u1", "1112222")
    texto = whatsapp_chats.leer("u1", "18097778888@s.whatsapp.net")
    assert "Pedro: y el pedido?" in texto and "Tu: va en camino" in texto


def test_responder_y_confirmar(conectado, monkeypatch):
    monkeypatch.setattr(evolution_wa, "chats", lambda inst, limite=50: CHATS)
    enviados = []
    monkeypatch.setattr(evolution_wa, "enviar", lambda inst, jid, texto: enviados.append((inst, jid, texto)) or "id1")
    assert "Pedro Gomez" in whatsapp_chats.preparar("u1", "18097778888@s.whatsapp.net", "Mañana llega")
    assert "Enviado" in whatsapp_chats.confirmar("u1")
    assert enviados == [("jarvis-u1", "18097778888@s.whatsapp.net", "Mañana llega")]


def test_responder_a_un_chat_que_no_es_suyo(conectado, monkeypatch):
    monkeypatch.setattr(evolution_wa, "chats", lambda inst, limite=50: CHATS)
    with pytest.raises(whatsapp_chats.ErrorChat, match="No encontre"):
        whatsapp_chats.preparar("u1", "otro@s.whatsapp.net", "hola")


def test_si_evolution_falla_lo_dice(conectado, monkeypatch):
    def falla(*a, **k):
        raise evolution_wa.ErrorEvolution("caido", 500)

    monkeypatch.setattr(evolution_wa, "chats", falla)
    with pytest.raises(whatsapp_chats.ErrorChat, match="caido"):
        whatsapp_chats.buscar("u1")


def test_barrido_recupera_el_ultimo_mensaje(conectado, monkeypatch):
    monkeypatch.setattr(evolution_wa, "chats", lambda inst, limite=50: CHATS)
    whatsapp_chats._ultimo_barrido["u1"] = time.time() - 3600
    whatsapp_chats.barrer("u1")
    (p,) = pendientes()
    assert (p["mensaje_id"], p["texto"], p["remitente"]) == ("m9", "y el pedido?", "Pedro Gomez")
    whatsapp_chats._ultimo_barrido["u1"] = time.time() - 3600
    whatsapp_chats.barrer("u1")
    assert len(pendientes()) == 1   # no lo repite
