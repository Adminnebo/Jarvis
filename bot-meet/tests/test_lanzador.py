from datetime import datetime, timedelta, timezone

from bot_meet.agenda import Agenda, Sesion
from bot_meet.config import Config
from bot_meet.lanzador import Lanzador, copiar_perfil

T0 = datetime(2026, 12, 1, 14, 0, tzinfo=timezone.utc)


def sesion(id_, inicio=T0):
    return Sesion(id_, "https://meet.google.com/abc-defg-hij", inicio, inicio + timedelta(hours=1),
                  "tok", "https://j.test")


def preparar(tmp_path, max_sesiones=2):
    config = Config(secreto="s" * 32, datos=tmp_path, max_sesiones=max_sesiones)
    agenda = Agenda(tmp_path / "agenda.json", max_sesiones=max_sesiones)
    corridas = []
    lanz = Lanzador(config, agenda, correr=lambda s: corridas.append(s.id) or "terminada",
                    iniciar_hilo=lambda f: f())
    return agenda, lanz, corridas


def test_arranca_a_la_hora_y_marca_el_final(tmp_path):
    agenda, lanz, corridas = preparar(tmp_path)
    agenda.agregar(sesion("r1"))
    lanz.revisar(T0 - timedelta(minutes=5))
    assert corridas == []
    lanz.revisar(T0)
    assert corridas == ["r1"]
    assert agenda.obtener("r1").estado == "terminada"
    lanz.revisar(T0 + timedelta(seconds=5))
    assert corridas == ["r1"]  # no la vuelve a lanzar


def test_queda_en_curso_mientras_corre(tmp_path):
    agenda, _, _ = preparar(tmp_path, max_sesiones=1)
    lanz = Lanzador(Config(secreto="s" * 32, datos=tmp_path, max_sesiones=1), agenda,
                    correr=lambda s: "terminada", iniciar_hilo=lambda f: None)  # quedan en curso
    agenda.agregar(sesion("r1"))
    lanz.revisar(T0)
    assert agenda.obtener("r1").estado == "en_curso"


def test_vence_las_que_ya_pasaron(tmp_path):
    agenda, lanz, corridas = preparar(tmp_path)
    agenda.agregar(sesion("r1"))
    lanz.revisar(T0 + timedelta(hours=3))
    assert corridas == [] and agenda.obtener("r1").estado == "vencida"


def test_un_error_en_la_sesion_no_tumba_el_lanzador(tmp_path):
    config = Config(secreto="s" * 32, datos=tmp_path)
    agenda = Agenda(tmp_path / "agenda.json")

    def explota(s):
        raise RuntimeError("chrome")
    lanz = Lanzador(config, agenda, correr=explota, iniciar_hilo=lambda f: f())
    agenda.agregar(sesion("r1"))
    lanz.revisar(T0)
    assert agenda.obtener("r1").estado == "terminada"


def test_limpieza_no_toca_una_cancelada_que_sigue_corriendo(tmp_path):
    config = Config(secreto="s" * 32, datos=tmp_path)
    agenda = Agenda(tmp_path / "agenda.json")
    lanz = Lanzador(config, agenda, correr=lambda s: "terminada", iniciar_hilo=lambda f: None)
    agenda.agregar(sesion("r1"))
    lanz.revisar(T0)                       # el hilo "sigue" (no se ejecuta)
    carpeta = lanz.carpeta("r1")
    (carpeta / "grabacion").mkdir(parents=True)
    agenda.cancelar("r1")                  # Jarvis cancela a mitad
    lanz.reintentar_subidas()
    assert carpeta.exists()


def test_limpieza_borra_la_carpeta_cuando_ya_no_queda_nada(tmp_path):
    agenda, lanz, _ = preparar(tmp_path)
    agenda.agregar(sesion("r1"))
    lanz.revisar(T0)                       # corre y termina
    (lanz.carpeta("r1") / "grabacion").mkdir(parents=True)
    lanz.reintentar_subidas()
    assert not lanz.carpeta("r1").exists()


def test_copiar_perfil_sin_candados_ni_cache(tmp_path):
    base = tmp_path / "perfil"
    (base / "Default" / "Cache").mkdir(parents=True)
    (base / "Default" / "Cookies").write_text("c")
    (base / "SingletonLock").write_text("x")
    destino = copiar_perfil(base, tmp_path / "copia")
    assert (destino / "Default" / "Cookies").read_text() == "c"
    assert not (destino / "SingletonLock").exists()
    assert not (destino / "Default" / "Cache").exists()
