"""Audio de las reuniones en Supabase Storage (bucket privado "reuniones").

Mismo proyecto y llave que archivos.py (SUPABASE_PROJECT_REF,
SUPABASE_SERVICE_ROLE_KEY). Se escucha con un enlace firmado de una hora.
"""

import os

import httpx


class ErrorAlmacen(Exception):
    pass


def _bucket() -> str:
    return os.getenv("JARVIS_BUCKET_REUNIONES", "reuniones").strip() or "reuniones"


def _base() -> str:
    return f"https://{os.getenv('SUPABASE_PROJECT_REF', '').strip()}.supabase.co/storage/v1"


def _cabeceras() -> dict:
    llave = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    return {"Authorization": f"Bearer {llave}", "apikey": llave}


def _http() -> httpx.Client:
    return httpx.Client(timeout=60)


def _ruta(reunion_id: str, n: int, formato: str = "ogg") -> str:
    return f"{reunion_id}/{n:05d}.{formato}"


def subir(reunion_id: str, n: int, datos: bytes, formato: str = "ogg") -> None:
    with _http() as http:
        r = http.post(f"{_base()}/object/{_bucket()}/{_ruta(reunion_id, n, formato)}", content=datos,
                      headers={**_cabeceras(), "Content-Type": f"audio/{formato}", "x-upsert": "true"})
    if not r.is_success:
        raise ErrorAlmacen(f"Storage respondió {r.status_code}: {r.text[:200]}")


def url_firmada(reunion_id: str, n: int, segundos: int = 3600, formato: str = "ogg") -> str:
    with _http() as http:
        r = http.post(f"{_base()}/object/sign/{_bucket()}/{_ruta(reunion_id, n, formato)}",
                      json={"expiresIn": segundos}, headers=_cabeceras())
    if not r.is_success:
        raise ErrorAlmacen(f"Storage respondió {r.status_code}")
    return _base() + r.json()["signedURL"]


def borrar(reunion_id: str, numeros: list[int], formatos: dict[int, str] | None = None) -> None:
    if not numeros:
        return
    formatos = formatos or {}
    with _http() as http:
        r = http.request("DELETE", f"{_base()}/object/{_bucket()}", headers=_cabeceras(),
                         json={"prefixes": [_ruta(reunion_id, n, formatos.get(n) or "ogg") for n in numeros]})
    if not r.is_success:
        raise ErrorAlmacen(f"Storage respondió {r.status_code}")
