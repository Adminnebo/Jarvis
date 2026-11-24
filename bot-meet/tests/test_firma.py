from bot_meet.firma import firmar, verificar

S = "s" * 32
CUERPO = b'{"id":"r1"}'


def test_firma_valida():
    f = firmar(S, 1000, "post", "/v1/sesiones", CUERPO)
    assert verificar(S, "1000", f, "POST", "/v1/sesiones", CUERPO, ahora=1100)


def test_firma_conocida():
    # Valor fijo: Jarvis (plan 2) tiene que dar exactamente esto.
    assert firmar(S, 1000, "POST", "/v1/sesiones", CUERPO) == (
        "48afd012f6332ff2f2e9e0835636f6a9b6d7f2085a983ab6068614d17d3520b9")


def test_rechaza_cuerpo_cambiado():
    f = firmar(S, 1000, "POST", "/v1/sesiones", CUERPO)
    assert not verificar(S, "1000", f, "POST", "/v1/sesiones", b'{"id":"r2"}', ahora=1000)


def test_rechaza_otra_ruta_o_metodo():
    f = firmar(S, 1000, "POST", "/v1/sesiones", CUERPO)
    assert not verificar(S, "1000", f, "DELETE", "/v1/sesiones", CUERPO, ahora=1000)
    assert not verificar(S, "1000", f, "POST", "/v1/sesiones/x", CUERPO, ahora=1000)


def test_rechaza_fuera_de_ventana():
    f = firmar(S, 1000, "POST", "/v1/sesiones", CUERPO)
    assert not verificar(S, "1000", f, "POST", "/v1/sesiones", CUERPO, ahora=1301)
    assert not verificar(S, "1000", f, "POST", "/v1/sesiones", CUERPO, ahora=699)


def test_rechaza_cabeceras_faltantes_o_raras():
    assert not verificar(S, None, None, "POST", "/v1/sesiones", CUERPO, ahora=1000)
    assert not verificar(S, "abc", "x", "POST", "/v1/sesiones", CUERPO, ahora=1000)
