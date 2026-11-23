"""Acciones de Jarvis dentro de los paneles de JH (lo que cambia algo, no solo lee).

Van en dos pasos, como los cambios de calendario: `preparar` revisa que se pueda
y dice que se va a hacer; `confirmar` lo hace solo despues de que la persona dijo
que si. Cada accion llama a la MISMA ruta que usa el boton del panel, con el token
de quien habla: el permiso (ej. reactivacion.llamar) lo sigue poniendo el panel.
"""

import json
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import quote

import httpx

from . import paneles_jh

VIGENCIA = 600   # una confirmacion vale 10 minutos

# panel -> accion -> como prepararla y hacerla
ACCIONES: dict[str, dict] = {
    "reactivacion": {
        "llamar": {
            "descripcion": "pone clientes en la cola para que Camila los llame (igual que el boton Llamar "
                           "del panel). parametros: codigos (lista de codigos de cliente, salen de la consulta "
                           "clientes)",
        },
    },
}


class ErrorAccion(Exception):
    pass


@dataclass
class Pendiente:
    panel: str
    accion: str
    datos: dict
    resumen: str
    creado: float = field(default_factory=time.time)


_pendientes: dict[str, Pendiente] = {}
_candado = threading.Lock()


def instruccion(panel: str) -> str:
    """Lo que se suma a la instruccion del panel si tiene acciones."""
    acciones = ACCIONES.get(panel)
    if not acciones:
        return ""
    lineas = [f"- {nombre}: {a['descripcion']}" for nombre, a in acciones.items()]
    return ("\nAcciones que puedes hacer en este panel (preparar_accion_panel y, SOLO despues de que la "
            "persona diga que si, confirmar_accion_panel):\n" + "\n".join(lineas)
            + "\nSi te piden llamar a un cliente, no digas que no puedes: busca su codigo con la consulta "
              "clientes y prepara la accion llamar.")


def _actual(usuario_id: str) -> dict:
    actual = paneles_jh.activo(usuario_id)
    if not actual:
        raise ErrorAccion("Esto solo funciona cuando te hablan desde un panel de JH.")
    return actual


def _pedir(actual: dict, metodo: str, ruta: str, cuerpo: dict | None = None) -> httpx.Response:
    url = paneles_jh.portal() + paneles_jh.PANELES[actual["panel"]]["prefijo"] + ruta
    try:
        return _http_pedir(metodo, url, cuerpo, actual["token"])
    except httpx.HTTPError as error:
        raise ErrorAccion(f"No pude hablar con el panel: {error}") from error


def _http_pedir(metodo: str, url: str, cuerpo, token: str) -> httpx.Response:
    return paneles_jh._http().request(metodo, url, json=cuerpo, headers={"Authorization": f"Bearer {token}"})


def _codigos(datos: dict) -> list[str]:
    crudo = datos.get("codigos", datos.get("codigo"))
    if isinstance(crudo, (str, int)):
        crudo = [crudo]
    codigos = [str(c).strip() for c in (crudo or []) if str(c).strip()]
    if not codigos:
        raise ErrorAccion("Falta el codigo del cliente: buscalo primero con la consulta clientes.")
    if len(codigos) > 20:
        raise ErrorAccion("Desde Jarvis se pueden poner hasta 20 clientes a la vez; para mas, usa el panel.")
    return list(dict.fromkeys(codigos))


def preparar(usuario_id: str, accion: str, parametros: str = "{}") -> str:
    actual = _actual(usuario_id)
    panel = actual["panel"]
    if accion not in ACCIONES.get(panel, {}):
        disponibles = ", ".join(ACCIONES.get(panel, {})) or "ninguna"
        raise ErrorAccion(f"La accion «{accion}» no existe en este panel. Disponibles: {disponibles}.")
    try:
        datos = json.loads(parametros or "{}")
        if not isinstance(datos, dict):
            raise ValueError
    except ValueError as error:
        raise ErrorAccion("Los parametros tienen que ser un objeto JSON, ej. {\"codigos\": [\"1234\"]}.") from error

    # reactivacion / llamar: cada cliente tiene que existir y poder llamarse.
    codigos = _codigos(datos)
    nombres, problemas = [], []
    for codigo in codigos:
        r = _pedir(actual, "GET", "/api/jarvis/clientes/" + quote(codigo, safe=""))
        if r.status_code in (401, 403):
            raise ErrorAccion("No tienes permiso para ver eso en el panel (o tu sesion del panel vencio).")
        if r.status_code == 404:
            problemas.append(f"{codigo}: no existe")
            continue
        if r.status_code >= 400:
            raise ErrorAccion(f"El panel respondio con un error ({r.status_code}).")
        cliente = (r.json() or {}).get("cliente") or {}
        nombre = cliente.get("nombre") or codigo
        if cliente.get("estado") in ("recuperado", "suspendido", "telefono_invalido"):
            problemas.append(f"{nombre}: esta {cliente['estado'].replace('_', ' ')}, no se llama")
        elif not cliente.get("telefonos"):
            problemas.append(f"{nombre}: no tiene telefono")
        else:
            nombres.append((codigo, nombre))
    if not nombres:
        raise ErrorAccion("No hay a quien llamar. " + "; ".join(problemas))

    resumen = ", ".join(n for _, n in nombres)
    with _candado:
        _pendientes[usuario_id] = Pendiente(panel, accion, {"codigos": [c for c, _ in nombres]}, resumen)
    aviso = f" No se incluyen: {'; '.join(problemas)}." if problemas else ""
    return (f"Listo para poner en la cola de Camila a: {resumen}. Camila llamara en cuanto le toque, dentro "
            f"del horario de llamadas.{aviso} Preguntale a la persona y llama a confirmar_accion_panel SOLO "
            "si dice que si.")


def confirmar(usuario_id: str) -> str:
    with _candado:
        pendiente = _pendientes.pop(usuario_id, None)   # un "si" repetido no hace nada dos veces
    if pendiente is None or time.time() - pendiente.creado > VIGENCIA:
        raise ErrorAccion("No hay ninguna accion pendiente (o pasaron mas de 10 minutos). Preparala de nuevo.")
    actual = _actual(usuario_id)
    if actual["panel"] != pendiente.panel:
        raise ErrorAccion("La accion era de otro panel. Preparala de nuevo desde este.")

    r = _pedir(actual, "POST", "/api/encolar", pendiente.datos)
    if r.status_code in (401, 403):
        raise ErrorAccion("El panel no te deja hacerlo: hace falta el permiso para mandar a llamar.")
    if r.status_code >= 400:
        raise ErrorAccion(f"El panel no lo acepto ({r.status_code}): {r.text[:200]}")
    res = r.json() if r.content else {}
    encolados, saltados = int(res.get("encolados") or 0), int(res.get("saltados") or 0)
    if not encolados:
        return f"El panel no puso a nadie en cola ({saltados} no se podian llamar)."
    extra = f" {saltados} no se pudieron poner." if saltados else ""
    print(f"[panel] {pendiente.panel}/{pendiente.accion} {pendiente.datos} -> {encolados} en cola")
    return f"Listo: {pendiente.resumen} en la cola de Camila ({encolados}).{extra}"
