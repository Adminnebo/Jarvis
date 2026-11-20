"""Rutas de la vista de WhatsApp (/apps/whatsapp). Todas con la sesion de la persona:
el middleware `guardia` de main.py ya dejo en peticion.state.usuario quien es, y cada
ruta trabaja solo sobre SU instancia de Evolution. Ver apps_whatsapp.py."""

import asyncio
import base64
import json
from pathlib import Path

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from pydantic import BaseModel

from . import apps_whatsapp, evolution_wa, integraciones

WEB = Path(__file__).resolve().parent.parent / "web"
MAX_ARCHIVO = 16 * 1024 * 1024   # el tope de WhatsApp para fotos; los documentos aguantan mas, pero basta
POR_PAGINA = 30
LATIDO = 25.0

router = APIRouter()


def _error(status: int, mensaje: str, **extra) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": mensaje, **extra})


def _con_instancia(peticion: Request, jid: str | None = None):
    """(instancia, jid) o la respuesta de error que corresponde."""
    try:
        instancia = apps_whatsapp.instancia_de(peticion.state.usuario.id)
    except apps_whatsapp.SinWhatsApp as error:
        return None, None, _error(409, str(error), vincular=True)
    if jid is None:
        return instancia, None, None
    try:
        return instancia, apps_whatsapp.jid_de(jid), None
    except ValueError as error:
        return None, None, _error(400, str(error))


def _evolution(funcion, *args, **kwargs):
    try:
        return funcion(*args, **kwargs), None
    except evolution_wa.ErrorEvolution as error:
        return None, _error(502, f"WhatsApp respondio con un error: {error}")


@router.get("/apps/whatsapp")
def pagina():
    return FileResponse(WEB / "apps.html")


@router.get("/api/apps/whatsapp/estado")
def estado(peticion: Request):
    conexion = integraciones.conexion(peticion.state.usuario.id, "whatsapp")
    conectado = bool(conexion and conexion["estado"] == "conectado"
                     and integraciones.instancia_evolution(peticion.state.usuario.id))
    return {"conectado": conectado, "cuenta": conexion["cuenta"] if conectado else None}


@router.get("/api/apps/whatsapp/chats")
def chats(peticion: Request):
    instancia, _, fallo = _con_instancia(peticion)
    if fallo:
        return fallo
    lista, fallo = _evolution(evolution_wa.chats, instancia, limite=200)
    return fallo or {"chats": lista}


@router.get("/api/apps/whatsapp/chats/{jid}/mensajes")
def mensajes(jid: str, peticion: Request, pagina: int = 1):
    instancia, jid, fallo = _con_instancia(peticion, jid)
    if fallo:
        return fallo
    lista, fallo = _evolution(evolution_wa.mensajes, instancia, jid, POR_PAGINA, pagina=max(1, pagina))
    return fallo or {"mensajes": lista}


class Leidos(BaseModel):
    ids: list[str] = []


@router.post("/api/apps/whatsapp/chats/{jid}/leido")
def leido(jid: str, peticion: Request, datos: Leidos):
    instancia, jid, fallo = _con_instancia(peticion, jid)
    if fallo:
        return fallo
    _, fallo = _evolution(evolution_wa.marcar_leido, instancia, jid, datos.ids[:100])
    return fallo or {"ok": True}


class Cita(BaseModel):
    id: str
    texto: str = ""


class Texto(BaseModel):
    texto: str
    cita: Cita | None = None


@router.post("/api/apps/whatsapp/chats/{jid}/mensajes")
def enviar_texto(jid: str, peticion: Request, datos: Texto):
    instancia, jid, fallo = _con_instancia(peticion, jid)
    if fallo:
        return fallo
    if not datos.texto.strip():
        return _error(400, "El mensaje esta vacio.")
    cita = datos.cita.model_dump() if datos.cita else None
    id_, fallo = _evolution(evolution_wa.enviar, instancia, jid, datos.texto, cita=cita)
    return fallo or {"id": id_, "jid": jid}


def _cita_de_formulario(texto: str) -> dict | None:
    try:
        cita = json.loads(texto) if texto else None
    except ValueError:
        return None
    return cita if isinstance(cita, dict) and cita.get("id") else None


async def _leer(subido: UploadFile) -> bytes | None:
    datos = await subido.read(MAX_ARCHIVO + 1)
    return None if len(datos) > MAX_ARCHIVO else datos


@router.post("/api/apps/whatsapp/chats/{jid}/archivo")
async def enviar_archivo(jid: str, peticion: Request, archivo: UploadFile = File(...),
                         pie: str = Form(""), cita: str = Form("")):
    instancia, jid, fallo = _con_instancia(peticion, jid)
    if fallo:
        return fallo
    datos = await _leer(archivo)
    if datos is None:
        return _error(413, "El archivo pasa de 16 MB: WhatsApp no lo acepta.")
    id_, fallo = _evolution(evolution_wa.enviar_archivo, instancia, jid,
                            archivo.content_type or "application/octet-stream", archivo.filename or "archivo",
                            base64.b64encode(datos).decode(), pie, cita=_cita_de_formulario(cita))
    return fallo or {"id": id_, "jid": jid}


@router.post("/api/apps/whatsapp/chats/{jid}/nota")
async def enviar_nota(jid: str, peticion: Request, audio: UploadFile = File(...), cita: str = Form("")):
    instancia, jid, fallo = _con_instancia(peticion, jid)
    if fallo:
        return fallo
    datos = await _leer(audio)
    if datos is None:
        return _error(413, "La nota de voz es demasiado larga.")
    id_, fallo = _evolution(evolution_wa.enviar_nota, instancia, jid, base64.b64encode(datos).decode(),
                            cita=_cita_de_formulario(cita))
    return fallo or {"id": id_, "jid": jid}


@router.get("/api/apps/whatsapp/archivo/{id_mensaje}")
def archivo_de_mensaje(id_mensaje: str, peticion: Request):
    instancia, _, fallo = _con_instancia(peticion)
    if fallo:
        return fallo
    datos, fallo = _evolution(evolution_wa.archivo, instancia, id_mensaje)
    if fallo:
        return fallo
    if not datos["base64"]:
        return _error(404, "Ese mensaje no tiene archivo (o ya no esta en WhatsApp).")
    cabeceras = {"Cache-Control": "private, max-age=86400"}
    if datos.get("nombre"):
        cabeceras["Content-Disposition"] = f"inline; filename*=UTF-8''{_nombre_seguro(datos['nombre'])}"
    return Response(base64.b64decode(datos["base64"]), media_type=datos["mime"].split(";")[0].strip(),
                    headers=cabeceras)


def _nombre_seguro(nombre: str) -> str:
    from urllib.parse import quote

    return quote(nombre.replace("\n", " ").replace("\r", " "), safe="")


@router.get("/api/apps/whatsapp/foto/{jid}")
def foto(jid: str, peticion: Request):
    instancia, jid, fallo = _con_instancia(peticion, jid)
    if fallo:
        return fallo
    url = apps_whatsapp.foto(instancia, jid)
    if not url:
        return Response(status_code=404, headers={"Cache-Control": "private, max-age=3600"})
    return RedirectResponse(url, status_code=302, headers={"Cache-Control": "private, max-age=3600"})


async def flujo(usuario_id: str, peticion, latido: float = LATIDO):
    """Server-Sent Events: lo que publique apps_whatsapp para esta persona, con latido."""
    cola = apps_whatsapp.suscribir(usuario_id)
    try:
        yield "retry: 3000\n\n"
        while not await peticion.is_disconnected():
            try:
                evento = await asyncio.wait_for(cola.get(), latido)
            except asyncio.TimeoutError:
                yield ": latido\n\n"
                continue
            yield f"data: {json.dumps(evento, ensure_ascii=False)}\n\n"
    finally:
        apps_whatsapp.desuscribir(usuario_id, cola)


@router.get("/api/apps/whatsapp/eventos")
def eventos(peticion: Request):
    return StreamingResponse(flujo(peticion.state.usuario.id, peticion), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
