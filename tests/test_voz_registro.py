"""El registro de los turnos de voz y el detector de precios dichos."""

import json

import pytest
from fastapi.testclient import TestClient

# Arriba del todo por la misma razon que en test_permisos: backend.main llama
# a load_dotenv(override=True) al importarse.
from backend.main import app

from backend import rutas, voz_registro

CATALOGO = json.dumps([{"producto": "Casco Truper blanco", "precio": 1614.55, "existencia": 12}])


@pytest.fixture(autouse=True)
def sin_memoria_vieja():
    """El detector recuerda sesiones entre llamadas; las pruebas no deben."""
    voz_registro._VISTOS.clear()
    voz_registro._ultima_rotacion = ""
    yield
    voz_registro._VISTOS.clear()
    voz_registro._ultima_rotacion = ""


def _herramienta(resultado=CATALOGO, argumentos='{"texto": "casco truper blanco"}'):
    return {
        "ts": "2026-09-29T20:11:03.000Z", "tipo": "herramienta",
        "nombre": "buscar_en_fuente", "argumentos": argumentos,
        "resultado": resultado, "ms": 1886,
    }


def _dicho(quien, texto, ts="2026-09-29T20:11:05.000Z"):
    return {"ts": ts, "tipo": "dicho", "quien": quien, "texto": texto}


# ------------------------------------------------------------ guardar y leer


def test_un_lote_se_guarda_y_se_relee():
    voz_registro.guardar("abc123", "lentes", [
        _dicho("tu", "dame el precio del casco truper blanco"),
        _herramienta(),
        _dicho("jarvis", "Cuesta 1,614.55 pesos por unidad."),
    ])

    eventos = voz_registro.leer()
    assert len(eventos) == 3
    assert {e["sesion"] for e in eventos} == {"abc123"}
    assert {e["dispositivo"] for e in eventos} == {"lentes"}
    assert eventos[1]["nombre"] == "buscar_en_fuente"
    assert eventos[1]["ms"] == 1886


def test_dos_lotes_de_la_misma_sesion_se_suman_en_el_dia():
    voz_registro.guardar("abc123", "lentes", [_dicho("tu", "hola")])
    voz_registro.guardar("abc123", "lentes", [_dicho("jarvis", "Dime.")])
    assert len(voz_registro.leer()) == 2


def test_un_dia_sin_nada_devuelve_vacio():
    assert voz_registro.leer("2020-01-01") == []


def test_un_dia_mal_formado_no_lee_otro_archivo():
    # Sin esto, ?dia=../../etc/passwd seria una ruta valida.
    assert voz_registro.leer("../consumo") == []
    assert not voz_registro.dia_valido("2026-9-1")


def test_una_linea_rota_no_se_lleva_el_resto_del_dia(entorno_limpio):
    voz_registro.guardar("abc123", "lentes", [_dicho("tu", "hola")])
    ruta = voz_registro.archivo_del_dia(voz_registro.hoy())
    with open(ruta, "a", encoding="utf-8") as archivo:
        archivo.write("{esto no es json\n")
    assert len(voz_registro.leer()) == 1


# ------------------------------------------------------------------ rotacion


def test_la_rotacion_borra_lo_viejo_y_deja_lo_reciente(entorno_limpio):
    for dia in ("2026-09-01", "2026-09-14", "2026-09-15", "2026-09-29"):
        voz_registro.archivo_del_dia(dia).write_text("{}\n", encoding="utf-8")

    borrados = voz_registro.rotar("2026-09-29")

    # El limite es 2026-09-15: ese dia y los posteriores se quedan.
    assert sorted(borrados) == ["2026-09-01", "2026-09-14"]
    quedan = sorted(p.name for p in rutas.datos().glob("voz-*.jsonl"))
    assert quedan == ["voz-2026-09-15.jsonl", "voz-2026-09-29.jsonl"]


def test_la_rotacion_no_recorre_la_carpeta_dos_veces_el_mismo_dia():
    assert voz_registro.rotar("2026-09-29") == []
    voz_registro.archivo_del_dia("2026-01-01").write_text("{}\n", encoding="utf-8")
    # Ya roto hoy: no vuelve a mirar hasta manana.
    assert voz_registro.rotar("2026-09-29") == []
    assert voz_registro.archivo_del_dia("2026-01-01").exists()


def test_la_rotacion_ignora_archivos_que_no_son_del_registro(entorno_limpio):
    rutas.archivo("voz-vieja.jsonl").write_text("{}\n", encoding="utf-8")
    voz_registro.rotar("2026-09-29")
    assert rutas.archivo("voz-vieja.jsonl").exists()


# ------------------------------------------------------------------ detector


def test_un_precio_que_si_estaba_en_el_resultado_no_se_marca():
    sospechas = voz_registro.guardar("s1", "lentes", [
        _dicho("tu", "precio del casco truper blanco"),
        _herramienta(),
        _dicho("jarvis", "Cuesta 1,614.55 pesos por unidad."),
    ])
    assert sospechas == []


def test_un_precio_inventado_se_marca():
    # El caso real del autotest de Camila: el catalogo decia 1614.55.
    sospechas = voz_registro.guardar("s2", "lentes", [
        _dicho("tu", "precio del casco truper blanco"),
        _herramienta(),
        _dicho("jarvis", "Cuesta 549.55 pesos por unidad."),
    ])
    assert len(sospechas) == 1
    assert sospechas[0]["cifra"] == 549.55
    assert sospechas[0]["sesion"] == "s2"
    assert "549.55" in sospechas[0]["texto"]


def test_la_sospecha_queda_escrita_en_el_evento():
    voz_registro.guardar("s2", "lentes", [
        _herramienta(),
        _dicho("jarvis", "Cuesta 549.55 pesos."),
    ])
    dichos = [e for e in voz_registro.leer() if e.get("quien") == "jarvis"]
    assert dichos[0]["sospechas"][0]["cifra"] == 549.55


def test_un_precio_dicho_sin_haber_consultado_nada_se_marca():
    sospechas = voz_registro.guardar("s3", "lentes", [
        _dicho("tu", "cuanto vale el casco"),
        _dicho("jarvis", "Vale 522.35 pesos."),
    ])
    assert [s["cifra"] for s in sospechas] == [522.35]


def test_el_mismo_precio_inventado_solo_avisa_una_vez():
    voz_registro.guardar("s4", "lentes", [_dicho("jarvis", "Son 549.55 pesos.")])
    repetido = voz_registro.guardar("s4", "lentes", [_dicho("jarvis", "Le dije, 549.55 pesos.")])
    assert repetido == []


def test_una_cifra_que_dijo_el_usuario_no_se_marca():
    sospechas = voz_registro.guardar("s5", "lentes", [
        _dicho("tu", "tengo 2,500.00 pesos, que me alcanza"),
        _dicho("jarvis", "Con 2,500.00 pesos te alcanza para el casco."),
    ])
    assert sospechas == []


def test_una_cantidad_del_usuario_no_es_un_precio():
    sospechas = voz_registro.guardar("s6", "lentes", [
        _dicho("tu", "dame 3 cascos"),
        _dicho("jarvis", "Anotado, 3 cascos. Mide 2 metros de cable y tarda 15 minutos."),
    ])
    assert sospechas == []


def test_un_telefono_no_es_un_precio():
    sospechas = voz_registro.guardar("s7", "lentes", [
        _dicho("jarvis", "El telefono de la sucursal es 809-555-1234 y el otro 8095551234."),
    ])
    assert sospechas == []


def test_una_fecha_y_un_porcentaje_no_son_precios():
    sospechas = voz_registro.guardar("s8", "lentes", [
        _dicho("jarvis", "Llego el 2026-09-29 a las 14:30 con 18% de descuento."),
    ])
    assert sospechas == []


def test_la_suma_de_dos_lineas_no_se_marca():
    resultado = json.dumps([
        {"producto": "Casco", "precio": 1614.55},
        {"producto": "Guantes", "precio": 522.35},
    ])
    sospechas = voz_registro.guardar("s9", "lentes", [
        _herramienta(resultado=resultado),
        _dicho("jarvis", "Entre los dos son 2,136.90 pesos."),
    ])
    assert sospechas == []


def test_una_cantidad_por_un_precio_no_se_marca():
    sospechas = voz_registro.guardar("s10", "lentes", [
        _herramienta(),
        _dicho("jarvis", "Tres cascos salen en 4,843.65 pesos."),
    ])
    assert sospechas == []


def test_un_redondeo_al_hablar_no_se_marca():
    sospechas = voz_registro.guardar("s11", "lentes", [
        _herramienta(),
        _dicho("jarvis", "Cuesta como 1,615 pesos."),
    ])
    assert sospechas == []


def test_el_orden_importa_lo_dicho_antes_de_consultar_se_marca():
    # Si la herramienta corrio despues, la cifra no salio de ella.
    sospechas = voz_registro.guardar("s12", "lentes", [
        _dicho("jarvis", "Cuesta 1,614.55 pesos."),
        _herramienta(),
    ])
    assert [s["cifra"] for s in sospechas] == [1614.55]


def test_los_separadores_de_miles_se_normalizan():
    assert voz_registro._a_numero("1,614.55") == (1614.55, 2)
    assert voz_registro._a_numero("1.614,55") == (1614.55, 2)
    assert voz_registro._a_numero("1614.55") == (1614.55, 2)
    assert voz_registro._a_numero("14") == (14.0, 0)


def test_la_sesion_se_reconstruye_si_el_servidor_reinicia():
    voz_registro.guardar("s13", "lentes", [_herramienta()])
    voz_registro._VISTOS.clear()  # como si el proceso hubiera arrancado de nuevo
    sospechas = voz_registro.guardar("s13", "lentes", [
        _dicho("jarvis", "Cuesta 1,614.55 pesos."),
    ])
    assert sospechas == []


# ------------------------------------------------------------------ endpoint


@pytest.fixture
def cliente(entorno_limpio, monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setenv("JARVIS_PASSWORD_PUENTE", "la-del-puente")
    monkeypatch.setenv("JARVIS_CLAVE_SECRETA", "clave-de-pruebas-larga")
    return TestClient(app)


def _entrar(cliente, contrasena):
    cliente.cookies.clear()
    assert cliente.post("/acceso", data={"clave": contrasena}, follow_redirects=False).status_code == 303


LOTE = {
    "sesion": "abc123", "dispositivo": "lentes",
    "eventos": [
        {"ts": "2026-09-29T20:11:02.345Z", "tipo": "dicho", "quien": "tu",
         "texto": "dame el precio del casco truper blanco"},
        {"ts": "2026-09-29T20:11:03.000Z", "tipo": "herramienta",
         "nombre": "buscar_en_fuente", "argumentos": "{}", "resultado": CATALOGO, "ms": 1886},
        {"ts": "2026-09-29T20:11:05.000Z", "tipo": "dicho", "quien": "jarvis",
         "texto": "Cuesta 522.35 pesos por unidad."},
    ],
}


def test_el_puente_puede_anotar_sin_ser_admin(cliente):
    _entrar(cliente, "la-del-puente")
    respuesta = cliente.post("/api/voz/registro", json=LOTE)
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["ok"] is True
    assert [s["cifra"] for s in cuerpo["sospechas"]] == [522.35]


def test_sin_sesion_no_se_puede_anotar(cliente):
    cliente.cookies.clear()
    assert cliente.post("/api/voz/registro", json=LOTE).status_code == 401


def test_leer_el_registro_es_solo_del_admin(cliente):
    _entrar(cliente, "la-del-puente")
    assert cliente.post("/api/voz/registro", json=LOTE).status_code == 200
    assert cliente.get("/api/voz/registro").status_code == 403

    _entrar(cliente, "la-del-admin")
    respuesta = cliente.get("/api/voz/registro")
    assert respuesta.status_code == 200
    assert respuesta.json()["total"] == 3
    assert respuesta.json()["dia"] == voz_registro.hoy()


def test_un_dia_mal_formado_da_400(cliente):
    _entrar(cliente, "la-del-admin")
    assert cliente.get("/api/voz/registro", params={"dia": "../consumo"}).status_code == 400


def test_si_el_disco_falla_la_peticion_no_se_cae(cliente, monkeypatch):
    def no_hay_disco(*_a, **_k):
        raise OSError("read-only file system")

    monkeypatch.setattr(voz_registro, "archivo_del_dia", no_hay_disco)

    _entrar(cliente, "la-del-puente")
    respuesta = cliente.post("/api/voz/registro", json=LOTE)
    assert respuesta.status_code == 200
    # Y aun sin poder guardar, la revision del lote se devuelve igual.
    assert [s["cifra"] for s in respuesta.json()["sospechas"]] == [522.35]


def test_si_la_rotacion_falla_tampoco_se_cae(monkeypatch):
    def no_hay_disco(*_a, **_k):
        raise OSError("read-only file system")

    monkeypatch.setattr(voz_registro, "rotar", no_hay_disco)
    assert voz_registro.guardar("s14", "lentes", [_dicho("tu", "hola")]) == []
