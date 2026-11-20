"""Evolution API para el WhatsApp propio de cada persona (vincular con QR o codigo).

No es whatsapp.py: ese manda avisos y cotizaciones desde la instancia de
Jarvis. Aqui cada persona tiene su instancia `jarvis-<usuario>`, que Jarvis crea
al conectar y borra al desconectar. Mismo servidor y misma clave global
(EVOLUTION_URL / EVOLUTION_API_KEY). Solo habla con Evolution: no sabe de
avisos ni de la base. Ver docs/superpowers/specs/2026-11-19-whatsapp-evolution-design.md.
"""

import os
import re
from datetime import datetime
from urllib.parse import quote

import httpx

EVENTOS = ["MESSAGES_UPSERT", "CONNECTION_UPDATE", "QRCODE_UPDATED"]

_cliente = httpx.Client(timeout=30)


class ErrorEvolution(Exception):
    def __init__(self, mensaje: str, status: int = 0):
        super().__init__(mensaje)
        self.status = status


def _http() -> httpx.Client:
    return _cliente   # las pruebas lo reemplazan por uno con MockTransport


def _env(nombre: str) -> str:
    return os.getenv(nombre, "").strip()


def configurado() -> bool:
    return bool(_env("EVOLUTION_URL") and _env("EVOLUTION_API_KEY"))


def nombre_instancia(usuario_id: str) -> str:
    limpio = re.sub(r"[^a-z0-9]+", "-", usuario_id.lower()).strip("-")[:40]
    return f"jarvis-{limpio or 'usuario'}"


def _llamar(metodo: str, ruta: str, *, cuerpo: dict | None = None, params: dict | None = None):
    if not configurado():
        raise ErrorEvolution("Evolution no esta configurado (EVOLUTION_URL / EVOLUTION_API_KEY).")
    try:
        r = _http().request(metodo, _env("EVOLUTION_URL").rstrip("/") + ruta, json=cuerpo,
                            params={k: v for k, v in (params or {}).items() if v},
                            headers={"apikey": _env("EVOLUTION_API_KEY")})
    except httpx.HTTPError as error:
        raise ErrorEvolution(f"No se pudo hablar con Evolution: {error}") from error
    try:
        datos = r.json() if r.content else {}
    except ValueError:
        datos = {}
    if r.status_code >= 400:
        detalle = (datos.get("response") or {}).get("message") if isinstance(datos, dict) else None
        if isinstance(detalle, list):
            detalle = "; ".join(str(x) for x in detalle)
        mensaje = detalle or (datos.get("message") if isinstance(datos, dict) else None) \
            or f"Evolution respondio {r.status_code}"
        raise ErrorEvolution(str(mensaje), r.status_code)
    return datos


def _q(instancia: str) -> str:
    return quote(instancia, safe="")


def _qr_de(datos: dict) -> dict:
    datos = datos or {}
    return {"qr": datos.get("base64") or None, "codigo": datos.get("pairingCode") or None}


# --------------------------------------------------------------------------
# Instancias
# --------------------------------------------------------------------------

def crear(instancia: str, webhook: str, numero: str = "") -> dict:
    """Crea la instancia ya configurada. Devuelve {qr, codigo} para vincularla."""
    cuerpo = {
        "instanceName": instancia, "integration": "WHATSAPP-BAILEYS", "qrcode": True,
        "groupsIgnore": True, "readMessages": False, "readStatus": False,
        "alwaysOnline": False, "syncFullHistory": False, "rejectCall": False,
        "webhook": {"url": webhook, "enabled": True, "byEvents": False, "base64": False,
                    "events": EVENTOS},
    }
    if numero:
        cuerpo["number"] = numero
    return _qr_de((_llamar("POST", "/instance/create", cuerpo=cuerpo) or {}).get("qrcode"))


def conectar(instancia: str, numero: str = "") -> dict:
    """Un QR (o codigo, con el numero) nuevo para una instancia que ya existe."""
    return _qr_de(_llamar("GET", f"/instance/connect/{_q(instancia)}", params={"number": numero}))


def estado(instancia: str) -> str | None:
    """'open', 'connecting', 'close'; None si la instancia no existe."""
    try:
        datos = _llamar("GET", f"/instance/connectionState/{_q(instancia)}")
    except ErrorEvolution as error:
        if error.status == 404:
            return None
        raise
    return ((datos or {}).get("instance") or {}).get("state")


def numero(instancia: str) -> str:
    """Los digitos del numero vinculado ('' si todavia no)."""
    for item in _llamar("GET", "/instance/fetchInstances", params={"instanceName": instancia}) or []:
        if item.get("name") == instancia:
            return re.sub(r"\D", "", str(item.get("ownerJid") or "").split("@")[0])
    return ""


def borrar(instancia: str) -> None:
    """Cierra la sesion (sale de "Dispositivos vinculados") y borra la instancia."""
    for ruta in (f"/instance/logout/{_q(instancia)}", f"/instance/delete/{_q(instancia)}"):
        try:
            _llamar("DELETE", ruta)
        except ErrorEvolution as error:
            if error.status not in (400, 404):
                raise


# --------------------------------------------------------------------------
# Mensajes de Baileys
# --------------------------------------------------------------------------

def texto_de(mensaje: dict | None) -> str:
    """Lo legible de un mensaje: texto, o [imagen]/[nota de voz]/[archivo: x] y su pie."""
    if not isinstance(mensaje, dict):
        return ""
    if "documentWithCaptionMessage" in mensaje:
        mensaje = (mensaje["documentWithCaptionMessage"] or {}).get("message") or {}
    if mensaje.get("conversation"):
        return str(mensaje["conversation"]).strip()
    if (mensaje.get("extendedTextMessage") or {}).get("text"):
        return str(mensaje["extendedTextMessage"]["text"]).strip()
    for clave, etiqueta in (("imageMessage", "[imagen]"), ("videoMessage", "[video]")):
        if clave in mensaje:
            pie = str((mensaje[clave] or {}).get("caption") or "").strip()
            return f"{etiqueta} {pie}".strip()
    if "audioMessage" in mensaje:
        return "[nota de voz]" if (mensaje["audioMessage"] or {}).get("ptt") else "[audio]"
    if "documentMessage" in mensaje:
        doc = mensaje["documentMessage"] or {}
        nombre = doc.get("fileName") or doc.get("title")
        pie = str(doc.get("caption") or "").strip()
        return f"{f'[archivo: {nombre}]' if nombre else '[archivo]'} {pie}".strip()
    return ""   # stickers, reacciones, mensajes de protocolo: nada que avisar


def telefono_de(clave: dict) -> str:
    """El numero de un remitente. Con los ids @lid nuevos, el numero viene en remoteJidAlt."""
    for jid in (clave.get("remoteJid"), clave.get("remoteJidAlt"), clave.get("senderPn")):
        if jid and str(jid).endswith("@s.whatsapp.net"):
            return re.sub(r"\D", "", str(jid).split("@")[0])
    return ""


def es_chat_personal(jid: str) -> bool:
    return bool(jid) and not jid.endswith(("@g.us", "@broadcast", "@newsletter"))


def _momento(valor) -> float:
    if isinstance(valor, (int, float)):
        return float(valor)
    try:
        return datetime.fromisoformat(str(valor).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return 0.0


# --------------------------------------------------------------------------
# Chats, mensajes y envio
# --------------------------------------------------------------------------

def chats(instancia: str, limite: int = 50) -> list[dict]:
    """Chats personales, el mas reciente primero, en una forma simple."""
    salida = []
    for c in _llamar("POST", f"/chat/findChats/{_q(instancia)}", cuerpo={}) or []:
        jid = str(c.get("remoteJid") or "")
        if not es_chat_personal(jid):
            continue
        ultimo = c.get("lastMessage") or {}
        clave = {"remoteJid": jid, **(ultimo.get("key") or {})}
        salida.append({
            "id": jid,
            "nombre": c.get("pushName") or (ultimo.get("pushName") if not (ultimo.get("key") or {}).get("fromMe") else None),
            "telefono": telefono_de(clave),
            "ultimo": texto_de(ultimo.get("message")),
            "ultimo_id": (ultimo.get("key") or {}).get("id"),
            "ultimo_mio": bool((ultimo.get("key") or {}).get("fromMe")),
            "no_leidos": int(c.get("unreadCount") or 0),
            "actualizado": _momento(c.get("updatedAt")),
        })
    salida.sort(key=lambda c: c["actualizado"], reverse=True)
    return salida[:limite]


_TIPOS = {
    "conversation": "texto", "extendedTextMessage": "texto", "imageMessage": "imagen",
    "videoMessage": "video", "audioMessage": "audio", "documentMessage": "documento",
    "stickerMessage": "sticker",
}
_ESTADOS = {"PENDING": 0, "SERVER_ACK": 1, "DELIVERY_ACK": 2, "READ": 3, "PLAYED": 3}
_NOMBRE_ESTADO = {0: "pendiente", 1: "enviado", 2: "entregado", 3: "leido"}


def estado_de(status: str | None) -> str | None:
    """SERVER_ACK/DELIVERY_ACK/READ de Evolution -> enviado/entregado/leido."""
    nivel = _ESTADOS.get(str(status or "").upper())
    return _NOMBRE_ESTADO.get(nivel) if nivel is not None else None


def _numero(valor) -> int | None:
    if isinstance(valor, dict):   # los Long de protobuf: {low, high}
        return int(valor.get("low") or 0) + (int(valor.get("high") or 0) << 32)
    try:
        return int(valor) if valor is not None else None
    except (TypeError, ValueError):
        return None


def normalizar_mensaje(registro: dict) -> dict | None:
    """Un mensaje de Evolution en la forma que usa la vista de WhatsApp. None si no se muestra
    (reacciones, mensajes de protocolo...)."""
    clave = registro.get("key") or {}
    contenido = registro.get("message") or {}
    if "documentWithCaptionMessage" in contenido:
        contenido = (contenido["documentWithCaptionMessage"] or {}).get("message") or {}
    clase = next((c for c in _TIPOS if c in contenido), None)
    if clase is None:
        return None
    datos = contenido[clase] if isinstance(contenido[clase], dict) else {}
    tipo = _TIPOS[clase]
    if clase == "audioMessage" and datos.get("ptt"):
        tipo = "nota"
    if tipo == "texto":
        texto = str(contenido.get("conversation") or datos.get("text") or "")
    else:
        texto = str(datos.get("caption") or "")

    archivo = None
    if tipo != "texto":
        miniatura = datos.get("jpegThumbnail")
        archivo = {
            "mime": datos.get("mimetype"), "nombre": datos.get("fileName") or datos.get("title"),
            "tamano": _numero(datos.get("fileLength")), "segundos": _numero(datos.get("seconds")),
            "miniatura": f"data:image/jpeg;base64,{miniatura}" if isinstance(miniatura, str) and miniatura else None,
            "ancho": _numero(datos.get("width")), "alto": _numero(datos.get("height")),
        }

    contexto = registro.get("contextInfo") or datos.get("contextInfo") or {}
    cita = None
    if contexto.get("stanzaId") and contexto.get("quotedMessage"):
        citado = contexto["quotedMessage"]
        cita = {"id": contexto["stanzaId"], "texto": texto_de(citado) or "Mensaje"}

    estado = None
    if clave.get("fromMe"):
        niveles = [_ESTADOS.get(str(u.get("status") or "").upper(), -1) for u in registro.get("MessageUpdate") or []]
        niveles.append(_ESTADOS.get(str(registro.get("status") or "").upper(), 1))
        estado = _NOMBRE_ESTADO[max(max(niveles), 1)]

    return {
        "id": clave.get("id"), "jid": clave.get("remoteJid"), "entrante": not clave.get("fromMe"),
        "nombre": registro.get("pushName"), "momento": _momento(registro.get("messageTimestamp")),
        "tipo": tipo, "texto": texto, "descripcion": texto_de(registro.get("message")),
        "estado": estado, "cita": cita, "archivo": archivo,
    }


def mensajes(instancia: str, jid: str, limite: int = 30, pagina: int = 1) -> list[dict]:
    """Una pagina de mensajes de un chat (la 1 = los mas nuevos), del mas viejo al mas nuevo."""
    datos = _llamar("POST", f"/chat/findMessages/{_q(instancia)}",
                    cuerpo={"where": {"key": {"remoteJid": jid}}, "limit": limite, "page": max(1, pagina)}) or {}
    registros = ((datos.get("messages") or {}).get("records") or []) if isinstance(datos, dict) else []
    salida = [m for m in (normalizar_mensaje(r) for r in registros) if m]
    salida.sort(key=lambda m: m["momento"])
    return salida


def enviar(instancia: str, jid: str, texto: str) -> str:
    destino = jid.split("@")[0] if jid.endswith("@s.whatsapp.net") else jid
    datos = _llamar("POST", f"/message/sendText/{_q(instancia)}", cuerpo={"number": destino, "text": texto}) or {}
    return str((datos.get("key") or {}).get("id") or "")
