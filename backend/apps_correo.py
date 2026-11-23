"""La bandeja de Gmail dentro de Jarvis (/apps/correo): lo que se prepara en el servidor.

Resumen de cada hilo para la lista, el correo listo para verse (HTML con las
imagenes incrustadas ya resueltas, adjuntos) y el MIME para enviar o guardar
borradores. Habla con Google solo a traves de gmail.py.
Ver docs/superpowers/specs/2026-11-23-apps-correo-design.md.
"""

import base64
import html
import re
from concurrent.futures import ThreadPoolExecutor
from email.message import EmailMessage
from email.utils import getaddresses, parseaddr

from . import gmail

EN_PARALELO = 10
MAX_INCRUSTADA = 2 * 1024 * 1024   # imagenes cid: mas grandes se dejan como adjunto


def _cabeceras(parte: dict) -> dict:
    return {c["name"].lower(): c["value"] for c in (parte or {}).get("headers", [])}


def _nombre_corto(direccion: str, propio: str) -> str:
    nombre, correo = parseaddr(direccion or "")
    if correo and correo.lower() == (propio or "").lower():
        return "yo"
    return (nombre or correo.split("@")[0] or "?").strip().strip('"')


# --------------------------------------------------------------------------
# Lista
# --------------------------------------------------------------------------

def resumen_de_hilo(hilo: dict, propio: str) -> dict:
    mensajes = hilo.get("messages") or []
    primero = _cabeceras((mensajes[0] if mensajes else {}).get("payload"))
    ultimo_m = mensajes[-1] if mensajes else {}
    ultimo = _cabeceras(ultimo_m.get("payload"))
    remitentes: list[str] = []
    etiquetas: set[str] = set()
    adjuntos = False
    for m in mensajes:
        nombre = _nombre_corto(_cabeceras(m.get("payload")).get("from", ""), propio)
        if nombre not in remitentes:
            remitentes.append(nombre)
        etiquetas |= set(m.get("labelIds") or [])
        adjuntos = adjuntos or (m.get("payload") or {}).get("mimeType") == "multipart/mixed"
    return {
        "id": hilo.get("id"),
        "asunto": primero.get("subject") or "(sin asunto)",
        "remitentes": remitentes,
        "para": [c for _, c in getaddresses([ultimo.get("to", "")]) if c],
        "fragmento": html.unescape(ultimo_m.get("snippet", "")),
        "fecha": int(ultimo_m.get("internalDate") or 0),
        "no_leido": any("UNREAD" in (m.get("labelIds") or []) for m in mensajes),
        "destacado": "STARRED" in etiquetas,
        "adjuntos": adjuntos,
        "cantidad": len(mensajes),
        "etiquetas": sorted(etiquetas),
    }


def hilos_para_lista(token: str, ids: list[str], propio: str) -> list[dict]:
    """Los resumenes de varios hilos, pedidos en paralelo, en el mismo orden. Un hilo que
    ya no existe (lo borraron entre medio) se salta."""
    def uno(identificador: str):
        try:
            return resumen_de_hilo(gmail.hilo_completo(token, identificador, solo_cabeceras=True), propio)
        except gmail.ErrorGmail as error:
            if error.revocado:
                raise
            return None

    with ThreadPoolExecutor(max_workers=EN_PARALELO) as grupo:
        return [r for r in grupo.map(uno, ids) if r]


# --------------------------------------------------------------------------
# Ver un correo
# --------------------------------------------------------------------------

_ENLACE = re.compile(r"(https?://[^\s<>\"']+)")


def _texto_a_html(texto: str) -> str:
    seguro = html.escape(texto)
    seguro = _ENLACE.sub(r'<a href="\1">\1</a>', seguro)
    return '<div style="white-space:normal">' + seguro.replace("\n", "<br>") + "</div>"


def _recorrer(parte: dict):
    yield parte
    for hija in parte.get("parts") or []:
        yield from _recorrer(hija)


def mensaje_para_ver(token: str, mensaje: dict) -> dict:
    """Un mensaje del hilo listo para la vista: cabeceras, HTML y adjuntos.

    El HTML se muestra en un iframe aislado (sin scripts ni acceso a Jarvis); aqui
    solo se quitan los <script> por las dudas y se resuelven las imagenes cid:."""
    carga = mensaje.get("payload") or {}
    cab = _cabeceras(carga)
    htmls, textos, incrustadas, adjuntos = [], [], {}, []
    for parte in _recorrer(carga):
        tipo = parte.get("mimeType", "")
        cuerpo = parte.get("body") or {}
        propias = _cabeceras(parte)
        cid = propias.get("content-id", "").strip("<>")
        if tipo in ("text/html", "text/plain") and cuerpo.get("data") and not parte.get("filename"):
            contenido = gmail._de_b64(cuerpo["data"]).decode("utf-8", "replace")
            (htmls if tipo == "text/html" else textos).append(contenido)
        elif cid and tipo.startswith("image/") and int(cuerpo.get("size") or 0) <= MAX_INCRUSTADA:
            datos = gmail._de_b64(cuerpo["data"]) if cuerpo.get("data") else (
                gmail.adjunto(token, mensaje["id"], cuerpo["attachmentId"]) if cuerpo.get("attachmentId") else b"")
            incrustadas[cid] = f"data:{tipo};base64,{base64.b64encode(datos).decode()}"
        elif parte.get("filename") and cuerpo.get("attachmentId"):
            adjuntos.append({"id": cuerpo["attachmentId"], "mensaje": mensaje.get("id"),
                             "nombre": parte["filename"], "tipo": tipo or "application/octet-stream",
                             "tamano": int(cuerpo.get("size") or 0)})

    cuerpo_html = "\n".join(htmls) if htmls else _texto_a_html("\n".join(textos))
    cuerpo_html = re.sub(r"(?is)<script\b.*?</script\s*>", "", cuerpo_html)
    for cid, datos in incrustadas.items():
        cuerpo_html = cuerpo_html.replace(f"cid:{cid}", datos)
    nombre, correo = parseaddr(cab.get("from", ""))
    etiquetas = mensaje.get("labelIds") or []
    return {
        "id": mensaje.get("id"), "hilo": mensaje.get("threadId"),
        "de": {"nombre": nombre.strip('"') or correo, "correo": correo},
        "para": cab.get("to", ""), "cc": cab.get("cc", ""), "asunto": cab.get("subject", ""),
        "fecha": int(mensaje.get("internalDate") or 0), "fecha_texto": cab.get("date", ""),
        "message_id": cab.get("message-id", ""), "referencias": cab.get("references", ""),
        "fragmento": html.unescape(mensaje.get("snippet", "")),
        "no_leido": "UNREAD" in etiquetas, "etiquetas": etiquetas,
        "html": cuerpo_html,
        "imagenes_remotas": bool(re.search(r"""(?i)(src|background)\s*=\s*["']?\s*https?:""", cuerpo_html)),
        "adjuntos": adjuntos,
    }


# --------------------------------------------------------------------------
# Armar correos
# --------------------------------------------------------------------------

def _html_a_texto(contenido: str) -> str:
    return gmail._sin_html(contenido or "")


def armar_mime(de: str, para: str = "", cc: str = "", cco: str = "", asunto: str = "", html: str = "",
               adjuntos: list[tuple[str, str, bytes]] = (), responder: dict | None = None) -> bytes:
    """Correo multipart: texto plano + HTML + adjuntos. Con `responder` ({message_id,
    referencias}) va como respuesta. Sin destinatarios sirve para un borrador."""
    correo = EmailMessage()
    correo["From"] = de
    for cabecera, valor in (("To", para), ("Cc", cc), ("Bcc", cco)):
        if (valor or "").strip():
            correo[cabecera] = valor.strip()
    correo["Subject"] = asunto or ""
    if responder and responder.get("message_id"):
        correo["In-Reply-To"] = responder["message_id"]
        correo["References"] = f"{responder.get('referencias', '')} {responder['message_id']}".strip()
    correo.set_content(_html_a_texto(html) or " ")
    if (html or "").strip():
        correo.add_alternative(html, subtype="html")
    for nombre, tipo, datos in adjuntos:
        principal, _, sub = (tipo or "application/octet-stream").partition("/")
        correo.add_attachment(datos, maintype=principal or "application", subtype=sub or "octet-stream",
                              filename=nombre)
    return correo.as_bytes()


# --------------------------------------------------------------------------
# Acciones
# --------------------------------------------------------------------------

_ACCIONES = {
    "archivar": ([], ["INBOX"]),
    "leido": ([], ["UNREAD"]),
    "no_leido": (["UNREAD"], []),
    "destacar": (["STARRED"], []),
    "quitar_estrella": ([], ["STARRED"]),
    "spam": (["SPAM"], ["INBOX"]),
    "no_spam": (["INBOX"], ["SPAM"]),
    "a_recibidos": (["INBOX"], []),
}


def etiquetas_de_accion(accion: str, etiqueta: str = "") -> tuple[list[str], list[str]]:
    """(agregar, quitar) para una accion de la bandeja. Eliminar no pasa por aqui (va a la papelera)."""
    if accion in _ACCIONES:
        agregar, quitar = _ACCIONES[accion]
        return list(agregar), list(quitar)
    if accion in ("mover", "quitar_etiqueta"):
        if not etiqueta:
            raise ValueError("Falta la etiqueta.")
        return ([etiqueta], ["INBOX"]) if accion == "mover" else ([], [etiqueta])
    raise ValueError(f"Accion desconocida: {accion}")
