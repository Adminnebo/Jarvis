"""La regla del prompt para cuando la transcripcion llega rota.

En los lentes, los primeros segundos del enlace traen ruido que el
transcriptor convierte en frases sin sentido ("topa un pale"). Jarvis se las
contestaba como si fueran del usuario. El prompt tiene que decirle que se calle.
"""

from backend import acceso, cerebro


def _prompt():
    return cerebro.instrucciones(acceso.por_defecto())


def test_el_prompt_manda_callar_ante_un_fragmento_roto():
    texto = _prompt()
    assert "Cuando el audio llega roto:" in texto
    assert "fragmento suelto, ininteligible" in texto
    assert "no respondas nada y espera" in texto
    assert "Quedarte callado es" in texto


def test_el_prompt_prohibe_inventar_una_interpretacion():
    texto = _prompt()
    assert "No inventes una interpretacion" in texto
    assert "el ruido no se contesta" in texto


def test_el_prompt_salva_las_respuestas_breves():
    texto = _prompt()
    assert "Una frase corta pero clara si se responde" in texto
    assert "no un\n  fragmento roto" in texto


def test_el_prompt_no_encadena_no_te_entendi():
    texto = _prompt()
    assert "pide que repita una sola vez" in texto
    assert 'Nunca encadenes dos "no te entendi" seguidos' in texto


def test_la_regla_vieja_de_anunciar_no_contradice_a_la_nueva():
    """La vieja daba por hecho que se contesta al ruido; ya no lo menciona."""
    texto = _prompt()
    assert "Tampoco anuncies cuando la respuesta es directa" in texto
    assert "lo ultimo que oiste fue silencio" not in texto


def test_la_regla_del_audio_no_quedo_duplicada():
    texto = _prompt()
    assert texto.count("pregunta lo justo") == 1
