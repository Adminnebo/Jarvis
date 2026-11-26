"""Grabar reuniones de Meet con el bot: quién pide, qué se le manda, qué vuelve.

El aviso previo (calendario._avisar) llama a proponer(). Con "Grabar siempre"
se pide solo; si no, el aviso trae Grabar / No grabar. Lo que el bot sube llega
por rutas_reuniones.py y lo procesa reuniones_trabajo.py.
Ver docs/superpowers/specs/2026-11-24-bot-grabacion-meet-design.md.
"""

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from . import bot_meet, rutas
from . import reuniones_datos as rd

PATRON = re.compile(r"(?:https://)?meet\.google\.com/([a-z]{3}-[a-z]{4}-[a-z]{3})")
BASE = "https://asistente.neboaiconsulting.com"
PIDE_BOT = ("propuesta", "cancelada", "sin_bot")


def link_meet(evento: dict) -> str | None:
    lugares = [((evento.get("conferencing") or {}).get("url") or ""),
               evento.get("location") or "", evento.get("description") or ""]
    for texto in lugares:
        m = PATRON.search(texto)
        if m:
            return f"https://meet.google.com/{m.group(1)}"
    return None


def proponer(usuario_id: str, evento: dict) -> dict | None:
    """La reunión de ese evento (creada si hace falta), o None si no aplica."""
    url = link_meet(evento)
    if not url or not bot_meet.configurado():
        return None
    codigo = url.rsplit("/", 1)[1]
    return rd.crear_o_obtener(f"{codigo}@{evento['start'][:16]}", url, evento.get("title") or "Reunión",
                              evento["start"], evento["end"])


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def token_valido(reunion_id: str, token: str) -> bool:
    r = rd.obtener(reunion_id)
    return bool(r and r["token_hash"] and token and hmac.compare_digest(r["token_hash"], _hash(token)))


def pedir(usuario_id: str, reunion_id: str) -> str:
    r = rd.obtener(reunion_id)
    if r is None:
        return "No encontré esa reunión."
    rd.interesar(reunion_id, usuario_id, True)
    if r["estado"] not in PIDE_BOT:
        return f"Listo, «{r['titulo']}» ya se va a grabar."
    token = secrets.token_urlsafe(32)
    try:
        bot_meet.agendar(reunion_id, r["meet_url"], r["inicio"], r["fin"], token)
    except bot_meet.SinBotLibre:
        rd.actualizar(reunion_id, estado="sin_bot")
        return f"No hay bot libre para grabar «{r['titulo']}»: ya hay dos reuniones grabándose a esa hora."
    except bot_meet.ErrorBot as error:
        print(f"  AVISO: no pude agendar el bot para {reunion_id}: {error}")
        return f"No pude mandar el bot a «{r['titulo']}». Inténtalo de nuevo en un momento."
    rd.actualizar(reunion_id, estado="agendada", token_hash=_hash(token), motivo=None)
    return f"Listo, voy a grabar «{r['titulo']}»."


def no_grabar(usuario_id: str, reunion_id: str) -> str:
    r = rd.obtener(reunion_id)
    if r is None:
        return "No encontré esa reunión."
    rd.interesar(reunion_id, usuario_id, False)
    if not rd.interesados(reunion_id) and r["estado"] == "agendada":
        try:
            bot_meet.cancelar(reunion_id)
        except bot_meet.ErrorBot as error:
            print(f"  AVISO: no pude cancelar el bot de {reunion_id}: {error}")
        rd.actualizar(reunion_id, estado="cancelada")
    return f"Listo, no grabo «{r['titulo']}»."


# --------------------------------------------------------------------------
# Enlace firmado de WhatsApp (Grabar / No grabar sin sesión)
# --------------------------------------------------------------------------

def _clave() -> bytes:
    from . import secretos
    return secretos.clave()


def _firma(usuario_id: str, reunion_id: str, accion: str) -> str:
    return hmac.new(_clave(), f"{usuario_id}|{reunion_id}|{accion}".encode(), hashlib.sha256).hexdigest()[:32]


def enlace(usuario_id: str, reunion_id: str, accion: str) -> str:
    q = {"u": usuario_id, "r": reunion_id, "a": accion, "f": _firma(usuario_id, reunion_id, accion)}
    return f"{BASE}/reuniones/accion?{urlencode(q)}"


def verificar_enlace(usuario_id: str, reunion_id: str, accion: str, firma: str) -> bool:
    if accion not in ("grabar", "no_grabar"):
        return False
    return hmac.compare_digest(_firma(usuario_id, reunion_id, accion), firma or "")


# --------------------------------------------------------------------------
# Lo que sube el bot
# --------------------------------------------------------------------------

ESTADOS = {"esperando": "esperando", "admitido": "grabando", "rechazado": "rechazada",
           "fallo": "fallida", "terminado": "procesando"}
MOTIVOS = {"sin_respuesta": "nadie lo admitió", "rechazado": "lo rechazaron",
           "sesion_google": "se cerró la sesión de Google del bot",
           "sin_boton_unirse": "Meet cambió su página"}


def _avisar(reunion_id: str, texto: str) -> None:
    from . import avisos
    for usuario_id in rd.interesados(reunion_id):
        avisos.crear(usuario_id, f"reunion-estado:{reunion_id}:{texto[:40]}", reunion_id, "Bot de reuniones",
                     "", texto, con_whatsapp=True, tipo="sistema", app="reuniones")


def recibir_evento(reunion_id: str, datos: dict) -> None:
    tipo = datos.get("tipo")
    if tipo not in ESTADOS:
        return
    r = rd.obtener(reunion_id)
    if tipo == "rechazado" and datos.get("motivo") == "cancelada":
        # Lo sacaron desde Jarvis mientras esperaba entrar: no es un rechazo.
        rd.actualizar(reunion_id, estado="cancelada", motivo="cancelada")
        return
    cambios = {"estado": ESTADOS[tipo]}
    if tipo == "terminado":
        cambios.update(terminada=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                       incompleta=int(bool(datos.get("incompleta"))), motivo=datos.get("motivo"))
    elif tipo in ("rechazado", "fallo"):
        cambios["motivo"] = datos.get("motivo")
    elif tipo == "admitido" and not r.get("grabando_desde"):
        cambios["grabando_desde"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rd.actualizar(reunion_id, **cambios)
    motivo = MOTIVOS.get(datos.get("motivo") or "", datos.get("motivo") or "")
    if tipo == "rechazado":
        _avisar(reunion_id, f"No me dejaron entrar a «{r['titulo']}» ({motivo}).")
    elif tipo == "fallo":
        _avisar(reunion_id, f"No pude entrar a «{r['titulo']}»: {motivo}.")


# Content-Type del pedazo → extensión. El bot manda ogg; Chrome/Android webm; Safari mp4.
FORMATOS = {"audio/ogg": "ogg", "audio/webm": "webm", "audio/mp4": "mp4", "": "ogg"}


def formato_de(content_type: str | None) -> str | None:
    return FORMATOS.get((content_type or "").split(";")[0].strip().lower())


def ruta_pedazo(reunion_id: str, n: int, formato: str = "ogg") -> Path:
    carpeta = Path(rutas.archivo(f"reuniones/{reunion_id}"))
    carpeta.mkdir(parents=True, exist_ok=True)
    return carpeta / f"{n:05d}.{formato or 'ogg'}"


def recibir_audio(reunion_id: str, n: int, datos: bytes, formato: str = "ogg",
                  inicio_s: int | None = None) -> bool:
    if not rd.guardar_pedazo(reunion_id, n, formato, inicio_s):
        return False
    ruta = ruta_pedazo(reunion_id, n, formato)
    tmp = ruta.with_suffix(".tmp")
    tmp.write_bytes(datos)
    tmp.replace(ruta)
    return True


def recibir_hablantes(reunion_id: str, linea: list) -> None:
    rd.actualizar(reunion_id, linea=linea if isinstance(linea, list) else [])


# --------------------------------------------------------------------------
# Grabar un Meet que no está en el calendario (pegando el link)
# --------------------------------------------------------------------------

DURACION_LINK = timedelta(hours=2)   # el bot sale antes si se queda solo
ZONA = ZoneInfo("America/Santo_Domingo")


def grabar_link(usuario_id: str, link: str, titulo: str = "") -> str:
    """Manda el bot ya a un Meet suelto (creado al momento, sin evento)."""
    if not bot_meet.configurado():
        return "El bot de reuniones no está configurado en este Jarvis."
    url = link_meet({"description": link or ""})
    if url is None:
        return "Eso no es un link de Google Meet (tiene que ser meet.google.com/xxx-xxxx-xxx)."
    ahora = datetime.now(ZONA).replace(microsecond=0)
    evento = {"title": (titulo or "").strip() or f"Meet de las {ahora:%H:%M}",
              "start": ahora.isoformat(), "end": (ahora + DURACION_LINK).isoformat(),
              "conferencing": {"url": url}}
    reunion = proponer(usuario_id, evento)
    return pedir(usuario_id, reunion["id"])


# --------------------------------------------------------------------------
# En curso: qué está grabando el bot y sacarlo
# --------------------------------------------------------------------------

ORDEN_EN_CURSO = {"grabando": 0, "esperando": 1, "agendada": 2}
VENCE_DESPUES = timedelta(minutes=15)   # lo mismo que espera el bot después del fin


def en_curso(usuario_id: str) -> list[dict]:
    """Grabando, esperando que lo admitan o agendadas (en ese orden), de las que pidió la
    persona. Una agendada cuya hora ya pasó no sale: el bot nunca entró y no va a entrar."""
    ahora = datetime.now(timezone.utc)
    salida = []
    for r in rd.en_curso_de(usuario_id):
        if r["estado"] == "agendada":
            try:
                if datetime.fromisoformat(r["fin"]) + VENCE_DESPUES < ahora:
                    continue
            except ValueError:
                pass
        salida.append({"id": r["id"], "titulo": r["titulo"], "estado": r["estado"], "inicio": r["inicio"],
                       "grabando_desde": r.get("grabando_desde"), "meet_url": r["meet_url"]})
    return sorted(salida, key=lambda x: (ORDEN_EN_CURSO[x["estado"]], x["inicio"]))


def sacar(usuario_id: str, reunion_id: str) -> str:
    """Saca al bot (para todos). Lo grabado hasta ahora se transcribe y resume igual:
    el bot, al salir, manda su "terminado" con motivo cancelada."""
    r = rd.obtener(reunion_id)
    if r is None or not rd.puede_ver(reunion_id, usuario_id):
        return "No encontré esa reunión."
    if r["estado"] not in rd.EN_CURSO:
        return f"El bot ya no está en «{r['titulo']}»."
    try:
        bot_meet.cancelar(reunion_id)
    except bot_meet.ErrorBot as error:
        print(f"  AVISO: no pude sacar al bot de {reunion_id}: {error}")
        return f"No pude sacar al bot de «{r['titulo']}». Inténtalo de nuevo en un momento."
    if r["estado"] == "agendada":   # todavía no había entrado: no hay nada que procesar
        rd.actualizar(reunion_id, estado="cancelada")
        return f"Listo, el bot no va a entrar a «{r['titulo']}»."
    return f"Listo, saco al bot de «{r['titulo']}». Lo grabado hasta ahora se resume en unos minutos."
