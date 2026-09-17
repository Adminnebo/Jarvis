"""Cuanto lleva consumido cada organizacion, y de donde sale ese numero."""

import pytest

from backend import consumo, cuentas

# Un millon de tokens de entrada de gpt-5.6-terra son 2 dolares.
UN_MILLON = {"input_tokens": 1_000_000}


@pytest.fixture
def organizacion():
    return cuentas.crear_organizacion("Acme", "Lucas", "lucas@acme.com", "una-clave-larga")


def test_una_organizacion_nueva_no_consumio_nada(organizacion):
    assert cuentas.consumido(organizacion.organizacion_id) == {
        "consultas": 0, "tokens": 0, "costo": 0.0, "cobrado": 0.0, "markup": 1.0,
    }


def test_lo_consumido_se_suma(organizacion):
    usuario = cuentas.entrar("lucas@acme.com", "una-clave-larga")
    consumo.registrar("texto", "gpt-5.6-terra", UN_MILLON, usuario=usuario)
    consumo.registrar("texto", "gpt-5.6-terra", UN_MILLON, usuario=usuario)

    resultado = cuentas.consumido(organizacion.organizacion_id)
    assert resultado["consultas"] == 2
    assert resultado["costo"] == 4.0
    assert resultado["tokens"] == 2_000_000


def test_el_markup_separa_lo_que_cuesta_de_lo_que_se_cobra(organizacion):
    from backend import basedatos

    with basedatos.conexion() as con:
        con.execute("UPDATE organizaciones SET markup = 2.5 WHERE id = ?",
                    (organizacion.organizacion_id,))

    usuario = cuentas.entrar("lucas@acme.com", "una-clave-larga")
    consumo.registrar("texto", "gpt-5.6-terra", UN_MILLON, usuario=usuario)

    resultado = cuentas.consumido(organizacion.organizacion_id)
    assert resultado["costo"] == 2.0      # lo que cuesta en OpenAI
    assert resultado["cobrado"] == 5.0    # lo que se le factura


def test_el_consumo_de_una_organizacion_no_le_pega_a_otra(organizacion):
    otra = cuentas.crear_organizacion("Otra", "Ana", "ana@otra.com", "otra-clave-larga")

    usuario = cuentas.entrar("lucas@acme.com", "una-clave-larga")
    consumo.registrar("texto", "gpt-5.6-terra", UN_MILLON, usuario=usuario)

    assert cuentas.consumido(organizacion.organizacion_id)["costo"] == 2.0
    assert cuentas.consumido(otra.organizacion_id)["costo"] == 0.0


def test_las_sesiones_de_voz_no_cuentan_como_consultas(organizacion):
    usuario = cuentas.entrar("lucas@acme.com", "una-clave-larga")
    consumo.registrar_sesion("gpt-realtime-2.1", 60.0, usuario=usuario)

    # La sesion solo aporta tiempo; su costo ya esta en las respuestas.
    assert cuentas.consumido(organizacion.organizacion_id)["consultas"] == 0


def test_sin_organizacion_no_hay_nada_que_medir():
    assert cuentas.consumido(None)["cobrado"] == 0.0


def test_listar_organizaciones_trae_lo_consumido(organizacion):
    usuario = cuentas.entrar("lucas@acme.com", "una-clave-larga")
    consumo.registrar("texto", "gpt-5.6-terra", UN_MILLON, usuario=usuario)

    lista = cuentas.organizaciones()
    assert len(lista) == 1
    assert lista[0]["nombre"] == "Acme"
    assert lista[0]["cobrado"] == 2.0


# --------------------------------------------------------------------------
# El consumo ahora vive en la base de datos
# --------------------------------------------------------------------------

def test_lo_registrado_se_lee_de_vuelta():
    registro = consumo.registrar("texto", "gpt-5.6-terra", {"input_tokens": 100})
    guardados = consumo.todos()

    assert len(guardados) == 1
    assert guardados[0]["modelo"] == "gpt-5.6-terra"
    assert guardados[0]["costo"] == registro["costo"]


def test_borrar_deja_la_tabla_vacia():
    consumo.registrar("texto", "gpt-5.6-terra", {"input_tokens": 100})
    consumo.borrar()
    assert consumo.todos() == []


def test_migrar_el_jsonl_viejo_sube_los_registros(entorno_limpio):
    import json

    viejo = consumo.archivo()
    viejo.write_text(
        json.dumps({"cuando": "2026-09-01T10:00:00", "modo": "texto",
                    "modelo": "gpt-5.6-terra", "tokens": 10, "costo": 0.5,
                    "entrada_texto": 10}) + "\n"
        # Una linea rota no puede impedir arrancar.
        + "esto no es json\n",
        encoding="utf-8",
    )

    consumo.migrar_jsonl()

    guardados = consumo.todos()
    assert len(guardados) == 1
    assert guardados[0]["costo"] == 0.5
    # Las casillas que no existian entran en cero, no en NULL.
    assert guardados[0]["entrada_audio"] == 0
    # El archivo viejo no se borra: se renombra.
    assert not viejo.exists()
    assert viejo.with_suffix(".jsonl.migrado").exists()


def test_migrar_es_idempotente(entorno_limpio):
    import json

    consumo.archivo().write_text(
        json.dumps({"cuando": "2026-09-01T10:00:00", "modo": "texto",
                    "modelo": "gpt-5.6-terra", "tokens": 10, "costo": 0.5}) + "\n",
        encoding="utf-8",
    )
    consumo.migrar_jsonl()
    consumo.migrar_jsonl()

    assert len(consumo.todos()) == 1
