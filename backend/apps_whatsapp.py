"""La vista de WhatsApp dentro de Jarvis (/apps/whatsapp): canal en vivo, fotos e instancia.

El navegador nunca habla con Evolution: pide todo por las rutas /api/apps/whatsapp
y recibe lo nuevo por Server-Sent Events. Aqui vive el reparto de esos eventos
(una cola por navegador abierto) y lo que la vista necesita de la instancia de
quien la usa. Jarvis corre en un solo proceso de uvicorn: el reparto en memoria
alcanza. Ver docs/superpowers/specs/2026-11-20-apps-whatsapp-design.md.
"""

import asyncio
import re
import threading
import time

from . import evolution_wa, integraciones

VIDA_FOTO = 86400
VIDA_SIN_FOTO = 3600


class SinWhatsApp(Exception):
    """La persona no tiene su WhatsApp vinculado por Evolution."""


_suscritos: dict[str, list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]]] = {}
_candado = threading.Lock()
_eventos_listos: set[str] = set()
_fotos: dict[tuple[str, str], tuple[str | None, float]] = {}


# --------------------------------------------------------------------------
# Canal en vivo
# --------------------------------------------------------------------------

def suscribir(usuario_id: str) -> asyncio.Queue:
    """Una cola para un navegador abierto. Se llama desde la ruta SSE (dentro del loop)."""
    cola: asyncio.Queue = asyncio.Queue(maxsize=500)
    with _candado:
        _suscritos.setdefault(usuario_id, []).append((asyncio.get_running_loop(), cola))
    return cola


def desuscribir(usuario_id: str, cola: asyncio.Queue) -> None:
    with _candado:
        lista = [(l, c) for l, c in _suscritos.get(usuario_id, []) if c is not cola]
        if lista:
            _suscritos[usuario_id] = lista
        else:
            _suscritos.pop(usuario_id, None)


def _poner(cola: asyncio.Queue, evento: dict) -> None:
    try:
        cola.put_nowait(evento)
    except asyncio.QueueFull:
        pass   # un navegador colgado no frena a nadie; al reconectar recarga todo


def publicar(usuario_id: str, evento: dict) -> None:
    """Manda un evento a todos los navegadores abiertos de esa persona. Seguro desde cualquier hilo."""
    with _candado:
        destinos = list(_suscritos.get(usuario_id, []))
    for loop, cola in destinos:
        try:
            loop.call_soon_threadsafe(_poner, cola, evento)
        except RuntimeError:
            desuscribir(usuario_id, cola)   # ese loop ya cerro


def evento_de_webhook(evento: dict) -> dict | None:
    """Lo que la vista tiene que saber de un evento del webhook de Evolution (o None)."""
    tipo = str(evento.get("event") or "").lower().replace("_", ".")
    datos = evento.get("data") or {}
    if tipo in ("messages.upsert", "send.message"):
        registro = datos[0] if isinstance(datos, list) and datos else datos
        if not isinstance(registro, dict):
            return None
        if not evolution_wa.es_chat_personal(str((registro.get("key") or {}).get("remoteJid") or "")):
            return None
        mensaje = evolution_wa.normalizar_mensaje(registro)
        return {"tipo": "mensaje", "mensaje": mensaje} if mensaje else None
    if tipo == "messages.update":
        estado = evolution_wa.estado_de(datos.get("status"))
        jid = str(datos.get("remoteJid") or "")
        if not estado or not evolution_wa.es_chat_personal(jid):
            return None
        return {"tipo": "estado", "id": datos.get("keyId") or datos.get("messageId"), "jid": jid, "estado": estado}
    if tipo == "connection.update":
        return {"tipo": "conexion", "estado": datos.get("state")}
    return None


# --------------------------------------------------------------------------
# Instancia, fotos y numeros
# --------------------------------------------------------------------------

def instancia_de(usuario_id: str) -> str:
    """La instancia de quien usa la vista. La primera vez en este proceso le pone los
    eventos que la vista necesita (las instancias viejas no los tenian)."""
    from . import whatsapp_chats

    instancia = whatsapp_chats._instancia(usuario_id)
    if not instancia:
        raise SinWhatsApp("No tienes WhatsApp vinculado.")
    if instancia not in _eventos_listos:
        fila = integraciones.instancia_evolution(usuario_id)
        try:
            evolution_wa.asegurar_eventos(instancia, whatsapp_chats.url_webhook_evolution(fila["clave"]))
            _eventos_listos.add(instancia)
        except evolution_wa.ErrorEvolution as error:
            print(f"  AVISO: no se pudieron poner los eventos de {instancia}: {error}")
    return instancia


def foto(instancia: str, jid: str) -> str | None:
    """URL de la foto de perfil, con cache (un dia; una hora si no tiene)."""
    clave = (instancia, jid)
    guardada = _fotos.get(clave)
    if guardada:
        url, cuando = guardada
        if time.time() - cuando < (VIDA_FOTO if url else VIDA_SIN_FOTO):
            return url
    try:
        url = evolution_wa.foto_perfil(instancia, jid)
    except evolution_wa.ErrorEvolution:
        url = None
    _fotos[clave] = (url, time.time())
    return url


def jid_de(texto: str) -> str:
    """Un chat personal: un jid tal cual, o un numero que se vuelve <numero>@s.whatsapp.net."""
    from . import whatsapp

    texto = (texto or "").strip()
    if "@" in texto:
        if not evolution_wa.es_chat_personal(texto):
            raise ValueError("Solo chats personales (no grupos ni difusiones).")
        return texto
    try:
        return f"{whatsapp.normalizar_numero(texto)}@s.whatsapp.net"
    except whatsapp.ErrorEnvio as error:
        raise ValueError(str(error)) from error


def digitos(jid: str) -> str:
    return re.sub(r"\D", "", jid.split("@")[0])
