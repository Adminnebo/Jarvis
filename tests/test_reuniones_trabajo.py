from datetime import datetime, timedelta, timezone

import pytest

from backend import almacen_reuniones, avisos, bot_meet, reuniones, reuniones_ia, reuniones_trabajo
from backend import reuniones_datos as rd

EVENTO = {"id": "e1", "title": "Ventas", "start": "2026-12-01T14:00:00-04:00",
          "end": "2026-12-01T15:00:00-04:00", "conferencing": {"url": "https://meet.google.com/abc-defg-hij"}}


@pytest.fixture
def todo(monkeypatch):
    monkeypatch.setattr(bot_meet, "configurado", lambda: True)
    monkeypatch.setattr(bot_meet, "agendar", lambda *a: None)
    subidos, borrados, creados = [], [], []
    monkeypatch.setattr(almacen_reuniones, "subir", lambda rid, n, d, formato="ogg": subidos.append((rid, n)))
    monkeypatch.setattr(almacen_reuniones, "borrar", lambda rid, ns, formatos=None: borrados.append((rid, list(ns))))
    monkeypatch.setattr(reuniones_ia, "transcribir",
                        lambda ruta, usuario, voces=None: [{"inicio": 0, "fin": 2, "hablante": "A", "texto": f"dicho en {ruta.stem}"}])
    monkeypatch.setattr(reuniones_ia, "resumir",
                        lambda titulo, texto, usuario: {"resumen": "Resumen.", "puntos_clave": [], "tareas": []})
    monkeypatch.setattr(avisos, "crear", lambda *a, **k: creados.append((a, k)) or True)
    monkeypatch.setattr(avisos, "mandar_pendientes", lambda: None)
    r = reuniones.proponer("u1", EVENTO)
    reuniones.pedir("u1", r["id"])
    return {"rid": r["id"], "subidos": subidos, "borrados": borrados, "creados": creados}


def test_transcribe_sube_y_borra_lo_local(todo):
    rid = todo["rid"]
    reuniones.recibir_audio(rid, 1, b"A")
    reuniones_trabajo.transcribir_pendientes()
    assert rd.pedazos(rid)[0]["estado"] == "transcrito"
    assert todo["subidos"] == [(rid, 1)]
    assert not reuniones.ruta_pedazo(rid, 1).exists()


def test_cierra_cuando_llego_todo_y_avisa(todo):
    rid = todo["rid"]
    reuniones.recibir_audio(rid, 1, b"A")
    reuniones.recibir_audio(rid, 2, b"B")
    reuniones.recibir_hablantes(rid, [])
    reuniones.recibir_evento(rid, {"tipo": "terminado", "motivo": "solo", "incompleta": False})
    reuniones_trabajo.una_vuelta()
    fila = rd.obtener(rid)
    assert fila["estado"] == "lista" and fila["resumen"] == "Resumen."
    assert [x["texto"] for x in fila["transcripcion"]] == ["dicho en 00001", "dicho en 00002"]
    (args, kw), = [c for c in todo["creados"] if c[1].get("tipo") == "reunion-lista"]
    assert args[0] == "u1" and kw["con_whatsapp"] is True


def test_no_cierra_si_falta_un_pedazo_por_transcribir(todo, monkeypatch):
    rid = todo["rid"]
    reuniones.recibir_audio(rid, 1, b"A")

    def falla(ruta, usuario):
        raise RuntimeError("OpenAI caído")
    monkeypatch.setattr(reuniones_ia, "transcribir", falla)
    reuniones.recibir_hablantes(rid, [])
    reuniones.recibir_evento(rid, {"tipo": "terminado", "motivo": "solo", "incompleta": False})
    reuniones_trabajo.una_vuelta()
    assert rd.obtener(rid)["estado"] == "procesando"
    for _ in range(3):
        reuniones_trabajo.una_vuelta()
    fila = rd.obtener(rid)   # tras 3 intentos el pedazo queda fallido y se cierra igual
    assert fila["estado"] == "lista" and fila["incompleta"] == 1


def test_retencion_borra_audio_viejo(todo):
    rid = todo["rid"]
    reuniones.recibir_audio(rid, 1, b"A")
    reuniones_trabajo.transcribir_pendientes()
    rd.actualizar(rid, estado="lista", inicio=(datetime.now(timezone.utc) - timedelta(days=91)).isoformat())
    reuniones_trabajo.borrar_audio_viejo()
    assert todo["borrados"] == [(rid, [1])] and rd.obtener(rid)["audio_borrado"] == 1


def test_texto_de_whatsapp_de_reunion_lista():
    texto = avisos._texto_whatsapp({"tipo": "reunion-lista", "resumen": "Ventas: se acordó el precio.",
                                    "asunto": "https://asistente.neboaiconsulting.com/apps/reuniones#r1",
                                    "remitente": "Reuniones", "app": "reuniones"})
    assert texto.startswith("📝 Ventas") and "apps/reuniones#r1" in texto


def test_transcribe_un_pedazo_webm(todo):
    rid = todo["rid"]
    reuniones.recibir_audio(rid, 1, b"W", "webm", 0)
    reuniones_trabajo.transcribir_pendientes()
    assert rd.pedazos(rid)[0]["estado"] == "transcrito"
    assert not reuniones.ruta_pedazo(rid, 1, "webm").exists()
