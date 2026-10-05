"""Donde quedo la conversacion, para que una sesion de voz no arranque en blanco.

Cada sesion de voz es nueva para el modelo: no sabe que se hablo en la anterior
ni que hay una cotizacion a medio hacer. Con los lentes eso se nota mucho,
porque el enlace se cae y se reabre varias veces en la misma conversacion: a
los cuarenta segundos de reconectar, "enviame la cotizacion del casco" acababa
en una busqueda en las facturas de JH, porque del borrador que el mismo Jarvis
habia armado no quedaba rastro.

Aqui se junta lo que hace falta para retomar: lo que quedo pendiente (un
borrador sin emitir, un envio de WhatsApp sin confirmar, la ultima cotizacion
emitida) y los ultimos turnos hablados, vengan del aparato que vengan. Sale
como un bloque al final de las instrucciones de la sesion de voz.

Los turnos viven en memoria: son contexto de la ultima media hora, no un
historial. Si el servidor se reinicia se pierden, y lo pendiente tambien.
"""

import re
import threading
import time
from collections import deque

# Lo que paso hace mas que esto ya no es "donde quedaron".
VENTANA_TURNOS = 30 * 60
VIGENCIA_EMITIDA = 2 * 60 * 60

MAX_TURNOS = 8
MAX_TEXTO = 220
MAX_GUARDADOS = 24

# Un "ok" o un "aja" sueltos no dicen de que se hablaba, y un fragmento que el
# transcriptor saco en otro alfabeto, menos.
MIN_PALABRAS_USUARIO = 3
_LETRAS_LATINAS = re.compile(r"[a-zA-ZáéíóúüñÁÉÍÓÚÜÑ]")
_OTRO_ALFABETO = re.compile(r"[^\x00-ɏ‐-›€]")

APARATOS = {
    "navegador": "la web", "web": "la web", "lentes": "los lentes",
    "telefono": "el telefono", "reloj": "el reloj", "texto": "el chat",
}

_turnos: dict[str, deque] = {}
_emitidas: dict[str, dict] = {}
_candado = threading.Lock()


def _quien(valor: str) -> str | None:
    valor = (valor or "").strip().lower()
    if valor in ("tu", "usuario", "user"):
        return "usuario"
    if valor in ("jarvis", "assistant"):
        return "jarvis"
    return None


def anotar_turno(id_usuario: str | None, quien: str, texto: str,
                 aparato: str = "", cuando: float | None = None) -> None:
    """Un turno hablado o escrito, de cualquier aparato."""
    quien = _quien(quien)
    texto = " ".join((texto or "").split())
    if not id_usuario or quien is None or not texto:
        return
    with _candado:
        cola = _turnos.setdefault(id_usuario, deque(maxlen=MAX_GUARDADOS))
        cola.append({
            "quien": quien, "texto": texto, "aparato": (aparato or "").strip().lower(),
            "cuando": time.time() if cuando is None else cuando,
        })


def anotar_emision(id_usuario: str | None, numero: str, cliente: str, total: float) -> None:
    """La ultima cotizacion que emitio esa persona."""
    if not id_usuario:
        return
    with _candado:
        _emitidas[id_usuario] = {
            "numero": numero, "cliente": cliente, "total": total, "cuando": time.time(),
        }


def olvidar(id_usuario: str | None = None) -> None:
    """Al reiniciar la conversacion. Sin usuario, todo: lo usan las pruebas."""
    with _candado:
        if id_usuario is None:
            _turnos.clear()
            _emitidas.clear()
        else:
            _turnos.pop(id_usuario, None)
            _emitidas.pop(id_usuario, None)


def _hace(segundos: float) -> str:
    minutos = int(segundos // 60)
    if minutos < 1:
        return "hace menos de un minuto"
    if minutos == 1:
        return "hace un minuto"
    if minutos < 60:
        return f"hace {minutos} minutos"
    horas = minutos // 60
    return "hace una hora" if horas == 1 else f"hace {horas} horas"


def _sirve(turno: dict) -> bool:
    texto = turno["texto"]
    if _OTRO_ALFABETO.search(texto) or not _LETRAS_LATINAS.search(texto):
        return False
    if turno["quien"] == "usuario" and len(texto.split()) < MIN_PALABRAS_USUARIO:
        return False
    return True


def _recortado(texto: str) -> str:
    return texto if len(texto) <= MAX_TEXTO else texto[:MAX_TEXTO].rstrip() + "..."


def _turnos_recientes(id_usuario: str, ahora: float) -> list[dict]:
    with _candado:
        guardados = list(_turnos.get(id_usuario, ()))
    recientes = [
        t for t in guardados
        if ahora - t["cuando"] <= VENTANA_TURNOS and _sirve(t)
    ]
    return recientes[-MAX_TURNOS:]


def _pendientes(id_usuario: str, ahora: float) -> list[str]:
    from . import cotizaciones, whatsapp

    lineas = []

    borrador = cotizaciones.borrador_de(id_usuario)
    if borrador is not None:
        productos = "; ".join(
            f"{linea['cantidad']:g} {linea['unidad'] or 'UND'} de {linea['descripcion']}"
            for linea in borrador.lineas[:6]
        )
        if len(borrador.lineas) > 6:
            productos += f"; y {len(borrador.lineas) - 6} mas"
        lineas.append(
            f"- Hay un borrador de cotizacion SIN emitir, armado {_hace(ahora - borrador.creado)}: "
            f"cliente {borrador.cliente['nombre']}, {productos}, total RD$ "
            f"{borrador.totales['total']:,.2f}. Si piden emitirla, enviarla o "
            "cambiarla, es esta: no la busques en otra parte."
        )

    with _candado:
        emitida = _emitidas.get(id_usuario)
    if emitida and ahora - emitida["cuando"] <= VIGENCIA_EMITIDA:
        lineas.append(
            f"- La ultima cotizacion emitida fue la {emitida['numero']}, "
            f"{_hace(ahora - emitida['cuando'])}: cliente {emitida['cliente']}, total RD$ "
            f"{emitida['total']:,.2f}. Si piden \"la cotizacion\" sin decir cual, es esta."
        )

    envio = whatsapp.pendiente_de(id_usuario)
    if envio is not None:
        lineas.append(
            f"- Hay un envio de WhatsApp preparado y SIN confirmar, a "
            f"{whatsapp.legible(envio.numero)}, con {len(envio.archivos)} archivo(s)."
        )

    return lineas


def para_prompt(usuario, ahora: float | None = None) -> str:
    """El bloque que se agrega a las instrucciones de voz. Vacio si no hay nada."""
    id_usuario = getattr(usuario, "id", None)
    if not id_usuario:
        return ""
    ahora = time.time() if ahora is None else ahora

    try:
        pendientes = _pendientes(id_usuario, ahora)
    except Exception:  # noqa: BLE001 - sin contexto la voz abre igual
        pendientes = []
    turnos = _turnos_recientes(id_usuario, ahora)
    if not pendientes and not turnos:
        return ""

    nombre = getattr(usuario, "nombre", "") or "el usuario"
    partes = [
        "\n\nDonde quedaron (contexto de hace poco, no ordenes nuevas):",
        f"- Esta sesion de voz acaba de abrirse, pero la conversacion con {nombre} "
        "viene de antes. Esto es solo para que sepas de que venian hablando: no lo "
        f"menciones ni actues sobre ello hasta que {nombre} lo retome.",
    ]
    partes.extend(pendientes)

    if turnos:
        ultimo = turnos[-1]
        donde = APARATOS.get(ultimo["aparato"], "")
        partes.append(
            f"- Lo ultimo que se hablo ({_hace(ahora - ultimo['cuando'])}"
            + (f", por {donde}" if donde else "") + "):"
        )
        for turno in turnos:
            quien = nombre if turno["quien"] == "usuario" else "Jarvis"
            partes.append(f"  {quien}: {_recortado(turno['texto'])}")

    return "\n".join(partes)
