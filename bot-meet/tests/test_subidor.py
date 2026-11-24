import json

import httpx

from bot_meet.subidor import Subidor


class Jarvis:
    """Jarvis falso: guarda lo que llega y responde lo que se le pida."""

    def __init__(self):
        self.recibido = []
        self.respuesta = 200

    def __call__(self, req: httpx.Request):
        self.recibido.append((req.method, req.url.path, dict(req.url.params), req.headers.get("authorization"), req.content))
        if self.respuesta == "red":
            raise httpx.ConnectError("caído")
        return httpx.Response(self.respuesta)


def nuevo(tmp_path, jarvis, reloj=lambda: 1000.0):
    cliente = httpx.Client(transport=httpx.MockTransport(jarvis))
    return Subidor(tmp_path / "subidas", "https://j.test/", "r1", "tok", cliente=cliente, reloj=reloj)


def test_envia_en_orden_con_token(tmp_path):
    j = Jarvis()
    s = nuevo(tmp_path, j)
    s.evento("admitido")
    pedazo = tmp_path / "p.ogg"
    pedazo.write_bytes(b"OGG")
    s.audio(1, pedazo)
    s.hablantes([{"t": 3, "nombres": ["Ana"]}])
    assert s.vaciar() == 0
    assert [r[1] for r in j.recibido] == [
        "/api/reuniones/r1/eventos", "/api/reuniones/r1/audio", "/api/reuniones/r1/hablantes"]
    assert j.recibido[0][3] == "Bearer tok"
    assert json.loads(j.recibido[0][4]) == {"tipo": "admitido"}
    assert j.recibido[1][2] == {"n": "1"} and j.recibido[1][4] == b"OGG"
    assert not pedazo.exists()  # se movió a la cola y se borró al confirmarse
    assert list((tmp_path / "subidas").iterdir()) == []


def test_si_jarvis_falla_guarda_y_reintenta_despues(tmp_path):
    j = Jarvis()
    j.respuesta = "red"
    t = [1000.0]
    s = nuevo(tmp_path, j, reloj=lambda: t[0])
    s.evento("admitido")
    s.evento("terminado", motivo="solo", incompleta=False)
    assert s.vaciar() == 2
    j.respuesta = 200
    assert s.vaciar() == 2  # todavía en espera (30 s)
    t[0] += 31
    assert s.vaciar() == 0
    assert [json.loads(r[4])["tipo"] for r in j.recibido if r[4]][-2:] == ["admitido", "terminado"]


def test_la_cola_sobrevive_a_un_reinicio(tmp_path):
    j = Jarvis()
    j.respuesta = 500
    nuevo(tmp_path, j).evento("admitido")
    j.respuesta = 200
    s2 = nuevo(tmp_path, j)
    assert s2.vaciar() == 0
    assert json.loads(j.recibido[-1][4]) == {"tipo": "admitido"}


def test_409_cuenta_como_recibido_y_otros_4xx_se_descartan(tmp_path):
    j = Jarvis()
    j.respuesta = 409
    s = nuevo(tmp_path, j)
    s.evento("admitido")
    assert s.vaciar() == 0
    j.respuesta = 422
    s.evento("admitido")
    assert s.vaciar() == 0  # no se traba la cola por un pedido que nunca va a pasar


def test_descarta_lo_que_tiene_mas_de_24_horas(tmp_path):
    j = Jarvis()
    j.respuesta = 500
    t = [1000.0]
    s = nuevo(tmp_path, j, reloj=lambda: t[0])
    s.evento("admitido")
    t[0] += 24 * 3600 + 1
    assert s.vaciar() == 0
