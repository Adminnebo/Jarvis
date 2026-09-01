"""Servidor local de Jarvis. Sirve la interfaz web y la API de chat."""

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

RAIZ = Path(__file__).resolve().parent.parent

# override=True para que .env gane siempre: sin esto, al recargar el servidor
# se quedan pegados los valores viejos del proceso padre y editar .env parece
# no tener efecto.
load_dotenv(RAIZ / ".env", override=True)

from . import (  # noqa: E402 - despues de load_dotenv a proposito
    acceso,
    cerebro,
    conectores,
    consumo,
    esquema,
    fuentes,
    herramientas,
    memoria,
    rutas,
    version,
)

WEB = RAIZ / "web"

app = FastAPI(title="Jarvis")


@app.on_event("startup")
def al_arrancar():
    # Antes que nada: en un servidor el disco viene vacio y las fuentes hay
    # que recrearlas, o no habria acceso a la base de productos.
    creadas = fuentes.sembrar_desde_entorno()
    if creadas:
        print(f"  Fuentes recreadas desde JARVIS_FUENTES: {', '.join(creadas)}")

    if acceso.obligatorio():
        print(
            "\n  AVISO: Jarvis esta hospedado y no hay JARVIS_PASSWORD.\n"
            "  No se servira nada hasta que definas esa variable.\n"
        )
    # Traer el esquema ahora evita que la primera pregunta sobre la base de
    # datos pague el costo de descubrirlo.
    esquema.refrescar_en_segundo_plano()

    # Y mantener las conexiones calientes evita que la pague en reconectar.
    fuentes.vigilar_conexiones()


@app.middleware("http")
async def guardia(peticion: Request, siguiente):
    """Nadie pasa sin contrasena cuando esto corre en un servidor."""
    ruta = peticion.url.path

    if acceso.es_libre(ruta):
        return await siguiente(peticion)

    if acceso.obligatorio():
        return HTMLResponse(acceso.pagina_sin_proteger(), status_code=503)

    if acceso.protegido() and not acceso.token_valido(peticion.cookies.get(acceso.COOKIE)):
        # A la interfaz le mostramos el formulario; a la API, un 401 limpio.
        if ruta.startswith("/api/"):
            return JSONResponse(status_code=401, content={"error": "No autorizado."})
        return HTMLResponse(acceso.pagina_login(), status_code=401)

    return await siguiente(peticion)


@app.get("/api/salud")
def salud():
    """Comprobacion de vida para el proveedor. No revela nada."""
    return {"ok": True}


@app.get("/api/version")
def version_actual():
    """Libre de autenticacion: la usa la pagina para detectar despliegues."""
    return version.info()


@app.get("/acceso")
def formulario_de_acceso():
    return HTMLResponse(acceso.pagina_login())


@app.post("/acceso")
async def entrar(clave: str = Form("")):
    if not acceso.protegido():
        return RedirectResponse("/", status_code=303)

    if not acceso.clave_correcta(clave):
        return HTMLResponse(
            acceso.pagina_login("Contrasena incorrecta."), status_code=401
        )

    respuesta = RedirectResponse("/", status_code=303)
    respuesta.set_cookie(
        acceso.COOKIE,
        acceso.crear_token(),
        max_age=acceso.DURACION,
        httponly=True,
        samesite="lax",
        secure=rutas.hospedado(),   # en local va por http, ahi no aplica
    )
    return respuesta


class PeticionDeChat(BaseModel):
    mensaje: str
    # El cliente puede pedir respuestas cortas para su pantalla. Va aparte del
    # mensaje a proposito: dentro quedaria en el historial y seguiria acortando
    # las respuestas de los demas clientes, que comparten la conversacion.
    breve: bool = False


class PeticionDeHerramienta(BaseModel):
    nombre: str
    argumentos: str = "{}"


class MensajeSuelto(BaseModel):
    role: str
    content: str


@app.get("/api/estado")
def estado():
    clave = os.getenv("OPENAI_API_KEY", "").strip()
    return {
        "nombre": os.getenv("JARVIS_NOMBRE", "Jarvis"),
        "usuario": os.getenv("JARVIS_USUARIO", ""),
        "modelo": os.getenv("OPENAI_MODEL", "gpt-5.6-terra"),
        "modelo_voz": os.getenv("OPENAI_MODELO_VOZ", "gpt-realtime-2.1-mini"),
        "clave_configurada": bool(clave) and not clave.startswith("sk-pon-tu-clave"),
        "hechos_recordados": len(memoria.todos_los_hechos()),
        "historial": memoria.cargar_conversacion(),
        "conectores": conectores.resumen(),
        "esquema": esquema.info(),
        "version": version.info(),
    }


@app.post("/api/esquema/refrescar")
def refrescar_esquema():
    """Para cuando cambies la base de datos y Jarvis siga viendo lo viejo."""
    return {"ok": esquema.refrescar() is not None, "esquema": esquema.info()}


@app.post("/api/chat")
def chat(peticion: PeticionDeChat):
    mensajes = memoria.cargar_conversacion()
    mensajes.append({"role": "user", "content": peticion.mensaje})

    extra = (
        "Respondes en la pantalla de un reloj y en voz alta: maximo dos frases, "
        "sin listas ni encabezados."
        if peticion.breve
        else ""
    )

    def flujo():
        for evento in cerebro.responder(mensajes, extra):
            yield cerebro.evento_sse(evento)

    return StreamingResponse(
        flujo(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/fuentes/tipos")
def tipos_de_fuente():
    """Los campos de cada motor. La interfaz dibuja los formularios con esto."""
    return fuentes.tipos_para_interfaz()


@app.get("/api/fuentes")
def listar_fuentes():
    return {"fuentes": fuentes.para_interfaz()}


@app.post("/api/fuentes")
def guardar_fuente(datos: dict):
    try:
        return fuentes.guardar(datos)
    except ValueError as error:
        return JSONResponse(status_code=400, content={"error": str(error)})


@app.delete("/api/fuentes/{id_fuente}")
def borrar_fuente(id_fuente: str):
    return {"borrado": fuentes.borrar(id_fuente)}


@app.post("/api/fuentes/probar")
def probar_fuente(datos: dict):
    return fuentes.probar(datos)


@app.get("/api/fuentes/salud")
def salud_de_fuentes(refrescar: bool = False):
    """Si todas las bases responden. Alimenta el LED verde de la cabecera."""
    return fuentes.salud(refrescar=refrescar)


@app.get("/api/fuentes/{id_fuente}/esquema")
def esquema_de_fuente(id_fuente: str):
    try:
        return fuentes.esquema_de(id_fuente)
    except Exception as error:  # noqa: BLE001
        return JSONResponse(status_code=400, content={"error": fuentes.explicar(error)})


@app.post("/api/fuentes/{id_fuente}/consultar")
def consultar_fuente(id_fuente: str, datos: dict):
    """Consola de SQL de la interfaz. Respeta el modo solo lectura."""
    try:
        filas = fuentes.consultar(id_fuente, datos.get("sql", ""), limite=200)
        return {"filas": filas, "total": len(filas)}
    except ValueError as error:
        return JSONResponse(status_code=400, content={"error": str(error)})
    except Exception as error:  # noqa: BLE001
        return JSONResponse(status_code=400, content={"error": fuentes.explicar(error)})


@app.get("/api/voz/config")
def config_de_voz():
    """Lo que el navegador necesita antes de abrir el microfono."""
    return cerebro.ajustes_de_voz()


@app.get("/api/voz/sesion")
def sesion_de_voz():
    """Configuracion completa de la sesion de voz: instrucciones + herramientas.

    La usa el puente del reloj para levantar un modo de voz alterno (Gemini
    Live) con exactamente el mismo cerebro y las mismas herramientas que la voz
    de OpenAI. Es de solo lectura y no altera el flujo existente.
    """
    return cerebro.configuracion_de_sesion()


@app.post("/api/voz/sdp")
async def negociar_voz(peticion: Request):
    """Intercambio SDP con OpenAI por cuenta del navegador.

    El navegador no puede hablar con api.openai.com directamente: lo bloquea
    CORS en cuanto la pagina no viene de localhost. Pasando por aqui, ademas,
    la API key no sale nunca del servidor.
    """
    oferta = (await peticion.body()).decode("utf-8")
    if not oferta.strip():
        return JSONResponse(status_code=400, content={"error": "Falta el SDP."})

    try:
        respuesta = cerebro.negociar_webrtc(oferta)
    except Exception as error:  # noqa: BLE001
        return JSONResponse(status_code=502, content={"error": str(error)})

    return Response(content=respuesta, media_type="application/sdp")


@app.post("/api/herramienta")
def ejecutar_herramienta(peticion: PeticionDeHerramienta):
    """Ejecuta una funcion local que pidio la sesion de voz.

    En modo voz el modelo habla directo con el navegador, asi que las
    herramientas que viven en este servidor pasan por aqui. Las de Supabase no:
    esas las resuelve OpenAI contra el MCP sin tocarnos.
    """
    return {"resultado": herramientas.ejecutar(peticion.nombre, peticion.argumentos)}


@app.post("/api/conversacion/agregar")
def agregar_a_conversacion(mensaje: MensajeSuelto):
    """Guarda un turno de voz para que texto y voz compartan historial."""
    mensajes = memoria.cargar_conversacion()
    mensajes.append({"role": mensaje.role, "content": mensaje.content})
    memoria.guardar_conversacion(mensajes)
    return {"ok": True}


@app.get("/api/consumo")
def ver_consumo(periodo: str = "7d", modo: str = "todos", modelo: str = "todos"):
    """Tokens y dolares, con los filtros del tablero."""
    return consumo.consultar(periodo=periodo, modo=modo, modelo=modelo)


@app.post("/api/consumo/voz")
def anotar_consumo_de_voz(datos: dict):
    """Lo manda el navegador: en voz el uso llega por el canal de datos."""
    modelo = datos.get("modelo") or os.getenv("OPENAI_MODELO_VOZ", "gpt-realtime-2.1")

    if datos.get("segundos_sesion"):
        return consumo.registrar_sesion(modelo, float(datos["segundos_sesion"]))

    return consumo.registrar("voz", modelo, datos.get("uso") or {})


@app.delete("/api/consumo")
def borrar_consumo():
    consumo.borrar()
    return {"ok": True}


@app.get("/api/memoria")
def ver_memoria():
    return {"hechos": memoria.todos_los_hechos()}


@app.delete("/api/memoria/{id_hecho}")
def borrar_hecho(id_hecho: str):
    return {"borrado": memoria.olvidar(id_hecho)}


@app.post("/api/conversacion/reiniciar")
def reiniciar_conversacion():
    memoria.borrar_conversacion()
    return {"ok": True}


@app.get("/")
def inicio():
    return FileResponse(WEB / "index.html")


app.mount("/", StaticFiles(directory=WEB), name="web")
