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

from . import almacen_reuniones, avisos, bot_meet, dispositivos, reuniones, reuniones_ia, reuniones_voces
from . import reuniones_datos as rd

RETENCION_DIAS = 90
ESPERA_HABLANTES_S = 120
BASE = "https://asistente.neboaiconsulting.com"


def _usuario(reunion_id: str):
    quienes = rd.interesados(reunion_id)
    return dispositivos.usuario_para(quienes[0]) if quienes else None


def transcribir_pendientes() -> None:
    for reunion_id, n in rd.para_transcribir():
        r = rd.obtener(reunion_id)
        presencial = bool(r and r.get("tipo") == "presencial")
        todos = {p["n"]: p for p in rd.pedazos(reunion_id)}
        # Las voces se reconocen en orden: este espera a los anteriores (a los que aún no
        # llegaron, solo mientras se graba; al terminar se sigue con lo que hay).
        if presencial and (any(m < n and p["estado"] == "recibido" for m, p in todos.items())
                           or (r["estado"] == "grabando" and any(m not in todos for m in range(1, n)))):
            continue
        formato = todos[n].get("formato") or "ogg"
        ruta = reuniones.ruta_pedazo(reunion_id, n, formato)
        if not ruta.exists():
            rd.marcar_pedazo(reunion_id, n, "fallido")
            continue
        try:
            voces = reuniones_voces.cargar(reunion_id) if presencial else None
            if voces and len(voces) > reuniones_voces.MAX_VOCES:
                # El modelo acepta 4 voces conocidas por llamada: una por grupo, y se unen.
                llamadas = [reuniones_ia.transcribir(ruta, _usuario(reunion_id), voces=g)
                            for g in reuniones_voces.grupos(voces)]
                segmentos = reuniones_voces.unir(llamadas, {n for n, _ in voces})
            else:
                segmentos = reuniones_ia.transcribir(ruta, _usuario(reunion_id), voces=voces)
            if presencial:
                segmentos = reuniones_voces.unificar(reunion_id, ruta, segmentos)
            almacen_reuniones.subir(reunion_id, n, ruta.read_bytes(), formato)
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


def _duracion(r: dict, pedazos: list[dict]) -> int:
    if r.get("tipo") == "presencial" and r.get("grabando_desde") and r.get("terminada"):
        return int((datetime.fromisoformat(r["terminada"]) - datetime.fromisoformat(r["grabando_desde"])).total_seconds())
    return max((p["n"] for p in pedazos), default=0) * reuniones_ia.PEDAZO_S


def cerrar(r: dict) -> None:
    pedazos = rd.pedazos(r["id"])
    por_n = {p["n"]: p["segmentos"] or [] for p in pedazos if p["estado"] == "transcrito"}
    inicios = {p["n"]: p["inicio_s"] for p in pedazos if p.get("inicio_s") is not None}
    faltan = any(p["estado"] == "fallido" for p in pedazos)
    texto = reuniones_ia.con_nombres(por_n, r["linea"] or [], inicios=inicios)
    usuario = _usuario(r["id"])
    resumen = reuniones_ia.resumir(r["titulo"], texto, usuario) if texto else {
        "resumen": "No se escuchó conversación en la grabación.", "puntos_clave": [], "tareas": [], "nombres": {}}
    rd.actualizar(r["id"], estado="lista", transcripcion=texto, resumen=resumen["resumen"],
                  puntos=resumen["puntos_clave"], tareas=resumen["tareas"], duracion_s=_duracion(r, pedazos),
                  nombres=resumen.get("nombres") or {}, incompleta=int(bool(r["incompleta"]) or faltan))
    puesta = reuniones.con_nombres_puestos(rd.obtener(r["id"]))
    corto = (puesta["resumen"] or "").split("\n")[0][:300]
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
        transcritos = [p for p in rd.pedazos(reunion_id) if p["estado"] == "transcrito"]
        numeros = [p["n"] for p in transcritos]
        formatos = {p["n"]: p.get("formato") or "ogg" for p in transcritos}
        try:
            almacen_reuniones.borrar(reunion_id, numeros, formatos)
        except almacen_reuniones.ErrorAlmacen as error:
            print(f"  AVISO: no pude borrar el audio de {reunion_id}: {error}")
            continue
        rd.actualizar(reunion_id, audio_borrado=1)


TOPE_PRESENCIAL = timedelta(hours=4, minutes=10)


def vencer_presenciales() -> None:
    """Si el aparato murió sin avisar, la presencial se cierra con lo que llegó."""
    ahora = datetime.now(timezone.utc)
    for r in rd.en_estado("grabando"):
        if r.get("tipo") != "presencial" or not r.get("grabando_desde"):
            continue
        if datetime.fromisoformat(r["grabando_desde"]) + TOPE_PRESENCIAL < ahora:
            rd.actualizar(r["id"], estado="procesando", motivo="maximo", linea=[],
                          terminada=ahora.isoformat(timespec="seconds"))


def una_vuelta() -> None:
    vencer_presenciales()
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
    # Las presenciales no necesitan el bot, pero sí con qué transcribir. (Sin la clave
    # tampoco arranca en las pruebas, donde un hilo suelto procesaría reuniones ajenas.)
    if not (bot_meet.configurado() or os.getenv("OPENAI_API_KEY", "").strip()):
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
