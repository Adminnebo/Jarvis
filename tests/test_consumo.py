from backend import consumo

# Uso real de gpt-realtime-2.1 con una imagen adjunta (2026-09-14).
USO_CON_IMAGEN = {
    "total_tokens": 527,
    "input_tokens": 494,
    "output_tokens": 33,
    "input_token_details": {
        "text_tokens": 171, "audio_tokens": 0, "image_tokens": 323,
        "cached_tokens": 0,
        "cached_tokens_details": {"text_tokens": 0, "audio_tokens": 0, "image_tokens": 0},
    },
    "output_token_details": {"text_tokens": 33, "audio_tokens": 0, "reasoning_tokens": 11},
}


def test_los_tokens_de_imagen_tienen_su_casilla():
    casillas = consumo.desglosar(USO_CON_IMAGEN)

    assert casillas["entrada_imagen"] == 323
    assert casillas["entrada_texto"] == 171
    assert sum(casillas.values()) == 527


def test_una_modalidad_desconocida_no_se_escapa():
    uso = {
        "input_tokens": 1000, "output_tokens": 50,
        "input_token_details": {"text_tokens": 200, "audio_tokens": 300, "video_tokens": 500},
        "output_token_details": {"audio_tokens": 40, "text_tokens": 0},
    }
    casillas = consumo.desglosar(uso)

    assert sum(casillas.values()) == 1050
    assert casillas["entrada_texto"] == 700
    assert casillas["salida_texto"] == 10


def test_el_modo_texto_sin_desglose_cuenta_todo():
    uso = {"input_tokens": 900, "output_tokens": 120,
           "input_tokens_details": {"cached_tokens": 400}}
    casillas = consumo.desglosar(uso)

    assert casillas["entrada_texto"] == 500
    assert casillas["cache_texto"] == 400
    assert casillas["salida_texto"] == 120


def test_la_imagen_cacheada_no_se_cobra_dos_veces():
    uso = {
        "input_tokens": 500,
        "input_token_details": {
            "text_tokens": 100, "image_tokens": 400, "cached_tokens": 300,
            "cached_tokens_details": {"text_tokens": 0, "image_tokens": 300},
        },
    }
    casillas = consumo.desglosar(uso)

    assert casillas["entrada_imagen"] == 100
    assert casillas["cache_imagen"] == 300
    assert casillas["cache_texto"] == 0


def test_sin_precio_de_imagen_se_cobra_como_texto():
    registro = consumo.registrar("voz", "gpt-realtime-2.1", USO_CON_IMAGEN)

    tarifa = consumo.precio_de("gpt-realtime-2.1")
    esperado = ((171 + 323) * tarifa["texto_entrada"] + 33 * tarifa["texto_salida"]) / 1_000_000
    assert registro["costo"] == round(esperado, 6)


def test_los_registros_de_antes_de_las_imagenes_siguen_sumando():
    viejo = {"modelo": "gpt-realtime-2.1", "modo": "voz", "tokens": 10,
             "costo": 0.1, "entrada_texto": 10}

    fila = consumo.agrupar([viejo])[0]

    assert fila["entrada_imagen"] == 0
    assert fila["tokens"] == 10
