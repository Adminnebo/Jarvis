import json

import pytest

from backend import archivos, cotizaciones, herramientas, whatsapp


@pytest.fixture
def configurado(entorno_limpio, monkeypatch):
    for variable, valor in {
        "EVOLUTION_URL": "https://evo.test/", "EVOLUTION_API_KEY": "llave",
        "EVOLUTION_INSTANCIA": "camila-test",
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

    def enviar(cuerpo):
        enviados.append(cuerpo)
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
    def enviar(cuerpo):
        if cuerpo["mediatype"] == "document":
            raise RuntimeError("Evolution respondio 400: numero no existe")
        return "id-ok"

    monkeypatch.setattr(whatsapp, "_enviar_media", enviar)
    _preparar(numero="8095551234", codigos="306714")
    resultado = _confirmar()

    assert "Enviado por WhatsApp" in resultado and "imagen de 306714" in resultado
    assert "No se pudo enviar: ficha tecnica de 306714 (Evolution respondio 400" in resultado
    registros = [json.loads(l) for l in (entorno_limpio / "envios_whatsapp.jsonl").read_text().splitlines()]
    assert [(r["tipo"], r["ok"]) for r in registros] == [("imagen", True), ("ficha", False)]
    assert registros[0]["numero"] == "18095551234" and registros[0]["id"] == "id-ok"


def test_sin_evolution_no_se_ofrece(entorno_limpio, monkeypatch):
    monkeypatch.delenv("EVOLUTION_API_KEY", raising=False)
    nombres = {e["name"] for e in herramientas.esquemas()}
    assert not {"preparar_envio_whatsapp", "confirmar_envio_whatsapp"} & nombres
