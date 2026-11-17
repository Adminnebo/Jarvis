"""Puente de ventas para el panel de Reactivacion de JH (portaljh /reactivacion/).

Nueva Data JH (gemelo-kpi) solo acepta conexiones de este servidor. El panel
corre en server2 y le pide aqui las ventas por cliente. Entra con su propia
clave (JARVIS_REACTIVACION_CLAVE) en Authorization: Bearer; sin la variable la
ruta responde como si no existiera.

Solo corre estas consultas fijas, de solo lectura, sobre la fuente
JARVIS_REACTIVACION_FUENTE (por defecto "Nueva Data JH"). Quien llama manda una
fecha, nunca SQL. Las credenciales de la base se quedan aqui.
"""

import hmac
import os
from datetime import date, timedelta

from . import fuentes

CLAVE = "JARVIS_REACTIVACION_CLAVE"
FUENTE = "JARVIS_REACTIVACION_FUENTE"
FUENTE_POR_DEFECTO = "89e5caf5"  # Nueva Data JH (gemelo-kpi, base sim)

# Mas filas que esto seria un error: hoy son ~3.000 clientes y ~40.000 marcas.
LIMITE = 200_000
# El panel pide 24 meses; un poco de margen, pero no la historia entera.
MAXIMO_DIAS = 1_100

_VENTAS = """
SELECT cliente, fecha, SubTotalItem, Marca FROM List_OrdenVentasIA WHERE fecha >= %(desde)s
UNION ALL
SELECT cliente, fecha, SubTotalItem, Marca FROM List_PreFacturasContadoIA
 WHERE fecha >= %(desde)s AND procesado = 1
"""

SQL_POR_CLIENTE = f"""
SELECT cliente AS codigo, MAX(fecha) AS ultima, SUM(SubTotalItem) AS monto
  FROM ({_VENTAS}) v GROUP BY cliente
"""

SQL_POR_MARCA = f"""
SELECT cliente AS codigo, Marca AS marca, SUM(SubTotalItem) AS monto
  FROM ({_VENTAS}) v WHERE ISNULL(Marca, '') <> '' GROUP BY cliente, Marca
"""

SQL_ULTIMO_DATO = "SELECT MAX(fecha) AS ultimo FROM List_OrdenVentasIA"


def clave() -> str:
    return os.getenv(CLAVE, "").strip()


def configurado() -> bool:
    return bool(clave())


def clave_valida(recibida: str | None) -> bool:
    """Compara en tiempo constante: la clave no se adivina midiendo demoras."""
    esperada = clave()
    if not esperada or not recibida:
        return False
    return hmac.compare_digest(esperada.encode(), recibida.strip().encode())


def fuente() -> str:
    return os.getenv(FUENTE, "").strip() or FUENTE_POR_DEFECTO


def desde_de(texto: str | None, hoy: date | None = None) -> date:
    """La fecha desde la que se cuentan ventas. Sin fecha: 24 meses atras."""
    hoy = hoy or date.today()
    if not texto:
        return hoy.replace(year=hoy.year - 2)
    try:
        desde = date.fromisoformat(texto)
    except ValueError:
        raise ValueError("La fecha 'desde' tiene que ser AAAA-MM-DD.") from None
    if desde > hoy:
        raise ValueError("La fecha 'desde' no puede ser futura.")
    if hoy - desde > timedelta(days=MAXIMO_DIAS):
        raise ValueError(f"La fecha 'desde' no puede ser de hace mas de {MAXIMO_DIAS} dias.")
    return desde


def ventas(desde: date) -> dict:
    """Ultima compra y monto por cliente, monto por cliente y marca, y el ultimo dato de la base."""
    id_fuente = fuente()
    parametros = {"desde": desde.isoformat()}
    filas = fuentes.consultar(id_fuente, SQL_POR_CLIENTE, LIMITE, parametros=parametros)
    marcas = fuentes.consultar(id_fuente, SQL_POR_MARCA, LIMITE, parametros=parametros)
    ultimo = fuentes.consultar(id_fuente, SQL_ULTIMO_DATO, 1)
    return {"ultimoDato": ultimo[0]["ultimo"] if ultimo else None, "filas": filas, "marcas": marcas}
