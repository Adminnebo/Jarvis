"""Descontar del saldo de cada organizacion en agentia lo que consume en Jarvis.

POST /api/credits/adjust redondea el monto a centavos. Una respuesta de Jarvis
cuesta decimas de centavo, asi que mandar cada una por separado descontaria
$0.00 cada vez. Lo cobrado se acumula por persona y se manda en centavos
enteros; lo que no llega a un centavo espera al proximo envio.

Cada envio se anota antes de mandarlo, con una referencia unica. agentia no
aplica dos veces la misma referencia, asi que reintentar -despues de una red
caida o un reinicio a mitad de camino- nunca cobra doble.

Se cobra desde que se configura, no hacia atras: la primera vez se marca el
consumo que ya habia como visto.
"""

import math
import os
import threading
import time
import uuid
from datetime import datetime, timezone

import httpx

from . import basedatos

URL = "JARVIS_CREDITOS_URL"
CALLER = "JARVIS_CREDITOS_CALLER_ID"
LLAVE = "JARVIS_CREDITOS_API_KEY"
PREFIJO_CLIENTE = "JARVIS_CREDITOS_CLIENTE_"
CADA = "JARVIS_CREDITOS_CADA_MINUTOS"

CONCEPTO = "Jarvis"


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _entero(valor: str | None) -> int | None:
    try:
        numero = int((valor or "").strip())
    except ValueError:
        return None
    return numero if numero > 0 else None


def configurado() -> bool:
    return bool(
        os.getenv(URL, "").strip()
        and _entero(os.getenv(CALLER))
        and os.getenv(LLAVE, "").strip()
    )


def cliente_de(organizacion_id: str | None) -> int | None:
    """El clientId de agentia de esa organizacion, o None si no se le cobra.

    JARVIS_CREDITOS_CLIENTE_<id>, igual que el margen. El sufijo se compara
    sin mayusculas: Windows las pone todas.
    """
    if not organizacion_id:
        return None
    for variable, valor in os.environ.items():
        if variable.startswith(PREFIJO_CLIENTE) and \
                variable[len(PREFIJO_CLIENTE):].lower() == organizacion_id:
            return _entero(valor)
    return None


def minutos() -> int:
    return _entero(os.getenv(CADA)) or 5


# --------------------------------------------------------------------------
# Un ciclo: mirar el consumo nuevo, juntar centavos, mandar
# --------------------------------------------------------------------------

def ciclo() -> dict:
    """Lo que hace el hilo de fondo cada tantos minutos. Devuelve un resumen."""
    if not configurado():
        return {"apagado": True}
    _acumular()
    _preparar_envios()
    return _mandar_pendientes()


def _acumular() -> None:
    from . import cuentas

    with basedatos.conexion() as con:
        visto = con.execute(
            "SELECT valor FROM creditos_estado WHERE clave = 'ultimo_consumo'"
        ).fetchone()
        maximo = con.execute("SELECT COALESCE(MAX(id), 0) AS m FROM consumo").fetchone()["m"]

        if visto is None:
            # Primera vez: lo que ya estaba no se cobra. Recien desde ahora.
            con.execute(
                "INSERT INTO creditos_estado (clave, valor) VALUES ('ultimo_consumo', ?)",
                (str(maximo),),
            )
            return

        filas = con.execute(
            "SELECT organizacion_id, usuario_id, costo FROM consumo "
            "WHERE id > ? AND id <= ? AND modo != 'sesion'",
            (int(visto["valor"]), maximo),
        ).fetchall()

        for fila in filas:
            organizacion = fila["organizacion_id"]
            # Sin clientId no hay a quien descontarle: ni la gente de la casa
            # ni una organizacion que todavia no se configuro.
            if cliente_de(organizacion) is None:
                continue
            con.execute(
                "INSERT INTO creditos_pendientes (organizacion_id, usuario_id, pendiente) "
                "VALUES (?, ?, ?) ON CONFLICT (organizacion_id, usuario_id) "
                "DO UPDATE SET pendiente = pendiente + excluded.pendiente",
                (organizacion, fila["usuario_id"] or "", fila["costo"] * cuentas.markup(organizacion)),
            )

        con.execute(
            "UPDATE creditos_estado SET valor = ? WHERE clave = 'ultimo_consumo'", (str(maximo),)
        )


def _preparar_envios() -> None:
    from . import cuentas

    with basedatos.conexion() as con:
        listos = con.execute(
            "SELECT organizacion_id, usuario_id, pendiente FROM creditos_pendientes "
            "WHERE pendiente >= 0.01"
        ).fetchall()
    if not listos:
        return

    # Fuera de la transaccion: los nombres de los paneles se piden a Supabase,
    # y esperar la red con la base tomada frenaria el registro del consumo.
    nombres = cuentas.nombres_de_usuarios(fila["usuario_id"] or None for fila in listos)

    with basedatos.conexion() as con:
        for fila in listos:
            cliente = cliente_de(fila["organizacion_id"])
            if cliente is None:
                continue
            # Solo centavos enteros: agentia redondea, y lo que sobra espera.
            monto = math.floor(fila["pendiente"] * 100 + 1e-9) / 100
            con.execute(
                "INSERT INTO creditos_envios "
                "(referencia, cliente_id, organizacion_id, usuario_id, monto, nota, creado) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    f"jarvis-{uuid.uuid4().hex}", cliente, fila["organizacion_id"],
                    fila["usuario_id"], monto,
                    nombres.get(fila["usuario_id"] or None, fila["usuario_id"]), _ahora(),
                ),
            )
            con.execute(
                "UPDATE creditos_pendientes SET pendiente = pendiente - ? "
                "WHERE organizacion_id = ? AND usuario_id = ?",
                (monto, fila["organizacion_id"], fila["usuario_id"]),
            )


def _mandar_pendientes() -> dict:
    with basedatos.conexion() as con:
        envios = con.execute(
            "SELECT * FROM creditos_envios WHERE enviado IS NULL ORDER BY creado"
        ).fetchall()

    enviados = fallidos = 0
    for envio in envios:
        error = _mandar(envio)
        with basedatos.conexion() as con:
            if error is None:
                con.execute(
                    "UPDATE creditos_envios SET enviado = ?, ultimo_error = NULL "
                    "WHERE referencia = ?",
                    (_ahora(), envio["referencia"]),
                )
                enviados += 1
            else:
                # Queda pendiente: el proximo ciclo lo reintenta con la misma
                # referencia, y agentia no lo cobra dos veces.
                con.execute(
                    "UPDATE creditos_envios SET ultimo_error = ? WHERE referencia = ?",
                    (error, envio["referencia"]),
                )
                fallidos += 1

    if fallidos:
        print(f"  Cobro en agentia: {fallidos} envio(s) sin mandar, se reintentan.")
    return {"enviados": enviados, "fallidos": fallidos}


def _mandar(envio) -> str | None:
    """None si agentia lo aplico; si no, el motivo, sin la API key."""
    try:
        respuesta = httpx.post(
            os.getenv(URL, "").strip(),
            json={
                "callerId": _entero(os.getenv(CALLER)),
                "apiKey": os.getenv(LLAVE, "").strip(),
                "clientId": envio["cliente_id"],
                "amount": envio["monto"],
                "operation": "subtract",
                "concept": CONCEPTO,
                "note": envio["nota"],
                "reference": envio["referencia"],
            },
            timeout=15,
        )
    except Exception as fallo:  # noqa: BLE001 - la red caida se reintenta
        return f"red: {type(fallo).__name__}"

    # 201 es aplicado; 200 con duplicate, que ya se habia aplicado antes.
    if respuesta.status_code in (200, 201):
        try:
            if respuesta.json().get("success"):
                return None
        except ValueError:
            pass
    # Va a la base y al tablero: la key no, aunque agentia la repitiera.
    detalle = respuesta.text[:200].replace(os.getenv(LLAVE, "").strip() or "\0", "<API_KEY>")
    return f"{respuesta.status_code}: {detalle}"


def resumen() -> dict:
    """Para el tablero: si esto esta andando o se esta acumulando sin salir."""
    with basedatos.conexion() as con:
        fila = con.execute(
            "SELECT "
            "  COUNT(*) FILTER (WHERE enviado IS NOT NULL) AS enviados, "
            "  COALESCE(SUM(monto) FILTER (WHERE enviado IS NOT NULL), 0) AS cobrado, "
            "  COUNT(*) FILTER (WHERE enviado IS NULL) AS pendientes "
            "FROM creditos_envios"
        ).fetchone()
        error = con.execute(
            "SELECT ultimo_error FROM creditos_envios "
            "WHERE enviado IS NULL AND ultimo_error IS NOT NULL "
            "ORDER BY creado DESC LIMIT 1"
        ).fetchone()
    return {
        "activo": configurado(),
        "enviados": fila["enviados"],
        "cobrado": round(fila["cobrado"], 2),
        "pendientes": fila["pendientes"],
        "ultimo_error": error["ultimo_error"] if error else None,
    }


# --------------------------------------------------------------------------
# El hilo de fondo
# --------------------------------------------------------------------------

def avisar_de_la_configuracion() -> None:
    """Todo lo que haria no cobrar sin que nadie se entere, dicho al arrancar.

    Un error de tipeo en el id de una organizacion, o una variable de las tres
    que falta, no rompe nada: simplemente no se cobra. Por eso se dice.
    """
    puestas = [v for v in (URL, CALLER, LLAVE) if os.getenv(v, "").strip()]
    if not configurado():
        if puestas:
            faltan = [v for v in (URL, CALLER, LLAVE) if v not in puestas or
                      (v == CALLER and not _entero(os.getenv(CALLER)))]
            print(f"  AVISO: el cobro en agentia esta apagado: falta {', '.join(faltan)}.")
        return

    with basedatos.conexion() as con:
        existentes = {fila["id"] for fila in con.execute("SELECT id FROM organizaciones")}

    alguna = False
    for variable, valor in sorted(os.environ.items()):
        if not variable.startswith(PREFIJO_CLIENTE):
            continue
        if _entero(valor) is None:
            print(f"  AVISO: se ignora {variable}={valor!r}: tiene que ser el clientId "
                  "de agentia, un numero.")
        elif variable[len(PREFIJO_CLIENTE):].lower() not in existentes:
            print(f"  AVISO: {variable} no corresponde a ninguna organizacion: no se "
                  "cobra. El id sale en el tablero de Consumo.")
        else:
            alguna = True

    if not alguna:
        print("  AVISO: el cobro en agentia esta encendido pero ninguna organizacion "
              "tiene JARVIS_CREDITOS_CLIENTE_<id>: no se cobra nada.")


def arrancar() -> None:
    """Se llama al arrancar. Sin configuracion no hace nada, pero lo avisa."""
    avisar_de_la_configuracion()
    if not configurado():
        return

    print(f"  Cobro en agentia: encendido, cada {minutos()} minuto(s).")

    def vigilar():
        while True:
            try:
                ciclo()
            except Exception as fallo:  # noqa: BLE001 - un ciclo roto no para los demas
                print(f"  Cobro en agentia: fallo un ciclo ({type(fallo).__name__}).")
            time.sleep(minutos() * 60)

    threading.Thread(target=vigilar, name="creditos", daemon=True).start()
