"""El cobro en agentia: juntar centavos, mandar una vez, reintentar sin doblar."""

import httpx
import pytest

from backend import consumo, creditos, cuentas

# Un millon de tokens de entrada de gpt-5.6-terra son 2 dolares.
UN_MILLON = {"input_tokens": 1_000_000}
# Mil tokens son 0.002: menos de un centavo.
MIL = {"input_tokens": 1_000}
LLAVE = "3d4cbb9f-clave-de-prueba"


class _Respuesta:
    def __init__(self, estado, cuerpo):
        self.status_code = estado
        self._cuerpo = cuerpo
        self.text = str(cuerpo)

    def json(self):
        return self._cuerpo


@pytest.fixture
def agentia(monkeypatch):
    """agentia simulada: anota lo que recibe y responde como la de verdad."""
    monkeypatch.setenv("JARVIS_CREDITOS_URL", "https://agentia.ejemplo/api/credits/adjust")
    monkeypatch.setenv("JARVIS_CREDITOS_CALLER_ID", "14")
    monkeypatch.setenv("JARVIS_CREDITOS_API_KEY", LLAVE)

    recibidos = []
    estado = {"respuesta": lambda cuerpo: _Respuesta(201, {"success": True})}

    def post(url, json, timeout):
        recibidos.append(json)
        return estado["respuesta"](json)

    monkeypatch.setattr(creditos.httpx, "post", post)
    return {"recibidos": recibidos, "estado": estado}


@pytest.fixture
def lucas(monkeypatch):
    organizacion = cuentas.crear_organizacion("Acme", "Lucas", "lucas@acme.com", "una-clave-larga")
    monkeypatch.setenv(f"JARVIS_CREDITOS_CLIENTE_{organizacion.organizacion_id}", "16")
    return cuentas.entrar("lucas@acme.com", "una-clave-larga")


def _activar():
    # El primer ciclo solo marca hasta donde hay consumo: no cobra lo de antes.
    creditos.ciclo()


def test_sin_configurar_no_manda_nada(lucas, monkeypatch):
    llamadas = []
    monkeypatch.setattr(creditos.httpx, "post", lambda *a, **k: llamadas.append(1))
    consumo.registrar("texto", "gpt-5.6-terra", UN_MILLON, usuario=lucas)

    assert creditos.ciclo() == {"apagado": True}
    assert llamadas == []


def test_lo_consumido_antes_de_activarlo_no_se_cobra(agentia, lucas):
    consumo.registrar("texto", "gpt-5.6-terra", UN_MILLON, usuario=lucas)
    _activar()
    creditos.ciclo()
    assert agentia["recibidos"] == []


def test_manda_lo_cobrado_con_concepto_jarvis_y_el_usuario_en_la_nota(agentia, lucas, monkeypatch):
    monkeypatch.setenv("JARVIS_MARGEN", "30")
    _activar()
    consumo.registrar("texto", "gpt-5.6-terra", UN_MILLON, usuario=lucas)

    assert creditos.ciclo() == {"enviados": 1, "fallidos": 0}

    [enviado] = agentia["recibidos"]
    assert enviado["amount"] == 2.6            # costo 2 + 30% de margen
    assert enviado["operation"] == "subtract"
    assert enviado["concept"] == "Jarvis"
    assert enviado["note"] == "Lucas"
    assert enviado["clientId"] == 16
    assert enviado["callerId"] == 14
    assert enviado["apiKey"] == LLAVE
    assert enviado["reference"].startswith("jarvis-")


def test_menos_de_un_centavo_espera_a_juntar_mas(agentia, lucas):
    # agentia redondea a centavos: mandar 0.002 descontaria $0.00.
    _activar()
    consumo.registrar("texto", "gpt-5.6-terra", MIL, usuario=lucas)
    creditos.ciclo()
    assert agentia["recibidos"] == []

    for _ in range(4):
        consumo.registrar("texto", "gpt-5.6-terra", MIL, usuario=lucas)
    creditos.ciclo()

    # 5 x 0.002 = 0.01: recien ahi sale un centavo.
    assert [e["amount"] for e in agentia["recibidos"]] == [0.01]


def test_lo_que_no_llega_al_centavo_queda_para_despues(agentia, lucas):
    _activar()
    for _ in range(7):                         # 7 x 0.002 = 0.014
        consumo.registrar("texto", "gpt-5.6-terra", MIL, usuario=lucas)
    creditos.ciclo()
    assert [e["amount"] for e in agentia["recibidos"]] == [0.01]

    for _ in range(3):                         # 0.004 que quedo + 0.006 = 0.01
        consumo.registrar("texto", "gpt-5.6-terra", MIL, usuario=lucas)
    creditos.ciclo()
    assert [e["amount"] for e in agentia["recibidos"]] == [0.01, 0.01]


def test_cada_persona_va_por_separado(agentia, lucas):
    ana = cuentas.agregar_usuario(lucas.organizacion_id, "Ana", "ana@acme.com", "otra-clave-larga")
    _activar()
    consumo.registrar("texto", "gpt-5.6-terra", UN_MILLON, usuario=lucas)
    consumo.registrar("texto", "gpt-5.6-terra", UN_MILLON, usuario=ana)
    consumo.registrar("texto", "gpt-5.6-terra", UN_MILLON, usuario=ana)

    creditos.ciclo()

    por_nota = {e["note"]: e["amount"] for e in agentia["recibidos"]}
    assert por_nota == {"Lucas": 2.0, "Ana": 4.0}


def test_sin_cliente_configurado_no_se_cobra(agentia, monkeypatch):
    otra = cuentas.crear_organizacion("Otra", "Beto", "beto@otra.com", "una-clave-larga")
    beto = cuentas.entrar("beto@otra.com", "una-clave-larga")
    _activar()
    consumo.registrar("texto", "gpt-5.6-terra", UN_MILLON, usuario=beto)
    # Y la gente de la casa, sin organizacion, tampoco.
    consumo.registrar("texto", "gpt-5.6-terra", UN_MILLON, usuario=None)

    creditos.ciclo()
    assert agentia["recibidos"] == []
    assert otra.organizacion_id


def test_si_agentia_falla_se_reintenta_con_la_misma_referencia(agentia, lucas):
    _activar()
    consumo.registrar("texto", "gpt-5.6-terra", UN_MILLON, usuario=lucas)

    agentia["estado"]["respuesta"] = lambda cuerpo: _Respuesta(500, {"success": False})
    assert creditos.ciclo() == {"enviados": 0, "fallidos": 1}

    agentia["estado"]["respuesta"] = lambda cuerpo: _Respuesta(201, {"success": True})
    assert creditos.ciclo() == {"enviados": 1, "fallidos": 0}

    primero, segundo = agentia["recibidos"]
    # Misma referencia: si el primero se hubiera aplicado igual, agentia no
    # lo cobra de nuevo.
    assert primero["reference"] == segundo["reference"]
    assert primero["amount"] == segundo["amount"] == 2.0


def test_una_red_caida_tampoco_pierde_el_cobro(agentia, lucas):
    _activar()
    consumo.registrar("texto", "gpt-5.6-terra", UN_MILLON, usuario=lucas)

    def sin_red(cuerpo):
        raise httpx.ConnectError("sin red")

    agentia["estado"]["respuesta"] = sin_red
    assert creditos.ciclo()["fallidos"] == 1
    assert creditos.resumen()["pendientes"] == 1

    agentia["estado"]["respuesta"] = lambda cuerpo: _Respuesta(201, {"success": True})
    creditos.ciclo()
    assert creditos.resumen()["pendientes"] == 0


def test_lo_ya_enviado_no_se_vuelve_a_mandar(agentia, lucas):
    _activar()
    consumo.registrar("texto", "gpt-5.6-terra", UN_MILLON, usuario=lucas)
    creditos.ciclo()
    creditos.ciclo()
    creditos.ciclo()
    assert len(agentia["recibidos"]) == 1


def test_un_duplicado_de_agentia_cuenta_como_enviado(agentia, lucas):
    # Si agentia ya lo tenia (se aplico pero no llego la respuesta), contesta
    # 200 con duplicate: esta cobrado, no hay que insistir.
    _activar()
    consumo.registrar("texto", "gpt-5.6-terra", UN_MILLON, usuario=lucas)
    agentia["estado"]["respuesta"] = lambda cuerpo: _Respuesta(200, {"success": True, "duplicate": True})

    assert creditos.ciclo() == {"enviados": 1, "fallidos": 0}


def test_las_sesiones_de_voz_no_se_cobran(agentia, lucas):
    # La sesion solo anota el tiempo; su costo ya viene en cada respuesta.
    _activar()
    consumo.registrar_sesion("gpt-realtime-2.1", 600.0, usuario=lucas)
    creditos.ciclo()
    assert agentia["recibidos"] == []


def test_la_api_key_no_queda_en_el_error_guardado(agentia, lucas):
    _activar()
    consumo.registrar("texto", "gpt-5.6-terra", UN_MILLON, usuario=lucas)
    agentia["estado"]["respuesta"] = lambda cuerpo: _Respuesta(401, {"error": f"mala: {LLAVE}"})
    creditos.ciclo()

    error = creditos.resumen()["ultimo_error"]
    assert error.startswith("401")
    assert LLAVE not in error


def test_el_resumen_cuenta_lo_cobrado(agentia, lucas):
    _activar()
    consumo.registrar("texto", "gpt-5.6-terra", UN_MILLON, usuario=lucas)
    creditos.ciclo()
    assert creditos.resumen() == {
        "activo": True, "enviados": 1, "cobrado": 2.0, "pendientes": 0, "ultimo_error": None,
    }


@pytest.mark.parametrize("escrito, esperado", [("16", 16), (" 16 ", 16), ("abc", None), ("-3", None)])
def test_el_cliente_de_una_organizacion(monkeypatch, escrito, esperado):
    monkeypatch.setenv("JARVIS_CREDITOS_CLIENTE_PANELES", escrito)
    assert creditos.cliente_de("paneles") == esperado


# --------------------------------------------------------------------------
# Avisos al arrancar: lo que haria no cobrar sin que nadie se entere
# --------------------------------------------------------------------------

def test_avisa_si_falta_una_de_las_tres(monkeypatch, capsys):
    monkeypatch.setenv("JARVIS_CREDITOS_URL", "https://agentia.ejemplo/api/credits/adjust")
    monkeypatch.setenv("JARVIS_CREDITOS_CALLER_ID", "14")
    creditos.avisar_de_la_configuracion()
    assert "falta JARVIS_CREDITOS_API_KEY" in capsys.readouterr().out


def test_sin_ninguna_variable_no_avisa_nada(capsys):
    # No usarlo es valido: no es un error.
    creditos.avisar_de_la_configuracion()
    assert capsys.readouterr().out == ""


def test_avisa_si_el_id_de_la_organizacion_no_existe(agentia, lucas, monkeypatch, capsys):
    monkeypatch.setenv("JARVIS_CREDITOS_CLIENTE_noexiste", "20")
    creditos.avisar_de_la_configuracion()
    salida = capsys.readouterr().out.lower()
    assert "jarvis_creditos_cliente_noexiste no corresponde" in salida


def test_avisa_si_ninguna_organizacion_tiene_cliente(agentia, capsys):
    creditos.avisar_de_la_configuracion()
    assert "no se cobra nada" in capsys.readouterr().out


def test_con_todo_bien_no_avisa(agentia, lucas, capsys):
    creditos.avisar_de_la_configuracion()
    assert capsys.readouterr().out == ""
