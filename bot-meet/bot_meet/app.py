"""API del bot: Jarvis agenda y cancela; el monitor mira la salud."""
import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .agenda import Agenda, DatosInvalidos, LinkInvalido, Sesion, SinBotLibre
from .config import Config, leer_config
from .firma import verificar

CAMPOS = ("id", "meet_url", "inicio", "fin", "token_subida", "url_jarvis")


def _memoria_libre_mb():
    try:
        with open("/proc/meminfo") as f:
            for linea in f:
                if linea.startswith("MemAvailable:"):
                    return int(linea.split()[1]) // 1024
    except OSError:
        pass
    return None


def _carga():
    try:
        return os.getloadavg()[0]
    except (OSError, AttributeError):
        return None


def crear_app(config: Config, agenda: Agenda, lanzador=None) -> FastAPI:
    @asynccontextmanager
    async def vida(app):
        tarea = asyncio.create_task(lanzador.correr_siempre()) if lanzador else None
        yield
        if tarea:
            tarea.cancel()

    app = FastAPI(lifespan=vida, docs_url=None, redoc_url=None, openapi_url=None)

    async def firmado(peticion: Request) -> bytes | None:
        cuerpo = await peticion.body()
        ok = verificar(config.secreto, peticion.headers.get("X-Bot-Tiempo"),
                       peticion.headers.get("X-Bot-Firma"), peticion.method,
                       peticion.url.path, cuerpo)
        return cuerpo if ok else None

    @app.post("/v1/sesiones")
    async def agendar(peticion: Request):
        cuerpo = await firmado(peticion)
        if cuerpo is None:
            return JSONResponse({"error": "firma"}, status_code=401)
        try:
            d = json.loads(cuerpo)
            if not all(isinstance(d.get(k), str) and d.get(k) for k in CAMPOS):
                raise DatosInvalidos("campos")
            if not (d["url_jarvis"].startswith("https://") or d["url_jarvis"].startswith("http://127.0.0.1")):
                raise DatosInvalidos("url_jarvis")
            s = Sesion(id=d["id"], meet_url=d["meet_url"],
                       inicio=datetime.fromisoformat(d["inicio"]), fin=datetime.fromisoformat(d["fin"]),
                       token_subida=d["token_subida"], url_jarvis=d["url_jarvis"])
            agenda.agregar(s)
        except LinkInvalido:
            return JSONResponse({"error": "link_invalido"}, status_code=400)
        except SinBotLibre:
            return JSONResponse({"error": "sin_bot_libre"}, status_code=409)
        except (DatosInvalidos, ValueError, TypeError, AttributeError):
            return JSONResponse({"error": "datos_invalidos"}, status_code=400)
        return JSONResponse({"estado": "agendada"}, status_code=202)

    @app.delete("/v1/sesiones/{id_}")
    async def cancelar(id_: str, peticion: Request):
        if await firmado(peticion) is None:
            return JSONResponse({"error": "firma"}, status_code=401)
        if not agenda.cancelar(id_):
            return JSONResponse({"error": "no_existe"}, status_code=404)
        return {"estado": "cancelada"}

    @app.get("/v1/salud")
    async def salud():
        todas = agenda.todas()
        return {"ok": True, "activas": agenda.activas(),
                "agendadas": sum(1 for s in todas if s.estado == "agendada"),
                "memoria_libre_mb": _memoria_libre_mb(), "carga": _carga()}

    return app


def crear_app_desde_entorno() -> FastAPI:
    from .lanzador import Lanzador
    config = leer_config()
    agenda = Agenda(config.datos / "agenda.json", max_sesiones=config.max_sesiones)
    return crear_app(config, agenda, Lanzador(config, agenda))
