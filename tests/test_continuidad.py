"""Una sesion de voz nueva sabe donde quedo la conversacion.

Con los lentes el enlace se cae y se reabre a mitad de una conversacion, y cada
sesion arrancaba en blanco: a los cuarenta segundos de reconectar, "enviame la
cotizacion del casco" terminaba en las facturas de JH porque del borrador que
Jarvis acababa de armar no quedaba nada.
"""

import time

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend import acceso, cerebro, continuidad, cotizaciones, whatsapp

AHORA = 1_000_000.0


@pytest.fixture(autouse=True)
def en_blanco():
    continuidad.olvidar()
    cotizaciones._borradores.clear()
    whatsapp._pendientes.clear()
    yield
    continuidad.olvidar()
    cotizaciones._borradores.clear()
    whatsapp._pendientes.clear()


def admin():
    return acceso.por_defecto()


def _borrador(creado):
    return cotizaciones.Borrador(
        {"nombre": "CLIENTE CONTADO"},
        [{"cantidad": 5.0, "unidad": "UND", "descripcion": "TRUPER CASCO PROTECTOR BLANCO"}],
        {"total": 2611.75}, creado=creado,
    )


def test_sin_nada_que_retomar_no_se_agrega_nada():
    assert continuidad.para_prompt(admin(), AHORA) == ""
    assert cerebro.configuracion_de_sesion(admin())["instructions"] == cerebro.instrucciones(admin())


def test_el_borrador_sin_emitir_llega_a_la_sesion_nueva():
    cotizaciones._borradores[admin().id] = _borrador(time.time() - 120)

    texto = cerebro.configuracion_de_sesion(admin())["instructions"]
    assert "Donde quedaron" in texto
    assert "borrador de cotizacion SIN emitir" in texto
    assert "5 UND de TRUPER CASCO PROTECTOR BLANCO" in texto
    assert "2,611.75" in texto
    assert "hace 2 minutos" in texto
    # Va despues de las reglas, que no cambian.
    assert texto.startswith(cerebro.instrucciones(admin()))


def test_si_el_contexto_falla_la_voz_abre_igual(monkeypatch, capsys):
    def roto(usuario):
        raise RuntimeError("algo se rompio")

    monkeypatch.setattr(continuidad, "para_prompt", roto)
    assert cerebro.configuracion_de_sesion(admin())["instructions"] == cerebro.instrucciones(admin())
    assert "abre sin contexto" in capsys.readouterr().out


def test_el_borrador_de_otro_no_se_cuela():
    cotizaciones._borradores["otra-persona"] = _borrador(time.time())
    assert continuidad.para_prompt(admin()) == ""


def test_la_ultima_emitida_y_el_envio_pendiente():
    continuidad.anotar_emision(admin().id, "JV-00012", "FERRETERIA ELIAM", 5443.0)
    whatsapp._pendientes[admin().id] = whatsapp.Pendiente("18095551234", [{"tipo": "cotizacion"}])

    texto = continuidad.para_prompt(admin())
    assert "JV-00012" in texto and "FERRETERIA ELIAM" in texto and "5,443.00" in texto
    assert "WhatsApp preparado y SIN confirmar" in texto
    assert "+1 809-555-1234" in texto


def test_una_emitida_de_hace_horas_ya_no_es_la_cotizacion():
    continuidad.anotar_emision(admin().id, "JV-00012", "X", 10.0)
    assert continuidad.para_prompt(admin(), time.time() + 3 * 60 * 60) == ""


def test_los_ultimos_turnos_con_quien_y_desde_donde():
    for quien, texto in (
        ("tu", "Quiero el precio de un casco truper amarillo."),
        ("jarvis", "Cuesta 566.15 y hay 38 unidades."),
    ):
        continuidad.anotar_turno(admin().id, quien, texto, "lentes", AHORA - 90)

    texto = continuidad.para_prompt(admin(), AHORA)
    assert "Lo ultimo que se hablo (hace un minuto, por los lentes):" in texto
    assert f"  {admin().nombre}: Quiero el precio de un casco truper amarillo." in texto
    assert "  Jarvis: Cuesta 566.15 y hay 38 unidades." in texto


def test_los_fragmentos_y_el_ruido_no_son_contexto():
    for basura in ("نعم", "Ok", "Aja.", "Para"):
        continuidad.anotar_turno(admin().id, "tu", basura, "lentes", AHORA)
    assert continuidad.para_prompt(admin(), AHORA) == ""


def test_lo_de_hace_mas_de_media_hora_no_cuenta():
    continuidad.anotar_turno(admin().id, "tu", "Cotizame cinco cascos blancos.", "web", AHORA - 31 * 60)
    assert continuidad.para_prompt(admin(), AHORA) == ""


def test_solo_los_ultimos_turnos_y_recortados():
    for i in range(20):
        continuidad.anotar_turno(admin().id, "jarvis", f"respuesta {i} " + "x" * 400, "web", AHORA)

    lineas = [l for l in continuidad.para_prompt(admin(), AHORA).splitlines() if l.startswith("  Jarvis:")]
    assert len(lineas) == continuidad.MAX_TURNOS
    assert "respuesta 19" in lineas[-1]
    assert all(len(l) < continuidad.MAX_TEXTO + 20 for l in lineas)


def test_cada_persona_ve_solo_lo_suyo():
    continuidad.anotar_turno("otra-persona", "tu", "Esto lo dijo otra persona.", "web", AHORA)
    assert continuidad.para_prompt(admin(), AHORA) == ""


# --------------------------------------------------------------------------
# Por donde entran los turnos
# --------------------------------------------------------------------------

@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setenv("JARVIS_CLAVE_SECRETA", "clave-de-pruebas-larga")
    cliente = TestClient(app)
    assert cliente.post("/acceso", data={"clave": "la-del-admin"},
                        follow_redirects=False).status_code == 303
    return cliente


def test_lo_que_manda_el_puente_de_los_lentes_queda_para_la_sesion_siguiente(cliente):
    cliente.post("/api/voz/registro", json={
        "sesion": "abc", "dispositivo": "lentes",
        "eventos": [
            {"tipo": "dicho", "quien": "tu", "texto": "Cotizame cinco cascos truper blancos."},
            {"tipo": "herramienta", "nombre": "preparar_cotizacion", "resultado": "Borrador listo"},
            {"tipo": "dicho", "quien": "jarvis", "texto": "Borrador listo de contado."},
        ],
    })

    texto = cliente.get("/api/voz/sesion").json()["instructions"]
    assert "Cotizame cinco cascos truper blancos." in texto
    assert "Jarvis: Borrador listo de contado." in texto
    assert "por los lentes" in texto
    # El resultado de la herramienta no es algo que se dijo.
    assert "preparar_cotizacion" not in texto.split("Donde quedaron")[1]


def test_la_voz_de_la_web_tambien_y_reiniciar_lo_borra(cliente):
    cliente.post("/api/conversacion/agregar",
                 json={"role": "user", "content": "Busca el breaker de cuarenta amperios."})
    assert "Busca el breaker de cuarenta amperios." in cliente.get("/api/voz/sesion").json()["instructions"]

    cliente.post("/api/conversacion/reiniciar")
    assert "Donde quedaron" not in cliente.get("/api/voz/sesion").json()["instructions"]


def test_la_voz_de_la_web_y_sus_consultas_quedan_en_el_log(cliente, capsys):
    cliente.post("/api/conversacion/agregar",
                 json={"role": "user", "content": "Precio del casco\ntruper amarillo."})
    cliente.post("/api/herramienta", json={"nombre": "hora_actual", "argumentos": "{}"})

    salida = capsys.readouterr().out
    assert "[dialogo] (web) tu: Precio del casco truper amarillo." in salida
    assert "[dialogo] (navegador) herramienta hora_actual" in salida


def test_el_log_recorta_lo_largo(capsys):
    from backend import voz_registro

    voz_registro.al_log("web", "jarvis", "x" * 1000)
    linea = capsys.readouterr().out
    assert len(linea) < 480 and "(1000 caracteres)" in linea


def test_la_traza_de_la_voz_queda_en_el_log(cliente, capsys):
    respuesta = cliente.post("/api/voz/traza", json={"pasos": [
        {"t": 3.21, "e": "habla empieza"},
        {"t": 5.0, "e": "respuesta fin", "d": "cancelled: turn_detected"},
    ]})

    assert respuesta.json() == {"ok": True}
    assert "[dialogo] (navegador) traza: +3.2s habla empieza | +5.0s respuesta fin (cancelled: turn_detected)" \
        in capsys.readouterr().out


def test_una_traza_vacia_no_ensucia_el_log(cliente, capsys):
    cliente.post("/api/voz/traza", json={"pasos": []})
    assert "traza" not in capsys.readouterr().out
