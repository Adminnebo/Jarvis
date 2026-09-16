"""Imagenes y fichas tecnicas de los productos, en Supabase Storage.

Cada archivo se llama como el Codigo del producto en el catalogo: 305400.png en
el bucket de imagenes, 305400.pdf en el de fichas. No hay tabla que los una, asi
que Jarvis arma un indice con los nombres de los archivos y busca ahi.

Listar un bucket exige la service role key, y por eso el indice se arma en el
servidor. Los archivos se entregan por su URL publica si el bucket es publico,
o con un enlace firmado de una hora si no lo es: la llave nunca sale de aqui.
"""

import json
import os
import re
import threading
import time
from urllib.parse import quote

import httpx

from . import rutas

# Tipo de archivo -> variable con el nombre de su bucket.
TIPOS = {"imagen": "JARVIS_BUCKET_IMAGENES", "ficha": "JARVIS_BUCKET_FICHAS"}

# Los archivos cambian poco. Listar ~25.000 nombres tarda unos segundos, asi
# que se hace al arrancar y despues cada tantas horas, en segundo plano.
VIGENCIA = 6 * 3600

# Si piden un codigo que no esta, puede ser un archivo recien subido. Se vuelve
# a listar, pero no mas de una vez cada tanto: la mayoria de los productos sin
# ficha simplemente no la tienen.
ESPERA_TRAS_FALLO = 600

DURACION_FIRMA = 3600
POR_PAGINA = 1000


def bucket(tipo: str) -> str:
    return os.getenv(TIPOS[tipo], "").strip()


def _llave() -> str:
    return os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()


def _base() -> str:
    referencia = os.getenv("SUPABASE_PROJECT_REF", "").strip()
    return f"https://{referencia}.supabase.co/storage/v1"


def configurado() -> bool:
    return bool(
        _llave()
        and os.getenv("SUPABASE_PROJECT_REF", "").strip()
        and any(bucket(tipo) for tipo in TIPOS)
    )


def _cliente() -> httpx.Client:
    return httpx.Client(
        headers={"Authorization": f"Bearer {_llave()}", "apikey": _llave()},
        timeout=30,
    )


# --------------------------------------------------------------------------
# Nombres de archivo -> codigos
# --------------------------------------------------------------------------

_COPIA = re.compile(r"(\s*-?\s*(copia|copy)(\s*\(\d+\))?)+$", re.IGNORECASE)
_NUMERADA = re.compile(r"\s*\(\d+\)$")


def normalizar(nombre: str) -> str:
    """El codigo que corresponde a un nombre de archivo, o a lo que pide el modelo.

    En el bucket hay copias sueltas ("0774 - copia.png", "11815 (2).png") y
    nombres con espacios de mas: todos apuntan al mismo codigo.
    """
    tallo = (nombre or "").rsplit("/", 1)[-1].strip()
    if re.search(r"\.[A-Za-z]{3,4}$", tallo):
        tallo = tallo.rsplit(".", 1)[0]
    tallo = _COPIA.sub("", tallo.strip())
    tallo = _NUMERADA.sub("", tallo)
    return tallo.strip().upper()


def _es_original(nombre: str) -> bool:
    tallo = nombre.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return tallo.upper() == normalizar(nombre)


def armar_indice(nombres: list[str]) -> dict[str, str]:
    """Codigo -> archivo. Si hay copias, gana el original."""
    indice: dict[str, str] = {}
    for nombre in sorted(nombres):
        codigo = normalizar(nombre)
        if not codigo:
            continue
        actual = indice.get(codigo)
        if actual is None or (_es_original(nombre) and not _es_original(actual)):
            indice[codigo] = nombre
    return indice


# --------------------------------------------------------------------------
# Indice
# --------------------------------------------------------------------------

_estado: dict = {"cuando": 0.0, "indices": {}, "publicos": {}}
_candado = threading.Lock()
_refrescando = threading.Lock()


def _cache():
    return rutas.archivo("archivos.json")


def usar_indices(indices: dict, publicos: dict, cuando: float | None = None) -> None:
    with _candado:
        _estado.update(
            cuando=time.time() if cuando is None else cuando,
            indices=indices,
            publicos=publicos,
        )


def _listar(http: httpx.Client, nombre_bucket: str, prefijo: str = "") -> list[str]:
    nombres: list[str] = []
    desde = 0
    while True:
        respuesta = http.post(
            f"{_base()}/object/list/{nombre_bucket}",
            json={
                "prefix": prefijo, "limit": POR_PAGINA, "offset": desde,
                "sortBy": {"column": "name", "order": "asc"},
            },
        )
        respuesta.raise_for_status()
        lote = respuesta.json()
        for item in lote:
            ruta = f"{prefijo}{item['name']}"
            # Las carpetas vienen sin id: hay que entrar.
            if item.get("id") is None:
                nombres.extend(_listar(http, nombre_bucket, ruta + "/"))
            else:
                nombres.append(ruta)
        if len(lote) < POR_PAGINA:
            return nombres
        desde += POR_PAGINA


def refrescar() -> None:
    """Vuelve a listar los buckets. Si ya hay otro listando, espera a ese."""
    with _refrescando:
        indices, publicos = {}, {}
        with _cliente() as http:
            for tipo in TIPOS:
                nombre_bucket = bucket(tipo)
                if not nombre_bucket:
                    continue
                info = http.get(f"{_base()}/bucket/{nombre_bucket}")
                info.raise_for_status()
                publicos[tipo] = bool(info.json().get("public"))
                indices[tipo] = armar_indice(_listar(http, nombre_bucket))

        usar_indices(indices, publicos)
        try:
            _cache().write_text(
                json.dumps({"cuando": _estado["cuando"], "indices": indices,
                            "publicos": publicos}),
                encoding="utf-8",
            )
        except OSError:
            pass   # sin cache en disco solo se lista de nuevo al reiniciar


def refrescar_en_segundo_plano() -> None:
    if not configurado() or _refrescando.locked():
        return

    def trabajo():
        try:
            refrescar()
            cuantos = {t: len(i) for t, i in _estado["indices"].items()}
            print(f"  Imagenes y fichas indexadas: {cuantos}")
        except Exception as error:  # noqa: BLE001
            print(f"  AVISO: no pude listar las imagenes y fichas: {error}")

    threading.Thread(target=trabajo, daemon=True).start()


def _estado_actual() -> dict:
    with _candado:
        vacio = not _estado["cuando"]
    if vacio:
        try:
            guardado = json.loads(_cache().read_text(encoding="utf-8"))
            usar_indices(guardado["indices"], guardado["publicos"], guardado["cuando"])
        except (OSError, ValueError, KeyError):
            # Sin cache: la primera peticion paga el listado entero.
            refrescar()
    with _candado:
        return dict(_estado)


# --------------------------------------------------------------------------
# Busqueda
# --------------------------------------------------------------------------

def url(tipo: str, archivo: str, publico: bool) -> str:
    ruta = f"{bucket(tipo)}/{quote(archivo)}"
    if publico:
        return f"{_base()}/object/public/{ruta}"
    with _cliente() as http:
        respuesta = http.post(f"{_base()}/object/sign/{ruta}",
                              json={"expiresIn": DURACION_FIRMA})
        respuesta.raise_for_status()
        return _base() + respuesta.json()["signedURL"]


def buscar(codigos: list[str], tipos: list[str]) -> tuple[list[dict], list[tuple[str, str]]]:
    """Los archivos que existen de esos codigos, y los (codigo, tipo) que no."""
    estado = _estado_actual()
    edad = time.time() - estado["cuando"]

    encontrados: list[dict] = []
    faltan: list[tuple[str, str]] = []
    for codigo in codigos:
        for tipo in tipos:
            archivo = estado["indices"].get(tipo, {}).get(normalizar(codigo))
            if archivo:
                encontrados.append({
                    "tipo": tipo,
                    "codigo": normalizar(codigo),
                    "archivo": archivo,
                    "url": url(tipo, archivo, estado["publicos"].get(tipo, True)),
                })
            else:
                faltan.append((normalizar(codigo), tipo))

    if edad > VIGENCIA or (faltan and edad > ESPERA_TRAS_FALLO):
        refrescar_en_segundo_plano()

    return encontrados, faltan
