"""Una reunión de punta a punta: entrar, grabar, seguir, salir, subir."""
import time
from datetime import datetime, timezone

from .reglas import motivo_para_salir

AVISO = "Jarvis está grabando esta reunión para tomar notas."
VOLCAR_CADA_S = 10
AUSENTE_MAX_S = 5
SILENCIAR_CADA_S = 60


def _log(sesion, texto):
    print(f"[sesion {sesion.id}] {texto}", flush=True)


def _pasar_pedazos(grabador, subidor, todos=False):
    for n, ruta in grabador.pedazos_listos(todos=todos):
        subidor.audio(n, ruta)


def ejecutar_sesion(sesion, meet, grabador, subidor, debe_parar,
                    ahora=lambda: datetime.now(timezone.utc), dormir=time.sleep,
                    espera_admision_s=600, volcar_dom=False, calibrar_s=0) -> str:
    """Devuelve "terminada", "incompleta", "rechazada" o "fallida"."""
    try:
        subidor.evento("esperando")
        subidor.vaciar()
        r = meet.unirse(sesion.meet_url, espera_admision_s, debe_parar)
        if r.estado == "rechazado":
            subidor.evento("rechazado", motivo=r.motivo)
            subidor.vaciar()
            return "rechazada"
        if r.estado != "admitido":
            meet.captura("fallo-entrar")
            subidor.evento("fallo", motivo=r.motivo)
            subidor.vaciar()
            return "fallida"

        subidor.evento("admitido")
        subidor.vaciar()
        _log(sesion, "admitido")
        if volcar_dom:
            meet.volcar("admitido")
        # Lo primero, que no se le oiga ni se le vea (al entrar directo quedaban prendidos).
        _log(sesion, f"apagados al entrar: {meet.silenciar()}")
        # Después grabar: si algo de lo cosmético se traba, el audio ya corre.
        grabador.iniciar()
        _log(sesion, "grabando")
        meet.solo_audio()
        _log(sesion, "solo audio intentado")
        meet.escribir_chat(AVISO)
        _log(sesion, "aviso intentado")

        entrada = ahora()
        linea, ultima_voz, solo_desde = [], None, None
        reintento_usado, incompleta, motivo = False, False, None
        ultimo_volcado, ausente_desde = 0.0, None
        ultimo_silencio = entrada
        while True:
            if debe_parar():
                motivo = "cancelada"
                break
            estado = meet.leer_estado()
            t = ahora()
            if estado.en_llamada and (t - ultimo_silencio).total_seconds() >= SILENCIAR_CADA_S:
                if meet.silenciar():
                    _log(sesion, "micrófono o cámara se habían prendido: apagados")
                ultimo_silencio = t
            if not estado.en_llamada:
                # Un parpadeo (un menú que tapa la llamada) no es una caída.
                ausente_desde = ausente_desde or t
                if (t - ausente_desde).total_seconds() < AUSENTE_MAX_S:
                    dormir(1)
                    continue
                _log(sesion, "fuera de la llamada")
                # Para saber qué pasó (las caídas del 2026-11-25 no dejaron rastro).
                meet.captura("fuera-de-la-llamada")
                meet.volcar("fuera-de-la-llamada")
                ausente_desde = None
                grabador.detener()
                _pasar_pedazos(grabador, subidor, todos=True)
                if not reintento_usado:
                    reintento_usado = True
                    otra = meet.unirse(sesion.meet_url, espera_admision_s, debe_parar)
                    _log(sesion, f"reintento: {otra.estado} {otra.motivo}")
                    if otra.estado == "admitido":
                        grabador.iniciar()
                        dormir(1)
                        continue
                incompleta, motivo = True, "caida"
                break
            ausente_desde = None
            # Calibración: foto de los mosaicos cada segundo durante los primeros calibrar_s.
            if calibrar_s and (t - entrada).total_seconds() < calibrar_s:
                meet.anotar_calibracion(round((t - entrada).total_seconds()))
            if estado.hablando:
                ultima_voz = t
                linea.append({"t": round((t - entrada).total_seconds()), "nombres": estado.hablando})
            solo_desde = (solo_desde or t) if estado.otros == 0 else None
            # Solo para calibrar: guarda el HTML cada 10 s, se detecte voz o no.
            if volcar_dom and time.monotonic() - ultimo_volcado > VOLCAR_CADA_S:
                meet.volcar("llamada")
                ultimo_volcado = time.monotonic()
            _pasar_pedazos(grabador, subidor)
            subidor.vaciar()
            motivo = motivo_para_salir(t, entrada, sesion.fin, solo_desde, ultima_voz)
            if motivo:
                break
            dormir(1)

        _log(sesion, f"saliendo: {motivo}")
        meet.salir()
        grabador.detener()
        _pasar_pedazos(grabador, subidor, todos=True)
        subidor.hablantes(linea)
        subidor.evento("terminado", motivo=motivo, incompleta=incompleta)
        subidor.vaciar()
        return "incompleta" if incompleta else "terminada"
    finally:
        meet.cerrar()
