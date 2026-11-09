# tests/test_avisos.py
import json
from types import SimpleNamespace

import pytest

from backend import avisos, cerebro


def test_crear_no_duplica_y_cuenta_no_vistos():
    assert avisos.crear("u1", "m1", "h1", "Carlos", "Precio", "pide precio", con_whatsapp=True)
    assert not avisos.crear("u1", "m1", "h1", "Carlos", "Precio", "pide precio", con_whatsapp=True)
    assert avisos.contador("u1") == 1 and avisos.contador("u2") == 0
    (aviso,) = avisos.listar("u1", solo_no_vistos=True)
    assert aviso["whatsapp"] == "pendiente" and aviso["ref"] == "m1"


def test_marcar_visto_es_solo_del_dueno():
    avisos.crear("u1", "m1", "h1", "C", "A", "r", con_whatsapp=False)
    (aviso,) = avisos.listar("u1")
    assert not avisos.marcar_visto("u2", aviso["id"])
    assert avisos.marcar_visto("u1", aviso["id"])
    assert avisos.contador("u1") == 0 and avisos.listar("u1", solo_no_vistos=True) == []


class _Cliente:
    def __init__(self, salida):
        self.pedidos = []
        self.responses = SimpleNamespace(create=self._crear)
        self._salida = salida

    def _crear(self, **kwargs):
        self.pedidos.append(kwargs)
        return SimpleNamespace(output_text=self._salida, usage=None)


CORREO = {"de": "Carlos <c@jh.com>", "asunto": "Precio", "texto": "Necesito cotizacion " * 300}


def test_clasificar_usa_las_reglas_y_delimita_el_correo(monkeypatch):
    cliente = _Cliente(json.dumps({"importante": True, "resumen": "Carlos pide cotizacion"}))
    monkeypatch.setattr(cerebro, "cliente", lambda: cliente)
    r = avisos.clasificar("clientes que piden cotizacion", CORREO, None)
    assert r == {"importante": True, "resumen": "Carlos pide cotizacion"}
    pedido = cliente.pedidos[0]
    assert pedido["model"] == "gpt-5.6-luna"
    assert "clientes que piden cotizacion" in pedido["input"]
    assert "<<<" in pedido["input"] and ">>>" in pedido["input"]
    assert "ignora" in pedido["instructions"].lower()
    assert len(pedido["input"]) < 3000   # el texto va recortado a 2000


def test_clasificar_con_json_raro_no_es_importante(monkeypatch):
    monkeypatch.setattr(cerebro, "cliente", lambda: _Cliente("no es json"))
    with pytest.raises(ValueError):
        avisos.clasificar("x", CORREO, None)


from backend import acceso, dispositivos, gmail, integraciones, whatsapp


def _correo(ref, etiquetas=("INBOX",), de="Carlos <c@jh.com>"):
    return {"id": ref, "threadId": "h-" + ref, "labelIds": list(etiquetas), "snippet": "",
            "payload": {"headers": [{"name": "From", "value": de}, {"name": "Subject", "value": "Asunto " + ref}],
                        "mimeType": "text/plain", "body": {}}}


@pytest.fixture
def buzon(monkeypatch):
    """u1 con Gmail conectado desde el cursor 100 y reglas escritas."""
    integraciones.guardar_gmail("u1", "ana@gmail.com", "r1", "100")
    integraciones.guardar_reglas("u1", "clientes que piden precio", "8095551234", True)
    monkeypatch.setattr(dispositivos, "usuario_para", lambda uid: acceso.Usuario(uid, "Ana", "usuario"))
    monkeypatch.setattr(gmail, "token_de_acceso", lambda r: "t")
    monkeypatch.setattr(whatsapp, "configurado", lambda: True)
    estado = {"ids": [], "nuevo": "200", "correos": {}, "clasificados": [], "veredicto": True}
    monkeypatch.setattr(gmail, "historial", lambda t, desde: (list(estado["ids"]), estado["nuevo"]))
    monkeypatch.setattr(gmail, "mensaje", lambda t, ref: estado["correos"][ref])

    def clasificar(reglas, correo, usuario):
        estado["clasificados"].append(correo["asunto"])
        if isinstance(estado["veredicto"], Exception):
            raise estado["veredicto"]
        return {"importante": estado["veredicto"], "resumen": "resumen de " + correo["asunto"]}

    monkeypatch.setattr(avisos, "clasificar", clasificar)
    return estado


def test_avisa_de_lo_importante_y_avanza_el_cursor(buzon):
    buzon["ids"] = ["m1"]
    buzon["correos"]["m1"] = _correo("m1")
    avisos.revisar_buzon(integraciones.conexion("u1"))
    (aviso,) = avisos.listar("u1")
    assert aviso["resumen"] == "resumen de Asunto m1" and aviso["whatsapp"] == "pendiente"
    assert integraciones.conexion("u1")["cursor"] == "200"


def test_descarta_categorias_y_lo_propio_sin_llamar_a_la_ia(buzon):
    buzon["ids"] = ["p", "s", "yo"]
    buzon["correos"] = {"p": _correo("p", ("INBOX", "CATEGORY_PROMOTIONS")),
                        "s": _correo("s", ("INBOX", "SPAM")),
                        "yo": _correo("yo", de="Ana <ana@gmail.com>")}
    avisos.revisar_buzon(integraciones.conexion("u1"))
    assert buzon["clasificados"] == [] and avisos.listar("u1") == []
    assert integraciones.conexion("u1")["cursor"] == "200"


def test_sin_reglas_no_hay_avisos(buzon):
    integraciones.guardar_reglas("u1", "", "", True)
    buzon["ids"] = ["m1"]
    buzon["correos"]["m1"] = _correo("m1")
    avisos.revisar_buzon(integraciones.conexion("u1"))
    assert buzon["clasificados"] == [] and integraciones.conexion("u1")["cursor"] == "200"


def test_si_la_ia_falla_no_avanza_y_a_los_tres_avisa_igual(buzon):
    buzon["ids"] = ["m1"]
    buzon["correos"]["m1"] = _correo("m1")
    buzon["veredicto"] = RuntimeError("caida")
    for _ in range(2):
        avisos.revisar_buzon(integraciones.conexion("u1"))
        assert integraciones.conexion("u1")["cursor"] == "100" and avisos.listar("u1") == []
    avisos.revisar_buzon(integraciones.conexion("u1"))
    (aviso,) = avisos.listar("u1")
    assert aviso["resumen"] == "Asunto m1"
    assert integraciones.conexion("u1")["cursor"] == "200"


def test_no_vuelve_a_clasificar_lo_resuelto(buzon):
    buzon["ids"] = ["m1", "m2"]
    buzon["correos"] = {"m1": _correo("m1"), "m2": _correo("m2")}
    buzon["veredicto"] = False
    avisos.revisar_buzon(integraciones.conexion("u1"))
    integraciones.mover_cursor("u1", "100")   # como si el cursor no hubiera avanzado
    avisos.revisar_buzon(integraciones.conexion("u1"))
    assert buzon["clasificados"] == ["Asunto m1", "Asunto m2"]


def test_mas_de_veinte_se_reparten_en_varias_vueltas(buzon):
    buzon["ids"] = [f"m{i}" for i in range(25)]
    buzon["correos"] = {i: _correo(i) for i in buzon["ids"]}
    buzon["veredicto"] = False
    avisos.revisar_buzon(integraciones.conexion("u1"))
    assert len(buzon["clasificados"]) == 20 and integraciones.conexion("u1")["cursor"] == "100"
    avisos.revisar_buzon(integraciones.conexion("u1"))
    assert len(buzon["clasificados"]) == 25 and integraciones.conexion("u1")["cursor"] == "200"


def test_historial_viejo_reinicia_desde_hoy_sin_avisar(buzon, monkeypatch):
    def viejo(t, desde):
        raise gmail.ErrorGmail("x", status=404)

    monkeypatch.setattr(gmail, "historial", viejo)
    monkeypatch.setattr(gmail, "perfil", lambda t: {"email": "ana@gmail.com", "historyId": "999"})
    avisos.revisar_buzon(integraciones.conexion("u1"))
    assert integraciones.conexion("u1")["cursor"] == "999" and avisos.listar("u1") == []


def test_acceso_revocado_desconecta_y_avisa(buzon, monkeypatch):
    def revocado(r):
        raise gmail.ErrorGmail("Google retiro el acceso a este Gmail.", revocado=True)

    monkeypatch.setattr(gmail, "token_de_acceso", revocado)
    avisos.revisar_buzon(integraciones.conexion("u1"))
    assert integraciones.conexion("u1")["estado"] == "desconectado"
    (aviso,) = avisos.listar("u1")
    assert aviso["tipo"] == "sistema" and "Integraciones" in aviso["resumen"]


def test_quien_perdio_el_acceso_a_jarvis_no_se_revisa(buzon, monkeypatch):
    monkeypatch.setattr(dispositivos, "usuario_para", lambda uid: None)
    buzon["ids"] = ["m1"]
    buzon["correos"]["m1"] = _correo("m1")
    avisos.revisar_buzon(integraciones.conexion("u1"))
    assert buzon["clasificados"] == []


def test_mandar_pendientes_respeta_el_tope_y_reintenta(buzon, monkeypatch):
    enviados = []
    monkeypatch.setattr(whatsapp, "enviar_texto", lambda n, t: enviados.append((n, t)))
    monkeypatch.setattr(avisos, "MAX_WHATSAPP_HORA", 2)
    for i in range(3):
        avisos.crear("u1", f"m{i}", None, "Carlos", "A", f"resumen {i}", con_whatsapp=True)
    avisos.mandar_pendientes()
    estados = sorted(a["whatsapp"] for a in avisos.listar("u1"))
    assert estados == ["enviado", "enviado", "tope"]
    assert enviados[0][0] == "18095551234" and "📧 Carlos" in enviados[0][1]


def test_whatsapp_que_falla_tres_veces_queda_fallido(buzon, monkeypatch):
    def falla(n, t):
        raise whatsapp.ErrorEnvio("caido")

    monkeypatch.setattr(whatsapp, "enviar_texto", falla)
    avisos.crear("u1", "m1", None, "Carlos", "A", "r", con_whatsapp=True)
    for _ in range(3):
        avisos.mandar_pendientes()
    assert avisos.listar("u1")[0]["whatsapp"] == "fallido"


def test_una_vuelta_no_se_cae_si_un_buzon_explota(buzon, monkeypatch):
    integraciones.guardar_gmail("u2", "b@gmail.com", "r2", "1")
    vistos = []

    def revisar(c):
        vistos.append(c["usuario_id"])
        if c["usuario_id"] == "u1":
            raise RuntimeError("boom")

    monkeypatch.setattr(avisos, "revisar_buzon", revisar)
    monkeypatch.setattr(avisos, "mandar_pendientes", lambda: None)
    avisos.una_vuelta()
    assert vistos == ["u1", "u2"]
