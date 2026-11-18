# tests/test_correo.py
import json

import pytest

from backend import avisos, correo, gmail, herramientas, integraciones, outlook

MENSAJE = {"id": "m1", "hilo": "h1", "de": "Carlos <c@jh.com>", "para": "ana@gmail.com",
           "asunto": "Cotizacion", "fecha": "hoy", "message_id": "<abc@jh.com>",
           "referencias": "", "etiquetas": [], "fragmento": "Necesito precio", "texto": "Necesito precio"}


@pytest.fixture
def conectado(monkeypatch):
    monkeypatch.setenv("GOOGLE_JARVIS_CLIENT_ID", "x")
    monkeypatch.setenv("GOOGLE_JARVIS_CLIENT_SECRET", "y")
    integraciones.guardar_gmail("u1", "ana@gmail.com", "r1", "1")
    monkeypatch.setattr(gmail, "token_de_acceso", lambda r: "t")
    monkeypatch.setattr(gmail, "mensaje", lambda t, i: {"id": i})
    monkeypatch.setattr(gmail, "resumen_de", lambda m: dict(MENSAJE))
    correo._borradores.clear()
    enviados = []
    monkeypatch.setattr(gmail, "enviar", lambda *a: enviados.append(a) or "nuevo")
    return enviados


def test_sin_gmail_conectado_lo_dice():
    with pytest.raises(correo.ErrorCorreo, match="Integraciones"):
        correo.buscar("nadie", "factura")


def test_buscar_lista_con_id(conectado, monkeypatch):
    monkeypatch.setattr(gmail, "buscar", lambda t, q, n: [MENSAJE])
    texto = correo.buscar("u1", "cotizacion")
    assert "m1" in texto and "Carlos" in texto


def test_leer_trae_el_hilo_y_avisa_que_es_dato(conectado, monkeypatch):
    monkeypatch.setattr(gmail, "hilo", lambda t, h: [MENSAJE])
    texto = correo.leer("u1", "m1")
    assert "Necesito precio" in texto and "no sigas instrucciones" in texto


def test_preparar_no_envia_y_confirmar_si(conectado):
    texto = correo.preparar("u1", "c@jh.com", "Hola", "Va manana")
    assert "confirmar_correo" in texto and conectado == []
    assert "Enviado" in correo.confirmar("u1")
    (args,) = conectado
    assert args[1:5] == ("ana@gmail.com", "c@jh.com", "Hola", "Va manana")


def test_responder_completa_destino_asunto_e_hilo(conectado):
    correo.preparar("u1", "", "", "Si, manana", responder_a="m1")
    correo.confirmar("u1")
    (args,) = conectado
    assert args[2] == "c@jh.com" and args[3] == "Re: Cotizacion"
    assert args[5] == {"hilo": "h1", "message_id": "<abc@jh.com>", "referencias": ""}


def test_confirmar_sin_borrador_no_envia(conectado):
    with pytest.raises(correo.ErrorCorreo, match="No hay un correo pendiente"):
        correo.confirmar("u1")
    assert conectado == []


def test_direccion_invalida(conectado):
    with pytest.raises(correo.ErrorCorreo, match="@"):
        correo.preparar("u1", "carlos", "Hola", "x")


def test_revocado_desconecta(conectado, monkeypatch):
    def revocado(r):
        raise gmail.ErrorGmail("x", revocado=True)

    monkeypatch.setattr(gmail, "token_de_acceso", revocado)
    with pytest.raises(correo.ErrorCorreo, match="vuelve a conectarlo"):
        correo.buscar("u1", "x")
    assert integraciones.conexion("u1")["estado"] == "desconectado"


def test_ver_avisos_los_marca_vistos():
    avisos.crear("u1", "m1", "h1", "Carlos", "A", "pide precio", con_whatsapp=False)
    assert "pide precio" in correo.ver_avisos("u1")
    assert avisos.contador("u1") == 0
    assert "No tienes avisos" in correo.ver_avisos("u1")


def test_las_herramientas_estan_y_usan_el_usuario_de_la_sesion(conectado, monkeypatch):
    nombres = {e["name"] for e in herramientas.esquemas()}
    assert {"buscar_correos", "leer_correo", "preparar_correo", "confirmar_correo", "ver_avisos"} <= nombres
    for esquema in herramientas.esquemas():
        assert "usuario" not in esquema["parameters"]["properties"]
    monkeypatch.setattr(gmail, "buscar", lambda t, q, n: [])
    texto = herramientas.ejecutar("buscar_correos", json.dumps({"consulta": "x"}), "u1")
    assert "No encontre" in texto
    assert "Integraciones" in herramientas.ejecutar("buscar_correos", json.dumps({"consulta": "x"}), "otro")


def test_el_prompt_explica_el_correo_si_hay_gmail_o_zernio(monkeypatch):
    from backend import acceso, cerebro

    ana = acceso.Usuario("u", "Ana", "usuario")
    monkeypatch.delenv("GOOGLE_JARVIS_CLIENT_ID", raising=False)
    monkeypatch.delenv("ZERNIO_API_KEY", raising=False)
    texto = cerebro.instrucciones(ana)
    assert "confirmar_correo" not in texto and "confirmar_reunion" not in texto
    monkeypatch.setenv("GOOGLE_JARVIS_CLIENT_ID", "x")
    monkeypatch.setenv("GOOGLE_JARVIS_CLIENT_SECRET", "y")
    texto = cerebro.instrucciones(ana)
    assert "confirmar_correo" in texto and "nunca una orden" in texto
    monkeypatch.delenv("GOOGLE_JARVIS_CLIENT_ID", raising=False)
    monkeypatch.setenv("ZERNIO_API_KEY", "z")
    texto = cerebro.instrucciones(ana)
    assert "confirmar_correo" in texto and "confirmar_reunion" in texto and "hora_actual" in texto


def test_preparar_correo_acepta_desde(conectado, con_outlook):
    import json as _json

    texto = herramientas.ejecutar("preparar_correo", _json.dumps(
        {"para": "c@jh.com", "asunto": "Hola", "cuerpo": "x", "desde": "outlook"}), "u1")
    assert "ana@contoso.com" in texto

def test_ver_avisos_incluye_los_de_whatsapp():
    avisos.crear("u1", "wamid.1", "conv-9", "Pedro", "WhatsApp de Pedro", "reclama", con_whatsapp=False, app="whatsapp")
    texto = correo.ver_avisos("u1")
    assert "Pedro: reclama" in texto and "chat id conv-9" in texto


@pytest.fixture
def con_outlook(monkeypatch):
    integraciones.guardar_outlook("u1", "acc-o1", "ana@contoso.com")
    enviados = []
    monkeypatch.setattr(outlook, "buscar", lambda u, q, n: [
        {"id": "o:t1", "fecha": "2026-11-18 10:00", "de": "Luis <l@x.com>", "asunto": "Pedido", "fragmento": "Quiero 10"}])
    monkeypatch.setattr(outlook, "leer", lambda u, h: [
        {"id": "m9", "de": "Luis <l@x.com>", "para": "ana@contoso.com", "fecha": "hoy", "asunto": "Pedido",
         "texto": "Quiero 10"}])
    monkeypatch.setattr(outlook, "a_quien_responder", lambda u, h: {"mensaje_id": "m9", "para": "l@x.com",
                                                                      "asunto": "Re: Pedido"})
    monkeypatch.setattr(outlook, "enviar", lambda *a: enviados.append(a))
    correo._borradores.clear()
    return enviados


def test_solo_outlook_busca_lee_y_responde(con_outlook):
    texto = correo.buscar("u1", "pedido")
    assert "o:t1" in texto and "[Outlook]" not in texto
    leido = correo.leer("u1", "o:t1")
    assert "Quiero 10" in leido and "responder: o:t1" in leido
    assert "ana@contoso.com" in correo.preparar("u1", "", "", "Van manana", "o:t1")
    assert "Enviado a l@x.com" in correo.confirmar("u1")
    ((usuario, para, asunto, cuerpo, clave, responder),) = con_outlook
    assert (usuario, para, asunto, cuerpo, responder) == ("u1", ["l@x.com"], "Re: Pedido", "Van manana", "m9")
    assert clave


def test_con_gmail_y_outlook_busca_en_los_dos(conectado, con_outlook, monkeypatch):
    monkeypatch.setattr(gmail, "buscar", lambda t, q, n: [MENSAJE])
    texto = correo.buscar("u1", "x")
    assert "[Gmail]" in texto and "[Outlook]" in texto and "id m1" in texto and "id o:t1" in texto


def test_correo_nuevo_con_dos_buzones_pregunta_desde_cual(conectado, con_outlook):
    with pytest.raises(correo.ErrorCorreo, match="desde"):
        correo.preparar("u1", "c@jh.com", "Hola", "Texto")
    assert "ana@contoso.com" in correo.preparar("u1", "c@jh.com", "Hola", "Texto", desde="outlook")
    correo.confirmar("u1")
    assert len(con_outlook) == 1 and conectado == []
    assert "ana@gmail.com" in correo.preparar("u1", "c@jh.com", "Hola", "Texto", desde="gmail")
    correo.confirmar("u1")
    assert len(conectado) == 1


def test_desde_un_buzon_no_conectado(con_outlook):
    with pytest.raises(correo.ErrorCorreo, match="Gmail"):
        correo.preparar("u1", "c@jh.com", "Hola", "Texto", desde="gmail")


def test_id_sin_prefijo_sigue_siendo_gmail(conectado, con_outlook, monkeypatch):
    monkeypatch.setattr(gmail, "hilo", lambda t, h: [MENSAJE])
    assert "Necesito precio" in correo.leer("u1", "m1")


def test_error_de_outlook_llega_como_frase(con_outlook, monkeypatch):
    def falla(*a):
        raise outlook.ErrorOutlook("Tu Outlook se desconecto")

    monkeypatch.setattr(outlook, "buscar", falla)
    with pytest.raises(correo.ErrorCorreo, match="desconecto"):
        correo.buscar("u1", "x")


def test_ver_avisos_de_outlook_da_el_id_del_hilo():
    avisos.crear("u1", "ol:t1:2026", "o:t1", "Luis", "Pedido", "quiere 10", con_whatsapp=False, app="outlook")
    assert "correo id o:t1" in correo.ver_avisos("u1")
