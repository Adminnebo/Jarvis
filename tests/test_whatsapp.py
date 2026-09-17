import json

import pytest

from backend import archivos, cotizaciones, herramientas, whatsapp

# La real, antes de que el fixture la reemplace por una de mentira.
ENVIAR_REAL = whatsapp._enviar_media


@pytest.fixture
def configurado(entorno_limpio, monkeypatch):
    for variable, valor in {
        "EVOLUTION_URL": "https://evo.test/", "EVOLUTION_API_KEY": "llave",
        "EVOLUTION_INSTANCIA": "nebo-wa", "EVOLUTION_INSTANCIA_RESPALDO": "nebo-wa (Respaldo)",
        "SUPABASE_SERVICE_ROLE_KEY": "llave", "SUPABASE_PROJECT_REF": "abcdefghijklmnopqrst",
        "JARVIS_BUCKET_IMAGENES": "Lucas_imagenes", "JARVIS_BUCKET_FICHAS": "Lucas_fichas_tecnicas",
        "JARVIS_FUENTE_CATALOGO": "656ef47a", "JARVIS_BUCKET_COTIZACIONES": "jarvis_cotizaciones",
        "PDFCO_API_KEY": "pdfco",
    }.items():
        monkeypatch.setenv(variable, valor)
    monkeypatch.setattr(archivos, "refrescar", lambda: pytest.fail("no debia listar"))
    monkeypatch.setattr(archivos, "refrescar_en_segundo_plano", lambda: None)
    archivos.usar_indices(
        {"imagen": {"306714": "306714.png"}, "ficha": {"306714": "306714.pdf"}},
        {"imagen": True, "ficha": True},
    )
    monkeypatch.setattr(cotizaciones, "buscar_emitida",
                        lambda n: {"pdf_ruta": f"{n}.pdf", "cliente": "PRUEBA"} if n == "JV-00002" else None)
    monkeypatch.setattr(cotizaciones, "firmar", lambda ruta, s: f"https://firmado/{ruta}?t={s}")

    enviados = []

    def enviar(cuerpo, instancia):
        enviados.append({**cuerpo, "_instancia": instancia})
        return f"id{len(enviados)}"

    monkeypatch.setattr(whatsapp, "_enviar_media", enviar)
    whatsapp._pendientes.clear()
    whatsapp._enviados.clear()
    return enviados


def _preparar(usuario="admin", **argumentos):
    return herramientas.ejecutar("preparar_envio_whatsapp", json.dumps(argumentos), usuario)


def _confirmar(usuario="admin"):
    return herramientas.ejecutar("confirmar_envio_whatsapp", "{}", usuario)


@pytest.mark.parametrize("texto, numero", [
    ("809-555-1234", "18095551234"),
    ("(829) 555 1234", "18295551234"),
    ("+1 849 555 1234", "18495551234"),
    ("+57 350 590 3076", "573505903076"),
])
def test_los_numeros_quedan_con_codigo_de_pais(texto, numero):
    assert whatsapp.normalizar_numero(texto) == numero


@pytest.mark.parametrize("texto", ["555-1234", "3505903076", "", "1234567890123456"])
def test_un_numero_incompleto_no_se_acepta(texto):
    with pytest.raises(whatsapp.ErrorEnvio):
        whatsapp.normalizar_numero(texto)


def test_preparar_no_manda_nada_y_confirmar_si(configurado):
    texto = _preparar(numero="809 555 1234", codigos="306714", nombres="Caja breaker",
                      cotizacion="JV-00002")

    assert "aun NO enviado" in texto and "+1 809-555-1234" in texto
    assert "imagen de Caja breaker" in texto and "cotizacion JV-00002" in texto
    assert configurado == []

    resultado = _confirmar()
    assert "Enviado por WhatsApp a +1 809-555-1234" in resultado
    assert [c["mediatype"] for c in configurado] == ["image", "document", "document"]
    imagen, ficha, cotizacion = configurado
    assert imagen["number"] == "18095551234"
    assert imagen["media"].endswith("/object/public/Lucas_imagenes/306714.png")
    assert imagen["mimetype"] == "image/png"
    assert imagen["caption"] == "JH Electroalambres · Caja breaker"
    assert ficha["fileName"] == "Ficha tecnica 306714.pdf"
    assert cotizacion["media"] == "https://firmado/JV-00002.pdf?t=600"
    assert cotizacion["caption"] == "JH Electroalambres · Cotización JV-00002"
    assert cotizacion["fileName"] == "PRUEBA - JV-00002.pdf"

    # Un segundo "si" no vuelve a mandar.
    assert "No hay un envio pendiente" in _confirmar()
    assert len(configurado) == 3


def test_manda_solo_lo_que_pidieron(configurado):
    _preparar(numero="8095551234", codigos="306714", tipo="ficha")
    _confirmar()
    assert [c["fileName"] for c in configurado] == ["Ficha tecnica 306714.pdf"]


def test_si_no_existe_el_archivo_no_hay_envio(configurado):
    texto = _preparar(numero="8095551234", codigos="999999", tipo="ficha")
    assert "No hay nada que enviar" in texto and "ficha tecnica de 999999" in texto
    assert "No hay un envio pendiente" in _confirmar()


def test_una_cotizacion_que_no_existe_no_se_prepara(configurado):
    assert "No existe una cotizacion JV-00009" in _preparar(numero="8095551234", cotizacion="9")
    assert "no es un numero de cotizacion" in _preparar(numero="8095551234", cotizacion="ABC")


def test_sin_confirmar_no_se_manda_y_cada_quien_confirma_lo_suyo(configurado):
    _preparar(usuario="jorge", numero="8095551234", codigos="306714")
    assert "No hay un envio pendiente" in _confirmar("admin")
    assert configurado == []


def test_un_envio_viejo_ya_no_se_puede_confirmar(configurado):
    _preparar(numero="8095551234", codigos="306714")
    whatsapp._pendientes["admin"].creado -= whatsapp.VIGENCIA_PENDIENTE + 1
    assert "No hay un envio pendiente" in _confirmar()


def test_el_tope_por_hora_frena_antes_de_mandar(configurado, monkeypatch):
    monkeypatch.setattr(whatsapp, "MAX_POR_HORA", 2)
    _preparar(numero="8095551234", codigos="306714", cotizacion="JV-00002")
    assert "tope de 2 envios por hora" in _confirmar()
    assert configurado == []


def test_si_falla_uno_se_dice_y_queda_anotado(configurado, monkeypatch, entorno_limpio):
    def enviar(cuerpo, instancia):
        if cuerpo["mediatype"] == "document":
            raise RuntimeError('Evolution respondio 400: {"response": {"message": [{"exists": false}]}}')
        return "id-ok"

    monkeypatch.setattr(whatsapp, "_enviar_media", enviar)
    _preparar(numero="8095551234", codigos="306714")
    resultado = _confirmar()

    assert "Enviado por WhatsApp" in resultado and "imagen de 306714" in resultado
    assert ("No se pudo enviar: ficha tecnica de 306714 (por el numero principal, ese numero "
            "no tiene WhatsApp; por el de respaldo, ese numero no tiene WhatsApp)") in resultado
    assert "{" not in resultado   # nada de JSON crudo para leer en voz alta
    registros = [json.loads(l) for l in (entorno_limpio / "envios_whatsapp.jsonl").read_text().splitlines()]
    assert [(r["tipo"], r["ok"]) for r in registros] == [("imagen", True), ("ficha", False)]
    assert registros[0]["numero"] == "18095551234" and registros[0]["id"] == "id-ok"
    assert registros[0]["instancia"] == "nebo-wa"
    assert len(registros[1]["errores"]) == 2


def test_sin_evolution_no_se_ofrece(entorno_limpio, monkeypatch):
    monkeypatch.delenv("EVOLUTION_API_KEY", raising=False)
    nombres = {e["name"] for e in herramientas.esquemas()}
    assert not {"preparar_envio_whatsapp", "confirmar_envio_whatsapp"} & nombres


def test_si_la_principal_falla_sale_por_el_respaldo_y_el_resto_va_directo(configurado, monkeypatch):
    intentos = []

    def enviar(cuerpo, instancia):
        intentos.append(instancia)
        if instancia == "nebo-wa":
            raise RuntimeError('Evolution respondio 500: {"error": "Internal Server Error", "message": "Connection Closed"}')
        return "id-respaldo"

    monkeypatch.setattr(whatsapp, "_enviar_media", enviar)
    _preparar(numero="8095551234", codigos="306714", cotizacion="JV-00002")
    resultado = _confirmar()

    # Tres archivos: el primero prueba la principal y cae al respaldo; los
    # siguientes ya van directo por el respaldo.
    assert intentos == ["nebo-wa", "nebo-wa (Respaldo)", "nebo-wa (Respaldo)", "nebo-wa (Respaldo)"]
    assert "Enviado por WhatsApp a +1 809-555-1234" in resultado
    assert "Salio por el numero de respaldo" in resultado
    assert "desconectado y hay que volver a vincularlo" in resultado
    assert "No se pudo enviar" not in resultado


def test_si_fallan_las_dos_lo_explica_y_se_puede_reintentar(configurado, monkeypatch):
    import httpx

    def enviar(cuerpo, instancia):
        if instancia == "nebo-wa":
            raise RuntimeError('Evolution respondio 500: {"message": "Connection Closed"}')
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(whatsapp, "_enviar_media", enviar)
    _preparar(numero="8095551234", cotizacion="JV-00002")
    resultado = _confirmar()

    assert ("por el numero principal, ese WhatsApp esta desconectado y hay que volver a "
            "vincularlo; por el de respaldo, WhatsApp no respondio a tiempo") in resultado
    assert "Dilo con calma" in resultado and "sigue preparado" in resultado

    # Vuelven a conectar y dicen "intentalo de nuevo": sin preparar otra vez.
    monkeypatch.setattr(whatsapp, "_enviar_media", lambda cuerpo, instancia: "id-ok")
    assert "Enviado por WhatsApp" in _confirmar()
    assert "No hay un envio pendiente" in _confirmar()


def test_sin_respaldo_configurado_solo_usa_la_principal(configurado, monkeypatch):
    monkeypatch.delenv("EVOLUTION_INSTANCIA_RESPALDO")
    intentos = []

    def enviar(cuerpo, instancia):
        intentos.append(instancia)
        raise RuntimeError("Evolution respondio 404: instance not found")

    monkeypatch.setattr(whatsapp, "_enviar_media", enviar)
    _preparar(numero="8095551234", codigos="306714", tipo="imagen")
    resultado = _confirmar()
    assert intentos == ["nebo-wa"]
    assert "esa instancia no existe" in resultado


def test_el_nombre_de_la_instancia_va_codificado_en_la_url(configurado, monkeypatch):
    import httpx

    llamadas = []

    class Respuesta:
        status_code = 201

        def json(self):
            return {"key": {"id": "ABC"}, "messages": {"records": [{"MessageUpdate": [{"status": "SERVER_ACK"}]}]}}

        def raise_for_status(self):
            return self

    monkeypatch.setattr(whatsapp, "CADA", 0)
    monkeypatch.setattr(httpx, "post", lambda url, **kw: llamadas.append(url) or Respuesta())
    assert ENVIAR_REAL({"number": "1"}, "nebo-wa (Respaldo)") == "ABC"
    assert llamadas == ["https://evo.test/message/sendMedia/nebo-wa%20%28Respaldo%29",
                        "https://evo.test/chat/findMessages/nebo-wa%20%28Respaldo%29"]


def test_si_whatsapp_lo_rechaza_despues_cuenta_como_fallo_y_va_al_respaldo(configurado, monkeypatch):
    import httpx

    monkeypatch.setattr(whatsapp, "CADA", 0)
    enviados = []

    class Respuesta:
        status_code = 201

        def __init__(self, datos):
            self.datos = datos

        def json(self):
            return self.datos

        def raise_for_status(self):
            return self

    def post(url, **kw):
        instancia = "respaldo" if "Respaldo" in url else "principal"
        if "/message/sendMedia/" in url:
            enviados.append(instancia)
            return Respuesta({"key": {"id": f"id-{instancia}"}, "status": "PENDING"})
        # findMessages: la principal termina en ERROR, el respaldo se entrega.
        estado = "ERROR" if instancia == "principal" else "DELIVERY_ACK"
        return Respuesta({"messages": {"records": [{"MessageUpdate": [{"status": estado}]}]}})

    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(whatsapp, "_enviar_media", ENVIAR_REAL)
    _preparar(numero="8095551234", codigos="306714", tipo="imagen")
    resultado = _confirmar()

    assert enviados == ["principal", "respaldo"]
    assert "Enviado por WhatsApp" in resultado
    assert "Salio por el numero de respaldo" in resultado
    assert "WhatsApp rechazo el envio desde ese numero" in resultado


def test_si_sigue_pendiente_al_tope_se_da_por_enviado(configurado, monkeypatch):
    import httpx

    monkeypatch.setattr(whatsapp, "CADA", 0)
    monkeypatch.setattr(whatsapp, "ESPERA_CONFIRMACION", 0.05)

    class Respuesta:
        status_code = 201

        def __init__(self, datos):
            self.datos = datos

        def json(self):
            return self.datos

        def raise_for_status(self):
            return self

    def post(url, **kw):
        if "/message/sendMedia/" in url:
            return Respuesta({"key": {"id": "id-1"}, "status": "PENDING"})
        return Respuesta({"messages": {"records": [{"MessageUpdate": []}]}})

    monkeypatch.setattr(httpx, "post", post)
    assert ENVIAR_REAL({"number": "1"}, "nebo-wa") == "id-1"
