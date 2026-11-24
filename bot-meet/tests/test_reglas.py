from datetime import datetime, timedelta, timezone

from bot_meet.reglas import motivo_para_salir

E = datetime(2026, 12, 1, 14, 0, tzinfo=timezone.utc)  # entró
FIN = E + timedelta(hours=1)
m = timedelta(minutes=1)


def test_sigue_en_reunion_normal():
    assert motivo_para_salir(E + 30 * m, E, FIN, None, E + 29 * m) is None


def test_sale_si_queda_solo_dos_minutos():
    assert motivo_para_salir(E + 10 * m, E, FIN, E + 9 * m, None) is None
    assert motivo_para_salir(E + 11 * m, E, FIN, E + 9 * m, None) == "solo"


def test_despues_del_fin_espera_15_min_de_silencio():
    assert motivo_para_salir(FIN + 10 * m, E, FIN, None, FIN + 5 * m) is None
    assert motivo_para_salir(FIN + 20 * m, E, FIN, None, FIN + 5 * m) == "silencio"


def test_silencio_desde_antes_del_fin_cuenta_desde_el_fin():
    assert motivo_para_salir(FIN + 14 * m, E, FIN, None, E + 30 * m) is None
    assert motivo_para_salir(FIN + 15 * m, E, FIN, None, E + 30 * m) == "silencio"


def test_sin_voz_detectada_sale_15_min_despues_del_fin():
    assert motivo_para_salir(FIN + 15 * m, E, FIN, None, None) == "silencio"


def test_tope_de_tres_horas():
    assert motivo_para_salir(E + 180 * m, E, E + 240 * m, None, E + 179 * m) == "tope"
