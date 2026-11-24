from pathlib import Path

import pytest

from bot_meet.config import leer_config

SECRETO = "s" * 32


def test_valores_por_defecto():
    c = leer_config({"BOT_MEET_SECRETO": SECRETO})
    assert c.secreto == SECRETO
    assert c.datos == Path("/data")
    assert c.max_sesiones == 2
    assert c.pedazo_s == 300
    assert c.headless is True
    assert c.espera_admision_s == 600
    assert c.sel_hablando == '[data-hablando="1"]'
    assert c.volcar_dom is False


def test_lee_las_variables():
    c = leer_config({
        "BOT_MEET_SECRETO": SECRETO, "BOT_MEET_DATOS": "/tmp/x",
        "BOT_MEET_MAX_SESIONES": "1", "BOT_MEET_PEDAZO_S": "60",
        "BOT_MEET_HEADLESS": "0", "BOT_MEET_ESPERA_ADMISION_S": "30",
        "BOT_MEET_SEL_HABLANDO": ".habla", "BOT_MEET_VOLCAR_DOM": "1",
    })
    assert c.datos == Path("/tmp/x")
    assert (c.max_sesiones, c.pedazo_s, c.headless, c.espera_admision_s) == (1, 60, False, 30)
    assert c.sel_hablando == ".habla"
    assert c.volcar_dom is True


@pytest.mark.parametrize("secreto", ["", "corto"])
def test_secreto_obligatorio_y_largo(secreto):
    with pytest.raises(ValueError, match="BOT_MEET_SECRETO"):
        leer_config({"BOT_MEET_SECRETO": secreto})
