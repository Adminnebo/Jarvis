"""Lo minimo para hablar con la API de Higgsfield (docs.higgsfield.ai).

Solo transporte: subir una imagen, pedir un video a partir de ella, preguntar
como va y bajar el resultado. Que se pide y que se hace con lo que vuelve lo
decide asistente.py.
"""

import os

import httpx

BASE = "https://api.higgsfield.ai"
MODELO_POR_DEFECTO = "kling-video/v2.5-turbo/pro/image-to-video"
# Cada modelo acepta sus duraciones: Kling 5 o 10, Hailuo 6 o 10.
DURACION = {"kling": 5, "minimax": 6}
NEGATIVO = "blurry, distorted face, extra limbs, text, watermark, camera movement"


class ErrorDeHiggsfield(RuntimeError):
    """Higgsfield dijo que no. El mensaje es el de su API, para mostrarlo tal cual."""


def configurado() -> bool:
    return bool(os.getenv("HIGGSFIELD_API_KEY_ID", "").strip()
                and os.getenv("HIGGSFIELD_API_KEY_SECRET", "").strip())


def _auth() -> dict:
    return {"Authorization": (
        f"Key {os.getenv('HIGGSFIELD_API_KEY_ID', '').strip()}:"
        f"{os.getenv('HIGGSFIELD_API_KEY_SECRET', '').strip()}"
    )}


def modelo() -> str:
    return os.getenv("JARVIS_AVATAR_MODELO", "").strip().strip("/") or MODELO_POR_DEFECTO


def _revisar(respuesta) -> dict:
    if respuesta.status_code >= 400:
        try:
            detalle = respuesta.json().get("detail") or respuesta.text
        except ValueError:
            detalle = respuesta.text
        raise ErrorDeHiggsfield(f"Higgsfield {respuesta.status_code}: {str(detalle)[:200]}")
    return respuesta.json()


def subir_imagen(contenido: bytes, tipo: str) -> str:
    """Sube la foto a su almacenamiento y devuelve la URL publica para el modelo."""
    datos = _revisar(httpx.post(f"{BASE}/files/generate-upload-url", json={"content_type": tipo},
                                headers={**_auth(), "Content-Type": "application/json"}, timeout=30))
    # A la URL firmada van SUS cabeceras; la clave de Higgsfield nunca sale hacia alla.
    subida = httpx.put(datos["upload_url"], content=contenido,
                       headers=datos.get("upload_headers") or {"Content-Type": tipo}, timeout=120)
    if subida.status_code >= 400:
        raise ErrorDeHiggsfield(f"No se pudo subir la foto ({subida.status_code}).")
    return datos["public_url"]


def crear_video(url_imagen: str, prompt: str) -> str:
    """Pide un video a partir de la imagen. Devuelve el request_id."""
    elegido = modelo()
    cuerpo = {
        "prompt": prompt,
        "image_url": url_imagen,
        "duration": DURACION.get(elegido.split("/")[0], 5),
    }
    if elegido.startswith("kling"):
        cuerpo["negative_prompt"] = NEGATIVO
    datos = _revisar(httpx.post(f"{BASE}/{elegido}", json=cuerpo,
                                headers={**_auth(), "Content-Type": "application/json"}, timeout=60))
    return datos["request_id"]


def estado(request_id: str) -> dict:
    """{'estado': 'generando'|'listo'|'error', 'url': str|None, 'error': str|None}"""
    datos = _revisar(httpx.get(f"{BASE}/requests/{request_id}/status", headers=_auth(), timeout=30))
    crudo = datos.get("status")
    if crudo == "completed":
        url = (datos.get("video") or {}).get("url")
        if not url:
            return {"estado": "error", "url": None, "error": "Higgsfield termino sin video."}
        return {"estado": "listo", "url": url, "error": None}
    if crudo in ("failed", "nsfw", "canceled"):
        motivo = {"nsfw": "Higgsfield rechazo la foto por moderacion de contenido.",
                  "canceled": "El trabajo se cancelo."}.get(crudo)
        return {"estado": "error", "url": None, "error": motivo or datos.get("error") or "Fallo en Higgsfield."}
    return {"estado": "generando", "url": None, "error": None}


def descargar(url: str) -> bytes:
    respuesta = httpx.get(url, timeout=180, follow_redirects=True)
    if respuesta.status_code >= 400:
        raise ErrorDeHiggsfield(f"No se pudo bajar el video ({respuesta.status_code}).")
    return respuesta.content
