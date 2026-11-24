from bot_meet.grabador import Grabador


class Proceso:
    def __init__(self, args):
        self.args = args
        self.senales = []

    def send_signal(self, s):
        self.senales.append(s)

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.senales.append("kill")


def test_comando_mono_16k_opus_en_pedazos(tmp_path):
    g = Grabador(tmp_path, pedazo_s=300)
    args = g.comando(1)
    assert args[:3] == ["ffmpeg", "-nostdin", "-loglevel"]
    for par in (["-f", "pulse"], ["-i", "grabacion.monitor"], ["-ac", "1"], ["-ar", "16000"],
                ["-c:a", "libopus"], ["-b:a", "24k"], ["-segment_time", "300"],
                ["-segment_start_number", "1"]):
        i = args.index(par[0])
        assert args[i:i + 2] == par
    assert args[-1] == str(tmp_path / "pedazo-%05d.ogg")


def test_pedazos_listos_deja_el_que_se_esta_escribiendo(tmp_path):
    procesos = []
    g = Grabador(tmp_path, popen=lambda a: procesos.append(Proceso(a)) or procesos[-1])
    g.iniciar()
    for n in (1, 2, 3):
        (tmp_path / f"pedazo-{n:05d}.ogg").write_bytes(b"x")
    assert [n for n, _ in g.pedazos_listos()] == [1, 2]
    assert [n for n, _ in g.pedazos_listos(todos=True)] == [1, 2, 3]


def test_al_reiniciar_sigue_la_numeracion(tmp_path):
    procesos = []
    g = Grabador(tmp_path, popen=lambda a: procesos.append(Proceso(a)) or procesos[-1])
    g.iniciar()
    (tmp_path / "pedazo-00001.ogg").write_bytes(b"x")
    (tmp_path / "pedazo-00002.ogg").write_bytes(b"x")
    g.detener()
    assert procesos[0].senales  # SIGINT para que ffmpeg cierre bien el archivo
    for _, ruta in g.pedazos_listos(todos=True):
        ruta.unlink()
    g.iniciar()
    args = procesos[1].args
    assert args[args.index("-segment_start_number") + 1] == "3"
