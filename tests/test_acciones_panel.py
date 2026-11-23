"""Acciones de Jarvis en los paneles de JH: se preparan, se confirman y van a la misma
ruta del boton del panel con el token de quien habla."""

import json
import time

import httpx
import pytest

from backend import acciones_panel, herramientas, paneles_jh


@pytest.fixture
def panel(monkeypatch):
    pedidos = []
    clientes = {
        "PRUEBA-JORGE": {"nombre": "Ferretería de Jorge (prueba)", "estado": "contactado", "telefonos": ["+57323"]},
        "REC": {"nombre": "Recuperado SA", "estado": "recuperado", "telefonos": ["809"]},
        "SINTEL": {"nombre": "Sin Telefono", "estado": "por_contactar", "telefonos": []},
    }
    estado = {"encolar": (200, {"encolados": 1, "saltados": 0})}

    def manejar(pedido: httpx.Request):
        pedidos.append(pedido)
        ruta = pedido.url.path
        if ruta.startswith("/reactivacion/api/jarvis/clientes/"):
            codigo = ruta.rsplit("/", 1)[1]
            if codigo not in clientes:
                return httpx.Response(404, json={"error": "Cliente no encontrado"})
            return httpx.Response(200, json={"cliente": {"codigo": codigo, **clientes[codigo]}})
        if ruta == "/reactivacion/api/encolar":
            return httpx.Response(estado["encolar"][0], json=estado["encolar"][1])
        return httpx.Response(404, json={})

    monkeypatch.setattr(paneles_jh, "_http", lambda: httpx.Client(transport=httpx.MockTransport(manejar)))
    paneles_jh._activos.clear()
    acciones_panel._pendientes.clear()
    paneles_jh.activar("u1", "reactivacion", "tok")
    return pedidos, estado


def test_preparar_no_llama_y_confirmar_encola_con_el_token(panel):
    pedidos, _ = panel
    texto = acciones_panel.preparar("u1", "llamar", json.dumps({"codigos": ["PRUEBA-JORGE"]}))
    assert "Ferretería de Jorge" in texto and "confirmar_accion_panel" in texto
    assert not any(p.method == "POST" for p in pedidos)

    listo = acciones_panel.confirmar("u1")
    post = [p for p in pedidos if p.method == "POST"][0]
    assert post.url.path == "/reactivacion/api/encolar"
    assert json.loads(post.content) == {"codigos": ["PRUEBA-JORGE"]}
    assert post.headers["authorization"] == "Bearer tok"
    assert "Listo" in listo
    # un "si" repetido no vuelve a encolar
    with pytest.raises(acciones_panel.ErrorAccion):
        acciones_panel.confirmar("u1")


def test_un_codigo_suelto_tambien_sirve(panel):
    assert "Ferretería" in acciones_panel.preparar("u1", "llamar", json.dumps({"codigo": "PRUEBA-JORGE"}))


def test_avisa_a_quien_no_se_puede_llamar(panel):
    texto = acciones_panel.preparar("u1", "llamar", json.dumps({"codigos": ["PRUEBA-JORGE", "REC", "SINTEL", "NO"]}))
    assert "recuperado" in texto and "no tiene telefono" in texto and "NO: no existe" in texto
    assert acciones_panel._pendientes["u1"].datos == {"codigos": ["PRUEBA-JORGE"]}
    with pytest.raises(acciones_panel.ErrorAccion, match="No hay a quien llamar"):
        acciones_panel.preparar("u1", "llamar", json.dumps({"codigos": ["REC"]}))


def test_sin_permiso_lo_dice_el_panel(panel):
    _, estado = panel
    estado["encolar"] = (403, {"error": "Sin permiso"})
    acciones_panel.preparar("u1", "llamar", json.dumps({"codigos": ["PRUEBA-JORGE"]}))
    with pytest.raises(acciones_panel.ErrorAccion, match="permiso"):
        acciones_panel.confirmar("u1")


def test_vence_y_no_sirve_fuera_del_panel(panel, monkeypatch):
    acciones_panel.preparar("u1", "llamar", json.dumps({"codigos": ["PRUEBA-JORGE"]}))
    acciones_panel._pendientes["u1"].creado = time.time() - acciones_panel.VIGENCIA - 1
    with pytest.raises(acciones_panel.ErrorAccion, match="pendiente"):
        acciones_panel.confirmar("u1")
    paneles_jh._activos.clear()
    with pytest.raises(acciones_panel.ErrorAccion, match="panel"):
        acciones_panel.preparar("u1", "llamar", json.dumps({"codigos": ["PRUEBA-JORGE"]}))


def test_accion_de_otro_panel(panel):
    paneles_jh.activar("u1", "cobranzas", "tok")
    with pytest.raises(acciones_panel.ErrorAccion, match="no existe"):
        acciones_panel.preparar("u1", "llamar", "{}")


def test_herramientas_e_instruccion():
    assert {"preparar_accion_panel", "confirmar_accion_panel"} <= set(herramientas.REGISTRO)
    assert "preparar_accion_panel" in paneles_jh.instruccion("reactivacion")
    assert "preparar_accion_panel" not in paneles_jh.instruccion("cobranzas")
