"""Lo que se dijo en voz, guardado en disco, y el detector de precios dichos.

Por que existe: las conversaciones de los lentes solo vivian en los logs de
Railway, que se borran en un dia. Cuando alguien decia "Jarvis se invento el
precio de un casco" ya no quedaba nada que revisar. Aqui cada turno queda en un
JSONL por dia en el volumen, catorce dias, y se puede releer por /api/voz.

El segundo trabajo de este modulo es el chequeo de precios: en el autotest de
Camila, con este mismo catalogo, se colo un 549.55 donde el catalogo decia
1614.55. Al guardar lo que dijo Jarvis se buscan las cifras que suenan a precio
y se comprueban contra los numeros que de verdad devolvieron las herramientas
de esa sesion.

MUY IMPORTANTE: esto es un DETECTOR, no una verdad. Marca para revisar, no
acusa. Hay cifras legitimas que no salen de ninguna herramienta -una cantidad
que dijo el usuario, un total que Jarvis suma, un telefono, una fecha, un
porcentaje- y por eso el filtro es deliberadamente conservador: ante la duda,
no marca. Una sospecha quiere decir "mira este turno", nunca "aqui mintio".
"""

import itertools
import json
import re
from datetime import datetime, timedelta, timezone

from . import rutas

# Dias que se conservan. Mas que suficiente para investigar un reclamo y poco
# para que el volumen crezca sin control.
RETENCION_DIAS = 14

# Un centavo de margen: los totales se redondean y no vale marcar por eso.
TOLERANCIA = 0.02

# Cuantos numeros de la sesion se combinan al buscar sumas y productos. Con
# todos, una sesion larga haria explotar las combinaciones.
MAX_COMBINABLES = 40

PREFIJO = "voz-"
_DIA = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Numeros por sesion vistos en resultados de herramientas y en lo que dijo el
# usuario. Vive en memoria porque un lote llega cada pocos segundos; si el
# proceso se reinicia a media conversacion se reconstruye desde el disco.
_VISTOS: dict[str, dict] = {}
MAX_SESIONES = 200

_ultima_rotacion = ""


def al_log(aparato: str, que: str, texto, maximo: int = 400) -> None:
    """Una linea en el log del servidor con lo que se dijo o se consulto.

    Los lentes ya dejan su dialogo en el log de su puente; la web y el reloj
    no dejaban nada, y sin eso no hay como revisar por que una conversacion
    salio mal. Va recortado y en una sola linea.
    """
    plano = " ".join(str(texto if texto is not None else "").split())
    if len(plano) > maximo:
        plano = plano[:maximo] + f"... ({len(plano)} caracteres)"
    print(f"  [dialogo] ({aparato or '?'}) {que}: {plano}", flush=True)


def hoy() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def archivo_del_dia(dia: str):
    return rutas.archivo(f"{PREFIJO}{dia}.jsonl")


def dia_valido(dia: str) -> bool:
    """Un dia mal formado no puede convertirse en una ruta a otro archivo."""
    return bool(_DIA.match(dia or ""))


# ---------------------------------------------------------------- numeros

# Un numero tal como se escribe: 1,614.55 / 1.614,55 / 522.35 / 14
_TOKEN = re.compile(r"\d[\d.,]*\d|\d")

# Lo que se borra del texto antes de buscar precios, porque nunca lo es.
_TELEFONO = re.compile(r"\b\d{3}[-. ]\d{3}[-. ]\d{4}\b|\(\d{3}\)\s*\d{3}[-. ]?\d{4}|\b\d{10,}\b")
_FECHA = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b|\b\d{1,2}:\d{2}\b")

# Que convierte una cifra en candidata a precio aunque venga sin decimales.
_ANTES_DINERO = re.compile(
    r"(rd\s*\$|\$|cuesta|cuestan|precio|precios|vale|valen|sale|total|cobra|cobran|pagas|pagar)[^\d]{0,12}$",
    re.IGNORECASE,
)
_DESPUES_DINERO = re.compile(r"^\s*(pesos|peso|dolares|dolar|usd|rd\b|dop\b)", re.IGNORECASE)

# Y lo que la descarta aunque traiga decimales: no es dinero, es una medida.
_DESPUES_NO_DINERO = re.compile(
    r"^\s*(%|por\s*ciento|unidades|unidad|piezas|pieza|cajas|caja|metros|metro|mts|cm\b|mm\b|"
    r"pulgadas|pulgada|libras|libra|kilos|kilo|kg\b|gramos|gramo|litros|litro|galones|galon|"
    r"minutos|minuto|horas|hora|dias|dia|anos|ano|veces|grados)",
    re.IGNORECASE,
)


def _a_numero(token: str):
    """1,614.55 -> 1614.55. Devuelve (valor, cuantos decimales traia)."""
    limpio = token.strip(".,")
    if not limpio or not limpio[0].isdigit():
        return None, 0

    tiene_punto = "." in limpio
    tiene_coma = "," in limpio

    if tiene_punto and tiene_coma:
        # El ultimo separador manda: 1,614.55 es ingles y 1.614,55 es espanol.
        decimal = "." if limpio.rfind(".") > limpio.rfind(",") else ","
        miles = "," if decimal == "." else "."
        limpio = limpio.replace(miles, "").replace(decimal, ".")
    elif tiene_coma:
        limpio = limpio.replace(",", "") if re.fullmatch(r"\d{1,3}(,\d{3})+", limpio) else limpio.replace(",", ".")
    elif tiene_punto:
        if re.fullmatch(r"\d{1,3}(\.\d{3})+", limpio):
            limpio = limpio.replace(".", "")

    try:
        valor = float(limpio)
    except ValueError:
        return None, 0

    decimales = len(limpio.split(".")[1]) if "." in limpio else 0
    return valor, decimales


def numeros_de(texto) -> list[float]:
    """Todos los numeros de un texto. Para lo que devolvio una herramienta.

    Aqui se es generoso a proposito: cuantos mas numeros se den por vistos,
    menos cifras dichas quedan sin explicacion y menos falsas alarmas salen.
    """
    if not isinstance(texto, str):
        texto = json.dumps(texto, ensure_ascii=False, default=str) if texto else ""

    vistos = []
    for token in _TOKEN.findall(texto):
        valor, _ = _a_numero(token)
        if valor is not None:
            vistos.append(valor)
    return vistos


def cifras_de_precio(texto: str) -> list[float]:
    """Las cifras de un texto hablado que suenan a precio.

    Solo pasa el filtro lo que trae decimales (522.35, 14.84) o lo que viene
    pegado a una marca de dinero (RD$, "cuesta", "pesos"). Un "tengo 3 cascos"
    o un "mide 2 metros" no son precios y no se revisan: de lo contrario el
    detector marcaria media conversacion.
    """
    if not texto:
        return []

    # Los telefonos y las fechas se borran antes de mirar: son los dos falsos
    # positivos mas faciles de cometer.
    limpio = _FECHA.sub(" ", _TELEFONO.sub(" ", texto))

    cifras = []
    for coincidencia in _TOKEN.finditer(limpio):
        valor, decimales = _a_numero(coincidencia.group())
        if valor is None or valor <= 0:
            continue

        antes = limpio[max(0, coincidencia.start() - 14):coincidencia.start()]
        despues = limpio[coincidencia.end():coincidencia.end() + 14]

        if _DESPUES_NO_DINERO.match(despues):
            continue

        parece_dinero = (
            decimales in (1, 2)
            or bool(_ANTES_DINERO.search(antes))
            or bool(_DESPUES_DINERO.match(despues))
        )
        if parece_dinero:
            cifras.append(valor)

    return cifras


def explicada(cifra: float, vistos) -> bool:
    """Si esa cifra se puede derivar de lo que ya se vio en la sesion.

    Vale el numero tal cual, su redondeo (Jarvis dice "como 1,615" de un
    1614.55), la suma de varias lineas de una cotizacion, una cantidad por un
    precio y el ITBIS. Todo esto existe para NO marcar lo que tiene una
    explicacion honesta.
    """
    candidatos = [v for v in list(vistos)[-MAX_COMBINABLES:] if v]
    if not candidatos:
        return False

    for v in candidatos:
        if abs(cifra - v) <= TOLERANCIA:
            return True
        # Redondeos al hablar: "mil seiscientos quince" por 1614.55.
        if abs(cifra - round(v)) <= TOLERANCIA or abs(cifra - round(v, 1)) <= TOLERANCIA:
            return True

    # Suma simple: el total de dos o tres lineas de una cotizacion.
    for cuantos in (2, 3):
        for grupo in itertools.combinations(candidatos, cuantos):
            if abs(cifra - sum(grupo)) <= TOLERANCIA:
                return True

    # Cantidad por precio, e ITBIS sobre un precio.
    for v in candidatos:
        for n in range(2, 13):
            if abs(cifra - v * n) <= TOLERANCIA:
                return True
        for factor in (1.18, 0.18):
            if abs(cifra - v * factor) <= 0.05:
                return True

    for a, b in itertools.combinations(candidatos, 2):
        if abs(cifra - a * b) <= TOLERANCIA:
            return True

    return False


# ---------------------------------------------------------------- sesiones


def _memoria_de(sesion: str) -> dict:
    """Lo que sabemos de esa sesion: numeros vistos y cifras ya marcadas."""
    memoria = _VISTOS.get(sesion)
    if memoria is None:
        memoria = _reconstruir(sesion)
        if len(_VISTOS) >= MAX_SESIONES:
            # Se cae la mas vieja: los dict conservan el orden de insercion.
            _VISTOS.pop(next(iter(_VISTOS)), None)
        _VISTOS[sesion] = memoria
    return memoria


def _reconstruir(sesion: str) -> dict:
    """La memoria de una sesion, releida del disco.

    Hace falta cuando el servidor se reinicia a media conversacion: sin esto,
    el primer lote de despues marcaria como inventado todo lo que ya se habia
    consultado.
    """
    memoria: dict = {"vistos": {}, "marcadas": {}}
    fecha = datetime.now(timezone.utc).date()
    for resta in (0, 1):
        dia = (fecha - timedelta(days=resta)).isoformat()
        for registro in leer(dia):
            if registro.get("sesion") != sesion:
                continue
            _anotar_vistos(memoria["vistos"], registro)
            for sospecha in registro.get("sospechas") or []:
                memoria["marcadas"][sospecha.get("cifra")] = None
    return memoria


def _anotar_vistos(vistos: dict, evento: dict) -> None:
    """Los numeros que ese evento pone sobre la mesa como legitimos.

    Cuentan los de un resultado de herramienta (el catalogo de verdad), los de
    sus argumentos y los que dijo el usuario: si el cliente dice "tengo 2,500
    pesos", que Jarvis lo repita no es inventarselo.
    """
    if evento.get("tipo") == "herramienta":
        for campo in ("resultado", "argumentos"):
            for numero in numeros_de(evento.get(campo)):
                vistos[numero] = None
    elif evento.get("quien") == "tu":
        for numero in numeros_de(evento.get("texto")):
            vistos[numero] = None


# ---------------------------------------------------------------- guardar


def revisar(sesion: str, eventos: list[dict]) -> list[dict]:
    """Recorre el lote en orden y devuelve las sospechas que encuentre.

    El orden importa: una cifra solo esta respaldada si la herramienta que la
    devolvio corrio ANTES de que Jarvis la dijera.
    """
    memoria = _memoria_de(sesion)
    vistos, marcadas = memoria["vistos"], memoria["marcadas"]
    sospechas = []

    for evento in eventos:
        if evento.get("tipo") != "dicho" or evento.get("quien") != "jarvis":
            _anotar_vistos(vistos, evento)
            continue

        texto = evento.get("texto") or ""
        propias = []
        for cifra in cifras_de_precio(texto):
            if explicada(cifra, vistos) or cifra in marcadas:
                # Si ya se marco antes en la misma sesion no se repite: cuando
                # Jarvis repite el precio inventado, el aviso sigue siendo uno.
                continue
            marcadas[cifra] = None
            sospecha = {
                "sesion": sesion,
                "ts": evento.get("ts", ""),
                "cifra": cifra,
                "texto": texto,
            }
            propias.append(sospecha)
            sospechas.append(sospecha)
            # Que salga en los logs de Railway aunque nadie abra el registro:
            # es la senal de que hay que ir a mirarlo.
            print(f"  Voz: cifra sin respaldo en {sesion}: {cifra} -> {texto[:160]}")

        if propias:
            evento["sospechas"] = propias

    return sospechas


def guardar(sesion: str, dispositivo: str, eventos: list[dict]) -> list[dict]:
    """Revisa el lote, lo escribe en el JSONL del dia y devuelve las sospechas.

    Nada de esto puede tumbar la peticion: si el disco falla, se avisa por el
    log y la conversacion sigue. Perder el registro es malo; cortarle la voz a
    quien lleva los lentes es peor.
    """
    sesion = (sesion or "sin-sesion").strip()[:80]
    dispositivo = (dispositivo or "desconocido").strip()[:40]

    try:
        sospechas = revisar(sesion, eventos)
    except Exception as fallo:  # noqa: BLE001
        print(f"  Voz: fallo el chequeo de precios ({type(fallo).__name__}: {fallo}).")
        sospechas = []

    guardado = datetime.now(timezone.utc).isoformat()
    lineas = []
    for evento in eventos:
        registro = {"sesion": sesion, "dispositivo": dispositivo, "guardado": guardado}
        registro.update({k: v for k, v in evento.items() if v not in (None, "")})
        lineas.append(json.dumps(registro, ensure_ascii=False, default=str))

    if not lineas:
        return sospechas

    try:
        rotar()
        with open(archivo_del_dia(hoy()), "a", encoding="utf-8") as archivo:
            archivo.write("\n".join(lineas) + "\n")
    except Exception as fallo:  # noqa: BLE001
        print(f"  Voz: no se pudo guardar el registro ({type(fallo).__name__}: {fallo}).")

    return sospechas


def leer(dia: str = "") -> list[dict]:
    """Los eventos de un dia. Vacio si ese dia no existe o no se puede leer."""
    dia = dia or hoy()
    if not dia_valido(dia):
        return []

    try:
        ruta = archivo_del_dia(dia)
        if not ruta.exists():
            return []
        contenido = ruta.read_text(encoding="utf-8")
    except Exception as fallo:  # noqa: BLE001
        print(f"  Voz: no se pudo leer el registro de {dia} ({type(fallo).__name__}).")
        return []

    eventos = []
    for linea in contenido.splitlines():
        linea = linea.strip()
        if not linea:
            continue
        try:
            eventos.append(json.loads(linea))
        except ValueError:
            # Una linea cortada por un despliegue a medio escribir no puede
            # dejar sin auditoria al resto del dia.
            continue
    return eventos


def rotar(dia_de_hoy: str = "") -> list[str]:
    """Borra los dias con mas de RETENCION_DIAS. Devuelve lo que borro.

    Se llama al guardar, pero solo hace el recorrido una vez por dia y proceso:
    no tiene sentido listar la carpeta en cada turno de voz.
    """
    global _ultima_rotacion

    dia_de_hoy = dia_de_hoy or hoy()
    if _ultima_rotacion == dia_de_hoy:
        return []
    _ultima_rotacion = dia_de_hoy

    limite = (datetime.fromisoformat(dia_de_hoy).date() - timedelta(days=RETENCION_DIAS)).isoformat()
    borrados = []
    for ruta in rutas.datos().glob(f"{PREFIJO}*.jsonl"):
        dia = ruta.stem[len(PREFIJO):]
        if dia_valido(dia) and dia < limite:
            try:
                ruta.unlink()
                borrados.append(dia)
            except OSError:
                continue
    return borrados
