"""El cerebro de Jarvis.

Usa la Responses API en vez de Chat Completions porque es la unica que acepta
servidores MCP remotos: asi Supabase queda disponible sin escribir un cliente
MCP ni instalar nada local.
"""

import json
import os
from collections.abc import Iterator

from openai import OpenAI

from . import conectores, consultas, esquema, fuentes, herramientas, memoria

MAX_RONDAS_DE_HERRAMIENTAS = 6

# Cuantos mensajes previos ve el modelo. Se guardan mas para la pantalla.
TURNOS_DE_CONTEXTO = 12

_cliente: OpenAI | None = None


def cliente() -> OpenAI:
    """Crea el cliente la primera vez que se usa, no al importar.

    Asi el servidor arranca aunque falte la API key y podemos mostrar un
    error claro en la interfaz en vez de morir en el arranque.
    """
    global _cliente
    if _cliente is None:
        _cliente = OpenAI(api_key=clave_openai())
    return _cliente


def clave_openai() -> str:
    clave = os.getenv("OPENAI_API_KEY", "").strip()
    if not clave or clave.startswith("sk-pon-tu-clave"):
        raise RuntimeError(
            "Falta OPENAI_API_KEY. Abre el archivo .env y pon tu clave real."
        )
    return clave


def instrucciones() -> str:
    nombre = os.getenv("JARVIS_NOMBRE", "Jarvis")
    usuario = os.getenv("JARVIS_USUARIO", "el usuario")
    ciudad = os.getenv("JARVIS_CIUDAD", "")

    texto = f"""Eres {nombre}, el asistente personal de {usuario}.

Como hablas:
- En espanol, natural y directo. Tuteas a {usuario}.
- Tus respuestas se leen en voz alta, asi que escribe para el oido: frases
  cortas, sin markdown, sin vinetas, sin emojis, sin URLs largas.
- Se breve. Dos o tres frases salvo que te pidan detalle.
- Si no sabes algo, dilo. Nunca inventes datos.

Memoria:
- Cuando {usuario} mencione algo que valga la pena recordar (gustos, personas,
  proyectos, rutinas, decisiones), guardalo con `recordar` sin avisar ni pedir
  permiso. No interrumpas la conversacion para confirmarlo.
- Si te preguntan algo que deberias saber de antes, usa `buscar_memoria`.

Contexto: la ciudad por defecto de {usuario} es {ciudad or 'desconocida'}."""

    if conectores.supabase():
        modo = (
            "Estas en modo solo lectura: puedes consultar pero no modificar nada. "
            "Si te piden escribir, explica que no tienes permiso."
            if conectores.solo_lectura()
            else "Tienes permiso de escritura. Antes de modificar o borrar datos, "
            "confirma en voz alta que entendiste bien y espera un si."
        )
        texto += f"""

Base de datos (Supabase):
- Tienes acceso a la base de datos real de {usuario}. {modo}
- **Usa `consultar_datos` con una consulta del catalogo de abajo.** Estan ya
  escritas y probadas, responden en decimas de segundo. Es tu via principal.
- Solo si NINGUNA consulta del catalogo sirve, escribe SQL con `execute_sql`.
  Es varias veces mas lento, asi que es el ultimo recurso, no el primero.
- Nunca llames a list_tables: ya tienes el esquema completo mas abajo.
- Nunca anuncies lo que vas a hacer. Nada de "voy a buscarlo", "dejame revisar"
  ni "un momento". Consulta primero y habla solo cuando tengas el dato. El
  silencio mientras consultas es normal y esperado.
- Si la pregunta es ambigua, elige la interpretacion mas razonable, responde, y
  di brevemente que asumiste. No preguntes antes de consultar.
- Los resultados se leen en voz alta: resume. Di el total y lo relevante, no
  listas largas de filas. Redondea los numeros grandes: "diecisiete millones
  novecientos mil", no la cifra exacta al centavo.
- Nunca leas identificadores largos, hashes ni URLs en voz alta.

- Si necesitas escribir SQL a mano, pide antes las columnas con `ver_esquema`.
  No adivines nombres de columnas.

CATALOGO DE CONSULTAS (usalas con `consultar_datos`):
{consultas.catalogo_para_prompt()}

Tablas existentes, con su numero de filas:
{esquema.indice() or "(no disponible)"}"""

    otras = fuentes.resumen_para_prompt()
    if otras:
        texto += f"""

Otras fuentes de datos conectadas (con sus columnas ya incluidas):
{otras}

Como consultar estas fuentes:
- Para encontrar algo por su nombre —un producto, un cliente— usa
  `buscar_en_fuente` con las palabras tal cual las dijo {usuario}. Exige que
  aparezcan todas y devuelve las mejores primero. Una sola llamada.
- `consultar_fuente` con SQL solo para contar, sumar o agrupar.
- NO llames a `ver_esquema_fuente`: ya tienes las columnas aqui arriba. Solo si
  necesitaras una tabla que no aparezca.
- Busca antes de preguntar. Si {usuario} dice "el cable de 6", busca "cable 6"
  y ofrece lo que salga. Pedir precisiones antes de mirar es lo que mas molesta
  al hablar.
- Si salen varios parecidos, di cuantos hay y describe el primero. No los
  recites todos en voz alta.
- Si la pregunta no dice de que fuente es y hay varias, elige la que encaje por
  su nombre o sus notas, y menciona cual usaste."""

    texto += f"\n\nEsto es lo que ya sabes de {usuario}:\n{memoria.resumen_para_prompt()}"
    return texto


def catalogo_de_herramientas(con_conectores: bool = True) -> list[dict]:
    catalogo = list(herramientas.esquemas())
    if con_conectores:
        catalogo.extend(conectores.activos())
    return catalogo


def es_fallo_de_conector(error: Exception) -> bool:
    """Distingue 'el MCP no responde' de cualquier otro error.

    Importa porque un token de Supabase malo no debe dejar a Jarvis mudo para
    todo lo demas: si el conector falla, seguimos sin el.
    """
    return "MCP server" in str(error)


def responder(mensajes: list[dict]) -> Iterator[dict]:
    """Genera la respuesta como un flujo de eventos.

    Eventos posibles:
      {"tipo": "texto",       "dato": fragmento de texto}
      {"tipo": "herramienta", "dato": nombre de la herramienta en curso}
      {"tipo": "error",       "dato": mensaje para mostrar}
      {"tipo": "fin",         "dato": historial completo actualizado}
    """
    modelo = os.getenv("OPENAI_MODEL", "gpt-5.6-terra")

    try:
        api = cliente()
    except RuntimeError as error:
        yield {"tipo": "error", "dato": str(error)}
        return

    # Solo los ultimos turnos van al modelo. La pantalla sigue mostrando todo
    # y los hechos importantes viven en la memoria, asi que no se pierde nada
    # por recortar aqui: se gana latencia en cada peticion.
    entrada: list[dict] = [
        {"role": mensaje["role"], "content": mensaje["content"]}
        for mensaje in mensajes[-TURNOS_DE_CONTEXTO:]
        if mensaje.get("content")
    ]

    con_conectores = bool(conectores.activos())

    for _ in range(MAX_RONDAS_DE_HERRAMIENTAS):
        texto = ""
        salida: list = []

        try:
            flujo = api.responses.create(
                model=modelo,
                instructions=instrucciones(),
                input=entrada,
                tools=catalogo_de_herramientas(con_conectores),
                stream=True,
            )

            for evento in flujo:
                tipo = getattr(evento, "type", "")

                if tipo == "response.output_text.delta":
                    texto += evento.delta
                    yield {"tipo": "texto", "dato": evento.delta}

                elif tipo == "response.output_item.added":
                    nombre = nombre_de_herramienta(getattr(evento, "item", None))
                    if nombre:
                        yield {"tipo": "herramienta", "dato": nombre}

                elif tipo == "response.completed":
                    salida = list(evento.response.output)

                elif tipo == "error":
                    yield {"tipo": "error", "dato": str(getattr(evento, "message", evento))}
                    return

        except Exception as error:  # noqa: BLE001
            # Un conector caido no debe tumbar la conversacion entera:
            # avisamos y reintentamos sin el.
            if con_conectores and es_fallo_de_conector(error) and not texto:
                con_conectores = False
                yield {
                    "tipo": "aviso",
                    "dato": "No pude conectar con Supabase. Revisa el token en .env. "
                            "Sigo respondiendo sin acceso a la base de datos.",
                }
                continue

            yield {"tipo": "error", "dato": f"Se corto la respuesta: {error}"}
            return

        llamadas = [item for item in salida if getattr(item, "type", "") == "function_call"]

        # Sin funciones locales pendientes, la respuesta ya esta completa.
        # Las llamadas MCP las resuelve OpenAI antes de llegar aqui.
        if not llamadas:
            mensajes.append({"role": "assistant", "content": texto})
            memoria.guardar_conversacion(mensajes)
            yield {"tipo": "fin", "dato": mensajes}
            return

        entrada.extend(para_reenviar(item) for item in salida)

        for llamada in llamadas:
            resultado = herramientas.ejecutar(llamada.name, llamada.arguments)
            entrada.append(
                {
                    "type": "function_call_output",
                    "call_id": llamada.call_id,
                    "output": resultado,
                }
            )

    yield {
        "tipo": "error",
        "dato": "Me enrede usando herramientas y no llegue a una respuesta.",
    }


def para_reenviar(item) -> dict:
    """Deja un item de salida listo para volver como entrada.

    La API devuelve campos que solo tienen sentido de salida ('status', y los
    nulos) y los rechaza si se los mandamos de vuelta.
    """
    return {
        clave: valor
        for clave, valor in item.model_dump().items()
        if clave != "status" and valor is not None
    }


def nombre_de_herramienta(item) -> str | None:
    """Nombre legible de la herramienta que empieza a ejecutarse, si la hay."""
    tipo = getattr(item, "type", "")
    if tipo == "function_call":
        return getattr(item, "name", None)
    if tipo == "mcp_call":
        etiqueta = getattr(item, "server_label", "MCP")
        nombre = getattr(item, "name", "")
        return f"{etiqueta}: {nombre}" if nombre else etiqueta
    return None


def evento_sse(evento: dict) -> str:
    return f"data: {json.dumps(evento, ensure_ascii=False)}\n\n"


# --------------------------------------------------------------------------
# Modo voz en vivo (Realtime)
# --------------------------------------------------------------------------

def sesion_de_voz() -> dict:
    """Pide a OpenAI una credencial efimera para que el navegador se conecte.

    La API key real nunca sale de este servidor: el navegador recibe un token
    de un solo uso y vida corta.
    """
    import httpx

    modelo = os.getenv("OPENAI_MODELO_VOZ", "gpt-realtime-2.1-mini")
    voz = os.getenv("JARVIS_VOZ", "marin")

    configuracion = {
        "session": {
            "type": "realtime",
            "model": modelo,
            "instructions": instrucciones(),
            "audio": {
                "input": {
                    "transcription": {"model": "gpt-live-transcribe"},
                },
                "output": {"voice": voz},
            },
            "tools": catalogo_de_herramientas(),
            "tool_choice": "auto",
        }
    }

    with httpx.Client(timeout=30) as http:
        respuesta = http.post(
            "https://api.openai.com/v1/realtime/client_secrets",
            headers={
                "Authorization": f"Bearer {clave_openai()}",
                "Content-Type": "application/json",
            },
            json=configuracion,
        )

    if respuesta.status_code >= 400:
        raise RuntimeError(f"OpenAI rechazo la sesion de voz: {respuesta.text}")

    datos = respuesta.json()
    return {"token": datos["value"], "modelo": modelo, "voz": voz}
