"""Puente de ventas para el panel de Reactivacion de JH.

Nueva Data JH (gemelo-kpi) solo acepta la IP de este servidor. El panel de JH
corre en otro y le pide aqui, con su propia clave, las dos consultas fijas que
necesita. Nunca manda SQL: solo una fecha.
"""

from datetime import date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from backend import fuentes, puente_reactivacion

CLAVE = "clave-del-panel-de-jh"


@pytest.fixture
def consultas(monkeypatch):
    """Simula la fuente y guarda lo que se le pidio."""
    pedidas = []

    def falsa(id_fuente, sql, limite=200, parametros=None):
        fuentes.validar_solo_lectura(sql)  # lo mismo que haria la fuente real
        pedidas.append({"fuente": id_fuente, "sql": sql, "limite": limite, "parametros": parametros})
        if "MAX(fecha) AS ultimo" in sql:
            return [{"ultimo": datetime(2026, 10, 19, 15, 9, 59)}]
        if "Marca AS marca" in sql:
            return [{"codigo": Decimal("10"), "marca": "MIGUELEZ", "monto": Decimal("900.50")}]
        return [{"codigo": Decimal("10"), "ultima": datetime(2026, 3, 1), "monto": Decimal("1000.25")}]

    monkeypatch.setattr(fuentes, "consultar", falsa)
    return pedidas


def test_ventas_corre_tres_consultas_de_solo_lectura_con_la_fecha_como_parametro(consultas):
    datos = puente_reactivacion.ventas(date(2024, 11, 17))
    assert len(consultas) == 3
    assert all(c["fuente"] == puente_reactivacion.FUENTE_POR_DEFECTO for c in consultas)
    con_fecha = [c for c in consultas if c["parametros"]]
    assert len(con_fecha) == 2
    assert all(c["parametros"] == {"desde": "2024-11-17"} for c in con_fecha)
    assert all("2024-11-17" not in c["sql"] for c in consultas), "la fecha va como parametro, no pegada al SQL"
    assert datos["filas"] == [{"codigo": Decimal("10"), "ultima": datetime(2026, 3, 1), "monto": Decimal("1000.25")}]
    assert datos["marcas"][0]["marca"] == "MIGUELEZ"
    assert datos["ultimoDato"] == datetime(2026, 10, 19, 15, 9, 59)


def test_la_fuente_se_puede_cambiar_por_variable(consultas, monkeypatch):
    monkeypatch.setenv("JARVIS_REACTIVACION_FUENTE", "otra")
    puente_reactivacion.ventas(date(2024, 11, 17))
    assert {c["fuente"] for c in consultas} == {"otra"}


def test_desde_valido():
    hoy = date(2026, 11, 17)
    assert puente_reactivacion.desde_de("2024-11-17", hoy) == date(2024, 11, 17)
    assert puente_reactivacion.desde_de(None, hoy) == date(2024, 11, 17)
    for malo in ("ayer", "2026-13-01", "2027-01-01", "2020-01-01"):
        with pytest.raises(ValueError):
            puente_reactivacion.desde_de(malo, hoy)


# --------------------------------------------------------------------------
# La ruta
# --------------------------------------------------------------------------

RUTA = "/api/puente/reactivacion/ventas"


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-contrasena-del-admin")
    from backend.main import app

    with TestClient(app) as cliente:
        yield cliente


def test_sin_la_variable_la_ruta_no_existe(cliente):
    assert cliente.get(RUTA).status_code == 404


def test_sin_clave_o_con_otra_no_entra(cliente, monkeypatch, consultas):
    monkeypatch.setenv("JARVIS_REACTIVACION_CLAVE", CLAVE)
    assert cliente.get(RUTA).status_code == 401
    assert cliente.get(RUTA, headers={"Authorization": "Bearer otra"}).status_code == 401
    assert cliente.get(RUTA, headers={"Authorization": "Bearer la-contrasena-del-admin"}).status_code == 401
    assert consultas == [], "sin clave no se toca la base"


def test_con_la_clave_devuelve_las_ventas(cliente, monkeypatch, consultas):
    monkeypatch.setenv("JARVIS_REACTIVACION_CLAVE", CLAVE)
    respuesta = cliente.get(f"{RUTA}?desde=2024-11-17", headers={"Authorization": f"Bearer {CLAVE}"})
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["ultimoDato"].startswith("2026-10-19T15:09:59")
    assert cuerpo["filas"][0]["monto"] == 1000.25
    assert cuerpo["marcas"][0] == {"codigo": 10.0, "marca": "MIGUELEZ", "monto": 900.5}


def test_fecha_mala_es_400(cliente, monkeypatch, consultas):
    monkeypatch.setenv("JARVIS_REACTIVACION_CLAVE", CLAVE)
    respuesta = cliente.get(f"{RUTA}?desde=ayer", headers={"Authorization": f"Bearer {CLAVE}"})
    assert respuesta.status_code == 400
    assert consultas == []


def test_si_la_base_falla_es_502_sin_detalles_internos(cliente, monkeypatch):
    monkeypatch.setenv("JARVIS_REACTIVACION_CLAVE", CLAVE)

    def caida(*_a, **_k):
        raise RuntimeError("Adaptive Server connection failed (gemelo-kpi:5033) usuario LMNeboUsrIA")

    monkeypatch.setattr(fuentes, "consultar", caida)
    respuesta = cliente.get(RUTA, headers={"Authorization": f"Bearer {CLAVE}"})
    assert respuesta.status_code == 502
    assert "LMNeboUsrIA" not in respuesta.text
