"""WhatsApp de cada persona por Zernio: recibir, agrupar, avisar, leer y responder.

El webhook deja cada mensaje entrante en whatsapp_pendientes; un hilo de fondo
espera a que el chat se calme (2 min sin mensajes) y clasifica el bloque con
las mismas reglas que el correo. Clasificado, se borra: Jarvis no guarda copia
de los chats. Leer y responder se hace contra Zernio en el momento.
Ver docs/superpowers/specs/2026-11-09-integraciones-whatsapp-design.md.
"""

import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import avisos, basedatos, integraciones, zernio

RETORNO = "https://asistente.neboaiconsulting.com/integraciones/whatsapp/callback"
MAX_BLOQUE = 3000
MAX_ESPERA = 600       # un chat que no para de escribir se clasifica igual a los 10 min
BARRIDO = 1800         # respaldo del webhook, por persona
VIGENCIA = 600         # de un borrador de respuesta
MAX_LECTURA = 6000


class ErrorChat(Exception):
    """Algo que Jarvis le puede decir a la persona tal cual."""


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _iso(momento: datetime) -> str:
    return momento.isoformat(timespec="seconds")


def retorno() -> str:
    return os.getenv("ZERNIO_JARVIS_RETORNO", RETORNO).strip()


def url_webhook() -> str:
    return retorno().rsplit("/", 1)[0] + "/webhook"


def calma() -> int:
    try:
        return max(10, int(os.getenv("JARVIS_WHATSAPP_CALMA", "120")))
    except ValueError:
        return 120


# --------------------------------------------------------------------------
# Eventos del webhook
# --------------------------------------------------------------------------

def ya_procesado(id_evento: str) -> bool:
    """Anota el evento. True si ya estaba (Zernio lo mando otra vez)."""
    with basedatos.conexion() as con:
        return con.execute("INSERT OR IGNORE INTO zernio_eventos (id, recibido) VALUES (?, ?)",
                           (id_evento, _iso(_ahora()))).rowcount == 0


def olvidar_evento(id_evento: str) -> None:
    """Si procesarlo fallo, se borra la marca para que el reintento de Zernio entre."""
    with basedatos.conexion() as con:
        con.execute("DELETE FROM zernio_eventos WHERE id = ?", (id_evento,))


def podar_eventos() -> None:
    with basedatos.conexion() as con:
        con.execute("DELETE FROM zernio_eventos WHERE recibido < ?", (_iso(_ahora() - timedelta(days=7)),))


def _describir(texto: str | None, adjuntos: list[dict]) -> str:
    partes = [texto.strip()] if (texto or "").strip() else []
    for adjunto in adjuntos or []:
        tipo = (adjunto.get("type") or "").lower()
        if tipo == "audio":
            partes.append("[nota de voz]" if (adjunto.get("payload") or {}).get("voice") else "[audio]")
        elif tipo == "image":
            partes.append("[imagen]")
        elif tipo == "video":
            partes.append("[video]")
        elif tipo == "file":
            nombre = adjunto.get("filename") or adjunto.get("name")
            partes.append(f"[archivo: {nombre}]" if nombre else "[archivo]")
    return " ".join(partes)


def _guardar_pendiente(usuario_id: str, conversacion: str, mensaje_id: str, remitente: str,
                       telefono: str, texto: str) -> None:
    with basedatos.conexion() as con:
        con.execute("INSERT OR IGNORE INTO whatsapp_pendientes (usuario_id, conversacion, mensaje_id, "
                    "remitente, telefono, texto, recibido) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (usuario_id, conversacion, mensaje_id, remitente, telefono, texto, _iso(_ahora())))


def _descartar_chat(usuario_id: str, conversacion: str, hasta_rowid: int | None = None) -> None:
    """Borra los pendientes del chat (todos, o hasta un rowid) y los deja como resueltos."""
    filtro, parametros = "usuario_id = ? AND conversacion = ?", [usuario_id, conversacion]
    if hasta_rowid is not None:
        filtro += " AND rowid <= ?"
        parametros.append(hasta_rowid)
    with basedatos.conexion() as con:
        ids = [f["mensaje_id"] for f in con.execute(
            f"SELECT mensaje_id FROM whatsapp_pendientes WHERE {filtro}", parametros)]
        con.execute(f"DELETE FROM whatsapp_pendientes WHERE {filtro}", parametros)
    for mensaje_id in ids:
        avisos._resolver(usuario_id, f"wa:{mensaje_id}")


def _desconectado(usuario_id: str, motivo: str) -> None:
    """Una sola vez: si ya estaba desconectado no se repite el aviso."""
    actual = integraciones.conexion(usuario_id, "whatsapp")
    if not actual or actual["estado"] != "conectado":
        return
    integraciones.marcar_desconectado(usuario_id, motivo, app="whatsapp")
    regla = integraciones.reglas(usuario_id)
    avisos.crear(usuario_id, f"desconexion-wa-{int(time.time())}", None, "WhatsApp",
                 "Reconecta tu WhatsApp",
                 "Jarvis perdio la conexion con tu WhatsApp. Abre WhatsApp Business en tu telefono "
                 "y vuelve a conectarlo en Integraciones.",
                 con_whatsapp=bool(regla["whatsapp"]), tipo="sistema", app="whatsapp")


def recibir(evento: dict) -> str:
    """Procesa un evento ya verificado. Devuelve que se hizo (para el log y las pruebas)."""
    from . import dispositivos, whatsapp

    tipo = evento.get("event") or ""
    cuenta_id = (evento.get("account") or {}).get("accountId")
    usuario_id = integraciones.usuario_de_cuenta(cuenta_id) if cuenta_id else None
    if usuario_id is None:
        return "cuenta ajena"   # otro perfil de la cuenta compartida de Zernio
    if tipo == "account.disconnected":
        _desconectado(usuario_id, "Meta corto la conexion (hay que abrir WhatsApp Business al menos cada 14 dias).")
        return "desconectado"

    mensaje = evento.get("message") or {}
    if (mensaje.get("platform") or "").lower() != "whatsapp":
        return "otra plataforma"
    conversacion = str(mensaje.get("conversationId") or "")
    if tipo == "message.sent":
        _descartar_chat(usuario_id, conversacion)
        return "contestado"
    if tipo != "message.received" or mensaje.get("direction") != "incoming":
        return "sin accion"
    if (evento.get("metadata") or {}).get("standby"):
        return "standby"

    regla = integraciones.reglas(usuario_id)
    if not regla["activo"] or not regla["reglas"].strip():
        return "sin reglas"
    if dispositivos.usuario_para(usuario_id) is None:
        return "sin acceso"
    remitente = mensaje.get("sender") or {}
    telefono = re.sub(r"\D", "", remitente.get("phoneNumber") or "")
    if telefono and telefono in whatsapp.numeros_propios():
        return "aviso de jarvis"
    texto = _describir(mensaje.get("text"), mensaje.get("attachments") or [])
    if not texto:
        return "vacio"
    mensaje_id = str(mensaje.get("platformMessageId") or mensaje.get("id") or "")
    nombre = remitente.get("name") or remitente.get("whatsappUsername") or (f"+{telefono}" if telefono else "Alguien")
    _guardar_pendiente(usuario_id, conversacion, mensaje_id, nombre, telefono, texto)
    return "pendiente"
