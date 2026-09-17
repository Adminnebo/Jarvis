"""Mandar fotos, fichas tecnicas y cotizaciones a un numero de WhatsApp.

Va por Evolution API, que maneja un numero como WhatsApp Web. Un mensaje
mandado no se puede deshacer, asi que siempre en dos pasos: preparar() arma el
envio y devuelve el resumen para leerselo a la persona; confirmar() lo manda
solo despues del "si". Con voz esto importa: un numero mal oido le llega a otro.

WhatsApp bloquea numeros que mandan mucho a gente que no les escribio, asi que
hay un tope por hora. Cada envio queda anotado en data/envios_whatsapp.jsonl.
"""

import json
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

import httpx

from . import rutas

MAX_POR_HORA = 20
VIGENCIA_PENDIENTE = 10 * 60
MAX_ARCHIVOS = 10
MARCA = "JH Electroalambres"

# Enlace firmado para las cotizaciones (bucket privado): Evolution lo descarga
# en el momento, asi que basta con pocos minutos.
FIRMA_ENVIO = 600

PREFIJOS_RD = ("809", "829", "849")


class ErrorEnvio(Exception):
    """Un problema que el modelo puede explicar o corregir."""


def _env(nombre: str) -> str:
    return os.getenv(nombre, "").strip()


def configurado() -> bool:
    return all(_env(v) for v in ("EVOLUTION_URL", "EVOLUTION_API_KEY", "EVOLUTION_INSTANCIA"))


# --------------------------------------------------------------------------
# Numeros
# --------------------------------------------------------------------------

def normalizar_numero(texto: str) -> str:
    """Solo digitos y con codigo de pais. Los de RD sin el 1 lo reciben."""
    digitos = re.sub(r"\D", "", texto or "")
    if len(digitos) == 10 and digitos.startswith(PREFIJOS_RD):
        return "1" + digitos
    if 11 <= len(digitos) <= 15:
        return digitos
    raise ErrorEnvio(
        f"El numero '{texto}' no parece valido. Pidelo completo: diez digitos si "
        "es de Republica Dominicana, o con el codigo de pais si es de otro lugar."
    )


def legible(numero: str) -> str:
    if len(numero) == 11 and numero.startswith("1"):
        return f"+1 {numero[1:4]}-{numero[4:7]}-{numero[7:]}"
    return f"+{numero}"


# --------------------------------------------------------------------------
# Envio pendiente
# --------------------------------------------------------------------------

@dataclass
class Pendiente:
    numero: str
    archivos: list[dict]
    creado: float = field(default_factory=time.time)


_pendientes: dict[str, Pendiente] = {}
_enviados: deque = deque()
_candado = threading.Lock()

NOMBRE = {"imagen": "imagen", "ficha": "ficha tecnica", "cotizacion": "cotizacion"}


def _archivos_de_productos(codigos: str, tipo: str, nombres: str) -> tuple[list[dict], list[str]]:
    from . import archivos

    tipos = {"imagen": ["imagen"], "ficha": ["ficha"], "ambas": ["imagen", "ficha"]}.get(
        (tipo or "ambas").strip().lower()
    )
    if tipos is None:
        raise ErrorEnvio("'tipo' tiene que ser 'imagen', 'ficha' o 'ambas'.")
    if not archivos.configurado():
        raise ErrorEnvio("Las imagenes y fichas tecnicas no estan configuradas.")

    lista = []
    for crudo in (codigos or "").split(","):
        codigo = archivos.normalizar(crudo)
        if codigo and codigo not in lista:
            lista.append(codigo)
    titulos = [n.strip() for n in (nombres or "").split("|")]
    titulo_de = {c: (titulos[i] if i < len(titulos) and titulos[i] else c) for i, c in enumerate(lista)}

    encontrados, faltan = archivos.buscar(lista, tipos)
    salida = [
        {
            "tipo": a["tipo"], "referencia": a["codigo"], "titulo": titulo_de[a["codigo"]],
            "url": a["url"], "archivo": a["archivo"],
        }
        for a in encontrados
    ]
    return salida, [f"{NOMBRE[t]} de {titulo_de[c]}" for c, t in faltan]


def _archivo_de_cotizacion(numero: str) -> dict:
    from . import cotizaciones

    texto = (numero or "").strip().upper()
    if re.fullmatch(r"\d{1,6}", texto):
        texto = cotizaciones.formato(int(texto))
    if not cotizaciones.NUMERO.match(texto):
        raise ErrorEnvio(f"'{numero}' no es un numero de cotizacion de Jarvis (JV-00001).")
    if not cotizaciones.configurado():
        raise ErrorEnvio("Las cotizaciones no estan configuradas.")

    fila = cotizaciones.buscar_emitida(texto)
    if fila is None:
        raise ErrorEnvio(f"No existe una cotizacion {texto} emitida.")
    # La URL se firma al enviar: el enlace dura poco y el "si" puede tardar.
    return {"tipo": "cotizacion", "referencia": texto, "titulo": fila["cliente"],
            "ruta": fila["pdf_ruta"], "archivo": fila["pdf_ruta"]}


def preparar(id_usuario: str, numero: str, codigos: str = "", tipo: str = "ambas",
             nombres: str = "", cotizacion: str = "") -> str:
    destino = normalizar_numero(numero)

    lista: list[dict] = []
    no_hay: list[str] = []
    if (codigos or "").strip():
        lista, no_hay = _archivos_de_productos(codigos, tipo, nombres)
    if (cotizacion or "").strip():
        lista.append(_archivo_de_cotizacion(cotizacion))

    if not lista:
        detalle = f" No existe {', '.join(no_hay)}." if no_hay else ""
        raise ErrorEnvio(
            "No hay nada que enviar." + detalle + " Di que ese archivo no existe; "
            "no mandes el de otro producto."
        )
    if len(lista) > MAX_ARCHIVOS:
        raise ErrorEnvio(f"Son {len(lista)} archivos; como mucho {MAX_ARCHIVOS} por envio.")

    with _candado:
        _pendientes[id_usuario] = Pendiente(destino, lista)

    que = ", ".join(_descripcion(a) for a in lista)
    faltan = f" No existe {', '.join(no_hay)}, eso no va." if no_hay else ""
    return (
        f"Envio preparado (aun NO enviado) al WhatsApp {legible(destino)}: {que}.{faltan} "
        "Lee el numero cifra por cifra y lo que se va a mandar, y pregunta si lo "
        "envias. Llama a confirmar_envio_whatsapp solo si dice que si."
    )


def _descripcion(archivo: dict) -> str:
    if archivo["tipo"] == "cotizacion":
        return f"la cotizacion {archivo['referencia']} de {archivo['titulo']}"
    return f"{NOMBRE[archivo['tipo']]} de {archivo['titulo']}"


def pendiente_de(id_usuario: str) -> Pendiente | None:
    with _candado:
        pendiente = _pendientes.get(id_usuario)
    if pendiente and time.time() - pendiente.creado > VIGENCIA_PENDIENTE:
        return None
    return pendiente


# --------------------------------------------------------------------------
# Evolution
# --------------------------------------------------------------------------

def _cuerpo(archivo: dict, destino: str) -> dict:
    if archivo["tipo"] == "imagen":
        extension = archivo["archivo"].rsplit(".", 1)[-1].lower()
        return {
            "number": destino, "mediatype": "image",
            "mimetype": "image/jpeg" if extension in ("jpg", "jpeg") else f"image/{extension}",
            "media": archivo["url"], "fileName": archivo["archivo"],
            "caption": f"{MARCA} · {archivo['titulo']}",
        }
    if archivo["tipo"] == "ficha":
        return {
            "number": destino, "mediatype": "document", "mimetype": "application/pdf",
            "media": archivo["url"], "fileName": f"Ficha tecnica {archivo['referencia']}.pdf",
            "caption": f"{MARCA} · Ficha técnica de {archivo['titulo']}",
        }
    from . import cotizaciones

    return {
        "number": destino, "mediatype": "document", "mimetype": "application/pdf",
        "media": cotizaciones.firmar(archivo["ruta"], FIRMA_ENVIO),
        "fileName": cotizaciones.nombre_de_archivo(archivo["titulo"], archivo["referencia"]),
        "caption": f"{MARCA} · Cotización {archivo['referencia']}",
    }


def _enviar_media(cuerpo: dict) -> str:
    """Manda un archivo y devuelve el id del mensaje."""
    respuesta = httpx.post(
        f"{_env('EVOLUTION_URL').rstrip('/')}/message/sendMedia/{_env('EVOLUTION_INSTANCIA')}",
        headers={"apikey": _env("EVOLUTION_API_KEY")},
        json=cuerpo, timeout=90,
    )
    if respuesta.status_code >= 400:
        try:
            detalle = json.dumps(respuesta.json(), ensure_ascii=False)[:300]
        except ValueError:
            detalle = respuesta.text[:300]
        raise RuntimeError(f"Evolution respondio {respuesta.status_code}: {detalle}")
    return str((respuesta.json().get("key") or {}).get("id") or "")


def _anotar(registro: dict) -> None:
    try:
        with _candado, rutas.archivo("envios_whatsapp.jsonl").open("a", encoding="utf-8") as salida:
            salida.write(json.dumps(registro, ensure_ascii=False) + "\n")
    except OSError:
        pass   # anotar no debe impedir el envio


def _cupo(cuantos: int) -> None:
    ahora = time.time()
    with _candado:
        while _enviados and ahora - _enviados[0] > 3600:
            _enviados.popleft()
        if len(_enviados) + cuantos > MAX_POR_HORA:
            raise ErrorEnvio(
                f"Se llego al tope de {MAX_POR_HORA} envios por hora, para cuidar el "
                "numero de un bloqueo de WhatsApp. Intentalo mas tarde."
            )
        _enviados.extend([ahora] * cuantos)


def confirmar(id_usuario: str, nombre_usuario: str) -> str:
    pendiente = pendiente_de(id_usuario)
    if pendiente is None:
        raise ErrorEnvio(
            "No hay un envio pendiente (o pasaron mas de diez minutos). Preparalo "
            "otra vez con preparar_envio_whatsapp."
        )
    # Se saca antes de mandar: un "si" repetido no debe enviar dos veces.
    with _candado:
        _pendientes.pop(id_usuario, None)

    _cupo(len(pendiente.archivos))

    enviados, fallidos = [], []
    for archivo in pendiente.archivos:
        registro = {
            "cuando": datetime.now().isoformat(timespec="seconds"),
            "usuario": nombre_usuario, "numero": pendiente.numero,
            "tipo": archivo["tipo"], "referencia": archivo["referencia"],
        }
        try:
            registro["id"] = _enviar_media(_cuerpo(archivo, pendiente.numero))
            registro["ok"] = True
            enviados.append(_descripcion(archivo))
        except Exception as error:  # noqa: BLE001
            registro.update(ok=False, error=str(error)[:300])
            fallidos.append(f"{_descripcion(archivo)} ({str(error)[:120]})")
        _anotar(registro)

    partes = []
    if enviados:
        partes.append(f"Enviado por WhatsApp a {legible(pendiente.numero)}: {', '.join(enviados)}.")
    if fallidos:
        partes.append(f"No se pudo enviar: {'; '.join(fallidos)}. Dilo tal cual.")
    return " ".join(partes)
