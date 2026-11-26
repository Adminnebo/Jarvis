from pathlib import Path

import pytest

pytest.importorskip("playwright")
from bot_meet.meet import ARGUMENTOS, QUITAR_POR_DEFECTO, MeetPlaywright  # noqa: E402

pytestmark = pytest.mark.navegador
PAGINA = (Path(__file__).parent / "meet_simulado" / "index.html").resolve().as_uri()


def test_chrome_no_sale_silenciado():
    # Si --mute-audio se cuela, la grabación queda en silencio sin ningún error.
    assert "--mute-audio" in QUITAR_POR_DEFECTO
    assert "--mute-audio" not in ARGUMENTOS


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


def test_entra_directo_con_un_cartel_encima(meet):
    # Prueba real 2026-11-24: entró sin sala de espera, un cartel tapaba la llamada y
    # el bot siguió "esperando" hasta rendirse.
    r = meet.unirse(PAGINA + "?admitir_ms=100&cartel=1", espera_s=5)
    assert r.estado == "admitido"
    assert meet._pagina.locator("#cartel").count() == 0   # lo cerró al entrar
    assert meet.leer_estado().en_llamada


def test_apaga_micro_y_camara_ya_dentro_de_la_llamada(meet):
    # Prueba real 2026-11-24: entró directo con la cámara y el micrófono falsos prendidos.
    meet.unirse(PAGINA + "?admitir_ms=100&prendidos=1", espera_s=5)
    assert meet.silenciar() == 2
    etiquetas = [meet._pagina.locator(f"#{i}").get_attribute("aria-label") for i in ("micro-llamada", "camara-llamada")]
    assert all(e.startswith("Activar") for e in etiquetas)
    assert meet.silenciar() == 0   # ya apagados: no los vuelve a prender


def test_foto_de_calibracion_muestra_que_cambia_al_hablar(meet, tmp_path):
    import json
    meet.unirse(PAGINA + "?admitir_ms=100", espera_s=5)
    meet.anotar_calibracion(0)
    meet._pagina.evaluate("hablar('p1', true)")
    meet.anotar_calibracion(1)
    lineas = [json.loads(x) for x in (tmp_path / "capturas" / "calibracion.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [x["t"] for x in lineas] == [0, 1]
    ana = [next(m for m in x["mosaicos"] if m["id"] == "p1") for x in lineas]
    assert 'a:data-hablando=1' not in ana[0]["marcas"] and 'a:data-hablando=1' in ana[1]["marcas"]
    assert "a:data-self-name=Ana" in ana[1]["marcas"]


@pytest.fixture
def meet_real(tmp_path):
    m = MeetPlaywright(tmp_path / "perfil", tmp_path / "capturas", headless=True, sel_hablando=".gjg47c")
    yield m
    m.cerrar()


def test_nombres_y_quien_habla_como_en_el_meet_real(meet_real):
    # Calibrado con las reuniones reales del 2026-11-25.
    meet_real.unirse(PAGINA + "?admitir_ms=100&real=1", espera_s=5)
    e = meet_real.leer_estado()
    # Jorge y Edmond; ni la presentación (aunque tenga la clase) ni el propio bot cuentan.
    assert e.en_llamada and e.otros == 2 and e.hablando == []
    meet_real._pagina.evaluate("hablaReal(1, true)")
    assert meet_real.leer_estado().hablando == ["Edmond Constantin"]
    meet_real._pagina.evaluate("hablaReal(0, true)")
    assert sorted(meet_real.leer_estado().hablando) == ["Edmond Constantin", "Jorge Salamanca"]


def test_si_todos_aparecen_hablando_a_la_vez_no_cuenta(meet_real):
    # Con la presentación, Meet marcó a tres a la vez (uno con el micrófono apagado).
    meet_real.unirse(PAGINA + "?admitir_ms=100&real=1", espera_s=5)
    meet_real._pagina.evaluate("""() => {
      const m = document.getElementById('mosaico');
      m.insertAdjacentHTML('beforeend', '<div data-participant-id="spaces/x/devices/5"><span>Más opciones para Lucas</span><div class="voz gjg47c"></div></div>');
      hablaReal(0, true); hablaReal(1, true);
    }""")
    assert meet_real.leer_estado().hablando == []


def test_sin_boton_de_colgar_pero_con_mosaicos_sigue_en_la_llamada(meet_real):
    # Con alguien presentando, el botón de colgar desaparecía y el bot se daba por caído.
    meet_real.unirse(PAGINA + "?admitir_ms=100&real=1", espera_s=5)
    meet_real._pagina.evaluate("document.querySelector('[aria-label=\"Abandonar la llamada\"]').remove()")
    assert meet_real.leer_estado().en_llamada


def test_si_no_confirma_la_entrada_deja_captura(meet, tmp_path):
    meet.unirse(PAGINA + "?admitir_ms=60000", espera_s=1)
    assert any(p.name.endswith("sin-admision.png") for p in (tmp_path / "capturas").iterdir())


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
    assert meet._pagina.locator("#recepcion").inner_text() == "Solo audio"
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
