"""Rutas de las reuniones grabadas por el bot de Meet.

- /api/reuniones/{id}/eventos|audio|hablantes: el bot, con el token de subida.
- /api/reuniones, /api/reuniones/{id}, /grabar, /no-grabar, /preferencias: la persona, con su sesión.
- /reuniones/accion: el enlace de WhatsApp (GET muestra, POST hace: la vista previa
  de WhatsApp abre los enlaces con GET y no debe grabar ni cancelar nada).
- /apps/reuniones: la página.
"""

import html
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

from . import almacen_reuniones, bot_meet, reuniones
from . import reuniones_datos as rd

WEB = Path(__file__).resolve().parent.parent / "web"
MAX_AUDIO = 20 * 1024 * 1024
router = APIRouter()


def _bot(peticion: Request, reunion_id: str) -> JSONResponse | None:
    autorizacion = peticion.headers.get("authorization", "")
    token = autorizacion[7:].strip() if autorizacion.lower().startswith("bearer ") else ""
    if not reuniones.token_valido(reunion_id, token):
        return JSONResponse(status_code=401, content={"error": "token"})
    return None


@router.post("/api/reuniones/{reunion_id}/eventos")
async def bot_eventos(reunion_id: str, peticion: Request):
    if (fallo := _bot(peticion, reunion_id)) is not None:
        return fallo
    reuniones.recibir_evento(reunion_id, await peticion.json())
    return {"ok": True}


@router.post("/api/reuniones/{reunion_id}/audio")
async def bot_audio(reunion_id: str, n: int, peticion: Request, inicio_s: int | None = None):
    if (fallo := _bot(peticion, reunion_id)) is not None:
        return fallo
    formato = reuniones.formato_de(peticion.headers.get("content-type"))
    if formato is None:
        return JSONResponse(status_code=415, content={"error": "formato"})
    datos = await peticion.body()
    if len(datos) > MAX_AUDIO:
        return JSONResponse(status_code=413, content={"error": "grande"})
    estado = rd.obtener(reunion_id)["estado"]
    if estado == "lista":   # ya se resumió: lo que llega tarde no entra, pero el aparato lo suelta
        return {"ok": False, "parar": True}
    if not reuniones.recibir_audio(reunion_id, n, datos, formato, inicio_s):
        return JSONResponse(status_code=409, content={"error": "repetido"})
    # Si la sacaron (desde «Grabando ahora» u otro aparato), quien graba se entera aquí.
    return {"ok": True, "parar": estado not in ("grabando", "esperando")}


MOTIVOS_MUESTRA = {"nombre": "Falta el nombre.", "repetido": "Ese nombre ya está.",
                   "muchas": "Son 10 personas como mucho.", "audio": "No pude leer la grabación, repítela."}


@router.post("/api/reuniones/{reunion_id}/voces")
async def voces(reunion_id: str, nombre: str, peticion: Request):
    """La muestra de voz de una persona (calibración de una presencial)."""
    from . import reuniones_voces
    if (fallo := _bot(peticion, reunion_id)) is not None:
        return fallo
    formato = reuniones.formato_de(peticion.headers.get("content-type"))
    if formato is None:
        return JSONResponse(status_code=415, content={"error": "formato"})
    datos = await peticion.body()
    if len(datos) > MAX_AUDIO:
        return JSONResponse(status_code=413, content={"error": "grande"})
    motivo = reuniones_voces.guardar_muestra(reunion_id, nombre, datos, formato)
    if motivo:
        return JSONResponse(status_code=400, content={"error": MOTIVOS_MUESTRA[motivo]})
    return {"ok": True, "voces": reuniones_voces.conocidas(reunion_id)}


@router.post("/api/reuniones/{reunion_id}/hablantes")
async def bot_hablantes(reunion_id: str, peticion: Request):
    if (fallo := _bot(peticion, reunion_id)) is not None:
        return fallo
    reuniones.recibir_hablantes(reunion_id, (await peticion.json()).get("linea") or [])
    return {"ok": True}


# --- la persona -----------------------------------------------------------

def _publica(r: dict, completa: bool = False) -> dict:
    campos = ["id", "titulo", "inicio", "fin", "estado", "motivo", "duracion_s", "incompleta", "meet_url", "tipo"]
    salida = {k: r.get(k) for k in campos}
    salida["tipo"] = salida["tipo"] or "meet"
    if completa:
        mapa = r.get("nombres") or {}
        p = reuniones.con_nombres_puestos(r)
        salida.update(resumen=p.get("resumen"), puntos=p.get("puntos") or [], tareas=p.get("tareas") or [],
                      transcripcion=p.get("transcripcion") or [], audio_borrado=bool(r.get("audio_borrado")),
                      hablantes=[{"etiqueta": e, "nombre": mapa.get(e, e)} for e in reuniones.etiquetas(r)],
                      pedazos=[x["n"] for x in rd.pedazos(r["id"]) if x["estado"] == "transcrito"])
    return salida


@router.get("/api/reuniones")
def lista(peticion: Request):
    return {"reuniones": [_publica(r) for r in rd.listar_de(peticion.state.usuario.id)]}


@router.get("/api/reuniones/en-curso")
def en_curso(peticion: Request):
    """Lo que el bot tiene agendado, esperando entrar o grabando, de quien pregunta."""
    return {"reuniones": reuniones.en_curso(peticion.state.usuario.id)}


@router.post("/api/reuniones/{reunion_id}/sacar")
def sacar(reunion_id: str, peticion: Request):
    return {"mensaje": reuniones.sacar(peticion.state.usuario.id, reunion_id)}


@router.get("/api/reuniones/preferencias")
def ver_preferencias(peticion: Request):
    # disponible: sin bot configurado, Integraciones no muestra el interruptor.
    return {"grabar_siempre": rd.grabar_siempre(peticion.state.usuario.id), "disponible": bot_meet.configurado()}


class Preferencias(BaseModel):
    grabar_siempre: bool


@router.put("/api/reuniones/preferencias")
def guardar_preferencias(peticion: Request, datos: Preferencias):
    rd.poner_grabar_siempre(peticion.state.usuario.id, datos.grabar_siempre)
    return {"grabar_siempre": datos.grabar_siempre}


class Presencial(BaseModel):
    titulo: str = ""


@router.post("/api/reuniones/presencial")
def presencial(peticion: Request, datos: Presencial):
    return reuniones.crear_presencial(peticion.state.usuario.id, datos.titulo)


class Link(BaseModel):
    url: str
    titulo: str = ""


@router.post("/api/reuniones/grabar-link")
def grabar_link(peticion: Request, datos: Link):
    """Un Meet que no está en el calendario: el bot entra ya."""
    if reuniones.link_meet({"description": datos.url}) is None:
        return JSONResponse(status_code=400, content={"mensaje": "Eso no es un link de Google Meet."})
    return {"mensaje": reuniones.grabar_link(peticion.state.usuario.id, datos.url, datos.titulo)}


@router.get("/api/reuniones/{reunion_id}")
def detalle(reunion_id: str, peticion: Request):
    r = rd.obtener(reunion_id)
    if r is None or not rd.puede_ver(reunion_id, peticion.state.usuario.id):
        return JSONResponse(status_code=404, content={"error": "No existe."})
    return _publica(r, completa=True)


class Renombre(BaseModel):
    de: str
    a: str = ""


@router.put("/api/reuniones/{reunion_id}/nombres")
def nombres(reunion_id: str, peticion: Request, datos: Renombre):
    fallo = reuniones.renombrar(peticion.state.usuario.id, reunion_id, datos.de, datos.a)
    if fallo == "no_existe":
        return JSONResponse(status_code=404, content={"error": "No existe."})
    if fallo == "etiqueta":
        return JSONResponse(status_code=400, content={"error": "Esa voz no está en la reunión."})
    return _publica(rd.obtener(reunion_id), completa=True)


@router.get("/api/reuniones/{reunion_id}/audio/{n}")
def audio(reunion_id: str, n: int, peticion: Request):
    r = rd.obtener(reunion_id)
    if r is None or not rd.puede_ver(reunion_id, peticion.state.usuario.id) or r["audio_borrado"]:
        return JSONResponse(status_code=404, content={"error": "No hay audio."})
    formato = next((p.get("formato") for p in rd.pedazos(reunion_id) if p["n"] == n), None) or "ogg"
    try:
        return {"url": almacen_reuniones.url_firmada(reunion_id, n, formato=formato)}
    except almacen_reuniones.ErrorAlmacen:
        return JSONResponse(status_code=502, content={"error": "No pude traer el audio."})


@router.post("/api/reuniones/{reunion_id}/grabar")
def grabar(reunion_id: str, peticion: Request):
    return {"mensaje": reuniones.pedir(peticion.state.usuario.id, reunion_id)}


@router.post("/api/reuniones/{reunion_id}/no-grabar")
def no_grabar(reunion_id: str, peticion: Request):
    return {"mensaje": reuniones.no_grabar(peticion.state.usuario.id, reunion_id)}


# --- enlace de WhatsApp ---------------------------------------------------

def _pagina(texto: str, formulario: str = "") -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
        "<title>Jarvis · Reuniones</title><body style='font:18px system-ui;margin:2rem;background:#111;color:#eee'>"
        f"<p>{html.escape(texto)}</p>{formulario}</body>")


@router.get("/reuniones/accion")
def accion_ver(u: str, r: str, a: str, f: str):
    if not reuniones.verificar_enlace(u, r, a, f):
        return _pagina("Este enlace no es válido.")
    reunion = rd.obtener(r)
    if reunion is None:
        return _pagina("Esa reunión ya no existe.")
    verbo = "Grabar" if a == "grabar" else "No grabar"
    return _pagina(f"«{reunion['titulo']}»",
                   f"<form method=post><button style='font-size:20px;padding:.6em 1.4em'>{verbo}</button></form>")


@router.post("/reuniones/accion")
def accion_hacer(u: str, r: str, a: str, f: str):
    if not reuniones.verificar_enlace(u, r, a, f):
        return HTMLResponse("Enlace no válido.", status_code=403)
    texto = reuniones.pedir(u, r) if a == "grabar" else reuniones.no_grabar(u, r)
    return _pagina(texto)


@router.get("/apps/reuniones")
def pagina():
    return FileResponse(WEB / "apps-reuniones.html")
