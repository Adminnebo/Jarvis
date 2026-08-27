"""El cerebro de Jarvis.

Usa la Responses API en vez de Chat Completions porque es la unica que acepta
servidores MCP remotos: asi Supabase queda disponible sin escribir un cliente
MCP ni instalar nada local.
"""

import json
import os
from collections.abc import Iterator

from openai import OpenAI

from . import (
    conectores,
    consultas,
    consumo,
    esquema,
    fuentes,
    herramientas,
    memoria,
)

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


def instrucciones(extra: str = "") -> str:
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

Cuando consultas algo:
- Al llamar a una herramienta NO pidas confirmacion. Se proactivo: en cuanto
  entiendas la intencion, ejecutala.
- NO anuncies lo que vas a hacer. Nada de "voy a buscarlo", "dejame revisar",
  "un momento" ni "ahora te digo". Consulta y habla cuando tengas el dato: el
  silencio de un segundo es normal y esperado.
- **Nunca cierres un turno prometiendo una consulta que no hiciste.** Si tu
  ultima frase iba a ser "lo busco" o "intento de nuevo", buscalo ahora y
  responde con el resultado. Si no pudiste, di por que.
- Tampoco anuncies cuando la respuesta es directa, cuando {usuario} solo esta
  confirmando o corrigiendo algo, ni cuando lo ultimo que oiste fue silencio,
  ruido de fondo o una conversacion ajena.
- Si la pregunta es ambigua, elige la interpretacion mas razonable, responde, y
  di brevemente que asumiste. No preguntes antes de consultar.
- Si no entendiste bien el audio, pregunta lo justo y sigue. No repitas lo que
  creiste oir palabra por palabra.
- Los resultados se leen en voz alta: resume. Di el total y lo relevante, no
  listas largas de filas. Redondea los numeros grandes: "diecisiete millones
  novecientos mil", no la cifra exacta al centavo.
- Nunca leas identificadores largos, hashes ni URLs en voz alta.

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
  su nombre o sus notas, y menciona cual usaste.
- **Las notas de cada fuente son reglas de negocio de {usuario}. Obedecelas al
  pie de la letra**: dicen que columna usar y como llamar a las cosas. Si una
  nota fija que precio dar, da ese y no menciones los demas salvo que te los
  pidan.
- Nunca leas en voz alta el nombre tecnico de una columna. Di "cuesta 164.44",
  no "el P1 es 164.44"."""

    texto += f"\n\nEsto es lo que ya sabes de {usuario}:\n{memoria.resumen_para_prompt()}"

    # Instruccion de un solo turno: la manda el cliente (un reloj pide frases
    # cortas) y va aqui, no en el mensaje del usuario. Metida en el mensaje
    # quedaria en el historial y seguiria condicionando los turnos siguientes,
    # incluidos los de otros clientes que comparten la conversacion.
    if extra:
        texto += f"\n\n{extra}"

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


def responder(mensajes: list[dict], extra: str = "") -> Iterator[dict]:
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
                instructions=instrucciones(extra),
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
                    anotar_consumo(modelo, getattr(evento.response, "usage", None))

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


def anotar_consumo(modelo: str, uso) -> None:
    """Guarda el gasto del turno. Nunca debe tumbar la respuesta."""
    if uso is None:
        return
    try:
        datos = uso.model_dump() if hasattr(uso, "model_dump") else dict(uso)
        consumo.registrar("texto", modelo, datos)
    except Exception:  # noqa: BLE001 - contabilizar no es critico
        pass


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

def deteccion_de_turno() -> dict:
    """Cuando decide el modelo que terminaste de hablar.

    Los valores por defecto de OpenAI estan pensados para un sitio silencioso.
    Con ruido de fondo cortan a media frase y, peor, un golpe o una voz ajena
    interrumpen a Jarvis mientras habla. Se sube el umbral y se alarga el
    silencio necesario, a costa de un pelin mas de espera al final de la frase.
    """
    return {
        "type": "server_vad",
        # Moderado a proposito: quien filtra el ruido mientras Jarvis habla es
        # la puerta del navegador, que distingue un golpe de una voz por su
        # duracion. Subirlo aqui solo obligaria a hablar mas fuerte siempre.
        "threshold": float(os.getenv("JARVIS_UMBRAL_VOZ", "0.55")),
        # Audio que se conserva justo antes de detectar voz, para no comerse
        # la primera silaba.
        "prefix_padding_ms": 300,
        # Cuanto silencio hace falta para dar el turno por terminado. Subirlo
        # evita que una pausa para pensar corte la frase.
        "silence_duration_ms": int(os.getenv("JARVIS_SILENCIO_MS", "700")),
        "create_response": True,
        # Se le puede hablar encima para cortarlo, como a una persona.
        "interrupt_response": os.getenv("JARVIS_INTERRUMPIBLE", "true").lower() != "false",
    }


def puerta_de_microfono() -> dict:
    """Ajustes de la puerta que corre en el navegador.

    `umbral` es el volumen minimo para considerar que hay alguien hablando, y
    `sostenido_ms` cuanto debe mantenerse. Ahi esta la diferencia entre un
    ruido y una persona: el ruido no dura.
    """
    return {
        "umbral": float(os.getenv("JARVIS_PUERTA_UMBRAL", "0.045")),
        "sostenido_ms": int(os.getenv("JARVIS_PUERTA_SOSTENIDO_MS", "220")),
    }


def configuracion_de_sesion() -> dict:
    modelo = os.getenv("OPENAI_MODELO_VOZ", "gpt-realtime-2.1")

    return {
        "type": "realtime",
        "model": modelo,
        "instructions": instrucciones(),
        # Cuanto piensa antes de hablar. 'low' es el punto recomendado para
        # agentes de voz; 'minimal' responde antes pero acierta menos con las
        # herramientas, y aqui casi todo turno lleva una consulta.
        "reasoning": {"effort": os.getenv("JARVIS_ESFUERZO", "low")},
        "audio": {
            "input": {
                # Sin idioma fijo, el transcriptor lo adivina en cada turno y
                # con frases cortas o ruido se va a otro idioma: una pregunta
                # de dos palabras volvia transcrita en coreano.
                "transcription": {
                    "model": "gpt-live-transcribe",
                    "language": os.getenv("JARVIS_IDIOMA", "es"),
                },
                # Filtra el ruido antes de que llegue al detector de voz, asi
                # que mejora tambien la deteccion de turnos.
                # far_field = microfono de portatil o de sala.
                # near_field = diadema o microfono pegado a la boca.
                "noise_reduction": {
                    "type": os.getenv("JARVIS_MICROFONO", "far_field")
                },
                "turn_detection": deteccion_de_turno(),
            },
            "output": {"voice": os.getenv("JARVIS_VOZ", "marin")},
        },
        "tools": catalogo_de_herramientas(),
        "tool_choice": "auto",
    }


def ajustes_de_voz() -> dict:
    """Lo que el navegador necesita saber antes de conectar."""
    return {
        "modelo": os.getenv("OPENAI_MODELO_VOZ", "gpt-realtime-2.1"),
        "voz": os.getenv("JARVIS_VOZ", "marin"),
        "puerta": puerta_de_microfono(),
    }


def negociar_webrtc(sdp_oferta: str) -> str:
    """Hace el intercambio SDP con OpenAI en nombre del navegador.

    El navegador no puede llamar a api.openai.com directamente: el navegador
    bloquea la peticion por CORS en cuanto la pagina no se sirve desde
    localhost. Ademas, pasando por aqui la API key nunca llega al cliente y no
    hacen falta credenciales efimeras.
    """
    import httpx

    with httpx.Client(timeout=60) as http:
        respuesta = http.post(
            "https://api.openai.com/v1/realtime/calls",
            headers={"Authorization": f"Bearer {clave_openai()}"},
            # Multipart con dos campos sueltos: el SDP crudo y la sesion.
            files={
                "sdp": (None, sdp_oferta),
                "session": (None, json.dumps(configuracion_de_sesion())),
            },
        )

    if respuesta.status_code >= 400:
        raise RuntimeError(f"OpenAI rechazo la sesion de voz: {respuesta.text[:400]}")

    return respuesta.text
