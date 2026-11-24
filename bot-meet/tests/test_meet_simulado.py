from pathlib import Path

import pytest

pytest.importorskip("playwright")
from bot_meet.meet import MeetPlaywright  # noqa: E402

pytestmark = pytest.mark.navegador
PAGINA = (Path(__file__).parent / "meet_simulado" / "index.html").resolve().as_uri()


@pytest.fixture
def meet(tmp_path):
    m = MeetPlaywright(tmp_path / "perfil", tmp_path / "capturas", headless=True,
                       sel_hablando='[data-hablando="1"]')
    yield m
    m.cerrar()


def test_entra_y_lee_el_estado(meet):
    r = meet.unirse(PAGINA + "?admitir_ms=200", espera_s=10)
    assert r.estado == "admitido"
    e = meet.leer_estado()
    assert e.en_llamada and e.otros == 1 and e.hablando == []
    meet._pagina.evaluate("hablar('p1', true)")
    assert meet.leer_estado().hablando == ["Ana"]
    meet._pagina.evaluate("quitar('p1')")
    assert meet.leer_estado().otros == 0


def test_apaga_micro_y_camara_antes_de_entrar(meet):
    meet.unirse(PAGINA + "?admitir_ms=5000", espera_s=0)
    assert meet._pagina.locator('[aria-label="Desactivar micrófono"]').get_attribute("data-apagado") == "1"
    assert meet._pagina.locator('[aria-label="Desactivar cámara"]').get_attribute("data-apagado") == "1"


def test_rechazado(meet):
    assert meet.unirse(PAGINA + "?rechazar=1&admitir_ms=200", espera_s=10).estado == "rechazado"


def test_nadie_admite_a_tiempo(meet):
    r = meet.unirse(PAGINA + "?admitir_ms=60000", espera_s=2)
    assert (r.estado, r.motivo) == ("rechazado", "sin_respuesta")


def test_solo_audio_y_chat(meet):
    meet.unirse(PAGINA + "?admitir_ms=100", espera_s=10)
    assert meet.solo_audio() is True
    assert meet._pagina.locator("#recepcion").input_value() == "Solo audio"
    assert meet.escribir_chat("Jarvis está grabando") is True
    assert meet._pagina.locator("#mensajes li").inner_text() == "Jarvis está grabando"


def test_salir(meet):
    meet.unirse(PAGINA + "?admitir_ms=100", espera_s=10)
    meet.salir()
    assert meet.leer_estado().en_llamada is False


def test_captura_guarda_imagen(meet, tmp_path):
    meet.unirse(PAGINA + "?admitir_ms=100", espera_s=10)
    ruta = meet.captura("prueba")
    assert ruta.exists() and ruta.suffix == ".png"
