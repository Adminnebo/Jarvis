"""apps_correo.py: lo que prepara Jarvis para la bandeja de /apps/correo."""

import base64
import email
from email import policy

import pytest

from backend import apps_correo, gmail


def b64(texto: bytes | str) -> str:
    datos = texto.encode() if isinstance(texto, str) else texto
    return base64.urlsafe_b64encode(datos).decode().rstrip("=")


def cabeceras(**valores):
    nombres = {"de": "From", "para": "To", "asunto": "Subject", "fecha": "Date", "cc": "Cc",
               "message_id": "Message-ID", "referencias": "References"}
    return [{"name": nombres[k], "value": v} for k, v in valores.items()]


def meta(id_, de, asunto="Precio", etiquetas=("INBOX",), fecha=1700000000000, mime="multipart/alternative",
         fragmento="hola", para="yo@gmail.com"):
    return {"id": id_, "threadId": "h1", "labelIds": list(etiquetas), "snippet": fragmento,
            "internalDate": str(fecha), "payload": {"mimeType": mime, "headers": cabeceras(de=de, para=para, asunto=asunto)}}


# --- lista ---

def test_resumen_de_hilo():
    hilo = {"id": "h1", "messages": [
        meta("m1", '"Pedro Gómez" <pedro@jh.com>', etiquetas=("INBOX",)),
        meta("m2", "Yo <yo@gmail.com>", etiquetas=("SENT",)),
        meta("m3", "Pedro Gómez <pedro@jh.com>", etiquetas=("INBOX", "UNREAD", "STARRED"),
             fecha=1700000999000, mime="multipart/mixed", fragmento="y el pedido &amp; la factura?"),
    ]}
    r = apps_correo.resumen_de_hilo(hilo, "yo@gmail.com")
    assert r["id"] == "h1" and r["asunto"] == "Precio" and r["cantidad"] == 3
    assert r["remitentes"] == ["Pedro Gómez", "yo"]
    assert r["no_leido"] and r["destacado"] and r["adjuntos"]
    assert r["fecha"] == 1700000999000 and r["fragmento"] == "y el pedido & la factura?"
    assert set(r["etiquetas"]) >= {"INBOX", "SENT", "UNREAD", "STARRED"}
    assert r["para"] == ["yo@gmail.com"]


def test_resumen_sin_asunto():
    r = apps_correo.resumen_de_hilo({"id": "h", "messages": [meta("m", "a@b.com", asunto="")]}, "yo@x.com")
    assert r["asunto"] == "(sin asunto)" and r["remitentes"] == ["a"]


def test_hilos_para_lista_en_orden(monkeypatch):
    monkeypatch.setattr(gmail, "hilo_completo", lambda token, id_, solo_cabeceras=False:
                        {"id": id_, "messages": [meta("m" + id_, "x@y.com")]})
    lista = apps_correo.hilos_para_lista("t", ["b", "a", "c"], "yo@x.com")
    assert [h["id"] for h in lista] == ["b", "a", "c"]


def test_un_hilo_que_falla_no_tumba_la_lista(monkeypatch):
    def hilo(token, id_, solo_cabeceras=False):
        if id_ == "malo":
            raise gmail.ErrorGmail("se borro", status=404)
        return {"id": id_, "messages": [meta("m", "x@y.com")]}

    monkeypatch.setattr(gmail, "hilo_completo", hilo)
    assert [h["id"] for h in apps_correo.hilos_para_lista("t", ["a", "malo"], "yo@x.com")] == ["a"]


# --- ver un correo ---

def test_mensaje_con_html_imagen_incrustada_y_adjunto(monkeypatch):
    monkeypatch.setattr(gmail, "adjunto", lambda token, m, a: b"PNGDATA" if a == "img1" else b"")
    mensaje = {"id": "m1", "threadId": "h1", "labelIds": ["INBOX", "UNREAD"], "internalDate": "1700000000000",
               "payload": {"mimeType": "multipart/mixed", "headers": cabeceras(
                   de="Pedro <pedro@jh.com>", para="yo@gmail.com", cc="ana@jh.com", asunto="Factura",
                   fecha="Mon, 23 Nov 2026 10:00:00 -0400", message_id="<abc@jh.com>", referencias="<x@jh.com>"),
                   "parts": [
                       {"mimeType": "multipart/related", "parts": [
                           {"mimeType": "text/html", "body": {"data": b64(
                               '<p>Hola</p><img src="cid:logo123"><img src="https://rastreo.com/p.gif">'
                               '<script>alert(1)</script>')}},
                           {"mimeType": "image/png", "filename": "logo.png",
                            "headers": [{"name": "Content-ID", "value": "<logo123>"}],
                            "body": {"attachmentId": "img1", "size": 7}}]},
                       {"mimeType": "application/pdf", "filename": "factura.pdf",
                        "body": {"attachmentId": "pdf1", "size": 2048}}]}}
    v = apps_correo.mensaje_para_ver("t", mensaje)
    assert v["de"] == {"nombre": "Pedro", "correo": "pedro@jh.com"}
    assert v["para"] == "yo@gmail.com" and v["cc"] == "ana@jh.com" and v["asunto"] == "Factura"
    assert v["message_id"] == "<abc@jh.com>" and v["no_leido"]
    assert "data:image/png;base64," + base64.b64encode(b"PNGDATA").decode() in v["html"]
    assert "cid:logo123" not in v["html"] and "<script" not in v["html"].lower()
    assert v["imagenes_remotas"] is True
    assert v["adjuntos"] == [{"id": "pdf1", "mensaje": "m1", "nombre": "factura.pdf",
                              "tipo": "application/pdf", "tamano": 2048}]


def test_mensaje_solo_texto_se_vuelve_html():
    mensaje = {"id": "m1", "labelIds": [], "internalDate": "0", "payload": {
        "mimeType": "text/plain", "headers": cabeceras(de="a@b.com", asunto="x"),
        "body": {"data": b64("Hola <Ana>\nmira https://jh.com")}}}
    v = apps_correo.mensaje_para_ver("t", mensaje)
    assert "Hola &lt;Ana&gt;<br>" in v["html"] and 'href="https://jh.com"' in v["html"]
    assert v["imagenes_remotas"] is False and v["adjuntos"] == []


# --- armar y enviar ---

def test_armar_mime_con_adjunto_y_respuesta():
    crudo = apps_correo.armar_mime(
        de="yo@gmail.com", para="pedro@jh.com", cc="ana@jh.com", cco="jefe@jh.com", asunto="Re: Factura",
        html="<p>Va <b>adjunta</b></p>", adjuntos=[("f.pdf", "application/pdf", b"%PDF")],
        responder={"message_id": "<abc@jh.com>", "referencias": "<x@jh.com>"})
    correo = email.message_from_bytes(crudo, policy=policy.default)
    assert correo["To"] == "pedro@jh.com" and correo["Cc"] == "ana@jh.com" and correo["Bcc"] == "jefe@jh.com"
    assert correo["In-Reply-To"] == "<abc@jh.com>" and correo["References"] == "<x@jh.com> <abc@jh.com>"
    assert correo.get_body(("plain",)).get_content().strip() == "Va adjunta"
    assert "<b>adjunta</b>" in correo.get_body(("html",)).get_content()
    (adjunto,) = list(correo.iter_attachments())
    assert adjunto.get_filename() == "f.pdf" and adjunto.get_content() == b"%PDF"


def test_armar_mime_sin_destinatarios_para_borrador():
    correo = email.message_from_bytes(apps_correo.armar_mime(de="yo@x.com", html=""), policy=policy.default)
    assert correo["To"] is None and correo["From"] == "yo@x.com"


@pytest.mark.parametrize("accion, etiqueta, esperado", [
    ("archivar", "", ([], ["INBOX"])),
    ("leido", "", ([], ["UNREAD"])),
    ("no_leido", "", (["UNREAD"], [])),
    ("destacar", "", (["STARRED"], [])),
    ("quitar_estrella", "", ([], ["STARRED"])),
    ("mover", "Label_1", (["Label_1"], ["INBOX"])),
    ("quitar_etiqueta", "Label_1", ([], ["Label_1"])),
    ("spam", "", (["SPAM"], ["INBOX"])),
    ("no_spam", "", (["INBOX"], ["SPAM"])),
    ("a_recibidos", "", (["INBOX"], [])),
])
def test_acciones_a_etiquetas(accion, etiqueta, esperado):
    assert apps_correo.etiquetas_de_accion(accion, etiqueta) == esperado


def test_accion_desconocida():
    with pytest.raises(ValueError):
        apps_correo.etiquetas_de_accion("volar", "")
    with pytest.raises(ValueError):
        apps_correo.etiquetas_de_accion("mover", "")
