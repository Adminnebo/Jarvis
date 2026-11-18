"""Outlook (Microsoft 365 / Outlook.com) de cada persona por Zernio: el correo y sus avisos.

La cuenta de Microsoft vive en el mismo perfil de Zernio que el WhatsApp de la
persona. Correo: buscar, leer, responder y enviar (lo llama correo.py; los ids
que salen de aqui son de hilo y llevan "o:" delante). Avisos: el webhook solo
anota a la persona "por revisar"; el hilo de fondo lista los hilos nuevos desde
el cursor y los clasifica con las reglas de siempre. El calendario esta en
calendario.py.
Ver docs/superpowers/specs/2026-11-18-integraciones-outlook-calendario-design.md.
"""

import html
import os
import re
import threading
import time
from datetime import datetime, timezone

from . import avisos, integraciones, zernio

RETORNO = "https://asistente.neboaiconsulting.com/integraciones/outlook/callback"
BARRIDO = 1800         # respaldo del webhook, por persona
MAX_POR_VUELTA = 20
PERDIDO = {"account_scope_missing", "admin_consent_required", "mailbox_not_available"}


class ErrorOutlook(Exception):
    """Algo que Jarvis le puede decir a la persona tal cual."""


def retorno() -> str:
    return os.getenv("ZERNIO_OUTLOOK_RETORNO", RETORNO).strip()


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _cuando(texto: str | None) -> datetime:
    return datetime.fromisoformat((texto or "1970-01-01T00:00:00+00:00").replace("Z", "+00:00"))


# --------------------------------------------------------------------------
# Cuenta y errores
# --------------------------------------------------------------------------

def cuenta(usuario_id: str) -> str:
    cuenta_id = integraciones.cuenta_outlook(usuario_id)
    if not cuenta_id:
        raise ErrorOutlook("No tienes Outlook conectado. Conectalo en Integraciones (menu de arriba) "
                           "y vuelve a pedirmelo.")
    return cuenta_id


def direccion(usuario_id: str) -> str:
    return (integraciones.conexion(usuario_id, "outlook") or {}).get("cuenta") or ""


def desconectado(usuario_id: str, motivo: str) -> None:
    """Una sola vez: si ya estaba desconectado no se repite el aviso."""
    actual = integraciones.conexion(usuario_id, "outlook")
    if not actual or actual["estado"] != "conectado":
        return
    integraciones.marcar_desconectado(usuario_id, motivo, app="outlook")
    regla = integraciones.reglas(usuario_id)
    avisos.crear(usuario_id, f"desconexion-ol-{int(time.time())}", None, "Outlook", "Reconecta tu Outlook",
                 "Jarvis perdio el acceso a tu Outlook. Vuelve a conectarlo en Integraciones.",
                 con_whatsapp=bool(regla["whatsapp"]), tipo="sistema", app="outlook")


def explicar(usuario_id: str, error: zernio.ErrorZernio) -> ErrorOutlook:
    """Traduce el error de Zernio y, si la cuenta perdio el permiso, la marca desconectada."""
    if error.status == 412 or (error.codigo or "") in PERDIDO:
        desconectado(usuario_id, str(error))
        return ErrorOutlook("Tu Outlook se desconecto o le falta un permiso: reconectalo en Integraciones.")
    if error.status == 429:
        return ErrorOutlook("Outlook no responde por ahora (limite de uso). Intentalo en un momento.")
    return ErrorOutlook(f"Outlook respondio con un error: {error}")


# --------------------------------------------------------------------------
# Correo (lo usa correo.py)
# --------------------------------------------------------------------------

def _persona(p: dict | None) -> str:
    if not p:
        return ""
    nombre, correo = (p.get("name") or "").strip(), p.get("email") or ""
    return f"{nombre} <{correo}>" if nombre else correo


def _fecha(texto: str | None) -> str:
    return (texto or "")[:16].replace("T", " ")


def _texto(m: dict) -> str:
    limpio = (m.get("clean") or {}).get("text")
    if limpio:
        return limpio.strip()
    if m.get("text"):
        return m["text"].strip()
    sin_etiquetas = re.sub(r"<[^>]+>", " ", m.get("html") or "")
    return re.sub(r"\s+", " ", html.unescape(sin_etiquetas)).strip()


def _de_otro(m: dict, propia: str) -> bool:
    return ((m.get("from") or {}).get("email") or "").lower() != propia


def buscar(usuario_id: str, consulta: str, cuantos: int) -> list[dict]:
    cuenta_id = cuenta(usuario_id)
    propia = direccion(usuario_id).lower()
    try:
        lista = zernio.hilos(cuenta_id, buscar=consulta, limite=cuantos)
    except zernio.ErrorZernio as error:
        raise explicar(usuario_id, error) from error
    salida = []
    for h in lista:
        otros = [p for p in h.get("participants") or [] if (p.get("email") or "").lower() != propia]
        salida.append({"id": f"o:{h.get('id')}",
                       "fecha": _fecha(h.get("latestMessageReceivedAt") or h.get("earliestMessageAt")),
                       "de": _persona(otros[0]) if otros else propia,
                       "asunto": h.get("subject") or "", "fragmento": h.get("snippet") or ""})
    return salida


def _hilo(usuario_id: str, hilo_id: str) -> dict:
    cuenta_id = cuenta(usuario_id)
    try:
        return zernio.hilo(hilo_id, cuenta_id)
    except zernio.ErrorZernio as error:
        raise explicar(usuario_id, error) from error


def leer(usuario_id: str, hilo_id: str) -> list[dict]:
    datos = _hilo(usuario_id, hilo_id)
    return [{"id": m.get("id", ""), "de": _persona(m.get("from")),
             "para": ", ".join(_persona(p) for p in m.get("to") or []),
             "fecha": _fecha(m.get("date")), "asunto": m.get("subject") or datos.get("subject") or "",
             "texto": _texto(m)} for m in datos.get("messages") or []]


def a_quien_responder(usuario_id: str, hilo_id: str) -> dict:
    """El ultimo mensaje del hilo que no mando la persona: {mensaje_id, para, asunto}."""
    propia = direccion(usuario_id).lower()
    datos = _hilo(usuario_id, hilo_id)
    mensajes = datos.get("messages") or []
    ajenos = [m for m in mensajes if _de_otro(m, propia)]
    if ajenos:
        ultimo = ajenos[-1]
        destino = ((ultimo.get("replyTo") or [None])[0] or ultimo.get("from") or {}).get("email", "")
    elif mensajes:
        ultimo = mensajes[-1]
        destino = ((ultimo.get("to") or [{}])[0]).get("email", "")
    else:
        raise ErrorOutlook("Ese hilo de Outlook esta vacio.")
    base = ultimo.get("subject") or datos.get("subject") or ""
    return {"mensaje_id": ultimo.get("id", ""), "para": destino,
            "asunto": base if base.lower().startswith("re:") else f"Re: {base}"}


def enviar(usuario_id: str, para: list[str], asunto: str, texto: str, clave: str,
           responder_a: str | None = None) -> None:
    cuenta_id = cuenta(usuario_id)
    try:
        zernio.enviar_correo(cuenta_id, para, asunto, texto, clave, responder_a)
    except zernio.ErrorZernio as error:
        raise explicar(usuario_id, error) from error


# --------------------------------------------------------------------------
# Avisos de correo nuevo
# --------------------------------------------------------------------------

_por_revisar: set[str] = set()
_ultimo_barrido: dict[str, float] = {}
_candado = threading.Lock()


def recibir(evento: dict) -> str:
    """Evento del webhook de Zernio de una cuenta de Outlook. No lee el mensaje
    (su forma no esta documentada para correo): anota a la persona para revisar."""
    cuenta_id = (evento.get("account") or {}).get("accountId")
    usuario_id = integraciones.usuario_de_outlook(cuenta_id) if cuenta_id else None
    if usuario_id is None:
        return "cuenta ajena"
    tipo = evento.get("event") or ""
    if tipo == "account.disconnected":
        desconectado(usuario_id, "Microsoft o Zernio cortaron la conexion.")
        return "desconectado"
    if tipo != "message.received":
        return "sin accion"
    with _candado:
        _por_revisar.add(usuario_id)
    return "por revisar"


def _procesar(usuario, usuario_id: str, cuenta_id: str, propia: str, h: dict, ref: str, regla: dict) -> bool:
    """True si el hilo quedo resuelto (avisado o descartado)."""
    try:
        datos = zernio.hilo(h.get("id"), cuenta_id)
    except zernio.ErrorZernio as error:
        if error.status == 404:   # lo borraron antes de que lo miraramos
            avisos._resolver(usuario_id, ref)
            return True
        explicar(usuario_id, error)
        return False
    recibidos = [m for m in datos.get("messages") or [] if _de_otro(m, propia)]
    if not recibidos:
        avisos._resolver(usuario_id, ref)
        return True
    m = recibidos[-1]
    correo = {"de": _persona(m.get("from")), "asunto": m.get("subject") or h.get("subject") or "",
              "texto": _texto(m)}
    intentos = avisos._sumar_intento(usuario_id, ref)
    try:
        veredicto = avisos.clasificar(regla["reglas"], correo, usuario, etiqueta="avisos-outlook")
    except Exception:  # noqa: BLE001 - la IA caida no debe perder el correo
        if intentos < avisos.MAX_INTENTOS:
            return False
        veredicto = {"importante": True, "resumen": correo["asunto"] or "(sin asunto)"}
    if veredicto["importante"]:
        avisos.crear(usuario_id, ref, f"o:{h.get('id')}", correo["de"], correo["asunto"],
                     veredicto["resumen"] or correo["asunto"], con_whatsapp=bool(regla["whatsapp"]),
                     app="outlook")
    avisos._resolver(usuario_id, ref)
    return True


def revisar(usuario_id: str) -> None:
    """Hilos con correo nuevo desde el cursor, del mas viejo al mas nuevo. El
    cursor avanza hasta el ultimo resuelto: si la IA falla, se retoma desde ahi."""
    from . import dispositivos

    conexion = integraciones.conexion(usuario_id, "outlook")
    cuenta_id = integraciones.cuenta_outlook(usuario_id)
    if not conexion or not cuenta_id:
        return
    usuario = dispositivos.usuario_para(usuario_id)
    if usuario is None:
        return   # ya no tiene acceso a Jarvis: no se lee su correo
    regla = integraciones.reglas(usuario_id)
    if not regla["activo"] or not regla["reglas"].strip():
        integraciones.mover_cursor(usuario_id, _ahora(), app="outlook")
        return
    desde = conexion["cursor"] or _ahora()
    try:
        lista = zernio.hilos(cuenta_id, despues=desde, limite=MAX_POR_VUELTA + 1, ascendente=True)
    except zernio.ErrorZernio as error:
        explicar(usuario_id, error)
        return   # 429/5xx: se intenta en la proxima vuelta
    propia = (conexion["cuenta"] or "").lower()
    nuevos = sorted((h for h in lista if _cuando(h.get("latestMessageReceivedAt")) > _cuando(desde)),
                    key=lambda h: _cuando(h.get("latestMessageReceivedAt")))
    cursor = desde
    for h in nuevos[:MAX_POR_VUELTA]:
        recibido = h.get("latestMessageReceivedAt") or ""
        ref = f"ol:{h.get('id')}:{recibido}"
        if not avisos._resuelto(usuario_id, ref) and not _procesar(usuario, usuario_id, cuenta_id, propia,
                                                                     h, ref, regla):
            break
        cursor = recibido
    if cursor != desde:
        integraciones.mover_cursor(usuario_id, cursor, app="outlook")


def una_vuelta() -> None:
    ahora = time.time()
    with _candado:
        anotados = set(_por_revisar)
        _por_revisar.clear()
    for conexion in integraciones.conectados("outlook"):
        usuario_id = conexion["usuario_id"]
        if usuario_id not in anotados and ahora - _ultimo_barrido.get(usuario_id, 0) < BARRIDO:
            continue
        _ultimo_barrido[usuario_id] = ahora
        try:
            revisar(usuario_id)
        except Exception as error:  # noqa: BLE001 - un buzon roto no frena a los demas
            print(f"  AVISO: fallo la revision de Outlook de {usuario_id}: {error}")
    try:
        avisos.mandar_pendientes()
    except Exception as error:  # noqa: BLE001
        print(f"  AVISO: fallo el envio de avisos de Outlook: {error}")


def cada() -> int:
    try:
        return max(10, int(os.getenv("JARVIS_OUTLOOK_CADA", "30")))
    except ValueError:
        return 30


def arrancar() -> None:
    if not zernio.configurado():
        print("  Outlook (Zernio): falta ZERNIO_API_KEY; Integraciones > Outlook apagado.")
        return

    def vigilar() -> None:
        while True:
            una_vuelta()
            time.sleep(cada())

    threading.Thread(target=vigilar, name="avisos-outlook", daemon=True).start()
