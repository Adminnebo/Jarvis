from datetime import datetime, timedelta, timezone

from bot_meet.agenda import Sesion
from bot_meet.meet import EstadoLlamada, ResultadoEntrada
from bot_meet.sesion import AVISO, ejecutar_sesion

T0 = datetime(2026, 12, 1, 14, 0, tzinfo=timezone.utc)


def sesion(minutos=60):
    return Sesion("r1", "https://meet.google.com/abc-defg-hij", T0, T0 + timedelta(minutes=minutos),
                  "tok", "https://j.test")


class Reloj:
    def __init__(self):
        self.t = T0

    def ahora(self):
        return self.t

    def dormir(self, s):
        self.t += timedelta(seconds=s)


class MeetFalso:
    def __init__(self, entradas, estados):
        self.entradas = list(entradas)   # ResultadoEntrada por cada unirse()
        self.estados = estados           # función (segundo) -> EstadoLlamada
        self.chat, self.salio, self.cerrado, self.capturas = [], False, False, []
        self.reloj = None

    def unirse(self, url, espera_s):
        return self.entradas.pop(0)

    def solo_audio(self):
        return True

    def silenciar(self):
        self.silencios = getattr(self, "silencios", 0) + 1
        return 0

    def escribir_chat(self, texto):
        self.chat.append(texto)
        return True

    def leer_estado(self):
        return self.estados(int((self.reloj.t - T0).total_seconds()))

    def salir(self):
        self.salio = True

    def captura(self, nombre):
        self.capturas.append(nombre)

    def volcar(self, nombre):
        pass

    def anotar_calibracion(self, t):
        self.calibrado = getattr(self, "calibrado", []) + [t]

    def cerrar(self):
        self.cerrado = True


class GrabadorFalso:
    def __init__(self):
        self.inicios, self.detenciones = 0, 0

    def iniciar(self):
        self.inicios += 1

    def detener(self):
        self.detenciones += 1

    def pedazos_listos(self, todos=False):
        return []


class SubidorFalso:
    def __init__(self):
        self.cosas = []

    def evento(self, tipo, **datos):
        self.cosas.append(("evento", tipo, datos))

    def audio(self, n, ruta):
        self.cosas.append(("audio", n))

    def hablantes(self, linea):
        self.cosas.append(("hablantes", linea))

    def vaciar(self):
        return 0

    def tipos(self):
        return [c[1] for c in self.cosas if c[0] == "evento"]


def correr(meet, debe_parar=lambda: False, minutos=60):
    reloj = Reloj()
    meet.reloj = reloj
    g, s = GrabadorFalso(), SubidorFalso()
    r = ejecutar_sesion(sesion(minutos), meet, g, s, debe_parar,
                        ahora=reloj.ahora, dormir=reloj.dormir, espera_admision_s=600)
    return r, g, s


def test_reunion_normal_hasta_quedar_solo():
    # Ana habla del segundo 10 al 20; a los 60 s se va; 2 min después el bot sale.
    def estados(seg):
        if seg >= 60:
            return EstadoLlamada(True, 0, [])
        return EstadoLlamada(True, 1, ["Ana"] if 10 <= seg < 20 else [])
    m = MeetFalso([ResultadoEntrada("admitido")], estados)
    r, g, s = correr(m)
    assert r == "terminada"
    assert s.tipos() == ["esperando", "admitido", "terminado"]
    assert s.cosas[-1] == ("evento", "terminado", {"motivo": "solo", "incompleta": False})
    linea = [c for c in s.cosas if c[0] == "hablantes"][0][1]
    assert linea[0] == {"t": 10, "nombres": ["Ana"]} and len(linea) == 10
    assert m.chat == [AVISO] and m.salio and m.cerrado
    assert g.inicios == 1 and g.detenciones == 1
    # Al entrar y una vez por minuto mientras está adentro (sale a los 180 s).
    assert m.silencios == 1 + 3


def test_calibracion_solo_los_primeros_segundos():
    m = MeetFalso([ResultadoEntrada("admitido")],
                  lambda seg: EstadoLlamada(True, 0 if seg >= 30 else 1, []))
    reloj = Reloj()
    m.reloj = reloj
    ejecutar_sesion(sesion(), m, GrabadorFalso(), SubidorFalso(), lambda: False,
                    ahora=reloj.ahora, dormir=reloj.dormir, calibrar_s=10)
    assert m.calibrado == list(range(10))


def test_rechazado():
    m = MeetFalso([ResultadoEntrada("rechazado", "sin_respuesta")], lambda s: EstadoLlamada(False))
    r, g, s = correr(m)
    assert r == "rechazada"
    assert s.cosas[-1] == ("evento", "rechazado", {"motivo": "sin_respuesta"})
    assert g.inicios == 0 and m.cerrado


def test_fallo_al_entrar_guarda_captura():
    m = MeetFalso([ResultadoEntrada("fallo", "sin_boton_unirse")], lambda s: EstadoLlamada(False))
    r, _, s = correr(m)
    assert r == "fallida"
    assert s.cosas[-1] == ("evento", "fallo", {"motivo": "sin_boton_unirse"})
    assert m.capturas == ["fallo-entrar"]


def test_un_parpadeo_no_es_una_caida():
    # Un diálogo abierto tapa la llamada 3 s: no se detiene la grabación.
    def estados(seg):
        if 30 <= seg < 33:
            return EstadoLlamada(False)
        if seg >= 100:
            return EstadoLlamada(True, 0, [])
        return EstadoLlamada(True, 1, [])
    m = MeetFalso([ResultadoEntrada("admitido")], estados)
    r, g, _ = correr(m)
    assert r == "terminada" and g.inicios == 1 and g.detenciones == 1


def test_se_cae_y_vuelve_a_entrar_una_vez():
    def estados(seg):
        if 30 <= seg < 40:
            return EstadoLlamada(False)   # Chrome se cayó
        if seg >= 100:
            return EstadoLlamada(True, 0, [])
        return EstadoLlamada(True, 1, [])
    m = MeetFalso([ResultadoEntrada("admitido"), ResultadoEntrada("admitido")], estados)
    r, g, s = correr(m)
    assert r == "terminada" and g.inicios == 2


def test_se_cae_dos_veces_queda_incompleta():
    m = MeetFalso([ResultadoEntrada("admitido"), ResultadoEntrada("fallo", "x")],
                  lambda seg: EstadoLlamada(seg < 30, 1, []))
    r, _, s = correr(m)
    assert r == "incompleta"
    assert s.cosas[-1] == ("evento", "terminado", {"motivo": "caida", "incompleta": True})


def test_cancelada_desde_jarvis():
    m = MeetFalso([ResultadoEntrada("admitido")], lambda seg: EstadoLlamada(True, 1, []))
    llamadas = [0]

    def debe_parar():
        llamadas[0] += 1
        return llamadas[0] > 5
    r, _, s = correr(m, debe_parar)
    assert r == "terminada"
    assert s.cosas[-1][2]["motivo"] == "cancelada"
