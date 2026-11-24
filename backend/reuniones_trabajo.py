"""Hilo de fondo de las reuniones grabadas.

Cada vuelta: transcribe los pedazos que llegaron (y los sube a Storage),
cierra las reuniones que ya terminaron y tienen todo, avisa a los
interesados y, una vez al día, borra el audio de más de 90 días.
"""

import os
import shutil
import threading
import time
from datetime import datetime, timedelta, timezone

from . import almacen_reuniones, avisos, bot_meet, dispositivos, reuniones, reuniones_ia
from . import reuniones_datos as rd

RETENCION_DIAS = 90
ESPERA_HABLANTES_S = 120
BASE = "https://asistente.neboaiconsulting.com"


def _usuario(reunion_id: str):
    quienes = rd.interesados(reunion_id)
    return dispositivos.usuario_para(quienes[0]) if quienes else None


def transcribir_pendientes() -> None:
    for reunion_id, n in rd.para_transcribir():
        ruta = reuniones.ruta_pedazo(reunion_id, n)
        if not ruta.exists():
            rd.marcar_pedazo(reunion_id, n, "fallido")
            continue
        try:
            segmentos = reuniones_ia.transcribir(ruta, _usuario(reunion_id))
            almacen_reuniones.subir(reunion_id, n, ruta.read_bytes())
        except Exception as error:  # noqa: BLE001 - se reintenta en la próxima vuelta
            print(f"  AVISO: no pude procesar el pedazo {n} de {reunion_id}: {error}")
            rd.marcar_pedazo(reunion_id, n, "recibido", sumar_intento=True)
            este = next(p for p in rd.pedazos(reunion_id) if p["n"] == n)
            if este["intentos"] >= rd.MAX_INTENTOS:
                rd.marcar_pedazo(reunion_id, n, "fallido")
            continue
        rd.marcar_pedazo(reunion_id, n, "transcrito", segmentos=segmentos)
        ruta.unlink(missing_ok=True)


def _lista_para_cerrar(r: dict) -> bool:
    pedazos = rd.pedazos(r["id"])
    if any(p["estado"] == "recibido" for p in pedazos):
        return False
    if r["linea"] is not None:
        return True
    terminada = datetime.fromisoformat(r["terminada"])
    return (datetime.now(timezone.utc) - terminada).total_seconds() > ESPERA_HABLANTES_S


def cerrar(r: dict) -> None:
    pedazos = rd.pedazos(r["id"])
    por_n = {p["n"]: p["segmentos"] or [] for p in pedazos if p["estado"] == "transcrito"}
    faltan = any(p["estado"] == "fallido" for p in pedazos)
    texto = reuniones_ia.con_nombres(por_n, r["linea"] or [])
    usuario = _usuario(r["id"])
    resumen = reuniones_ia.resumir(r["titulo"], texto, usuario) if texto else {
        "resumen": "No se escuchó conversación en la grabación.", "puntos_clave": [], "tareas": []}
    duracion = max((p["n"] for p in pedazos), default=0) * reuniones_ia.PEDAZO_S
    rd.actualizar(r["id"], estado="lista", transcripcion=texto, resumen=resumen["resumen"],
                  puntos=resumen["puntos_clave"], tareas=resumen["tareas"], duracion_s=duracion,
                  incompleta=int(bool(r["incompleta"]) or faltan))
    corto = resumen["resumen"].split("\n")[0][:300]
    for usuario_id in rd.interesados(r["id"]):
        avisos.crear(usuario_id, f"reunion-lista:{r['id']}", r["id"], "Reuniones",
                     f"{BASE}/apps/reuniones#{r['id']}", f"{r['titulo']}: {corto}",
                     con_whatsapp=True, tipo="reunion-lista", app="reuniones")
    shutil.rmtree(reuniones.ruta_pedazo(r["id"], 1).parent, ignore_errors=True)


def cerrar_terminadas() -> None:
    for r in rd.en_estado("procesando"):
        if _lista_para_cerrar(r):
            try:
                cerrar(r)
            except Exception as error:  # noqa: BLE001 - se reintenta en la próxima vuelta
                print(f"  AVISO: no pude cerrar la reunión {r['id']}: {error}")


def borrar_audio_viejo() -> None:
    limite = (datetime.now(timezone.utc) - timedelta(days=RETENCION_DIAS)).isoformat()
    for reunion_id in rd.con_audio_desde_antes(limite):
        numeros = [p["n"] for p in rd.pedazos(reunion_id) if p["estado"] == "transcrito"]
        try:
            almacen_reuniones.borrar(reunion_id, numeros)
        except almacen_reuniones.ErrorAlmacen as error:
            print(f"  AVISO: no pude borrar el audio de {reunion_id}: {error}")
            continue
        rd.actualizar(reunion_id, audio_borrado=1)


def una_vuelta() -> None:
    transcribir_pendientes()
    cerrar_terminadas()
    avisos.mandar_pendientes()


def cada() -> int:
    try:
        return max(5, int(os.getenv("JARVIS_REUNIONES_CADA", "15")))
    except ValueError:
        return 15


def arrancar() -> None:
    if not bot_meet.configurado():
        print("\n  AVISO: el bot de reuniones está apagado (faltan BOT_MEET_URL o BOT_MEET_SECRETO).\n")
        return

    def vigilar() -> None:
        ultimo_borrado = 0.0
        while True:
            try:
                una_vuelta()
                if time.time() - ultimo_borrado > 24 * 3600:
                    borrar_audio_viejo()
                    ultimo_borrado = time.time()
            except Exception as error:  # noqa: BLE001 - el hilo no se puede morir
                print(f"  AVISO: falló la vuelta de reuniones: {error}")
            time.sleep(cada())

    threading.Thread(target=vigilar, daemon=True, name="reuniones").start()
