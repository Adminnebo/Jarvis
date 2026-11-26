from datetime import datetime, timedelta, timezone

import pytest

from backend import acceso, avisos, basedatos, reuniones, reuniones_ia, reuniones_trabajo, salas
from backend import reuniones_datos as rd

JORGE = acceso.Usuario(id="admin", nombre="Jorge", rol="admin")
ANA = acceso.Usuario(id="ana", nombre="Ana", rol="usuario")


def sala():
    return reuniones.crear_presencial("admin", "En la sala", sala=True, nombre="Jorge")


def ms(r, segundos):
    """La hora del servidor (en ms) a `segundos` de que empezó la reunión."""
    return int((datetime.fromisoformat(rd.obtener(r["id"])["grabando_desde"]).timestamp() + segundos) * 1000)


def test_crear_sala_con_quien_organiza_adentro():
    x = sala()
    assert salas.CODIGO.match(x["sala"]) and x["link"].endswith(f"/sala/{x['sala']}")
    assert x["participante"] and x["participante_token"] and x["ahora_ms"] > 0
    assert salas.por_codigo(x["sala"])["id"] == x["id"]
    assert [p["nombre"] for p in salas.participantes(x["id"])] == ["Jorge"]
    assert salas.por_codigo("no-existe-xx") is None and salas.por_codigo("../../etc") is None


def test_unirse_como_invitado_y_con_cuenta():
    x = sala()
    invitado = salas.unirse(x["sala"], "  Lucas   Pérez ", None)
    assert invitado["nombre"] == "Lucas Pérez" and invitado["token"]
    assert salas.unirse(x["sala"], "   ", None) == "nombre"
    ana = salas.unirse(x["sala"], "lo que escriba", ANA)
    assert ana["nombre"] == "Ana" and "ana" in rd.interesados(x["id"])   # le llega el resumen
    otra_vez = salas.unirse(x["sala"], "", ANA)                          # recargó la página
    assert otra_vez["participante"] == ana["participante"]
    assert len(salas.participantes(x["id"])) == 3
    rd.actualizar(x["id"], estado="procesando")
    assert salas.unirse(x["sala"], "Tarde", None) == "cerrada"


def test_niveles_por_segundo_y_token():
    x = sala()
    p = salas.unirse(x["sala"], "Lucas", None)
    # 8 niveles de 250 ms desde el segundo 10: segundos 10 y 11, guarda el máximo de cada uno.
    assert salas.guardar_niveles(x["sala"], p["participante"], p["token"], ms(x, 10), [0.1, 0.5, 0.2, 0.1, 0, 0, 0.3, 0])
    assert salas.guardar_niveles(x["sala"], p["participante"], "malo", ms(x, 10), [1]) is None
    with basedatos.conexion() as con:
        filas = con.execute("SELECT segundo, nivel FROM reunion_niveles ORDER BY segundo").fetchall()
    assert [(f[0], f[1]) for f in filas] == [(10, 0.5), (11, 0.3)]
    # Otro paquete del mismo segundo no baja el máximo.
    salas.guardar_niveles(x["sala"], p["participante"], p["token"], ms(x, 10), [0.2])
    with basedatos.conexion() as con:
        assert con.execute("SELECT nivel FROM reunion_niveles WHERE segundo = 10").fetchone()[0] == 0.5
    rd.actualizar(x["id"], estado="procesando")
    assert salas.guardar_niveles(x["sala"], p["participante"], p["token"], ms(x, 12), [0.4]) is False


def test_quien_habla_es_el_microfono_que_mas_oye():
    x = sala()
    jorge = {"participante": x["participante"], "token": x["participante_token"]}
    lucas = salas.unirse(x["sala"], "Lucas", None)
    poner = lambda p, s, v: salas.guardar_niveles(x["sala"], p["participante"], p["token"], ms(x, s), [v])  # noqa: E731
    poner(jorge, 1, 0.30); poner(lucas, 1, 0.05)     # Jorge claro
    poner(jorge, 2, 0.05); poner(lucas, 2, 0.40)     # Lucas claro
    poner(jorge, 3, 0.20); poner(lucas, 3, 0.18)     # parejo: no se sabe
    poner(jorge, 4, 0.01); poner(lucas, 4, 0.005)    # silencio
    assert salas.linea(x["id"]) == [{"t": 1, "nombres": ["Jorge"]}, {"t": 2, "nombres": ["Lucas"]}]


def test_cerrar_una_sala_usa_su_linea_y_borra_los_niveles(monkeypatch):
    monkeypatch.setattr(reuniones_ia, "transcribir", lambda ruta, u, voces=None: [
        {"inicio": 0, "fin": 3, "hablante": "A", "texto": "hola"}])
    monkeypatch.setattr(reuniones_ia, "resumir", lambda t, texto, u: {
        "resumen": "R", "puntos_clave": [], "tareas": [], "nombres": {}})
    monkeypatch.setattr(avisos, "crear", lambda *a, **k: True)
    from backend import almacen_reuniones
    monkeypatch.setattr(almacen_reuniones, "subir", lambda *a, **k: None)
    x = sala()
    lucas = salas.unirse(x["sala"], "Lucas", None)
    for s in range(4):
        salas.guardar_niveles(x["sala"], lucas["participante"], lucas["token"], ms(x, s), [0.5])
    reuniones.recibir_audio(x["id"], 1, b"W", "webm", 0)
    reuniones_trabajo.transcribir_pendientes()
    reuniones.recibir_evento(x["id"], {"tipo": "terminado", "motivo": "usuario"})
    reuniones_trabajo.cerrar_terminadas()
    r = rd.obtener(x["id"])
    assert r["estado"] == "lista" and r["transcripcion"][0]["quien"] == "Lucas"
    with basedatos.conexion() as con:
        assert con.execute("SELECT COUNT(*) FROM reunion_niveles").fetchone()[0] == 0


@pytest.fixture
def con_equipo(monkeypatch):
    from backend import asistente, cuentas
    monkeypatch.setattr(asistente, "organizacion_de", lambda u: "org1")
    monkeypatch.setattr(cuentas, "nombres_de_usuarios",
                        lambda ids: {i: {"sb-1": "Edmond", "sb-2": "Lucas", "admin": "Jorge"}.get(i, i) for i in ids})
    reciente = datetime.now(timezone.utc).isoformat()
    viejo = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    with basedatos.conexion() as con:
        for uid, org, cuando in [("sb-1", "org1", reciente), ("sb-2", "org1", reciente), ("admin", "org1", reciente),
                                 ("sb-3", "org1", viejo), ("sb-9", "otra", reciente)]:
            con.execute("INSERT INTO consumo (cuando, modo, modelo, usuario_id, organizacion_id) VALUES (?, 'x', 'x', ?, ?)",
                        (cuando, uid, org))


def test_equipo_de_la_misma_organizacion(con_equipo):
    assert salas.equipo(JORGE) == [{"id": "sb-1", "nombre": "Edmond"}, {"id": "sb-2", "nombre": "Lucas"}]


def test_invitar_manda_un_aviso_con_el_link(con_equipo, monkeypatch):
    creados = []
    monkeypatch.setattr(avisos, "crear", lambda *a, **k: creados.append((a, k)) or True)
    x = sala()
    assert salas.invitar(JORGE, x["id"], ["sb-1", "sb-9", "sb-1"]) == 1   # sb-9 es de otra organización
    (args, kw), = creados
    assert args[0] == "sb-1" and args[4] == x["link"] and "Jorge te invitó" in args[5]
    assert kw["tipo"] == "sala" and kw["con_whatsapp"] is True
    assert salas.invitar(ANA, x["id"], ["sb-1"]) == 0                    # no es suya
