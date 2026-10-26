# Asistente configurable (nombre + avatar holograma) — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que cada organización de Jarvis tenga su asistente con nombre propio y un avatar animado (tres videos de Higgsfield generados desde la interfaz) que se ve como holograma sutil en la web.

**Architecture:** Backend FastAPI: tablas nuevas en `jarvis.db`, un módulo `asistente.py` (configuración, nombre efectivo, orquestación de la generación y un hilo que vigila los trabajos) y un cliente fino `higgsfield.py`. Web vanilla JS: un panel de configuración (`asistente.js`, solo super admin) y un avatar en canvas (`avatar.js`) que reemplaza al orbe y toma el estado (reposo/escuchando/hablando) observando las clases que `app.js` ya le pone al orbe. Los puentes sacan el nombre de las instrucciones que ya reciben de Jarvis.

**Tech Stack:** Python 3.12, FastAPI, sqlite3, httpx, pytest; JS en módulos ES sin build; MediaPipe Tasks Vision 0.10.14 desde jsDelivr (solo para la foto animada de respaldo); API de Higgsfield (`https://api.higgsfield.ai`, auth `Key <id>:<secreto>`).

**Spec:** `docs/superpowers/specs/2026-10-26-avatar-holograma-design.md`. Ajustes respecto del spec, por lo que se encontró al planificar:
- La API de Higgsfield no devuelve los créditos de cada trabajo: no hay columna `creditos`; el costo que se muestra es un **estimado** de `JARVIS_AVATAR_CREDITOS_POR_VIDEO` (si no está, no se muestra cifra).
- No hay librería de imágenes en el servidor: la foto **no se achica**; se acepta JPG/PNG/WEBP de hasta 8 MB.
- El modelo por defecto es `kling-video/v2.5-turbo/pro/image-to-video` (documentado en la OpenAPI de Higgsfield; cuerpo `{prompt, image_url, duration, negative_prompt}`), cambiable con `JARVIS_AVATAR_MODELO`. La alternativa documentada es `minimax/hailuo-2.3/standard/image-to-video` (duración 6).
- El resplandor del holograma sigue el volumen real solo en la voz en vivo (hay un stream de audio); con la voz del navegador (`speechSynthesis`) late con una onda.

**Cómo correr las pruebas:** desde `C:\Users\Jorge\jarvis`, `.venv/Scripts/python.exe -m pytest -q` (hoy pasan 499). Puentes: `node --test test/*.test.js` dentro de cada carpeta.

**Despliegue:** Railway está desconectado del repo; Jarvis corre en el EC2 (`ssh ec2`, `/opt/jarvis`). Ver Task 11.

---

## Mapa de archivos

| Archivo | Qué | Responsabilidad |
|---|---|---|
| `backend/basedatos.py` | Modificar | Tablas `asistentes` y `asistente_videos`. |
| `backend/asistente.py` | Crear | Configuración por organización, nombre efectivo, archivos, generación y vigilancia de trabajos. |
| `backend/higgsfield.py` | Crear | Hablar con la API de Higgsfield: subir la foto, crear un video, leer el estado, bajar el resultado. Nada más. |
| `backend/cerebro.py` | Modificar | Usar `asistente.nombre(usuario)` en vez de `JARVIS_NOMBRE`. |
| `backend/acceso.py` | Modificar | `/api/asistente*` exige admin. |
| `backend/main.py` | Modificar | Rutas `/api/asistente/*`, `/avatares/*`, bloque `asistente` en `/api/estado`, arrancar el vigilante. |
| `web/index.html` | Modificar | Botón y panel "Asistente"; contenedor del avatar. |
| `web/asistente.js` | Crear | Panel de configuración (super admin). |
| `web/avatar.js` | Crear | Avatar en canvas: videos + holograma + foto animada de respaldo. |
| `web/style.css` | Modificar | Estilos del panel y del avatar. |
| `web/app.js` | Modificar | Abrir el panel, pasarle el bloque `asistente` al avatar. |
| `tests/test_asistente.py`, `tests/test_higgsfield.py`, `tests/test_asistente_api.py` | Crear | Pruebas. |
| Repo nuevo `Adminnebo/jarvis-puentes` | Crear | Código de `puente-reloj` y `puente-android` (hoy solo en el EC2). |

---

### Task 1: Tablas del asistente

**Files:**
- Modify: `backend/basedatos.py` (dentro de `_ESQUEMA`, al final, antes del cierre `"""`)
- Test: `tests/test_asistente.py`

- [ ] **Step 1: Escribir la prueba que falla**

Crear `tests/test_asistente.py`:

```python
import sqlite3

import pytest

from backend import basedatos


def test_las_tablas_del_asistente_existen():
    with basedatos.conexion() as con:
        tablas = {fila["name"] for fila in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )}
    assert {"asistentes", "asistente_videos"} <= tablas


def test_un_video_solo_puede_ser_de_los_tres_estados():
    with basedatos.conexion() as con:
        con.execute("INSERT INTO organizaciones (id, nombre, creada) VALUES ('o1', 'Org', 'x')")
        with pytest.raises(sqlite3.IntegrityError):
            con.execute(
                "INSERT INTO asistente_videos (organizacion_id, estado, actualizado) "
                "VALUES ('o1', 'bailando', 'x')"
            )
```

- [ ] **Step 2: Correrla y ver que falla**

Run: `.venv/Scripts/python.exe -m pytest tests/test_asistente.py -v`
Expected: FAIL — `asistentes` no está en las tablas.

- [ ] **Step 3: Agregar las tablas**

En `backend/basedatos.py`, dentro de `_ESQUEMA`, después de `creditos_envios`:

```sql
    -- El asistente de cada organizacion: su nombre y su foto. Sin fila, o con
    -- nombre NULL, se usa JARVIS_NOMBRE. Ver asistente.py.
    CREATE TABLE IF NOT EXISTS asistentes (
        organizacion_id TEXT PRIMARY KEY REFERENCES organizaciones(id) ON DELETE CASCADE,
        nombre TEXT,
        foto TEXT,
        actualizado TEXT NOT NULL
    );

    -- Los tres videos del avatar. `archivo` es el que se muestra; `trabajo_*`
    -- el que se esta generando en Higgsfield (el viejo sigue a la vista hasta
    -- que el nuevo termina bien).
    CREATE TABLE IF NOT EXISTS asistente_videos (
        organizacion_id TEXT NOT NULL REFERENCES organizaciones(id) ON DELETE CASCADE,
        estado TEXT NOT NULL CHECK (estado IN ('reposo', 'escuchando', 'hablando')),
        archivo TEXT,
        trabajo_id TEXT,
        trabajo_estado TEXT CHECK (trabajo_estado IN ('generando', 'listo', 'error')),
        trabajo_desde TEXT,
        error TEXT,
        actualizado TEXT NOT NULL,
        PRIMARY KEY (organizacion_id, estado)
    );
```

- [ ] **Step 4: Correr la prueba**

Run: `.venv/Scripts/python.exe -m pytest tests/test_asistente.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/basedatos.py tests/test_asistente.py
git commit -m "Asistente: tablas del nombre, la foto y los videos por organizacion"
```

---

### Task 2: Nombre efectivo y configuración (`asistente.py`)

**Files:**
- Create: `backend/asistente.py`
- Test: `tests/test_asistente.py` (agregar)

- [ ] **Step 1: Escribir las pruebas que fallan**

Agregar a `tests/test_asistente.py`:

```python
from backend import acceso, asistente


def _org(id_="o1", nombre="JH"):
    with basedatos.conexion() as con:
        con.execute("INSERT OR IGNORE INTO organizaciones (id, nombre, creada) VALUES (?, ?, 'x')",
                    (id_, nombre))


def _usuario(org=None):
    return acceso.Usuario("u-1", "Ana", "usuario", organizacion_id=org)


def test_sin_configurar_se_usa_la_variable(monkeypatch):
    monkeypatch.setenv("JARVIS_NOMBRE", "Nebo")
    _org()
    assert asistente.nombre(_usuario("o1")) == "Nebo"


def test_sin_variable_ni_configuracion_es_jarvis(monkeypatch):
    monkeypatch.delenv("JARVIS_NOMBRE", raising=False)
    assert asistente.nombre(_usuario(None)) == "Jarvis"


def test_el_nombre_de_la_organizacion_gana(monkeypatch):
    monkeypatch.setenv("JARVIS_NOMBRE", "Nebo")
    _org()
    asistente.guardar_nombre("o1", "  Sofía ")
    assert asistente.nombre(_usuario("o1")) == "Sofía"
    # Otra organizacion, o alguien sin organizacion, sigue con la variable.
    _org("o2", "Otra")
    assert asistente.nombre(_usuario("o2")) == "Nebo"
    assert asistente.nombre(_usuario(None)) == "Nebo"


def test_un_nombre_vacio_vuelve_a_la_variable(monkeypatch):
    monkeypatch.setenv("JARVIS_NOMBRE", "Nebo")
    _org()
    asistente.guardar_nombre("o1", "Sofía")
    asistente.guardar_nombre("o1", "   ")
    assert asistente.nombre(_usuario("o1")) == "Nebo"


def test_el_nombre_no_puede_ser_larguisimo():
    _org()
    with pytest.raises(asistente.ErrorDeAsistente):
        asistente.guardar_nombre("o1", "x" * 41)


def test_configuracion_de_una_organizacion_sin_nada():
    _org()
    datos = asistente.configuracion("o1")
    assert datos == {
        "organizacion_id": "o1", "nombre": None, "foto": None,
        "videos": {e: {"archivo": None, "trabajo_estado": None, "error": None}
                   for e in asistente.ESTADOS},
    }
```

- [ ] **Step 2: Correrlas y ver que fallan**

Run: `.venv/Scripts/python.exe -m pytest tests/test_asistente.py -v`
Expected: FAIL — `cannot import name 'asistente'`.

- [ ] **Step 3: Crear `backend/asistente.py`**

```python
"""El asistente de cada organizacion: como se llama y como se ve.

El nombre sale de la tabla `asistentes`; si la organizacion no lo configuro (o
la persona no tiene organizacion, como las contrasenas por variable), de
JARVIS_NOMBRE, y si tampoco esta, "Jarvis". Los archivos -la foto y los tres
videos del avatar- viven en datos/avatares/<organizacion>/. Solo el super admin
los cambia: lo controla acceso.exige_admin.
"""

import os
from datetime import datetime, timezone
from pathlib import Path

from . import acceso, basedatos, rutas

ESTADOS = ("reposo", "escuchando", "hablando")
LARGO_MAXIMO = 40


class ErrorDeAsistente(ValueError):
    """Algo de lo que mando el super admin no sirve; el mensaje es para el."""


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def por_defecto() -> str:
    return os.getenv("JARVIS_NOMBRE", "").strip() or "Jarvis"


def nombre(usuario: acceso.Usuario | None) -> str:
    organizacion_id = getattr(usuario, "organizacion_id", None)
    if organizacion_id:
        with basedatos.conexion() as con:
            fila = con.execute(
                "SELECT nombre FROM asistentes WHERE organizacion_id = ?", (organizacion_id,)
            ).fetchone()
        if fila and fila["nombre"]:
            return fila["nombre"]
    return por_defecto()


def _asegurar_fila(con, organizacion_id: str) -> None:
    con.execute(
        "INSERT OR IGNORE INTO asistentes (organizacion_id, actualizado) VALUES (?, ?)",
        (organizacion_id, _ahora()),
    )


def guardar_nombre(organizacion_id: str, valor: str) -> None:
    limpio = " ".join((valor or "").split())
    if len(limpio) > LARGO_MAXIMO:
        raise ErrorDeAsistente(f"El nombre puede tener hasta {LARGO_MAXIMO} letras.")
    with basedatos.conexion() as con:
        _asegurar_fila(con, organizacion_id)
        con.execute(
            "UPDATE asistentes SET nombre = ?, actualizado = ? WHERE organizacion_id = ?",
            (limpio or None, _ahora(), organizacion_id),
        )


def carpeta(organizacion_id: str) -> Path:
    destino = rutas.datos() / "avatares" / organizacion_id
    destino.mkdir(parents=True, exist_ok=True)
    return destino


def configuracion(organizacion_id: str) -> dict:
    with basedatos.conexion() as con:
        fila = con.execute(
            "SELECT nombre, foto FROM asistentes WHERE organizacion_id = ?", (organizacion_id,)
        ).fetchone()
        videos = {
            v["estado"]: v for v in con.execute(
                "SELECT estado, archivo, trabajo_estado, error FROM asistente_videos "
                "WHERE organizacion_id = ?", (organizacion_id,)
            )
        }
    return {
        "organizacion_id": organizacion_id,
        "nombre": fila["nombre"] if fila else None,
        "foto": fila["foto"] if fila else None,
        "videos": {
            e: {
                "archivo": videos[e]["archivo"] if e in videos else None,
                "trabajo_estado": videos[e]["trabajo_estado"] if e in videos else None,
                "error": videos[e]["error"] if e in videos else None,
            }
            for e in ESTADOS
        },
    }
```

- [ ] **Step 4: Correr las pruebas**

Run: `.venv/Scripts/python.exe -m pytest tests/test_asistente.py -v`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/asistente.py tests/test_asistente.py
git commit -m "Asistente: nombre por organizacion con JARVIS_NOMBRE de respaldo"
```

---

### Task 3: La personalidad usa el nombre de la organización

**Files:**
- Modify: `backend/cerebro.py:59` (en `instrucciones`) y `backend/cerebro.py:438` (en la lectura de fotos)
- Test: `tests/test_asistente.py` (agregar)

- [ ] **Step 1: Escribir la prueba que falla**

```python
def test_las_instrucciones_usan_el_nombre_de_la_organizacion(monkeypatch):
    from backend import cerebro

    monkeypatch.setenv("JARVIS_NOMBRE", "Nebo")
    _org()
    asistente.guardar_nombre("o1", "Sofía")
    assert cerebro.instrucciones(_usuario("o1")).startswith("Eres Sofía, el asistente personal de Ana.")
    assert cerebro.instrucciones(_usuario(None)).startswith("Eres Nebo, el asistente personal de Ana.")
```

- [ ] **Step 2: Correrla y ver que falla**

Run: `.venv/Scripts/python.exe -m pytest tests/test_asistente.py::test_las_instrucciones_usan_el_nombre_de_la_organizacion -v`
Expected: FAIL — empieza con "Eres Nebo" en el primer assert.

- [ ] **Step 3: Cambiar `cerebro.py`**

Agregar `asistente` al import de módulos del paquete (junto a `acceso`) y reemplazar las dos lecturas:

```python
# en instrucciones(usuario, extra=""):
    nombre = asistente.nombre(usuario)
```

```python
# en la funcion de la foto (linea ~438), que recibe `usuario`:
    nombre = asistente.nombre(usuario)
```

Comprobar que no queda ninguna: `grep -n "JARVIS_NOMBRE" backend/cerebro.py` → sin resultados.

- [ ] **Step 4: Correr toda la suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: todas pasan (499 + las nuevas).

- [ ] **Step 5: Commit**

```bash
git add backend/cerebro.py tests/test_asistente.py
git commit -m "La personalidad de Jarvis se presenta con el nombre de la organizacion"
```

---

### Task 4: Cliente de Higgsfield (`higgsfield.py`)

**Files:**
- Create: `backend/higgsfield.py`
- Test: `tests/test_higgsfield.py`

- [ ] **Step 1: Escribir las pruebas que fallan**

```python
import httpx
import pytest

from backend import higgsfield


@pytest.fixture
def con_clave(monkeypatch):
    monkeypatch.setenv("HIGGSFIELD_API_KEY_ID", "id1")
    monkeypatch.setenv("HIGGSFIELD_API_KEY_SECRET", "sec1")


class _R:
    def __init__(self, estado, cuerpo=None, contenido=b""):
        self.status_code = estado
        self._cuerpo = cuerpo or {}
        self.content = contenido
        self.text = str(cuerpo)

    def json(self):
        return self._cuerpo


def test_sin_clave_no_esta_configurado(monkeypatch):
    monkeypatch.delenv("HIGGSFIELD_API_KEY_ID", raising=False)
    assert higgsfield.configurado() is False


def test_crear_video_sube_la_foto_y_pide_el_modelo(con_clave, monkeypatch):
    pedidos = []

    def post(url, json=None, headers=None, timeout=None):
        pedidos.append(("POST", url, json, headers))
        if url.endswith("/files/generate-upload-url"):
            return _R(200, {"upload_url": "https://s3/subir", "public_url": "https://cdn/foto.jpg",
                            "upload_headers": {"Content-Type": "image/jpeg", "x-amz-tagging": "t"}})
        return _R(200, {"request_id": "req-1", "status": "queued"})

    def put(url, content=None, headers=None, timeout=None):
        pedidos.append(("PUT", url, None, headers))
        return _R(200)

    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(httpx, "put", put)

    url = higgsfield.subir_imagen(b"jpg", "image/jpeg")
    request_id = higgsfield.crear_video(url, "breathing calmly")

    assert url == "https://cdn/foto.jpg"
    assert request_id == "req-1"
    assert pedidos[0][3]["Authorization"] == "Key id1:sec1"
    # La subida a S3 lleva SUS cabeceras y nunca la clave de Higgsfield.
    assert pedidos[1][0] == "PUT" and "Authorization" not in pedidos[1][3]
    assert pedidos[2][1] == "https://api.higgsfield.ai/kling-video/v2.5-turbo/pro/image-to-video"
    assert pedidos[2][2]["image_url"] == "https://cdn/foto.jpg"
    assert pedidos[2][2]["duration"] == 5


def test_el_modelo_se_cambia_con_una_variable(con_clave, monkeypatch):
    monkeypatch.setenv("JARVIS_AVATAR_MODELO", "minimax/hailuo-2.3/standard/image-to-video")
    vistos = []
    monkeypatch.setattr(httpx, "post", lambda url, **k: vistos.append((url, k["json"])) or _R(200, {"request_id": "r"}))
    higgsfield.crear_video("https://cdn/f.jpg", "p")
    assert vistos[0][0].endswith("/minimax/hailuo-2.3/standard/image-to-video")
    assert vistos[0][1]["duration"] == 6


def test_estado_terminado_trae_la_url_del_video(con_clave, monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda url, **k: _R(200, {
        "status": "completed", "request_id": "req-1", "video": {"url": "https://cdn/v.mp4"}}))
    assert higgsfield.estado("req-1") == {"estado": "listo", "url": "https://cdn/v.mp4", "error": None}


@pytest.mark.parametrize("crudo,esperado", [
    ("queued", "generando"), ("in_progress", "generando"),
    ("failed", "error"), ("nsfw", "error"), ("canceled", "error"),
])
def test_estados_de_higgsfield(con_clave, monkeypatch, crudo, esperado):
    monkeypatch.setattr(httpx, "get", lambda url, **k: _R(200, {"status": crudo, "request_id": "r", "error": "x"}))
    assert higgsfield.estado("r")["estado"] == esperado


def test_un_rechazo_de_la_api_es_un_error_legible(con_clave, monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda url, **k: _R(402, {"detail": "Not enough credits"}))
    with pytest.raises(higgsfield.ErrorDeHiggsfield, match="Not enough credits"):
        higgsfield.crear_video("https://cdn/f.jpg", "p")
```

- [ ] **Step 2: Correrlas y ver que fallan**

Run: `.venv/Scripts/python.exe -m pytest tests/test_higgsfield.py -v`
Expected: FAIL — `cannot import name 'higgsfield'`.

- [ ] **Step 3: Crear `backend/higgsfield.py`**

```python
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
```

- [ ] **Step 4: Correr las pruebas**

Run: `.venv/Scripts/python.exe -m pytest tests/test_higgsfield.py -v`
Expected: PASS (10 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/higgsfield.py tests/test_higgsfield.py
git commit -m "Cliente minimo de la API de Higgsfield: subir foto, crear video, estado, bajar"
```

---

### Task 5: Foto del asistente

**Files:**
- Modify: `backend/asistente.py`
- Test: `tests/test_asistente.py` (agregar)

- [ ] **Step 1: Escribir las pruebas que fallan**

```python
JPG = b"\xff\xd8\xff\xe0" + b"0" * 100
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100


def test_guardar_la_foto_la_deja_en_su_carpeta():
    _org()
    archivo = asistente.guardar_foto("o1", JPG)
    assert archivo.startswith("foto-") and archivo.endswith(".jpg")
    assert (asistente.carpeta("o1") / archivo).read_bytes() == JPG
    assert asistente.configuracion("o1")["foto"] == archivo


def test_una_foto_nueva_borra_la_vieja():
    _org()
    vieja = asistente.guardar_foto("o1", JPG)
    nueva = asistente.guardar_foto("o1", PNG)
    assert nueva.endswith(".png") and nueva != vieja
    assert not (asistente.carpeta("o1") / vieja).exists()


def test_solo_jpg_png_o_webp_y_hasta_8_mb():
    _org()
    with pytest.raises(asistente.ErrorDeAsistente, match="JPG, PNG o WEBP"):
        asistente.guardar_foto("o1", b"GIF89a" + b"0" * 10)
    with pytest.raises(asistente.ErrorDeAsistente, match="8 MB"):
        asistente.guardar_foto("o1", JPG + b"0" * (8 * 1024 * 1024))
```

- [ ] **Step 2: Correrlas y ver que fallan**

Run: `.venv/Scripts/python.exe -m pytest tests/test_asistente.py -v -k foto`
Expected: FAIL — `module 'backend.asistente' has no attribute 'guardar_foto'`.

- [ ] **Step 3: Agregar a `backend/asistente.py`**

```python
import time

MAXIMO_FOTO = 8 * 1024 * 1024
# Por la firma del archivo, no por lo que diga el navegador.
FIRMAS = ((b"\xff\xd8\xff", "jpg", "image/jpeg"), (b"\x89PNG", "png", "image/png"))


def tipo_de_imagen(contenido: bytes) -> tuple[str, str] | None:
    """(extension, content type) o None si no es una imagen aceptada."""
    for firma, extension, tipo in FIRMAS:
        if contenido.startswith(firma):
            return extension, tipo
    if contenido[:4] == b"RIFF" and contenido[8:12] == b"WEBP":
        return "webp", "image/webp"
    return None


def _marca() -> str:
    return str(int(time.time() * 1000))


def guardar_foto(organizacion_id: str, contenido: bytes) -> str:
    if len(contenido) > MAXIMO_FOTO:
        raise ErrorDeAsistente("La foto puede pesar hasta 8 MB.")
    tipo = tipo_de_imagen(contenido)
    if not tipo:
        raise ErrorDeAsistente("La foto tiene que ser JPG, PNG o WEBP.")
    archivo = f"foto-{_marca()}.{tipo[0]}"
    (carpeta(organizacion_id) / archivo).write_bytes(contenido)
    with basedatos.conexion() as con:
        _asegurar_fila(con, organizacion_id)
        vieja = con.execute(
            "SELECT foto FROM asistentes WHERE organizacion_id = ?", (organizacion_id,)
        ).fetchone()["foto"]
        con.execute(
            "UPDATE asistentes SET foto = ?, actualizado = ? WHERE organizacion_id = ?",
            (archivo, _ahora(), organizacion_id),
        )
    if vieja:
        (carpeta(organizacion_id) / vieja).unlink(missing_ok=True)
    return archivo
```

- [ ] **Step 4: Correr las pruebas**

Run: `.venv/Scripts/python.exe -m pytest tests/test_asistente.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/asistente.py tests/test_asistente.py
git commit -m "Asistente: guardar la foto (JPG/PNG/WEBP, hasta 8 MB) y borrar la anterior"
```

---

### Task 6: Generar los videos y vigilarlos

**Files:**
- Modify: `backend/asistente.py`
- Test: `tests/test_asistente.py` (agregar)

- [ ] **Step 1: Escribir las pruebas que fallan**

```python
class _HiggsfieldFalso:
    """Reemplaza a backend.higgsfield en las pruebas."""

    def __init__(self):
        self.creados = []
        self.estados = {}
        self.subidas = []

    def configurado(self):
        return True

    def subir_imagen(self, contenido, tipo):
        self.subidas.append(tipo)
        return "https://cdn/foto"

    def crear_video(self, url, prompt):
        rid = f"req-{len(self.creados) + 1}"
        self.creados.append((url, prompt))
        self.estados[rid] = {"estado": "generando", "url": None, "error": None}
        return rid

    def estado(self, rid):
        return self.estados[rid]

    def descargar(self, url):
        return b"MP4-" + url.encode()


@pytest.fixture
def hf(monkeypatch):
    falso = _HiggsfieldFalso()
    monkeypatch.setattr(asistente, "higgsfield", falso)
    return falso



def test_generar_sin_foto_avisa(hf):
    _org()
    with pytest.raises(asistente.ErrorDeAsistente, match="foto"):
        asistente.generar("o1", ["reposo"])


def test_generar_crea_un_trabajo_por_estado_con_su_prompt(hf):
    _org()
    asistente.guardar_foto("o1", JPG)
    asistente.generar("o1", ["reposo", "hablando"])
    assert hf.subidas == ["image/jpeg"]           # la foto se sube una sola vez
    assert [p for _, p in hf.creados] == [asistente.PROMPTS["reposo"], asistente.PROMPTS["hablando"]]
    videos = asistente.configuracion("o1")["videos"]
    assert videos["reposo"]["trabajo_estado"] == "generando"
    assert videos["escuchando"]["trabajo_estado"] is None


def test_un_estado_inventado_no_se_genera(hf):
    _org()
    asistente.guardar_foto("o1", JPG)
    with pytest.raises(asistente.ErrorDeAsistente):
        asistente.generar("o1", ["bailando"])


def test_al_terminar_baja_el_video_y_reemplaza_al_viejo(hf):
    _org()
    asistente.guardar_foto("o1", JPG)
    asistente.generar("o1", ["reposo"])
    hf.estados["req-1"] = {"estado": "listo", "url": "https://cdn/v1.mp4", "error": None}
    asistente.revisar_trabajos()
    v = asistente.configuracion("o1")["videos"]["reposo"]
    assert v["trabajo_estado"] == "listo" and v["archivo"].startswith("reposo-")
    primero = v["archivo"]
    assert (asistente.carpeta("o1") / primero).read_bytes() == b"MP4-https://cdn/v1.mp4"

    # Regenerar: mientras se genera se sigue viendo el viejo; al terminar se borra.
    asistente.generar("o1", ["reposo"])
    assert asistente.configuracion("o1")["videos"]["reposo"]["archivo"] == primero
    hf.estados["req-2"] = {"estado": "listo", "url": "https://cdn/v2.mp4", "error": None}
    asistente.revisar_trabajos()
    segundo = asistente.configuracion("o1")["videos"]["reposo"]["archivo"]
    assert segundo != primero
    assert not (asistente.carpeta("o1") / primero).exists()


def test_un_fallo_queda_a_la_vista_y_no_toca_el_video_anterior(hf):
    _org()
    asistente.guardar_foto("o1", JPG)
    asistente.generar("o1", ["reposo"])
    hf.estados["req-1"] = {"estado": "error", "url": None, "error": "Not enough credits"}
    asistente.revisar_trabajos()
    v = asistente.configuracion("o1")["videos"]["reposo"]
    assert v == {"archivo": None, "trabajo_estado": "error", "error": "Not enough credits"}


def test_un_trabajo_de_mas_de_30_minutos_se_da_por_perdido(hf):
    _org()
    asistente.guardar_foto("o1", JPG)
    asistente.generar("o1", ["reposo"])
    with basedatos.conexion() as con:
        con.execute("UPDATE asistente_videos SET trabajo_desde = '2000-01-01T00:00:00+00:00'")
    asistente.revisar_trabajos()
    v = asistente.configuracion("o1")["videos"]["reposo"]
    assert v["trabajo_estado"] == "error" and "no respondio" in v["error"]


def test_si_higgsfield_no_contesta_se_reintenta_despues(hf):
    _org()
    asistente.guardar_foto("o1", JPG)
    asistente.generar("o1", ["reposo"])

    def caido(rid):
        raise RuntimeError("timeout")
    hf.estado = caido
    asistente.revisar_trabajos()               # no lanza
    assert asistente.configuracion("o1")["videos"]["reposo"]["trabajo_estado"] == "generando"


def test_un_rechazo_al_crear_queda_como_error_de_ese_video(hf):
    _org()
    asistente.guardar_foto("o1", JPG)

    def rechaza(url, prompt):
        raise asistente.higgsfield_error("Higgsfield 402: Not enough credits")
    hf.crear_video = rechaza
    asistente.generar("o1", ["reposo"])
    v = asistente.configuracion("o1")["videos"]["reposo"]
    assert v["trabajo_estado"] == "error" and "402" in v["error"]
```

- [ ] **Step 2: Correrlas y ver que fallan**

Run: `.venv/Scripts/python.exe -m pytest tests/test_asistente.py -v -k "generar or terminar or fallo or minutos or contesta or rechazo"`
Expected: FAIL — `module 'backend.asistente' has no attribute 'generar'`.

- [ ] **Step 3: Agregar a `backend/asistente.py`**

```python
import threading
from datetime import timedelta

from . import higgsfield

# Para atrapar los rechazos de la API sin depender del modulo real en las pruebas.
higgsfield_error = higgsfield.ErrorDeHiggsfield

COMUN = ("same person as the image, head and shoulders, looking at the camera, "
         "plain dark background, soft studio light, static camera")
PROMPTS = {
    "reposo": f"{COMUN}. Breathing calmly, natural blinking, very slight head movement, mouth closed.",
    "escuchando": f"{COMUN}. Attentive expression, slight nod as if listening carefully, mouth closed.",
    "hablando": f"{COMUN}. Talking naturally as if explaining something, mouth moving, subtle head gestures.",
}
VENCE = timedelta(minutes=30)
CADA_SEGUNDOS = 15


def generar(organizacion_id: str, estados: list[str]) -> None:
    """Pide a Higgsfield un video por estado. El anterior sigue a la vista."""
    if not estados or any(e not in ESTADOS for e in estados):
        raise ErrorDeAsistente("Los videos son: reposo, escuchando y hablando.")
    if not higgsfield.configurado():
        raise ErrorDeAsistente("Falta la clave de Higgsfield en el servidor (HIGGSFIELD_API_KEY_ID/SECRET).")
    foto = configuracion(organizacion_id)["foto"]
    if not foto:
        raise ErrorDeAsistente("Primero subi una foto.")

    contenido = (carpeta(organizacion_id) / foto).read_bytes()
    url = higgsfield.subir_imagen(contenido, tipo_de_imagen(contenido)[1])
    for estado_ in dict.fromkeys(estados):
        try:
            rid, est, error = higgsfield.crear_video(url, PROMPTS[estado_]), "generando", None
        except higgsfield_error as fallo:
            rid, est, error = None, "error", str(fallo)
        with basedatos.conexion() as con:
            con.execute(
                "INSERT INTO asistente_videos "
                "(organizacion_id, estado, trabajo_id, trabajo_estado, trabajo_desde, error, actualizado) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (organizacion_id, estado) DO UPDATE SET trabajo_id = excluded.trabajo_id, "
                "trabajo_estado = excluded.trabajo_estado, trabajo_desde = excluded.trabajo_desde, "
                "error = excluded.error, actualizado = excluded.actualizado",
                (organizacion_id, estado_, rid, est, _ahora(), error, _ahora()),
            )


def _terminar(fila, nuevo: bytes) -> None:
    org, estado_ = fila["organizacion_id"], fila["estado"]
    archivo = f"{estado_}-{_marca()}.mp4"
    (carpeta(org) / archivo).write_bytes(nuevo)
    with basedatos.conexion() as con:
        con.execute(
            "UPDATE asistente_videos SET archivo = ?, trabajo_id = NULL, trabajo_estado = 'listo', "
            "error = NULL, actualizado = ? WHERE organizacion_id = ? AND estado = ?",
            (archivo, _ahora(), org, estado_),
        )
    if fila["archivo"]:
        (carpeta(org) / fila["archivo"]).unlink(missing_ok=True)


def _fallar(fila, motivo: str) -> None:
    with basedatos.conexion() as con:
        con.execute(
            "UPDATE asistente_videos SET trabajo_id = NULL, trabajo_estado = 'error', error = ?, "
            "actualizado = ? WHERE organizacion_id = ? AND estado = ?",
            (motivo[:300], _ahora(), fila["organizacion_id"], fila["estado"]),
        )


def revisar_trabajos() -> None:
    """Una pasada sobre los trabajos en curso. La llama el hilo de fondo."""
    with basedatos.conexion() as con:
        filas = con.execute(
            "SELECT organizacion_id, estado, archivo, trabajo_id, trabajo_desde "
            "FROM asistente_videos WHERE trabajo_estado = 'generando'"
        ).fetchall()
    ahora = datetime.now(timezone.utc)
    for fila in filas:
        if ahora - datetime.fromisoformat(fila["trabajo_desde"]) > VENCE:
            _fallar(fila, "Higgsfield no respondio en 30 minutos. Proba de nuevo.")
            continue
        try:
            resultado = higgsfield.estado(fila["trabajo_id"])
            if resultado["estado"] == "listo":
                _terminar(fila, higgsfield.descargar(resultado["url"]))
            elif resultado["estado"] == "error":
                _fallar(fila, resultado["error"] or "Fallo en Higgsfield.")
        except Exception as fallo:  # noqa: BLE001 - un corte de red no es un video fallado
            print(f"  Avatar: no se pudo revisar {fila['trabajo_id']} ({type(fallo).__name__}).")


def vigilar() -> None:
    """Hilo de fondo. Al arrancar retoma lo que quedo en 'generando'."""
    def bucle():
        while True:
            try:
                revisar_trabajos()
            except Exception as fallo:  # noqa: BLE001 - nunca debe matar el hilo
                print(f"  Avatar: fallo una revision ({type(fallo).__name__}).")
            time.sleep(CADA_SEGUNDOS)

    threading.Thread(target=bucle, name="avatar", daemon=True).start()


def costo_estimado(cuantos: int) -> float | None:
    valor = os.getenv("JARVIS_AVATAR_CREDITOS_POR_VIDEO", "").strip().replace(",", ".")
    try:
        return round(float(valor) * cuantos, 2) if valor else None
    except ValueError:
        return None
```

- [ ] **Step 4: Correr las pruebas**

Run: `.venv/Scripts/python.exe -m pytest tests/test_asistente.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/asistente.py tests/test_asistente.py
git commit -m "Asistente: generar los tres videos con Higgsfield y vigilarlos hasta que terminen"
```

---

### Task 7: Rutas de la API

**Files:**
- Modify: `backend/acceso.py` (`exige_admin`), `backend/main.py` (rutas, `/api/estado`, arranque)
- Test: `tests/test_asistente_api.py`

- [ ] **Step 1: Escribir las pruebas que fallan**

```python
import pytest
from fastapi.testclient import TestClient

from backend import asistente, cuentas
from backend.main import app

JPG = b"\xff\xd8\xff\xe0" + b"0" * 100


@pytest.fixture
def admin(monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setenv("JARVIS_CLAVE_SECRETA", "clave-de-pruebas-larga")
    monkeypatch.setenv("JARVIS_NOMBRE", "Nebo")
    cliente = TestClient(app)
    cliente.post("/acceso", data={"clave": "la-del-admin"}, follow_redirects=False)
    return cliente


def _org_con_persona():
    usuario = cuentas.crear_organizacion("JH", "Ana", "ana@jh.com", "una-clave-larga")
    return usuario.organizacion_id


def test_el_admin_cambia_el_nombre(admin):
    org = _org_con_persona()
    r = admin.put(f"/api/asistente/{org}", json={"nombre": "Sofía"})
    assert r.status_code == 200
    assert admin.get(f"/api/asistente/{org}").json()["nombre"] == "Sofía"


def test_una_organizacion_que_no_existe_da_404(admin):
    assert admin.get("/api/asistente/no-existe").status_code == 404


def test_el_admin_sube_la_foto(admin):
    org = _org_con_persona()
    r = admin.post(f"/api/asistente/{org}/foto", files={"foto": ("cara.jpg", JPG, "image/jpeg")})
    assert r.status_code == 200 and r.json()["foto"].startswith("foto-")


def test_una_foto_mala_es_400(admin):
    org = _org_con_persona()
    r = admin.post(f"/api/asistente/{org}/foto", files={"foto": ("x.gif", b"GIF89a", "image/gif")})
    assert r.status_code == 400 and "JPG" in r.json()["error"]


def test_quien_no_es_admin_no_entra(monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setenv("JARVIS_CLAVE_SECRETA", "clave-de-pruebas-larga")
    org = _org_con_persona()
    cliente = TestClient(app)
    cliente.post("/acceso/cuenta", data={"email": "ana@jh.com", "password": "una-clave-larga"},
                 follow_redirects=False)
    assert cliente.get(f"/api/asistente/{org}").status_code == 403
    assert cliente.put(f"/api/asistente/{org}", json={"nombre": "X"}).status_code == 403


def test_el_estado_trae_el_asistente_de_la_organizacion(monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setenv("JARVIS_CLAVE_SECRETA", "clave-de-pruebas-larga")
    monkeypatch.setenv("JARVIS_NOMBRE", "Nebo")
    org = _org_con_persona()
    asistente.guardar_nombre(org, "Sofía")
    archivo = asistente.guardar_foto(org, JPG)
    cliente = TestClient(app)
    cliente.post("/acceso/cuenta", data={"email": "ana@jh.com", "password": "una-clave-larga"},
                 follow_redirects=False)
    estado = cliente.get("/api/estado").json()
    assert estado["nombre"] == "Sofía"
    assert estado["asistente"]["foto"] == f"/avatares/{org}/{archivo}"
    assert estado["asistente"]["videos"] == {"reposo": None, "escuchando": None, "hablando": None}
    # Su foto la puede ver; la de otra organizacion no.
    assert cliente.get(f"/avatares/{org}/{archivo}").content == JPG
    otra = cuentas.crear_organizacion("Otra", "Beto", "beto@otra.com", "otra-clave-larga").organizacion_id
    otro_archivo = asistente.guardar_foto(otra, JPG)
    assert cliente.get(f"/avatares/{otra}/{otro_archivo}").status_code == 404


def test_avatares_no_deja_salir_de_la_carpeta(admin):
    org = _org_con_persona()
    assert admin.get(f"/avatares/{org}/..%2F..%2Fjarvis.db").status_code == 404


def test_generar_sin_clave_de_higgsfield_es_400(admin, monkeypatch):
    monkeypatch.delenv("HIGGSFIELD_API_KEY_ID", raising=False)
    org = _org_con_persona()
    admin.post(f"/api/asistente/{org}/foto", files={"foto": ("cara.jpg", JPG, "image/jpeg")})
    r = admin.post(f"/api/asistente/{org}/generar", json={"estados": ["reposo"]})
    assert r.status_code == 400 and "Higgsfield" in r.json()["error"]
```

- [ ] **Step 2: Correrlas y ver que fallan**

Run: `.venv/Scripts/python.exe -m pytest tests/test_asistente_api.py -v`
Expected: FAIL — 404 en `/api/asistente/...` y `KeyError: 'asistente'`.

- [ ] **Step 3a: `exige_admin` en `backend/acceso.py`**

Dentro de `exige_admin`, junto a las otras reglas:

```python
    # El asistente de cada organizacion (nombre, foto, videos) lo configura
    # solo el super admin de Nebo.
    if ruta.startswith("/api/asistente"):
        return True
```

- [ ] **Step 3b: Rutas en `backend/main.py`**

Agregar `asistente` al import de módulos. En `al_arrancar()`, al final: `asistente.vigilar()`. Antes de `app.mount("/", StaticFiles(...))` (las rutas deben quedar antes del montaje):

```python
def _organizacion_o_404(organizacion_id: str):
    if not cuentas.nombre_organizacion(organizacion_id):
        return JSONResponse(status_code=404, content={"error": "Esa organizacion no existe."})
    return None


def _publico(organizacion_id: str) -> dict:
    """El asistente como lo ve la web: URLs en vez de nombres de archivo."""
    datos = asistente.configuracion(organizacion_id)
    base = f"/avatares/{organizacion_id}/"
    return {
        **datos,
        "foto_url": base + datos["foto"] if datos["foto"] else None,
        "videos": {
            e: {**v, "url": base + v["archivo"] if v["archivo"] else None}
            for e, v in datos["videos"].items()
        },
        "costo_por_video": asistente.costo_estimado(1),
        "higgsfield": higgsfield.configurado(),
    }


@app.get("/api/asistente/{organizacion_id}")
def ver_asistente(organizacion_id: str):
    return _organizacion_o_404(organizacion_id) or _publico(organizacion_id)


@app.put("/api/asistente/{organizacion_id}")
def cambiar_asistente(organizacion_id: str, datos: dict):
    if (falta := _organizacion_o_404(organizacion_id)):
        return falta
    try:
        asistente.guardar_nombre(organizacion_id, str(datos.get("nombre") or ""))
    except asistente.ErrorDeAsistente as error:
        return JSONResponse(status_code=400, content={"error": str(error)})
    return _publico(organizacion_id)


@app.post("/api/asistente/{organizacion_id}/foto")
async def subir_foto_del_asistente(organizacion_id: str, foto: UploadFile = File(...)):
    if (falta := _organizacion_o_404(organizacion_id)):
        return falta
    contenido = await foto.read(asistente.MAXIMO_FOTO + 1)
    try:
        asistente.guardar_foto(organizacion_id, contenido)
    except asistente.ErrorDeAsistente as error:
        return JSONResponse(status_code=400, content={"error": str(error)})
    return _publico(organizacion_id)


@app.post("/api/asistente/{organizacion_id}/generar")
def generar_videos_del_asistente(organizacion_id: str, datos: dict):
    if (falta := _organizacion_o_404(organizacion_id)):
        return falta
    try:
        asistente.generar(organizacion_id, list(datos.get("estados") or []))
    except (asistente.ErrorDeAsistente, higgsfield.ErrorDeHiggsfield) as error:
        return JSONResponse(status_code=400, content={"error": str(error)})
    return _publico(organizacion_id)


@app.get("/avatares/{organizacion_id}/{archivo}")
def archivo_del_avatar(organizacion_id: str, archivo: str, peticion: Request):
    """Solo la gente de esa organizacion, o el super admin."""
    usuario = peticion.state.usuario
    if usuario.rol != "admin" and usuario.organizacion_id != organizacion_id:
        return JSONResponse(status_code=404, content={"error": "No existe."})
    datos = asistente.configuracion(organizacion_id)
    validos = {datos["foto"], *(v["archivo"] for v in datos["videos"].values())} - {None}
    if archivo not in validos:
        return JSONResponse(status_code=404, content={"error": "No existe."})
    return FileResponse(asistente.carpeta(organizacion_id) / archivo,
                        headers={"Cache-Control": "private, max-age=31536000, immutable"})
```

Imports nuevos al principio de `main.py`: `from fastapi import File, UploadFile` (junto a los de fastapi que ya están) y `higgsfield` en el import de módulos del paquete.

- [ ] **Step 3c: `/api/estado`**

En `estado()`, reemplazar `"nombre": os.getenv("JARVIS_NOMBRE", "Jarvis"),` por:

```python
        "nombre": asistente.nombre(usuario),
        "asistente": _asistente_para(usuario),
```

y agregar, junto a `_publico`:

```python
def _asistente_para(usuario) -> dict:
    """Lo que necesita el avatar de la web: URLs de la foto y de los tres videos."""
    vacio = {"foto": None, "videos": {e: None for e in asistente.ESTADOS}}
    if not usuario.organizacion_id:
        return vacio
    datos = _publico(usuario.organizacion_id)
    return {"foto": datos["foto_url"], "videos": {e: v["url"] for e, v in datos["videos"].items()}}
```

- [ ] **Step 4: Correr toda la suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: todas pasan.

- [ ] **Step 5: Commit**

```bash
git add backend/acceso.py backend/main.py tests/test_asistente_api.py
git commit -m "API del asistente: nombre, foto, generar videos y servir los archivos por organizacion"
```

---

### Task 8: Panel "Asistente" en la web

**Files:**
- Modify: `web/index.html`, `web/app.js`, `web/style.css`
- Create: `web/asistente.js`

- [ ] **Step 1: Botón y panel en `web/index.html`**

En `.acciones`, después de `btn-organizacion`:

```html
      <button id="btn-asistente" class="boton-texto" hidden data-super-admin>Asistente</button>
```

Junto a los otros `<aside class="panel">` (copiar la estructura de `panel-organizacion`):

```html
  <aside class="panel" id="panel-asistente" hidden>
    <div class="panel-barra">
      <h2>Asistente</h2>
      <button class="boton-cerrar" id="btn-cerrar-asistente" aria-label="Cerrar">&times;</button>
    </div>
    <div class="panel-cuerpo">
      <label class="campo">Organización
        <select id="asistente-org"></select>
      </label>
      <label class="campo">Nombre del asistente
        <input id="asistente-nombre" maxlength="40" placeholder="Si lo dejás vacío: el de siempre">
      </label>
      <button id="asistente-guardar-nombre" class="boton-texto">Guardar nombre</button>
      <div class="asistente-foto">
        <img id="asistente-foto" alt="" hidden>
        <label class="boton-texto">Subir foto<input id="asistente-archivo" type="file"
               accept="image/jpeg,image/png,image/webp" hidden></label>
        <p class="tenue">De frente, cara bien visible, boca cerrada. JPG, PNG o WEBP, hasta 8 MB.</p>
      </div>
      <div id="asistente-videos" class="asistente-videos"></div>
      <button id="asistente-generar-todo" class="boton-texto">Generar los tres videos</button>
      <p id="asistente-aviso" class="tenue"></p>
    </div>
  </aside>
```

- [ ] **Step 2: Crear `web/asistente.js`**

```js
/* Panel del asistente: nombre, foto y videos de cada organizacion. Solo para
   el super admin (el servidor lo exige; esconder el boton es comodidad). */

const $$ = (id) => document.getElementById(id);
const ESTADOS = [["reposo", "En reposo"], ["escuchando", "Escuchando"], ["hablando", "Hablando"]];
let organizacion = null;
let sondeo = null;

async function pedir(url, opciones = {}) {
  const r = await fetch(url, opciones);
  const datos = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(datos.error || `Error ${r.status}`);
  return datos;
}

export async function abrirPanelAsistente() {
  $$("panel-asistente").hidden = false;
  const { organizaciones } = await pedir("/api/organizaciones");
  const select = $$("asistente-org");
  select.innerHTML = "";
  for (const o of organizaciones) select.add(new Option(o.nombre, o.id));
  organizacion = select.value || null;
  select.onchange = () => { organizacion = select.value; refrescar(); };
  await refrescar();
}

function cerrar() {
  $$("panel-asistente").hidden = true;
  clearTimeout(sondeo);
}

function aviso(texto) { $$("asistente-aviso").textContent = texto || ""; }

function pintar(datos) {
  $$("asistente-nombre").value = datos.nombre || "";
  const foto = $$("asistente-foto");
  foto.hidden = !datos.foto_url;
  if (datos.foto_url) foto.src = datos.foto_url;

  const caja = $$("asistente-videos");
  caja.innerHTML = "";
  let enCurso = false;
  for (const [estado, titulo] of ESTADOS) {
    const v = datos.videos[estado];
    enCurso ||= v.trabajo_estado === "generando";
    const fila = document.createElement("div");
    fila.className = "asistente-video";
    const situacion = v.trabajo_estado === "generando" ? "Generando…"
      : v.trabajo_estado === "error" ? `Falló: ${v.error}` : v.url ? "Listo" : "Sin video";
    fila.innerHTML = `<strong>${titulo}</strong><span class="tenue"></span>`;
    fila.querySelector("span").textContent = situacion;
    if (v.url) {
      const video = document.createElement("video");
      Object.assign(video, { src: v.url, muted: true, loop: true, autoplay: true, playsInline: true });
      fila.prepend(video);
    }
    const boton = document.createElement("button");
    boton.className = "boton-texto";
    boton.textContent = v.url ? "Regenerar" : "Generar";
    boton.disabled = v.trabajo_estado === "generando" || !datos.foto || !datos.higgsfield;
    boton.onclick = () => generar([estado], datos);
    fila.append(boton);
    caja.append(fila);
  }
  $$("asistente-generar-todo").disabled = enCurso || !datos.foto || !datos.higgsfield;
  $$("asistente-generar-todo").onclick = () => generar(ESTADOS.map(([e]) => e), datos);
  if (!datos.higgsfield) aviso("Falta la clave de Higgsfield en el servidor: no se puede generar.");

  clearTimeout(sondeo);
  if (enCurso) sondeo = setTimeout(refrescar, 5000);
}

async function refrescar() {
  if (!organizacion) { aviso("No hay organizaciones."); return; }
  try {
    pintar(await pedir(`/api/asistente/${encodeURIComponent(organizacion)}`));
  } catch (error) { aviso(error.message); }
}

async function generar(estados, datos) {
  const costo = datos.costo_por_video ? ` (unos ${datos.costo_por_video * estados.length} créditos)` : "";
  if (!confirm(`¿Generar ${estados.length} video${estados.length > 1 ? "s" : ""} con Higgsfield${costo}?`)) return;
  aviso("Pidiendo los videos…");
  try {
    pintar(await pedir(`/api/asistente/${encodeURIComponent(organizacion)}/generar`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ estados }),
    }));
    aviso("Higgsfield está generando. Tarda unos minutos; podés cerrar este panel.");
  } catch (error) { aviso(error.message); }
}

$$("btn-cerrar-asistente").onclick = cerrar;
$$("asistente-guardar-nombre").onclick = async () => {
  try {
    pintar(await pedir(`/api/asistente/${encodeURIComponent(organizacion)}`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nombre: $$("asistente-nombre").value }),
    }));
    aviso("Nombre guardado.");
  } catch (error) { aviso(error.message); }
};
$$("asistente-archivo").onchange = async (e) => {
  const archivo = e.target.files[0];
  if (!archivo) return;
  const cuerpo = new FormData();
  cuerpo.append("foto", archivo);
  aviso("Subiendo la foto…");
  try {
    pintar(await pedir(`/api/asistente/${encodeURIComponent(organizacion)}/foto`, { method: "POST", body: cuerpo }));
    aviso("Foto guardada. Ahora podés generar los videos.");
  } catch (error) { aviso(error.message); }
  e.target.value = "";
};
```

- [ ] **Step 3: Conectar el botón en `web/app.js`**

Junto al import de `organizacion.js` y donde se engancha `btn-organizacion`:

```js
import { abrirPanelAsistente } from "./asistente.js";
// ...
$("btn-asistente").addEventListener("click", () => abrirPanelAsistente());
```

- [ ] **Step 4: Estilos en `web/style.css`** (al final)

```css
.asistente-foto { display: flex; align-items: center; gap: 12px; margin: 12px 0; flex-wrap: wrap; }
.asistente-foto img { width: 72px; height: 72px; border-radius: 50%; object-fit: cover; border: 1px solid var(--borde); }
.asistente-videos { display: grid; gap: 10px; margin: 12px 0; }
.asistente-video { display: grid; grid-template-columns: 64px 1fr auto; gap: 10px; align-items: center;
  background: var(--panel); border: 1px solid var(--borde); border-radius: 10px; padding: 8px; }
.asistente-video video { width: 64px; height: 64px; object-fit: cover; border-radius: 8px; grid-row: span 2; }
.asistente-video:not(:has(video)) { grid-template-columns: 1fr auto; }
.campo { display: grid; gap: 4px; margin-bottom: 10px; color: var(--tenue); font-size: 13px; }
.campo input, .campo select { background: var(--fondo); color: var(--texto); border: 1px solid var(--borde);
  border-radius: 8px; padding: 8px; font-size: 14px; }
```

- [ ] **Step 5: Probar a mano en local**

Run: `.venv/Scripts/python.exe -m uvicorn backend.main:app --port 8000` con `JARVIS_PASSWORD` en `.env`; entrar como admin, abrir "Asistente", elegir una organización, guardar un nombre, subir una foto. Expected: la foto aparece en el panel; el título de arriba no cambia para el admin (no tiene organización); sin clave de Higgsfield local el botón "Generar" queda deshabilitado con el aviso.

- [ ] **Step 6: Commit**

```bash
git add web/index.html web/asistente.js web/app.js web/style.css
git commit -m "Web: panel Asistente para configurar nombre, foto y videos de cada organizacion"
```

---

### Task 9: El avatar holograma en la web

**Files:**
- Create: `web/avatar.js`
- Modify: `web/index.html`, `web/app.js` (`cargarEstado`), `web/style.css`

- [ ] **Step 1: Contenedor en `web/index.html`**

Dentro de `<main class="escena">`, antes del `<div class="orbe" id="orbe">`:

```html
    <canvas id="avatar" class="avatar" width="360" height="450" hidden></canvas>
```

- [ ] **Step 2: Crear `web/avatar.js`**

```js
/* El avatar del asistente: tres videos (reposo, escuchando, hablando) dibujados
   en un canvas con un holograma sutil. Sin videos, la foto animada (MediaPipe
   ubica ojos y boca); sin foto, queda el orbe de siempre.

   El estado se toma de las clases que app.js ya le pone al orbe (escuchando,
   pensando, hablando): asi no hay que tocar la logica de voz. El orbe se
   esconde con CSS pero sigue recibiendo esas clases. */

const W = 360, H = 450;
const FUNDIDO_MS = 300, EMPALME_MS = 400;
const MEDIAPIPE = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14";

const lienzo = document.getElementById("avatar");
const ctx = lienzo.getContext("2d");
const orbe = document.getElementById("orbe");
const capa = Object.assign(document.createElement("canvas"), { width: W, height: H });
const cc = capa.getContext("2d");
const tinte = Object.assign(document.createElement("canvas"), { width: W, height: H });
const tc = tinte.getContext("2d");

let videos = {};            // estado -> <video>
let foto = null;            // { base, pt } para la foto animada
let actual = "reposo", anterior = null, desde = 0;
let nivelVoz = 0;           // 0..1, lo empuja app.js en la voz en vivo
let cuadrosLentos = 0, sinEfecto = false, ultimo = 0;
let configurado = "";       // para no recargar si nada cambio

export function nivelDeVoz(valor) { nivelVoz = Math.max(0, Math.min(1, valor)); }

function estadoDelOrbe() {
  if (orbe.classList.contains("hablando")) return "hablando";
  if (orbe.classList.contains("escuchando") || orbe.classList.contains("pensando")) return "escuchando";
  return "reposo";
}

new MutationObserver(() => {
  const nuevo = estadoDelOrbe();
  if (nuevo !== actual) { anterior = actual; actual = nuevo; desde = performance.now(); }
}).observe(orbe, { attributes: true, attributeFilter: ["class"] });

/* Cada estado son DOS copias del mismo video: cuando a la que se ve le quedan
   EMPALME_MS, la otra arranca desde el principio y se funden. Asi el bucle no
   muestra el salto entre el ultimo cuadro y el primero. */
function nuevoVideo(url) {
  const copia = () => Object.assign(document.createElement("video"),
    { src: url, muted: true, loop: false, playsInline: true, preload: "auto" });
  const par = { a: copia(), b: copia(), activa: "a" };
  par.a.play().catch(() => {});
  return par;
}

/** La llama app.js con estado.asistente cada vez que carga /api/estado. */
export async function configurarAvatar(asistente) {
  const clave = JSON.stringify(asistente || {});
  if (clave === configurado) return;
  configurado = clave;
  const urls = asistente?.videos || {};
  videos = {};
  for (const [estado, url] of Object.entries(urls)) if (url) videos[estado] = nuevoVideo(url);
  foto = null;
  if (!videos.reposo && asistente?.foto) foto = await prepararFoto(asistente.foto).catch(() => null);
  const hay = Boolean(videos.reposo || foto);
  lienzo.hidden = !hay;
  document.body.classList.toggle("con-avatar", hay);
  if (hay && !ultimo) requestAnimationFrame(dibujar);
}

// ---------------------------------------------------------------- foto animada

async function prepararFoto(url) {
  const { FaceLandmarker, FilesetResolver } = await import(`${MEDIAPIPE}/vision_bundle.mjs`);
  const resolver = await FilesetResolver.forVisionTasks(`${MEDIAPIPE}/wasm`);
  const detector = await FaceLandmarker.createFromOptions(resolver, {
    baseOptions: { modelAssetPath: "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task" },
    runningMode: "IMAGE", numFaces: 1,
  });
  const img = new Image();
  await new Promise((ok, mal) => { img.onload = ok; img.onerror = mal; img.src = url; });
  const lm = detector.detect(img).faceLandmarks[0];
  if (!lm) return null;
  const xs = lm.map((p) => p.x * img.width), ys = lm.map((p) => p.y * img.height);
  const cx = (Math.min(...xs) + Math.max(...xs)) / 2, cy = (Math.min(...ys) + Math.max(...ys)) / 2;
  const escala = (W * 0.42) / (Math.max(...xs) - Math.min(...xs));
  const x0 = cx - W / 2 / escala, y0 = cy - (H * 0.36) / escala;
  const base = Object.assign(document.createElement("canvas"), { width: W, height: H });
  base.getContext("2d").drawImage(img, x0, y0, W / escala, H / escala, 0, 0, W, H);
  const P = (i) => ({ x: (lm[i].x * img.width - x0) * escala, y: (lm[i].y * img.height - y0) * escala });
  return {
    base,
    pt: { la: P(13), lb: P(14), ci: P(61), cd: P(291), me: P(152),
          ojos: [{ ar: P(159), ab: P(145), a: P(33), b: P(133) }, { ar: P(386), ab: P(374), a: P(362), b: P(263) }] },
    parpadeo: 0, proximo: performance.now() + 2500,
  };
}

function dibujarFoto(t, apertura) {
  const { base, pt } = foto;
  const r = Math.sin(t / 1300) * 0.01 + (actual === "escuchando" ? 0.02 : 0);
  cc.save(); cc.translate(W / 2, H * 0.6); cc.rotate(Math.sin(t / 2700) * 0.01); cc.scale(1 + r, 1 + r); cc.translate(-W / 2, -H * 0.6);
  cc.drawImage(base, 0, 0);
  if (t > foto.proximo) { foto.parpadeo = t; foto.proximo = t + 2000 + Math.random() * 4000; }
  const f = (t - foto.parpadeo) / 150, cierre = f < 2 ? 1 - Math.abs(1 - f) : 0;
  for (const o of pt.ojos) if (cierre > 0) {
    const x = Math.min(o.a.x, o.b.x) - 5, w = Math.abs(o.b.x - o.a.x) + 10, h = Math.max(o.ab.y - o.ar.y, 5) + 8, y = o.ar.y - 6;
    cc.save(); cc.beginPath(); cc.ellipse(x + w / 2, y + h / 2, w / 2, h / 2, 0, 0, 7); cc.clip();
    cc.drawImage(base, x, y - h * 0.6, w, h * 0.6, x, y, w, h * cierre); cc.restore();
  }
  if (apertura > 0.02) {
    const d = apertura * (pt.me.y - pt.la.y) * 0.22, an = pt.cd.x - pt.ci.x, x = pt.ci.x - an * 0.45, w = an * 1.9;
    const yc = (pt.la.y + pt.lb.y) / 2, al = (pt.me.y - yc) + an * 0.15;
    cc.save(); cc.beginPath(); cc.ellipse(x + w / 2, yc + al / 2, w / 2, al / 2 + d, 0, 0, 7); cc.clip();
    cc.drawImage(base, x, yc, w, al, x, yc + d, w, al); cc.restore();
    cc.fillStyle = "#2a0d0e"; cc.beginPath(); cc.ellipse((pt.ci.x + pt.cd.x) / 2, yc + d / 2, an * 0.36, d / 2 + 1, 0, 0, 7); cc.fill();
  }
  cc.restore();
}

// ---------------------------------------------------------------- videos

function cuadroDe(par, alfa) {
  if (!par) return;
  const activa = par[par.activa], otra = par[par.activa === "a" ? "b" : "a"];
  if (activa.readyState < 2) return;
  if (activa.paused && !activa.ended) activa.play().catch(() => {});
  const resto = (activa.duration - activa.currentTime) * 1000;
  // Empalme: la otra copia arranca desde 0 y se funde encima mientras termina esta.
  if (resto < EMPALME_MS && otra.paused) { otra.currentTime = 0; otra.play().catch(() => {}); }
  cc.globalAlpha = alfa;
  cc.drawImage(activa, 0, 0, W, H);
  if (!otra.paused && otra.readyState >= 2) {
    cc.globalAlpha = alfa * Math.min(1, 1 - Math.max(0, resto) / EMPALME_MS);
    cc.drawImage(otra, 0, 0, W, H);
  }
  cc.globalAlpha = 1;
  if (activa.ended) { activa.pause(); par.activa = par.activa === "a" ? "b" : "a"; }
}

// ---------------------------------------------------------------- holograma

function holograma(t, apertura) {
  // Bordes desvanecidos: el busto flota, sin recuadro.
  cc.globalCompositeOperation = "destination-in";
  const m = cc.createRadialGradient(W / 2, H * 0.42, W * 0.18, W / 2, H * 0.5, W * 0.62);
  m.addColorStop(0, "#000"); m.addColorStop(1, "rgba(0,0,0,0)");
  cc.fillStyle = m; cc.fillRect(0, 0, W, H);
  cc.globalCompositeOperation = "source-over";

  ctx.clearRect(0, 0, W, H);
  ctx.drawImage(capa, 0, 0);
  if (sinEfecto) return;
  // Velo azul por luminancia (35 %).
  tc.clearRect(0, 0, W, H);
  tc.filter = "grayscale(1) contrast(1.25) brightness(1.15)"; tc.drawImage(capa, 0, 0); tc.filter = "none";
  tc.globalCompositeOperation = "multiply"; tc.fillStyle = "#6fc3ff"; tc.fillRect(0, 0, W, H);
  tc.globalCompositeOperation = "destination-in"; tc.drawImage(capa, 0, 0); tc.globalCompositeOperation = "source-over";
  ctx.globalAlpha = 0.35; ctx.drawImage(tinte, 0, 0); ctx.globalAlpha = 1;
  // Lineas finas que bajan y un barrido suave.
  ctx.globalCompositeOperation = "source-atop"; ctx.fillStyle = "#000";
  const off = (t / 40) % 4;
  ctx.globalAlpha = 0.12; for (let y = off - 4; y < H; y += 4) ctx.fillRect(0, y, W, 1);
  ctx.fillStyle = "rgba(77,163,255,.5)"; ctx.globalAlpha = 0.16; ctx.fillRect(0, (t / 9) % (H + 80) - 40, W, 18);
  ctx.globalAlpha = 1; ctx.globalCompositeOperation = "source-over";
  lienzo.style.filter = `drop-shadow(0 0 ${8 + apertura * 12}px rgba(77,163,255,.55))`;
}

// ---------------------------------------------------------------- bucle

function dibujar(t) {
  requestAnimationFrame(dibujar);
  if (lienzo.hidden) { ultimo = 0; return; }
  // Si el dispositivo no da los cuadros (>2 s por debajo de 20 fps), sin efecto.
  if (ultimo && t - ultimo > 50) { if (++cuadrosLentos > 40) sinEfecto = true; } else cuadrosLentos = 0;
  ultimo = t;

  const apertura = actual === "hablando"
    ? (nivelVoz || Math.max(0, Math.sin(t / 95) * 0.6 + Math.sin(t / 37) * 0.3 + 0.15)) : 0;
  cc.clearRect(0, 0, W, H);
  if (videos.reposo) {
    const mezcla = Math.min(1, (t - desde) / FUNDIDO_MS);
    if (anterior && mezcla < 1) cuadroDe(videos[anterior] || videos.reposo, 1);
    cuadroDe(videos[actual] || videos.reposo, anterior ? mezcla : 1);
  } else if (foto) {
    dibujarFoto(t, apertura);
  }
  holograma(t, apertura);
}
```

- [ ] **Step 3: Conectarlo en `web/app.js`**

Import arriba: `import { configurarAvatar, nivelDeVoz } from "./avatar.js";`

En `cargarEstado()`, después de `$("titulo").textContent = estado.nombre; document.title = estado.nombre;`:

```js
    configurarAvatar(estado.asistente);
```

En el callback `onNivel` de la voz en vivo (línea ~492), además de lo que ya hace, cuando el que habla es el asistente: el nivel que hoy llega es el del micrófono, así que aquí solo se usa si `orbe.classList.contains("hablando")`:

```js
      if (orbe.classList.contains("hablando")) nivelDeVoz(nivel * 4);
```

- [ ] **Step 4: CSS en `web/style.css`** (al final)

```css
/* Con avatar, el orbe deja su lugar pero sigue recibiendo las clases de estado. */
.avatar { width: min(240px, 60vw); height: auto; aspect-ratio: 360 / 450; }
body.con-avatar .orbe { position: absolute; width: 1px; height: 1px; opacity: 0; pointer-events: none; }
```

- [ ] **Step 5: Probar a mano**

Con un servidor local y una organización con foto (Task 8): entrar como persona de esa organización. Expected: en vez del orbe aparece la foto animada con el velo azul; al escribir una pregunta pasa a "escuchando/pensando" y al responder mueve la boca. Probar en el celular (Chrome Android) que no se traba.

- [ ] **Step 6: Commit**

```bash
git add web/avatar.js web/index.html web/app.js web/style.css
git commit -m "Web: avatar holograma (videos de Higgsfield o foto animada) en lugar del orbe"
```

---

### Task 10: Los puentes usan el nombre del asistente

**Files:**
- Create: repo `Adminnebo/jarvis-puentes` con `puente-reloj/` y `puente-android/` (copias de `/opt/jarvis/puente-*` del EC2)
- Modify: `puente-reloj/src/gemini.js`, `puente-android/src/gemini.js`
- Test: `puente-android/test/nombre.test.js`, `puente-reloj/test/nombre.test.js`

- [ ] **Step 1: Crear el repo con el código tal como corre**

```bash
mkdir -p /c/Users/Jorge/jarvis-puentes && cd /c/Users/Jorge/jarvis-puentes
ssh ec2 'sudo tar czf - -C /opt/jarvis puente-reloj puente-android --exclude=node_modules' | tar xzf -
printf 'node_modules/\n.env\n' > .gitignore
git init -q && git add . && git commit -qm "Puentes del reloj y de los lentes tal como corren en el EC2 de Jarvis"
gh repo create Adminnebo/jarvis-puentes --private --source . --push
```

(`gh` con `GH_TOKEN` de la credencial `Adminnebo`, ver la nota de memoria de GitHub.)

- [ ] **Step 2: Escribir la prueba que falla** (`puente-android/test/nombre.test.js`, y la misma en `puente-reloj/test/`)

```js
import { test } from "node:test";
import assert from "node:assert/strict";
import { construirPromptVoz } from "../src/gemini.js";

test("el prompt se presenta con el nombre que manda Jarvis", () => {
  const p = construirPromptVoz("Eres Sofía, el asistente personal de Ana.\n");
  assert.match(p, /^Eres Sofía, el asistente de voz de Ana\./);
});

test("sin nombre en las instrucciones sigue siendo Jarvis", () => {
  assert.match(construirPromptVoz(""), /^Eres Jarvis, el asistente de voz de tu jefe\./);
});
```

- [ ] **Step 3: Correrla y ver que falla**

Run: `cd puente-android && node --test test/nombre.test.js`
Expected: FAIL — el prompt empieza con "Eres Jarvis, el asistente de voz de Ana."

- [ ] **Step 4: Cambiar `construirPromptVoz` en los dos `src/gemini.js`**

Debajo de la línea que saca `usuario`:

```js
  // Jarvis arranca sus instrucciones con "Eres <nombre>, el asistente personal
  // de <usuario>": el nombre lo configura cada organizacion en Jarvis.
  const nombre = texto.match(/^Eres ([^,\n]+), el asistente/i)?.[1]?.trim() || "Jarvis";
```

y en el `return`, cambiar `Eres Jarvis, el asistente de voz de ${usuario}.` por `Eres ${nombre}, el asistente de voz de ${usuario}.`

- [ ] **Step 5: Correr las pruebas de los dos puentes**

Run: `cd puente-android && node --test test/*.test.js` y `cd ../puente-reloj && node --test test/*.test.js`
Expected: PASS.

- [ ] **Step 6: Commit y push**

```bash
git add puente-reloj puente-android
git commit -m "Gemini: el asistente se presenta con el nombre que manda Jarvis"
git push
```

---

### Task 11: Despliegue y prueba real

**Files:** ninguno nuevo.

- [ ] **Step 1: Suite completa y push de Jarvis**

Run: `.venv/Scripts/python.exe -m pytest -q` → todas pasan. Después `git push` a `main` de `Adminnebo/Jarvis` (Railway ya no despliega).

- [ ] **Step 2: Desplegar Jarvis en el EC2**

```bash
git archive HEAD backend web requirements.txt Procfile | ssh ec2 'sudo sh -c "cd /opt/jarvis/jarvis && rm -rf backend web && tar xf - && cd .. && docker compose build -q jarvis && docker builder prune -af >/dev/null && docker compose up -d jarvis"'
curl -s https://asistente.neboaiconsulting.com/api/salud
```

Expected: `{"ok":true}`. En el log: sin errores al arrancar (`ssh ec2 'cd /opt/jarvis && sudo docker compose logs --tail 30 jarvis'`).

- [ ] **Step 3: Desplegar los puentes en el EC2**

```bash
cd /c/Users/Jorge/jarvis-puentes
for p in puente-reloj puente-android; do tar czf - -C $p src | ssh ec2 "sudo sh -c 'cd /opt/jarvis/$p && rm -rf src && tar xzf -'"; done
ssh ec2 'cd /opt/jarvis && sudo docker compose build -q puente-reloj puente-android && sudo docker compose up -d puente-reloj puente-android'
curl -s https://reloj.neboaiconsulting.com/salud; curl -s https://android.neboaiconsulting.com/salud
```

Expected: `{"ok":true,"jarvis":true}` en los dos. (Los puentes de Railway siguen con su código viejo hasta que los dispositivos se pasen a los dominios propios: dicen "Jarvis", que es aceptable.)

- [ ] **Step 4: Prueba real con Higgsfield (gasta créditos: confirmar con Jorge antes)**

En `https://asistente.neboaiconsulting.com`, como super admin: Asistente → organización "JH Electroalambres" → nombre → foto de prueba → "Generar los tres videos". Expected: a los pocos minutos los tres en "Listo" con su vista previa. Entrar como alguien de JH: el avatar holograma en el centro, cambia a escuchando y hablando.

Si Kling no da buen resultado con caras, probar `JARVIS_AVATAR_MODELO=minimax/hailuo-2.3/standard/image-to-video` en `/opt/jarvis/jarvis.env`, `docker compose up -d jarvis`, y regenerar.

- [ ] **Step 5: Anotar en memoria** el estado (módulos nuevos, variables `JARVIS_AVATAR_MODELO` y `JARVIS_AVATAR_CREDITOS_POR_VIDEO`, repo de puentes).
