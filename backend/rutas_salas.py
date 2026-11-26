"""Rutas de la sala de una reunión presencial (salas.py).

Las de quien organiza van con su sesión. Las del participante son libres (lo revisa
cada ruta, no la sesión): un invitado entra sin cuenta con el código de la sala, y
después cada paquete de niveles lleva su token de participante. Si quien entra
tiene sesión de Jarvis, se usa para su nombre y para mandarle el resumen.
"""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from . import acceso, salas
from . import reuniones_datos as rd

WEB = Path(__file__).resolve().parent.parent / "web"
router = APIRouter()


def _con_sesion(peticion: Request):
    """Quien entra a una ruta libre, si trae sesión de Jarvis (si no, None)."""
    if not acceso.protegido():
        return acceso.por_defecto()
    return acceso.usuario_de_token(peticion.cookies.get(acceso.COOKIE))


# --- quien organiza (con sesión) ----------------------------------------------

@router.get("/api/reuniones/equipo")
def equipo(peticion: Request):
    return {"equipo": salas.equipo(peticion.state.usuario)}


def _suya(peticion: Request, reunion_id: str) -> dict | None:
    r = rd.obtener(reunion_id)
    if r is None or not r.get("sala") or not rd.puede_ver(reunion_id, peticion.state.usuario.id):
        return None
    return r


@router.get("/api/reuniones/{reunion_id}/sala")
def ver_sala(reunion_id: str, peticion: Request):
    r = _suya(peticion, reunion_id)
    if r is None:
        return JSONResponse(status_code=404, content={"error": "No existe."})
    return {"codigo": r["sala"], "link": salas.link(r["sala"]), "abierta": salas.abierta(r),
            "participantes": salas.participantes(reunion_id)}


@router.get("/api/reuniones/{reunion_id}/sala/qr.svg")
def qr(reunion_id: str, peticion: Request):
    import io

    import segno
    r = _suya(peticion, reunion_id)
    if r is None:
        return JSONResponse(status_code=404, content={"error": "No existe."})
    salida = io.BytesIO()
    segno.make(salas.link(r["sala"]), error="m").save(salida, kind="svg", scale=6, border=2,
                                                       dark="#111", light="#fff", xmldecl=False)
    return Response(salida.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "private, max-age=3600"})


class Invitacion(BaseModel):
    usuarios: list[str]


@router.post("/api/reuniones/{reunion_id}/invitar")
def invitar(reunion_id: str, peticion: Request, datos: Invitacion):
    if _suya(peticion, reunion_id) is None:
        return JSONResponse(status_code=404, content={"error": "No existe."})
    return {"enviadas": salas.invitar(peticion.state.usuario, reunion_id, datos.usuarios[:50])}


# --- participante (libres) -----------------------------------------------------

@router.get("/sala/{codigo}")
def pagina(codigo: str):
    return FileResponse(WEB / "sala.html")


@router.get("/api/salas/{codigo}")
def estado(codigo: str, peticion: Request):
    r = salas.por_codigo(codigo)
    if r is None:
        return JSONResponse(status_code=404, content={"error": "Esa sala no existe."})
    yo = _con_sesion(peticion)
    return {"titulo": r["titulo"], "abierta": salas.abierta(r), "nombre": yo.nombre if yo else ""}


class Unirse(BaseModel):
    nombre: str = ""


@router.post("/api/salas/{codigo}/unirse")
def unirse(codigo: str, peticion: Request, datos: Unirse):
    if salas.por_codigo(codigo) is None:
        return JSONResponse(status_code=404, content={"error": "Esa sala no existe."})
    x = salas.unirse(codigo, datos.nombre, _con_sesion(peticion))
    if x == "cerrada":
        return JSONResponse(status_code=409, content={"error": "La reunión ya terminó."})
    if x == "nombre":
        return JSONResponse(status_code=400, content={"error": "Escribe tu nombre."})
    return x


class Niveles(BaseModel):
    participante: str
    token: str
    desde_ms: int
    niveles: list[float]


@router.post("/api/salas/{codigo}/niveles")
def niveles(codigo: str, datos: Niveles):
    seguir = salas.guardar_niveles(codigo, datos.participante, datos.token, datos.desde_ms, datos.niveles)
    if seguir is None:
        return JSONResponse(status_code=401, content={"error": "token"})
    return {"seguir": seguir}
