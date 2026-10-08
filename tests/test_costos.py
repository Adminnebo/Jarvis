"""El resumen para el Panel Maestro: lo que costo Jarvis y lo que cobro."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend import basedatos, consumo, costos, creditos, cuentas

# Un millon de tokens de entrada de gpt-5.6-terra son 2 dolares.
UN_MILLON = {"input_tokens": 1_000_000}
CLAVE = "clave-del-panel-maestro"


class _Respuesta:
    status_code = 201
    text = ""

    def json(self):
        return {"success": True}


@pytest.fixture
def acme(monkeypatch):
    """Una organizacion a la que se le cobra con 30% de margen, y agentia simulada."""
    organizacion = cuentas.crear_organizacion("Acme", "Lucas", "lucas@acme.com", "una-clave-larga")
    monkeypatch.setenv(f"JARVIS_MARGEN_{organizacion.organizacion_id}", "30")
    monkeypatch.setenv(f"JARVIS_CREDITOS_CLIENTE_{organizacion.organizacion_id}", "16")
    monkeypatch.setenv("JARVIS_CREDITOS_URL", "https://agentia.ejemplo/api/credits/adjust")
    monkeypatch.setenv("JARVIS_CREDITOS_CALLER_ID", "14")
    monkeypatch.setenv("JARVIS_CREDITOS_API_KEY", "una-llave")
    monkeypatch.setattr(creditos.httpx, "post", lambda url, json, timeout: _Respuesta())
    return cuentas.entrar("lucas@acme.com", "una-clave-larga")


def _todo():
    ahora = datetime.now(timezone.utc)
    return ahora - timedelta(days=1), ahora + timedelta(minutes=5)


def test_sin_uso_todo_esta_en_cero():
    resumen = costos.resumen(*_todo())
    assert resumen["ingreso"] == {"valor": 0, "etiqueta": "medido"}
    assert resumen["costo"] == {"valor": 0, "etiqueta": "estimado", "por_proveedor": {}}
    assert resumen["unidades"] == {"valor": 0, "nombre": "consultas"}
    assert resumen["detalle"]["cobro_activo"] is False


def test_el_costo_cuenta_todo_y_el_ingreso_solo_lo_que_se_desconto(acme):
    creditos.ciclo()  # la primera vuelta solo marca desde donde se cobra

    consumo.registrar("texto", "gpt-5.6-terra", UN_MILLON, usuario=acme)
    consumo.registrar("texto", "gpt-5.6-terra", UN_MILLON)  # alguien de la casa

    antes = costos.resumen(*_todo())
    assert antes["costo"]["valor"] == 4.0
    assert antes["unidades"]["valor"] == 2
    # Todavia no corrio el cobro: ya se debe, pero no se desconto.
    assert antes["ingreso"]["valor"] == 0
    assert antes["detalle"]["devengado"] == 2.6
    assert antes["detalle"]["costo_cobrable"] == 2.0
    assert antes["detalle"]["costo_de_la_casa"] == 2.0

    creditos.ciclo()

    despues = costos.resumen(*_todo())
    assert despues["ingreso"] == {"valor": 2.6, "etiqueta": "medido"}
    assert despues["detalle"]["envios"] == 1
    assert despues["detalle"]["pendiente_de_cobro"] == 0
    assert despues["detalle"]["cobro_activo"] is True


def test_las_sesiones_y_aperturas_no_son_consultas_ni_costo(acme):
    consumo.registrar("texto", "gpt-5.6-terra", UN_MILLON, usuario=acme)
    consumo.registrar_sesion("gpt-realtime-2.1", 90, usuario=acme)
    consumo.registrar_apertura("gpt-realtime-2.1", usuario=acme)

    resumen = costos.resumen(*_todo())
    assert resumen["unidades"]["valor"] == 1
    assert resumen["costo"]["valor"] == 2.0


def test_solo_entra_lo_del_rango(acme):
    consumo.registrar("texto", "gpt-5.6-terra", UN_MILLON, usuario=acme)
    with basedatos.conexion() as con:
        con.execute("UPDATE consumo SET cuando = ?", ((datetime.now() - timedelta(days=40)).isoformat(timespec="seconds"),))
    consumo.registrar("texto", "gpt-5.6-terra", UN_MILLON, usuario=acme)

    assert costos.resumen(*_todo())["costo"]["valor"] == 2.0
    ahora = datetime.now(timezone.utc)
    viejo = costos.resumen(ahora - timedelta(days=60), ahora - timedelta(days=30))
    assert viejo["costo"]["valor"] == 2.0
    assert viejo["unidades"]["valor"] == 1


def test_el_gasto_sale_separado_por_origen(acme):
    consumo.registrar("texto", "gpt-5.6-terra", UN_MILLON, usuario=acme)
    consumo.registrar("texto", "gpt-5.6-terra", UN_MILLON, usuario=acme, dispositivo="lentes")
    consumo.registrar("texto", "gpt-5.6-terra", UN_MILLON, usuario=acme, dispositivo="lentes")

    origenes = {f["origen"]: f for f in costos.resumen(*_todo())["detalle"]["por_origen"]}
    assert origenes["lentes"]["costo"] == 4.0
    assert origenes["lentes"]["consultas"] == 2
    assert origenes["navegador"]["costo"] == 2.0


def test_el_costo_se_reparte_entre_los_proveedores_a_los_que_se_les_paga(acme):
    consumo.registrar("texto", "gpt-5.6-terra", UN_MILLON, usuario=acme)
    consumo.registrar("voz", "gpt-realtime-2.1", {"input_tokens": 1_000_000}, usuario=acme)
    consumo.registrar_cotizacion(1000)  # creditos de PDF.co

    costo = costos.resumen(*_todo())["costo"]
    assert set(costo["por_proveedor"]) == {"openai", "pdfco"}
    assert costo["por_proveedor"]["pdfco"] == 0.6
    # Lo repartido suma exactamente lo informado: nada queda sin proveedor.
    assert round(sum(costo["por_proveedor"].values()), 6) == costo["valor"]


@pytest.mark.parametrize("modelo, proveedor", [
    ("gpt-5.6-terra", "openai"), ("gpt-realtime-2.1-mini", "openai"), ("gpt-live-transcribe", "openai"),
    ("gpt-4o-mini-tts", "openai"), ("pdfco", "pdfco"), ("gemini-live-2.5", "google"),
    ("claude-haiku-4-5", "anthropic"), (None, "openai"),
])
def test_cada_modelo_se_le_paga_a_su_proveedor(modelo, proveedor):
    assert costos.proveedor_de(modelo) == proveedor


def test_el_rango_por_defecto_son_los_ultimos_30_dias():
    inicio, fin = costos.rango(None, None)
    assert fin - inicio == timedelta(days=30)


def test_una_fecha_sin_zona_se_toma_como_utc():
    inicio, fin = costos.rango("2026-09-01T00:00:00", "2026-10-01T00:00:00Z")
    assert inicio == datetime(2026, 9, 1, tzinfo=timezone.utc)
    assert fin == datetime(2026, 10, 1, tzinfo=timezone.utc)


@pytest.mark.parametrize("desde, hasta", [
    ("2026-10-01", "2026-09-01"),   # al reves
    ("2020-01-01", "2026-10-01"),   # demasiado largo
    ("ayer", None),                 # no es una fecha
])
def test_un_rango_que_no_sirve_se_rechaza(desde, hasta):
    with pytest.raises(ValueError):
        costos.rango(desde, hasta)


# --------------------------------------------------------------------------
# La ruta
# --------------------------------------------------------------------------

@pytest.fixture
def cliente(monkeypatch):
    # En un servidor: con contrasena, para comprobar que la ruta no depende de ella.
    monkeypatch.setenv("JARVIS_PASSWORD", "la-contrasena-del-admin")
    from backend.main import app

    with TestClient(app) as cliente:
        yield cliente


def test_sin_la_variable_la_ruta_no_existe(cliente):
    assert cliente.get("/api/costos/resumen").status_code == 404


def test_sin_clave_o_con_otra_no_entra(cliente, monkeypatch):
    monkeypatch.setenv("JARVIS_COSTOS_CLAVE", CLAVE)
    assert cliente.get("/api/costos/resumen").status_code == 401
    assert cliente.get("/api/costos/resumen", headers={"Authorization": "Bearer otra"}).status_code == 401
    # La contrasena del admin no sirve aqui: es otra puerta.
    respuesta = cliente.get("/api/costos/resumen", headers={"Authorization": "Bearer la-contrasena-del-admin"})
    assert respuesta.status_code == 401


def test_con_la_clave_devuelve_el_resumen(cliente, monkeypatch):
    monkeypatch.setenv("JARVIS_COSTOS_CLAVE", CLAVE)
    consumo.registrar("texto", "gpt-5.6-terra", UN_MILLON)

    respuesta = cliente.get("/api/costos/resumen", headers={"Authorization": f"Bearer {CLAVE}"})
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["producto"] == "jarvis"
    assert cuerpo["costo"] == {"valor": 2.0, "etiqueta": "estimado", "por_proveedor": {"openai": 2.0}}
    assert cuerpo["unidades"]["valor"] == 1


def test_un_rango_invalido_es_un_400(cliente, monkeypatch):
    monkeypatch.setenv("JARVIS_COSTOS_CLAVE", CLAVE)
    respuesta = cliente.get(
        "/api/costos/resumen?desde=2026-10-01&hasta=2026-09-01",
        headers={"Authorization": f"Bearer {CLAVE}"},
    )
    assert respuesta.status_code == 400


def test_la_clave_no_abre_el_resto_de_la_api(cliente, monkeypatch):
    monkeypatch.setenv("JARVIS_COSTOS_CLAVE", CLAVE)
    assert cliente.get("/api/consumo", headers={"Authorization": f"Bearer {CLAVE}"}).status_code == 401
