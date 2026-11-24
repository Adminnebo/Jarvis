"""Configuración del bot, toda desde variables de entorno."""
import os
from dataclasses import dataclass
from pathlib import Path

# Selector que usa la página de Meet simulada. El de la página real se calibra
# con una reunión de verdad (plan, tarea 14) y va en BOT_MEET_SEL_HABLANDO.
SEL_HABLANDO_SIMULADO = '[data-hablando="1"]'


@dataclass(frozen=True)
class Config:
    secreto: str
    datos: Path
    max_sesiones: int = 2
    pedazo_s: int = 300
    headless: bool = True
    espera_admision_s: int = 600
    sel_hablando: str = SEL_HABLANDO_SIMULADO
    volcar_dom: bool = False
    calibrar_s: int = 0


def leer_config(entorno=None) -> Config:
    e = os.environ if entorno is None else entorno
    secreto = e.get("BOT_MEET_SECRETO", "")
    if len(secreto) < 32:
        raise ValueError("BOT_MEET_SECRETO falta o tiene menos de 32 caracteres")
    return Config(
        secreto=secreto,
        datos=Path(e.get("BOT_MEET_DATOS", "/data")),
        max_sesiones=int(e.get("BOT_MEET_MAX_SESIONES", "2")),
        pedazo_s=int(e.get("BOT_MEET_PEDAZO_S", "300")),
        headless=e.get("BOT_MEET_HEADLESS", "1") != "0",
        espera_admision_s=int(e.get("BOT_MEET_ESPERA_ADMISION_S", "600")),
        sel_hablando=e.get("BOT_MEET_SEL_HABLANDO", SEL_HABLANDO_SIMULADO),
        volcar_dom=e.get("BOT_MEET_VOLCAR_DOM", "0") == "1",
        calibrar_s=int(e.get("BOT_MEET_CALIBRAR_S", "0")),
    )
