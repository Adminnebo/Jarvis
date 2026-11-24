"""Una reunión de punta a punta: entrar, grabar, seguir, salir, subir."""
import time
from datetime import datetime, timezone

from .reglas import motivo_para_salir

AVISO = "Jarvis está grabando esta reunión para tomar notas."
VOLCAR_CADA_S = 10


def _pasar_pedazos(grabador, subidor, todos=False):
    for n, ruta in grabador.pedazos_listos(todos=todos):
        subidor.audio(n, ruta)


def ejecutar_sesion(sesion, meet, grabador, subidor, debe_parar,
                    ahora=lambda: datetime.now(timezone.utc), dormir=time.sleep,
                    espera_admision_s=600, volcar_dom=False) -> str:
    """Devuelve "terminada", "incompleta", "rechazada" o "fallida"."""
    try:
        subidor.evento("esperando")
        subidor.vaciar()
        r = meet.unirse(sesion.meet_url, espera_admision_s)
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
        meet.solo_audio()
        meet.escribir_chat(AVISO)

        entrada = ahora()
        linea, ultima_voz, solo_desde = [], None, None
        reintento_usado, incompleta, motivo = False, False, None
        ultimo_volcado = 0.0
        grabador.iniciar()
        while True:
            if debe_parar():
                motivo = "cancelada"
                break
            estado = meet.leer_estado()
            t = ahora()
            if not estado.en_llamada:
                grabador.detener()
                _pasar_pedazos(grabador, subidor, todos=True)
                if not reintento_usado:
                    reintento_usado = True
                    if meet.unirse(sesion.meet_url, espera_admision_s).estado == "admitido":
                        grabador.iniciar()
                        dormir(1)
                        continue
                incompleta, motivo = True, "caida"
                break
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

        meet.salir()
        grabador.detener()
        _pasar_pedazos(grabador, subidor, todos=True)
        subidor.hablantes(linea)
        subidor.evento("terminado", motivo=motivo, incompleta=incompleta)
        subidor.vaciar()
        return "incompleta" if incompleta else "terminada"
    finally:
        meet.cerrar()
