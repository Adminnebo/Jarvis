"""Lo que gastan los puentes (lentes y reloj) y lo que se cobra aparte:
transcripcion, TTS y el PDF de las cotizaciones."""

import json

import pytest
from fastapi.testclient import TestClient

# Arriba del todo, como en test_permisos: backend.main carga el .env al
# importarse y no debe pisar las contrasenas de prueba.
from backend.main import app
from backend import acceso, consumo, creditos, cuentas

UN_MILLON = {"input_tokens": 1_000_000}   # $2 en gpt-5.6-terra


@pytest.fixture
def puentes_a_jh(monkeypatch):
    monkeypatch.setenv("JARVIS_ORGANIZACION_PANELES", "JH Electroalambres")
    cuentas.asegurar_organizacion_de_paneles()
    monkeypatch.setenv("JARVIS_RELOJ_ORGANIZACION", cuentas.ID_PANELES)
    monkeypatch.setenv("JARVIS_LENTES_ORGANIZACION", cuentas.ID_PANELES)
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setenv("JARVIS_PASSWORD_LENTES", "la-de-los-lentes")
    monkeypatch.setenv("JARVIS_PASSWORD_RELOJ", "la-del-reloj")


def lentes():
    return acceso.quien_entra("la-de-los-lentes")


# --------------------------------------------------------------------------
# Los lentes, con su propia clave
# --------------------------------------------------------------------------

def test_los_lentes_con_su_clave_se_cobran_a_su_organizacion(puentes_a_jh):
    puente = lentes()
    assert (puente.id, puente.nombre) == ("lentes", "Lentes")

    consumo.registrar("texto", "gpt-5.6-terra", UN_MILLON, usuario=puente)
    consumo.registrar("voz", "gpt-realtime-2.1", {"input_tokens": 1000}, usuario=puente)
    consumo.registrar_sesion("gpt-realtime-2.1", 60.0, usuario=puente)

    for registro in consumo.todos():
        assert registro["usuario_id"] == "lentes"
        assert registro["organizacion_id"] == cuentas.ID_PANELES
        assert registro["dispositivo"] == "lentes"


def test_la_clave_de_los_lentes_gana_a_la_pista_del_reloj(puentes_a_jh):
    # Los lentes tambien piden respuestas cortas, y eso los hacia pasar por
    # reloj. Con su clave, son lentes.
    consumo.registrar("texto", "gpt-5.6-terra", UN_MILLON,
                      usuario=lentes(), dispositivo=consumo.RELOJ_SIN_VINCULAR)

    [registro] = consumo.todos()
    assert registro["dispositivo"] == "lentes"
    assert registro["usuario_id"] == "lentes"


def test_sin_organizacion_los_lentes_quedan_como_lentes_sin_cobro(monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD_LENTES", "la-de-los-lentes")
    consumo.registrar("texto", "gpt-5.6-terra", UN_MILLON, usuario=lentes())

    [registro] = consumo.todos()
    assert registro["dispositivo"] == "lentes"
    assert registro["organizacion_id"] is None


def test_los_lentes_tienen_nombre_en_el_tablero(monkeypatch):
    assert cuentas.nombres_de_usuarios(["lentes"]) == {"lentes": "Lentes"}
    monkeypatch.setenv("JARVIS_LENTES_NOMBRE", "Lentes de JH")
    assert cuentas.nombres_de_usuarios(["lentes"]) == {"lentes": "Lentes de JH"}


def test_avisa_si_un_puente_tiene_la_clave_del_admin(monkeypatch, capsys):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-misma")
    monkeypatch.setenv("JARVIS_PASSWORD_RELOJ", "la-misma")
    monkeypatch.setenv("JARVIS_PASSWORD_LENTES", "otra")

    acceso.avisar_de_contrasenas_repetidas()

    salida = capsys.readouterr().out
    assert "JARVIS_PASSWORD_RELOJ es igual a JARVIS_PASSWORD" in salida
    assert "no se cobra" in salida
    assert "JARVIS_PASSWORD_LENTES es igual" not in salida


# --------------------------------------------------------------------------
# Transcripcion, TTS y cotizacion
# --------------------------------------------------------------------------

def test_la_transcripcion_se_cobra_por_segundos():
    # Asi llega el usage de gpt-live-transcribe (probado contra OpenAI).
    registro = consumo.registrar(
        "transcripcion", consumo.MODELO_TRANSCRIPCION, {"type": "duration", "seconds": 5}
    )
    assert registro["segundos"] == 5
    assert registro["tokens"] == 0
    assert registro["costo"] == round(5 / 60 * 0.017, 6)


def test_el_tts_cobra_su_salida_como_audio():
    # Asi llega el usage del TTS con stream_format "sse" (probado): 4.6 s de voz.
    uso = {"input_tokens": 13, "output_tokens": 118, "total_tokens": 131}
    registro = consumo.registrar("tts", "gpt-4o-mini-tts", uso)

    assert registro["salida_audio"] == 118
    assert registro["salida_texto"] == 0
    assert registro["entrada_texto"] == 13
    assert registro["costo"] == round((13 * 0.6 + 118 * 12.0) / 1_000_000, 6)


def test_la_cotizacion_se_anota_a_quien_la_pidio(puentes_a_jh):
    with consumo.atribuir(lentes(), "navegador"):
        consumo.registrar_cotizacion(9)

    [registro] = consumo.todos()
    assert registro["modo"] == "cotizacion"
    assert registro["modelo"] == consumo.MODELO_PDF
    assert registro["tokens"] == 9          # creditos de PDF.co
    assert registro["costo"] == round(9 * 0.0006, 6)
    assert registro["dispositivo"] == "lentes"
    assert registro["organizacion_id"] == cuentas.ID_PANELES


def test_una_cotizacion_sin_contexto_igual_se_anota():
    consumo.registrar_cotizacion(9)
    [registro] = consumo.todos()
    assert registro["usuario_id"] is None
    assert registro["costo"] > 0


def test_la_herramienta_sabe_quien_la_pidio(puentes_a_jh, monkeypatch):
    from backend import herramientas

    def emitir_falso(usuario):
        consumo.registrar_cotizacion(12)
        return "listo"

    monkeypatch.setitem(herramientas.REGISTRO, "emitir_falso", {
        "funcion": emitir_falso, "necesita_usuario": True,
    })
    herramientas.ejecutar_completo("emitir_falso", "{}", "lentes", lentes(), "lentes")

    [registro] = consumo.todos()
    assert registro["dispositivo"] == "lentes"
    assert registro["organizacion_id"] == cuentas.ID_PANELES


# --------------------------------------------------------------------------
# Precios
# --------------------------------------------------------------------------

def test_un_precios_json_viejo_no_deja_sin_precio_lo_nuevo():
    # Un volumen con el archivo de antes: sin transcripcion, TTS ni imagen.
    viejo = {"gpt-realtime-2.1": {"texto_entrada": 4.0, "texto_cache": 0.4,
                                  "texto_salida": 24.0, "audio_entrada": 32.0,
                                  "audio_cache": 0.4, "audio_salida": 64.0}}
    consumo.archivo_precios().write_text(json.dumps(viejo), encoding="utf-8")

    tabla = consumo.precios()
    assert tabla[consumo.MODELO_TRANSCRIPCION]["minuto"] == 0.017
    assert tabla["gpt-4o-mini-tts"]["audio_salida"] == 12.0
    assert tabla["gpt-realtime-2.1"]["imagen_entrada"] == 5.0


def test_lo_escrito_a_mano_gana():
    consumo.archivo_precios().write_text(
        json.dumps({consumo.MODELO_PDF: {"credito": 0.001}}), encoding="utf-8"
    )
    assert consumo.precio_de(consumo.MODELO_PDF)["credito"] == 0.001


def test_un_modelo_sin_precio_avisa_una_vez(capsys):
    consumo.registrar("texto", "modelo-que-no-existe", UN_MILLON)
    consumo.registrar("texto", "modelo-que-no-existe", UN_MILLON)
    assert capsys.readouterr().out.count("no hay precio para 'modelo-que-no-existe'") == 1


# --------------------------------------------------------------------------
# Aperturas: cuentan sesiones, no cuestan ni se cobran
# --------------------------------------------------------------------------

def test_una_apertura_no_es_consumo(puentes_a_jh, monkeypatch):
    monkeypatch.setenv("JARVIS_CREDITOS_URL", "https://agentia.example")
    monkeypatch.setenv("JARVIS_CREDITOS_CALLER_ID", "1")
    monkeypatch.setenv("JARVIS_CREDITOS_API_KEY", "x")
    monkeypatch.setenv("JARVIS_CREDITOS_CLIENTE_PANELES", "16")
    creditos._acumular()                  # la primera vez solo marca el inicio

    consumo.registrar_apertura("gpt-realtime-2.1", usuario=lentes())
    creditos._acumular()

    assert cuentas.consumido(cuentas.ID_PANELES)["consultas"] == 0
    assert consumo.totalizar(consumo.todos())["consultas"] == 0
    from backend import basedatos
    with basedatos.conexion() as con:
        assert con.execute("SELECT COUNT(*) FROM creditos_pendientes").fetchone()[0] == 0


# --------------------------------------------------------------------------
# Por origen: de donde sale cada total
# --------------------------------------------------------------------------

def test_el_total_de_cada_puente_es_la_suma_de_sus_conceptos(puentes_a_jh, monkeypatch):
    monkeypatch.setenv("JARVIS_MARGEN", "30")
    monkeypatch.setenv("JARVIS_CREDITOS_CLIENTE_PANELES", "16")
    puente = lentes()

    consumo.registrar("texto", "gpt-5.6-terra", UN_MILLON, usuario=puente)            # $2
    consumo.registrar("transcripcion", consumo.MODELO_TRANSCRIPCION,
                      {"type": "duration", "seconds": 120}, usuario=puente)          # 2 min
    consumo.registrar("tts", "gpt-4o-mini-tts",
                      {"input_tokens": 0, "output_tokens": 1_000_000}, usuario=puente)  # $12
    consumo.registrar_apertura("gpt-realtime-2.1", usuario=puente)
    consumo.registrar_apertura("gpt-realtime-2.1", usuario=puente)
    consumo.registrar_sesion("gpt-realtime-2.1", 90.0, usuario=puente)
    # Lo del admin no se cobra: cobrado en cero.
    consumo.registrar("texto", "gpt-5.6-terra", UN_MILLON,
                      usuario=acceso.quien_entra("la-del-admin"))

    origenes = {fila["origen"]: fila for fila in consumo.agrupar_por_origen(consumo.todos())}

    fila = origenes["lentes"]
    assert fila["nombre"] == "Puente de los lentes"
    assert fila["costo"] == round(sum(c["costo"] for c in fila["conceptos"]), 6)
    assert fila["costo"] == round(2 + 2 * 0.017 + 12, 6)
    assert fila["cobrado"] == round(fila["costo"] * 1.3, 6)
    conceptos = {c["modo"]: c for c in fila["conceptos"]}
    assert conceptos["transcripcion"]["cantidad"] == 2.0     # minutos
    assert conceptos["texto"]["cantidad"] == 1
    assert (fila["sesiones_abiertas"], fila["sesiones_informadas"]) == (2, 1)
    assert fila["sesiones_sin_informar"] == 1
    assert fila["minutos_voz"] == 1.5

    assert origenes["navegador"]["costo"] == 2.0
    assert origenes["navegador"]["cobrado"] == 0.0


def test_las_cotizaciones_van_aparte():
    consumo.registrar_cotizacion(9)
    [fila] = consumo.agrupar_por_origen(consumo.todos())
    assert fila["origen"] == "cotizaciones"
    assert fila["conceptos"][0]["creditos"] == 9


def test_el_tablero_no_se_corta_en_los_ultimos_5000(monkeypatch):
    monkeypatch.setattr(consumo, "MAXIMO_REGISTROS", 3)
    for _ in range(5):
        consumo.registrar("texto", "gpt-5.6-terra", UN_MILLON)

    assert consumo.consultar(periodo="30d")["totales"]["consultas"] == 5


# --------------------------------------------------------------------------
# /api/consumo/voz
# --------------------------------------------------------------------------

@pytest.fixture
def cliente_lentes(puentes_a_jh, monkeypatch):
    monkeypatch.setenv("JARVIS_CLAVE_SECRETA", "clave-de-pruebas-larga")
    cliente = TestClient(app)
    respuesta = cliente.post("/acceso", data={"clave": "la-de-los-lentes"},
                             follow_redirects=False)
    assert respuesta.status_code == 303
    return cliente


def test_el_puente_informa_transcripcion_tts_y_apertura(cliente_lentes):
    for cuerpo in (
        {"modo": "transcripcion", "uso": {"type": "duration", "seconds": 5}},
        {"modo": "tts", "modelo": "gpt-4o-mini-tts",
         "uso": {"input_tokens": 13, "output_tokens": 118}},
        {"modo": "apertura"},
        {"modelo": "gpt-realtime-2.1", "uso": {"input_tokens": 100}},   # como siempre: voz
    ):
        assert cliente_lentes.post("/api/consumo/voz", json=cuerpo).status_code == 200

    modos = [(r["modo"], r["modelo"], r["dispositivo"]) for r in consumo.todos()]
    assert modos == [
        ("transcripcion", consumo.MODELO_TRANSCRIPCION, "lentes"),
        ("tts", "gpt-4o-mini-tts", "lentes"),
        ("apertura", "gpt-realtime-2.1", "lentes"),
        ("voz", "gpt-realtime-2.1", "lentes"),
    ]


def test_un_modo_desconocido_se_rechaza(cliente_lentes):
    respuesta = cliente_lentes.post("/api/consumo/voz", json={"modo": "gratis", "uso": {}})
    assert respuesta.status_code == 400
    assert consumo.todos() == []


def test_el_tts_sin_modelo_se_rechaza(cliente_lentes):
    respuesta = cliente_lentes.post("/api/consumo/voz", json={"modo": "tts", "uso": {}})
    assert respuesta.status_code == 400


# --------------------------------------------------------------------------
# Puente con la clave del admin que se identifica con X-Jarvis-Puente
# --------------------------------------------------------------------------

def test_la_pista_de_los_lentes_anota_a_su_organizacion(puentes_a_jh):
    admin = acceso.quien_entra("la-del-admin")
    consumo.registrar("voz", "gpt-realtime-2.1", {"input_tokens": 1000},
                      usuario=admin, dispositivo=consumo.LENTES_SIN_VINCULAR)

    [registro] = consumo.todos()
    assert registro["usuario_id"] == "lentes"
    assert registro["organizacion_id"] == cuentas.ID_PANELES
    assert registro["dispositivo"] == "lentes"


def test_sin_organizacion_la_pista_solo_etiqueta(monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    consumo.registrar("voz", "gpt-realtime-2.1", {"input_tokens": 1000},
                      usuario=acceso.quien_entra("la-del-admin"),
                      dispositivo=consumo.LENTES_SIN_VINCULAR)

    [registro] = consumo.todos()
    assert registro["usuario_id"] == "admin"      # sigue siendo del admin, sin cobro
    assert registro["organizacion_id"] is None
    assert registro["dispositivo"] == "lentes"    # pero se ve que fue de los lentes


@pytest.fixture
def cliente_admin(puentes_a_jh, monkeypatch):
    monkeypatch.setenv("JARVIS_CLAVE_SECRETA", "clave-de-pruebas-larga")
    cliente = TestClient(app)
    respuesta = cliente.post("/acceso", data={"clave": "la-del-admin"}, follow_redirects=False)
    assert respuesta.status_code == 303
    return cliente


def test_el_encabezado_cambia_a_quien_se_anota_no_quien_entra(cliente_admin):
    cuerpo = {"modo": "transcripcion", "uso": {"type": "duration", "seconds": 5}}
    cliente_admin.post("/api/consumo/voz", json=cuerpo, headers={"X-Jarvis-Puente": "lentes"})
    cliente_admin.post("/api/consumo/voz", json=cuerpo)                       # la web del admin
    cliente_admin.post("/api/consumo/voz", json=cuerpo, headers={"X-Jarvis-Puente": "otro"})

    registros = [(r["dispositivo"], r["usuario_id"], r["organizacion_id"]) for r in consumo.todos()]
    assert registros == [
        ("lentes", "lentes", cuentas.ID_PANELES),
        ("navegador", "admin", None),
        ("navegador", "admin", None),       # una pista desconocida no hace nada
    ]
    # Entra como admin: su estado y su conversacion son las del admin.
    estado = cliente_admin.get("/api/estado", headers={"X-Jarvis-Puente": "lentes"}).json()
    assert estado["usuario"] == "Admin"


def test_en_el_chat_los_lentes_no_pasan_por_reloj(cliente_admin, monkeypatch):
    # Los lentes piden respuestas cortas, como el reloj; con el encabezado
    # se sabe que son los lentes.
    from backend import cerebro

    vistos = []

    def responder_falso(mensajes, usuario, extra="", dispositivo="navegador"):
        vistos.append(dispositivo)
        return iter(())

    monkeypatch.setattr(cerebro, "responder", responder_falso)
    cliente_admin.post("/api/chat", json={"mensaje": "hola", "breve": True},
                       headers={"X-Jarvis-Puente": "lentes"})
    cliente_admin.post("/api/chat", json={"mensaje": "hola", "breve": True})

    assert vistos == [consumo.LENTES_SIN_VINCULAR, consumo.RELOJ_SIN_VINCULAR]


# --------------------------------------------------------------------------
# Lo que se gasta probando
# --------------------------------------------------------------------------

def test_las_pruebas_salen_en_su_fila_y_no_se_cobran(cliente_admin):
    cuerpo = {"modelo": "gpt-realtime-2.1", "uso": {"input_tokens": 1000}}
    cliente_admin.post("/api/consumo/voz", json=cuerpo, headers={"X-Jarvis-Puente": "pruebas"})

    [registro] = consumo.todos()
    assert (registro["dispositivo"], registro["usuario_id"], registro["organizacion_id"]) == \
        ("pruebas", "admin", None)

    [fila] = consumo.agrupar_por_origen(consumo.todos())
    assert fila["nombre"] == "Pruebas (banco de pruebas)"
    assert fila["costo"] > 0 and fila["cobrado"] == 0


def test_un_cliente_no_se_libra_de_pagar_diciendo_que_es_una_prueba(puentes_a_jh):
    cliente = acceso.Usuario("u1", "Cliente", "usuario", organizacion_id=cuentas.ID_PANELES)
    assert not consumo.es_de_pruebas("pruebas", cliente)
    assert consumo.es_de_pruebas("pruebas", acceso.por_defecto())
    assert not consumo.es_de_pruebas("pruebas", None)
