"""El resumen que lee el Panel Maestro: cuanto costo Jarvis y cuanto cobro.

El panel junta lo de todos los productos en una tabla de costos y margenes. De
Jarvis necesita tres numeros de un rango de fechas -lo que se cobro, lo que
costo y cuantas consultas fueron-, y aqui salen de lo mismo que ya alimenta el
tablero de Consumo y el cobro en agentia. No hay una segunda contabilidad.

Solo lee. Se entra con una clave propia (JARVIS_COSTOS_CLAVE), no con una
sesion: quien pregunta es otro servidor, no una persona. Sin la variable, la
ruta no existe.

Cada numero dice que tan firme es, con las mismas palabras que usa el panel:

  medido    lo que de verdad se desconto en agentia
  estimado  tokens por la lista de precios de consumo.py: es lo que deberia
            cobrar el proveedor, no su factura
"""

import hmac
import os
from datetime import datetime, timedelta, timezone

from . import basedatos, consumo, creditos, cuentas

CLAVE = "JARVIS_COSTOS_CLAVE"

# Un rango mas largo que esto es un error de quien llama, no una consulta.
MAXIMO_DIAS = 400


def proveedor_de(modelo: str | None) -> str:
    """A quien se le paga ese modelo, con los nombres que usa el panel.

    El panel compara lo que cada producto dice haber gastado con un proveedor
    contra lo que ese proveedor cobro de verdad. Lo que no cierra es gasto que
    nadie esta anotando.
    """
    nombre = (modelo or "").lower()
    if nombre == consumo.MODELO_PDF:
        return "pdfco"
    if nombre.startswith("gemini"):
        return "google"
    if nombre.startswith("claude"):
        return "anthropic"
    return "openai"


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


def leer_fecha(texto: str | None, por_defecto: datetime) -> datetime:
    """Una fecha ISO con o sin zona. Sin zona se toma como UTC."""
    if not texto:
        return por_defecto
    fecha = datetime.fromisoformat(texto.strip().replace("Z", "+00:00"))
    return fecha if fecha.tzinfo else fecha.replace(tzinfo=timezone.utc)


def rango(desde: str | None, hasta: str | None) -> tuple[datetime, datetime]:
    """El rango pedido, o los ultimos 30 dias. Lanza ValueError si no sirve."""
    # Las fechas se guardan al segundo: sin el segundo de mas, "hasta ahora"
    # dejaria afuera lo que se acaba de anotar.
    ahora = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(seconds=1)
    fin = leer_fecha(hasta, ahora)
    inicio = leer_fecha(desde, fin - timedelta(days=30))
    if inicio >= fin:
        raise ValueError("'desde' tiene que ser anterior a 'hasta'.")
    if fin - inicio > timedelta(days=MAXIMO_DIAS):
        raise ValueError(f"El rango no puede pasar de {MAXIMO_DIAS} dias.")
    return inicio, fin


def _hora_del_consumo(fecha: datetime) -> str:
    """'cuando' se guarda con la hora del servidor y sin zona."""
    return fecha.astimezone().replace(tzinfo=None).isoformat(timespec="seconds")


def _hora_del_envio(fecha: datetime) -> str:
    """'enviado' se guarda en UTC con su zona."""
    return fecha.astimezone(timezone.utc).isoformat(timespec="seconds")


def resumen(desde: datetime, hasta: datetime) -> dict:
    with basedatos.conexion() as con:
        usos = con.execute(
            "SELECT organizacion_id, dispositivo, modelo, COUNT(*) AS consultas, "
            "       COALESCE(SUM(costo), 0) AS costo "
            "FROM consumo "
            "WHERE cuando >= ? AND cuando < ? AND modo NOT IN ('sesion', 'apertura') "
            "GROUP BY organizacion_id, dispositivo, modelo",
            (_hora_del_consumo(desde), _hora_del_consumo(hasta)),
        ).fetchall()
        cobrado = con.execute(
            "SELECT COUNT(*) AS envios, COALESCE(SUM(monto), 0) AS monto "
            "FROM creditos_envios WHERE enviado >= ? AND enviado < ?",
            (_hora_del_envio(desde), _hora_del_envio(hasta)),
        ).fetchone()
        sin_mandar = con.execute(
            "SELECT COALESCE(SUM(monto), 0) AS monto FROM creditos_envios WHERE enviado IS NULL"
        ).fetchone()["monto"]
        sin_juntar = con.execute(
            "SELECT COALESCE(SUM(pendiente), 0) AS monto FROM creditos_pendientes"
        ).fetchone()["monto"]

    consultas = 0
    costo = costo_cobrable = devengado = 0.0
    por_origen: dict[str, dict] = {}
    por_proveedor: dict[str, float] = {}

    for uso in usos:
        organizacion = uso["organizacion_id"]
        consultas += uso["consultas"]
        costo += uso["costo"]
        proveedor = proveedor_de(uso["modelo"])
        por_proveedor[proveedor] = por_proveedor.get(proveedor, 0.0) + uso["costo"]
        # Lo mismo que decide creditos.py: se cobra lo que tiene a quien.
        if creditos.cliente_de(organizacion) is not None:
            costo_cobrable += uso["costo"]
            devengado += uso["costo"] * cuentas.markup(organizacion)

        origen = uso["dispositivo"] or "navegador"
        fila = por_origen.setdefault(origen, {
            "origen": origen,
            "nombre": consumo.ORIGENES.get(origen, origen),
            "consultas": 0, "costo": 0.0,
        })
        fila["consultas"] += uso["consultas"]
        fila["costo"] += uso["costo"]

    for fila in por_origen.values():
        fila["costo"] = round(fila["costo"], 6)

    return {
        "producto": "jarvis",
        "desde": _hora_del_envio(desde),
        "hasta": _hora_del_envio(hasta),
        "moneda": "USD",
        # Lo que salio de verdad del saldo de los clientes en agentia en ese
        # rango. Va en centavos enteros y un rato despues del uso, asi que en
        # un rango corto no coincide con lo devengado: mirar el detalle.
        "ingreso": {"valor": round(cobrado["monto"], 2), "etiqueta": "medido"},
        # Todo lo que se gasto, tambien lo de la casa, que no se le cobra a nadie.
        # por_proveedor reparte ese mismo costo entre a quienes se les paga: el
        # panel lo cruza con la factura de cada uno.
        # interno es la parte de ese costo que no se le cobra a nadie: lo que usa
        # la gente de la casa, sin organizacion a la que facturarle. El panel lo
        # saca de la fila de Jarvis, para que su margen sea el de lo que se vende.
        "costo": {
            "valor": round(costo, 6),
            "etiqueta": "estimado",
            "interno": round(costo - costo_cobrable, 6),
            "por_proveedor": {nombre: round(monto, 6) for nombre, monto in sorted(por_proveedor.items())},
        },
        "unidades": {"valor": consultas, "nombre": "consultas"},
        "detalle": {
            "cobro_activo": creditos.configurado(),
            "envios": cobrado["envios"],
            # Costo con el margen encima: lo que se termina cobrando por el uso
            # de este rango, se haya mandado ya o no.
            "devengado": round(devengado, 6),
            "costo_cobrable": round(costo_cobrable, 6),
            "costo_de_la_casa": round(costo - costo_cobrable, 6),
            # Lo que ya se debe y todavia no se desconto, de cualquier fecha:
            # envios que agentia no acepto y centavos que aun no llegan a uno.
            "pendiente_de_cobro": round(sin_mandar + sin_juntar, 6),
            "por_origen": sorted(por_origen.values(), key=lambda f: f["costo"], reverse=True),
        },
    }
