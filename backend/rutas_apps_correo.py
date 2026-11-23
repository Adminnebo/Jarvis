"""Rutas de la bandeja de correo (/apps/correo). Todas con la sesion de la persona y
siempre sobre SU Gmail (integraciones, app 'gmail'). Ver apps_correo.py."""

import json
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel
from starlette.datastructures import UploadFile

from . import apps_correo, gmail, integraciones

WEB = Path(__file__).resolve().parent.parent / "web"
MAX_ADJUNTOS = 25 * 1024 * 1024   # el limite de Gmail para un correo

router = APIRouter()


def _error(status: int, mensaje: str, **extra) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": mensaje, **extra})


class _Fallo(Exception):
    def __init__(self, respuesta: JSONResponse):
        self.respuesta = respuesta


def _gmail(peticion: Request, modificar: bool = False) -> tuple[str, dict]:
    """(token de acceso, conexion) de quien pide, o _Fallo con la respuesta de error."""
    usuario_id = peticion.state.usuario.id
    conexion = integraciones.conexion(usuario_id)
    if not conexion or conexion["estado"] != "conectado" or not conexion["token"]:
        raise _Fallo(_error(409, "No tienes Gmail conectado.", conectar=True))
    try:
        token = gmail.token_de_acceso(conexion["token"])
        if modificar and not gmail.puede_modificar(conexion["token"]):
            raise _Fallo(_error(403, "Reconecta tu Gmail para archivar, eliminar y marcar correos.", reconectar=True))
    except gmail.ErrorGmail as error:
        if error.revocado:
            integraciones.marcar_desconectado(usuario_id, str(error))
            raise _Fallo(_error(409, "Google retiro el acceso: vuelve a conectar tu Gmail.", conectar=True)) from error
        raise _Fallo(_error(502, str(error))) from error
    return token, conexion


def _con_gmail(funcion):
    """Convierte _Fallo y ErrorGmail en respuestas, para no repetirlo en cada ruta."""
    import functools
    import inspect

    if inspect.iscoroutinefunction(funcion):
        @functools.wraps(funcion)
        async def envuelta(*args, **kwargs):
            try:
                return await funcion(*args, **kwargs)
            except _Fallo as fallo:
                return fallo.respuesta
            except gmail.ErrorGmail as error:
                return _error(409 if error.revocado else 502, str(error), conectar=error.revocado)
        return envuelta

    @functools.wraps(funcion)
    def envuelta_sync(*args, **kwargs):
        try:
            return funcion(*args, **kwargs)
        except _Fallo as fallo:
            return fallo.respuesta
        except gmail.ErrorGmail as error:
            return _error(409 if error.revocado else 502, str(error), conectar=error.revocado)
    return envuelta_sync


@router.get("/apps/correo")
def pagina():
    return FileResponse(WEB / "apps-correo.html")


@router.get("/api/apps/correo/estado")
@_con_gmail
def estado(peticion: Request):
    conexion = integraciones.conexion(peticion.state.usuario.id)
    if not conexion or conexion["estado"] != "conectado":
        return {"conectado": False, "configurado": gmail.configurado()}
    token, conexion = _gmail(peticion)
    return {"conectado": True, "cuenta": conexion["cuenta"], "modificar": gmail.puede_modificar(conexion["token"]),
            "historyId": gmail.perfil(token)["historyId"]}


@router.get("/api/apps/correo/etiquetas")
@_con_gmail
def etiquetas(peticion: Request):
    token, _ = _gmail(peticion)
    return {"etiquetas": gmail.etiquetas(token)}


@router.get("/api/apps/correo/hilos")
@_con_gmail
def hilos(peticion: Request, etiqueta: str = "INBOX", q: str = "", pagina: str = ""):
    token, conexion = _gmail(peticion)
    ids, siguiente = gmail.hilos(token, etiqueta, q, pagina or None)
    return {"hilos": apps_correo.hilos_para_lista(token, ids, conexion["cuenta"]), "siguiente": siguiente}


@router.get("/api/apps/correo/hilos/{hilo_id}")
@_con_gmail
def hilo(hilo_id: str, peticion: Request):
    token, conexion = _gmail(peticion)
    datos = gmail.hilo_completo(token, hilo_id)
    mensajes = [apps_correo.mensaje_para_ver(token, m) for m in datos.get("messages", [])]
    sin_leer = any("UNREAD" in (m.get("labelIds") or []) for m in datos.get("messages", []))
    if sin_leer and gmail.puede_modificar(conexion["token"]):
        gmail.modificar_hilos(token, [hilo_id], quitar=["UNREAD"])   # abrirlo lo marca leido, como en Gmail
    return {"id": hilo_id, "mensajes": mensajes, "cuenta": conexion["cuenta"]}


@router.get("/api/apps/correo/adjunto/{mensaje_id}/{adjunto_id}")
@_con_gmail
def adjunto(mensaje_id: str, adjunto_id: str, peticion: Request, nombre: str = "archivo",
            tipo: str = "application/octet-stream", ver: int = 0):
    token, _ = _gmail(peticion)
    datos = gmail.adjunto(token, mensaje_id, adjunto_id)
    nombre_seguro = quote(nombre.replace("\r", " ").replace("\n", " "), safe="")
    disposicion = "inline" if ver else "attachment"
    return Response(datos, media_type=tipo.split(";")[0].strip() or "application/octet-stream", headers={
        "Content-Disposition": f"{disposicion}; filename*=UTF-8''{nombre_seguro}",
        "Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"})


class Accion(BaseModel):
    ids: list[str]
    accion: str
    etiqueta: str = ""


@router.post("/api/apps/correo/acciones")
@_con_gmail
def acciones(peticion: Request, datos: Accion):
    token, _ = _gmail(peticion, modificar=True)
    ids = datos.ids[:200]
    if datos.accion == "eliminar":
        gmail.papelera(token, ids)
    elif datos.accion == "restaurar":
        gmail.restaurar(token, ids)
    else:
        try:
            agregar, quitar = apps_correo.etiquetas_de_accion(datos.accion, datos.etiqueta)
        except ValueError as error:
            return _error(400, str(error))
        gmail.modificar_hilos(token, ids, agregar=agregar, quitar=quitar)
    return {"ok": True}


async def _correo_del_formulario(peticion: Request, token: str, cuenta: str) -> tuple[bytes, dict]:
    """Arma el MIME con lo que manda la ventana de redactar. Lanza _Fallo si los adjuntos pasan el limite."""
    formulario = await peticion.form()
    campo = lambda nombre: str(formulario.get(nombre) or "")  # noqa: E731
    adjuntos, total = [], 0
    for subido in formulario.getlist("adjuntos"):
        if isinstance(subido, UploadFile):
            datos = await subido.read()
            total += len(datos)
            adjuntos.append((subido.filename or "archivo", subido.content_type or "application/octet-stream", datos))
    try:
        originales = json.loads(campo("adjuntos_originales") or "[]")
    except ValueError:
        originales = []
    for original in originales if isinstance(originales, list) else []:
        datos = gmail.adjunto(token, str(original.get("mensaje")), str(original.get("id")))
        total += len(datos)
        adjuntos.append((str(original.get("nombre") or "archivo"), str(original.get("tipo") or "application/octet-stream"), datos))
    if total > MAX_ADJUNTOS:
        raise _Fallo(_error(413, "Los adjuntos pasan de 25 MB: Gmail no los acepta."))
    responder = None
    if campo("responder_message_id"):
        responder = {"message_id": campo("responder_message_id"), "referencias": campo("responder_referencias")}
    crudo = apps_correo.armar_mime(de=cuenta, para=campo("para"), cc=campo("cc"), cco=campo("cco"),
                                   asunto=campo("asunto"), html=campo("html"), adjuntos=adjuntos, responder=responder)
    return crudo, {"hilo": campo("hilo") or None, "borrador_id": campo("borrador_id") or None,
                   "hay_destino": any(campo(c).strip() for c in ("para", "cc", "cco"))}


@router.put("/api/apps/correo/borrador")
@_con_gmail
async def guardar_borrador(peticion: Request):
    token, conexion = _gmail(peticion, modificar=True)
    crudo, datos = await _correo_del_formulario(peticion, token, conexion["cuenta"])
    guardado = gmail.guardar_borrador(token, crudo, datos["borrador_id"], datos["hilo"])
    return {"id": guardado.get("id"), "mensaje": (guardado.get("message") or {}).get("id")}


@router.delete("/api/apps/correo/borrador/{borrador_id}")
@_con_gmail
def descartar_borrador(borrador_id: str, peticion: Request):
    token, _ = _gmail(peticion, modificar=True)
    gmail.borrar_borrador(token, borrador_id)
    return {"ok": True}


@router.post("/api/apps/correo/enviar")
@_con_gmail
async def enviar(peticion: Request):
    token, conexion = _gmail(peticion)
    crudo, datos = await _correo_del_formulario(peticion, token, conexion["cuenta"])
    if not datos["hay_destino"]:
        return _error(400, "Falta a quién enviarlo.")
    if datos["borrador_id"] and gmail.puede_modificar(conexion["token"]):
        gmail.guardar_borrador(token, crudo, datos["borrador_id"], datos["hilo"])
        enviado = gmail.enviar_borrador(token, datos["borrador_id"])   # asi no queda el borrador suelto
    else:
        enviado = gmail.enviar_mime(token, crudo, datos["hilo"])
    return {"ok": True, "id": enviado.get("id")}


@router.get("/api/apps/correo/cambios")
@_con_gmail
def cambios(peticion: Request, desde: str):
    token, _ = _gmail(peticion)
    try:
        datos = gmail.cambios(token, desde)
    except gmail.ErrorGmail as error:
        if error.status != 404:
            raise
        return {"historyId": gmail.perfil(token)["historyId"], "hay": True}   # demasiado viejo: recargar todo
    return {"historyId": datos["historyId"], "hay": bool(datos["hilos"])}


@router.get("/api/apps/correo/borrador-de/{mensaje_id}")
@_con_gmail
def borrador_de(mensaje_id: str, peticion: Request):
    token, _ = _gmail(peticion)
    borrador_id = gmail.borrador_de_mensaje(token, mensaje_id)
    return {"id": borrador_id} if borrador_id else _error(404, "Ese borrador ya no existe.")
