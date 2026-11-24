"""Cuándo sale el bot de la reunión. Función pura, sin reloj propio."""
from datetime import timedelta

SOLO_MAX = timedelta(minutes=2)
SILENCIO_MAX = timedelta(minutes=15)
TOPE = timedelta(hours=3)


def motivo_para_salir(ahora, entrada, fin_evento, solo_desde, ultima_voz):
    """Devuelve "tope", "solo", "silencio" o None (seguir)."""
    if ahora - entrada >= TOPE:
        return "tope"
    if solo_desde is not None and ahora - solo_desde >= SOLO_MAX:
        return "solo"
    if ahora >= fin_evento:
        referencia = max(fin_evento, ultima_voz) if ultima_voz else fin_evento
        if ahora - referencia >= SILENCIO_MAX:
            return "silencio"
    return None
