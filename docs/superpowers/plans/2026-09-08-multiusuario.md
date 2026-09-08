# Varias personas usando Jarvis — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que varias personas entren a Jarvis con su propia contraseña, cada una con su conversación, su memoria y su nombre, compartiendo las fuentes de datos.

**Architecture:** Una variable de entorno por persona (`JARVIS_PASSWORD_<NOMBRE>`). La contraseña escrita en el login identifica a quien entra, así que la pantalla no cambia. El token de la cookie pasa a llevar el id del usuario, firmado con una clave del servidor. El middleware resuelve el usuario y lo deja en `peticion.state.usuario`; cada ruta lo lee y lo pasa **explícito** hacia abajo. Los archivos de memoria pasan a llevar el id.

**Tech Stack:** Python 3.12, FastAPI, pytest (se agrega en este plan), librería estándar para HMAC.

**Spec:** `docs/superpowers/specs/2026-09-08-multiusuario-design.md`

---

## Estructura de archivos

| Archivo | Responsabilidad |
|---|---|
| `backend/acceso.py` (modificar) | Quién es quién: leer el entorno, identificar por contraseña, firmar y validar el token, decidir qué ruta es de admin. |
| `backend/memoria.py` (modificar) | Hechos y conversación, ahora por usuario. Migración de los archivos sueltos. |
| `backend/herramientas.py` (modificar) | Inyectar el usuario a las herramientas que lo necesitan, sin que aparezca en el esquema que ve el modelo. |
| `backend/cerebro.py` (modificar) | Recibir el usuario y usarlo para el nombre y la memoria del prompt. |
| `backend/main.py` (modificar) | Login por usuario, middleware que resuelve identidad y permisos, rutas que pasan el usuario. |
| `web/app.js` (modificar) | Ocultar lo de admin según el rol. |
| `tests/` (crear) | Pruebas de `acceso`, `memoria` y permisos de rutas. |

`backend/fuentes.py`, `backend/esquema.py` y `backend/consumo.py` **no se tocan**: son datos comunes.

---

## Task 0: Preparar pytest

**Files:**
- Create: `requirements-dev.txt`
- Create: `tests/conftest.py`
- Modify: `.gitignore`

> **Requisito previo.** En esta máquina **no hay Python instalado**. Lo que
> responde a `python` es el alias de la Microsoft Store
> (`WindowsApps\python.exe`), que solo abre la tienda, y la ruta que busca
> `iniciar.bat` (`%LOCALAPPDATA%\Programs\Python\Python312\python.exe`) no
> existe. Sin Python no se puede correr ni una sola prueba de este plan.
>
> Instalar Python 3.12 desde python.org (no hay `winget` en esta edición de
> Windows) marcando "Add python.exe to PATH". Después, desde `C:\Users\Jorge\jarvis`:
>
> ```bash
> python -m venv .venv
> .venv/Scripts/activate
> ```
>
> Todos los comandos de este plan asumen ese entorno virtual activo.

- [ ] **Step 1: Crear el archivo de dependencias de desarrollo**

`requirements-dev.txt`:

```
-r requirements.txt

pytest>=8.3
```

- [ ] **Step 2: Crear el conftest que aisla cada prueba**

`tests/conftest.py`:

```python
"""Aislamiento de las pruebas.

Cada prueba corre contra una carpeta de datos vacia y sin ninguna variable
JARVIS_ heredada de la maquina. Sin esto, la contrasena real del desarrollador
se colaria en las pruebas de acceso y los resultados cambiarian segun quien las
corra.
"""

import os

import pytest


@pytest.fixture(autouse=True)
def entorno_limpio(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))
    for nombre in list(os.environ):
        if nombre.startswith("JARVIS_PASSWORD"):
            monkeypatch.delenv(nombre, raising=False)
    for nombre in ("JARVIS_CLAVE_SECRETA", "JARVIS_USUARIO"):
        monkeypatch.delenv(nombre, raising=False)
    return tmp_path
```

- [ ] **Step 3: Ignorar la basura de pytest**

Añadir al final de `.gitignore`:

```
.pytest_cache/
__pycache__/
```

- [ ] **Step 4: Instalar y comprobar que pytest corre**

Run: `pip install -r requirements-dev.txt && python -m pytest tests/ -q`
Expected: `no tests ran` (sin errores de importación).

- [ ] **Step 5: Commit**

```bash
git add requirements-dev.txt tests/conftest.py .gitignore
git commit -m "Preparar pytest con entorno aislado por prueba"
```

---

## Task 1: `acceso.usuarios()` lee el entorno

**Files:**
- Modify: `backend/acceso.py`
- Test: `tests/test_acceso.py`

- [ ] **Step 1: Escribir la prueba que falla**

`tests/test_acceso.py`:

```python
from backend import acceso


def test_sin_variables_hay_un_solo_admin_por_defecto():
    lista = acceso.usuarios()
    assert len(lista) == 1
    assert lista[0].id == "admin"
    assert lista[0].rol == "admin"


def test_el_admin_toma_su_nombre_de_jarvis_usuario(monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "secreta")
    monkeypatch.setenv("JARVIS_USUARIO", "Lucas")
    lista = acceso.usuarios()
    assert [u.nombre for u in lista] == ["Lucas"]


def test_cada_variable_con_prefijo_es_una_persona(monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "secreta")
    monkeypatch.setenv("JARVIS_PASSWORD_JORGE", "otra")
    lista = acceso.usuarios()
    assert [(u.id, u.nombre, u.rol) for u in lista] == [
        ("admin", "Admin", "admin"),
        ("jorge", "Jorge", "usuario"),
    ]


def test_se_descartan_sufijos_y_contrasenas_vacias(monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "secreta")
    monkeypatch.setenv("JARVIS_PASSWORD_", "huerfana")
    monkeypatch.setenv("JARVIS_PASSWORD_ANA", "   ")
    assert [u.id for u in acceso.usuarios()] == ["admin"]
```

- [ ] **Step 2: Correr la prueba y ver que falla**

Run: `python -m pytest tests/test_acceso.py -q`
Expected: FAIL con `AttributeError: module 'backend.acceso' has no attribute 'usuarios'`

- [ ] **Step 3: Implementar**

En `backend/acceso.py`, añadir el import de `dataclass` arriba:

```python
from dataclasses import dataclass
```

Y después de `DURACION`, antes de `def clave()`:

```python
PREFIJO = "JARVIS_PASSWORD_"


@dataclass(frozen=True)
class Usuario:
    id: str
    nombre: str
    rol: str        # "admin" | "usuario"


def _catalogo() -> list[tuple[Usuario, str]]:
    """Cada persona con su contrasena, leidas del entorno.

    El admin es quien tiene JARVIS_PASSWORD; su nombre sigue saliendo de
    JARVIS_USUARIO, como cuando habia un solo usuario. Los demas salen del
    sufijo de la variable: JARVIS_PASSWORD_JORGE es jorge, y se llama Jorge.
    """
    entradas: list[tuple[Usuario, str]] = []

    nombre_admin = os.getenv("JARVIS_USUARIO", "").strip() or "Admin"
    principal = os.getenv("JARVIS_PASSWORD", "").strip()
    entradas.append((Usuario("admin", nombre_admin, "admin"), principal))

    for variable, valor in sorted(os.environ.items()):
        if not variable.startswith(PREFIJO):
            continue

        sufijo = variable[len(PREFIJO):].strip()
        contrasena = (valor or "").strip()

        # Una contrasena vacia dejaria entrar a cualquiera, y un sufijo vacio
        # no da un id con el que separar la memoria. Ninguna de las dos se
        # ignora en silencio: se avisa al arrancar.
        if not sufijo or not contrasena:
            print(f"  AVISO: se ignora {variable}: sufijo o contrasena vacios.")
            continue

        entradas.append(
            (Usuario(sufijo.lower(), sufijo.capitalize(), "usuario"), contrasena)
        )

    return entradas


def usuarios() -> list[Usuario]:
    return [usuario for usuario, _ in _catalogo()]
```

- [ ] **Step 4: Correr la prueba y ver que pasa**

Run: `python -m pytest tests/test_acceso.py -q`
Expected: PASS, 4 pruebas.

- [ ] **Step 5: Commit**

```bash
git add backend/acceso.py tests/test_acceso.py
git commit -m "Acceso: una variable de entorno por persona"
```

---

## Task 2: Identificar a la persona por su contraseña

**Files:**
- Modify: `backend/acceso.py`
- Test: `tests/test_acceso.py`

- [ ] **Step 1: Escribir la prueba que falla**

Añadir a `tests/test_acceso.py`:

```python
def test_la_contrasena_dice_quien_entra(monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setenv("JARVIS_PASSWORD_JORGE", "la-de-jorge")
    assert acceso.quien_entra("la-del-admin").id == "admin"
    assert acceso.quien_entra("la-de-jorge").id == "jorge"


def test_una_contrasena_incorrecta_no_entra(monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    assert acceso.quien_entra("cualquier-cosa") is None
    assert acceso.quien_entra("") is None


def test_sin_proteccion_no_entra_nadie_por_contrasena():
    # Sin JARVIS_PASSWORD no hay login: la identidad la da por_defecto().
    assert acceso.quien_entra("lo-que-sea") is None
    assert acceso.por_defecto().rol == "admin"
```

- [ ] **Step 2: Correr la prueba y ver que falla**

Run: `python -m pytest tests/test_acceso.py -q`
Expected: FAIL con `AttributeError: module 'backend.acceso' has no attribute 'quien_entra'`

- [ ] **Step 3: Implementar**

En `backend/acceso.py`, reemplazar la función `clave_correcta` (la última del bloque de lógica) por:

```python
def quien_entra(intento: str) -> Usuario | None:
    """Devuelve la persona cuya contrasena es la escrita, o None.

    Recorre todas las contrasenas sin cortar en la primera coincidencia: si
    saliera antes, el tiempo de respuesta revelaria cuantos usuarios hay y en
    que orden estan.
    """
    escrita = (intento or "").strip()
    encontrado: Usuario | None = None

    for usuario, contrasena in _catalogo():
        if not contrasena:
            continue
        if hmac.compare_digest(escrita, contrasena) and encontrado is None:
            encontrado = usuario

    return encontrado


def por_defecto() -> Usuario:
    """Quien es el usuario cuando no hay login: en local, y solo ahi."""
    return _catalogo()[0][0]
```

`clave()`, `protegido()` y `obligatorio()` se quedan como están.

- [ ] **Step 4: Correr la prueba y ver que pasa**

Run: `python -m pytest tests/test_acceso.py -q`
Expected: PASS, 7 pruebas.

- [ ] **Step 5: Commit**

```bash
git add backend/acceso.py tests/test_acceso.py
git commit -m "Acceso: la contrasena identifica a quien entra"
```

---

## Task 3: El token lleva el id del usuario

**Files:**
- Modify: `backend/acceso.py`
- Test: `tests/test_acceso.py`

- [ ] **Step 1: Escribir la prueba que falla**

Añadir a `tests/test_acceso.py`:

```python
import time


def test_un_token_valido_devuelve_a_su_dueno(monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setenv("JARVIS_PASSWORD_JORGE", "la-de-jorge")
    token = acceso.crear_token(acceso.quien_entra("la-de-jorge"))
    assert acceso.usuario_de_token(token).id == "jorge"


def test_un_token_manipulado_se_rechaza(monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setenv("JARVIS_PASSWORD_JORGE", "la-de-jorge")
    token = acceso.crear_token(acceso.quien_entra("la-de-jorge"))
    # Cambiarse a si mismo por el admin es justo lo que hay que impedir.
    assert acceso.usuario_de_token(token.replace("jorge", "admin", 1)) is None
    assert acceso.usuario_de_token("basura") is None
    assert acceso.usuario_de_token(None) is None


def test_un_token_vencido_se_rechaza(monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setattr(acceso, "DURACION", -10)
    token = acceso.crear_token(acceso.quien_entra("la-del-admin"))
    assert acceso.usuario_de_token(token) is None


def test_el_token_de_alguien_que_ya_no_esta_se_rechaza(monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setenv("JARVIS_CLAVE_SECRETA", "una-clave-larga-y-estable")
    monkeypatch.setenv("JARVIS_PASSWORD_JORGE", "la-de-jorge")
    token = acceso.crear_token(acceso.quien_entra("la-de-jorge"))

    # Le quitamos su variable: asi se echa a alguien.
    monkeypatch.delenv("JARVIS_PASSWORD_JORGE")
    assert acceso.usuario_de_token(token) is None
```

- [ ] **Step 2: Correr la prueba y ver que falla**

Run: `python -m pytest tests/test_acceso.py -q`
Expected: FAIL — `crear_token()` no acepta argumentos y no existe `usuario_de_token`.

- [ ] **Step 3: Implementar**

En `backend/acceso.py`, reemplazar `_firma`, `crear_token` y `token_valido` por:

```python
def clave_de_sesion() -> bytes:
    """La clave con la que se firman las cookies.

    Antes se firmaba con la contrasena misma, pero con varias personas el token
    tiene que decir quien es y la firma no puede depender de una sola clave.

    Se deriva de JARVIS_CLAVE_SECRETA en vez de usarla tal cual, para no
    reutilizar la clave que cifra las credenciales. Sin esa variable se deriva
    de las contrasenas configuradas: estable entre despliegues mientras no
    cambien. Cambiar JARVIS_CLAVE_SECRETA cierra la sesion de todos, y esa es
    la forma de echar a alguien de inmediato.
    """
    secreta = os.getenv("JARVIS_CLAVE_SECRETA", "").strip()
    if not secreta:
        secreta = "|".join(sorted(c for _, c in _catalogo() if c))
    return hmac.new(secreta.encode("utf-8"), b"sesiones", hashlib.sha256).digest()


def _firma(id_usuario: str, caduca: int) -> str:
    cuerpo = f"{id_usuario}.{caduca}".encode("utf-8")
    return hmac.new(clave_de_sesion(), cuerpo, hashlib.sha256).hexdigest()


def crear_token(usuario: Usuario) -> str:
    caduca = int(time.time()) + DURACION
    return f"{usuario.id}.{caduca}.{_firma(usuario.id, caduca)}"


def usuario_de_token(valor: str | None) -> Usuario | None:
    """El usuario que hay dentro de un token valido, o None."""
    if not valor:
        return None

    partes = valor.split(".", 2)
    if len(partes) != 3:
        return None

    id_usuario, caduca_texto, firma = partes

    try:
        caduca = int(caduca_texto)
    except ValueError:
        return None

    if caduca < time.time():
        return None

    if not hmac.compare_digest(firma, _firma(id_usuario, caduca)):
        return None

    # Que la firma sea buena no basta: si le quitaron su variable, ese token
    # ya no vale.
    return next((u for u in usuarios() if u.id == id_usuario), None)
```

- [ ] **Step 4: Correr la prueba y ver que pasa**

Run: `python -m pytest tests/test_acceso.py -q`
Expected: PASS, 11 pruebas.

- [ ] **Step 5: Commit**

```bash
git add backend/acceso.py tests/test_acceso.py
git commit -m "Acceso: el token lleva el id y se firma con una clave del servidor"
```

---

## Task 4: Avisar cuando dos personas comparten contraseña

**Files:**
- Modify: `backend/acceso.py`
- Test: `tests/test_acceso.py`

- [ ] **Step 1: Escribir la prueba que falla**

Añadir a `tests/test_acceso.py`:

```python
def test_avisa_si_dos_personas_comparten_contrasena(monkeypatch, capsys):
    monkeypatch.setenv("JARVIS_PASSWORD", "repetida")
    monkeypatch.setenv("JARVIS_PASSWORD_JORGE", "repetida")

    acceso.avisar_de_contrasenas_repetidas()

    salida = capsys.readouterr().out
    assert "repiten" in salida
    # Gana el primero: el admin.
    assert acceso.quien_entra("repetida").id == "admin"


def test_no_avisa_si_todas_son_distintas(monkeypatch, capsys):
    monkeypatch.setenv("JARVIS_PASSWORD", "una")
    monkeypatch.setenv("JARVIS_PASSWORD_JORGE", "otra")

    acceso.avisar_de_contrasenas_repetidas()

    assert capsys.readouterr().out == ""
```

- [ ] **Step 2: Correr la prueba y ver que falla**

Run: `python -m pytest tests/test_acceso.py -q`
Expected: FAIL con `AttributeError: ... has no attribute 'avisar_de_contrasenas_repetidas'`

- [ ] **Step 3: Implementar**

En `backend/acceso.py`, después de `por_defecto()`:

```python
def avisar_de_contrasenas_repetidas() -> None:
    """Dos personas con la misma contrasena son indistinguibles al entrar.

    Callarlo mezclaria sus memorias sin que nadie se entere, asi que se avisa
    al arrancar. Gana el primero del catalogo.
    """
    vistas: dict[str, str] = {}
    repetidas: list[str] = []

    for usuario, contrasena in _catalogo():
        if not contrasena:
            continue
        if contrasena in vistas:
            repetidas.append(f"{usuario.id} y {vistas[contrasena]}")
        else:
            vistas[contrasena] = usuario.id

    for par in repetidas:
        print(
            f"  AVISO: {par} se repiten la contrasena. No se pueden distinguir "
            "al entrar y comparten memoria. Ponles contrasenas distintas."
        )
```

- [ ] **Step 4: Correr la prueba y ver que pasa**

Run: `python -m pytest tests/test_acceso.py -q`
Expected: PASS, 13 pruebas.

- [ ] **Step 5: Commit**

```bash
git add backend/acceso.py tests/test_acceso.py
git commit -m "Acceso: avisar cuando dos personas comparten contrasena"
```

---

## Task 5: Decidir qué rutas son de administración

**Files:**
- Modify: `backend/acceso.py`
- Test: `tests/test_acceso.py`

- [ ] **Step 1: Escribir la prueba que falla**

Añadir a `tests/test_acceso.py`:

```python
import pytest


@pytest.mark.parametrize("ruta, metodo", [
    ("/api/fuentes", "GET"),
    ("/api/fuentes", "POST"),
    ("/api/fuentes/tipos", "GET"),
    ("/api/fuentes/abc123/consultar", "POST"),
    ("/api/fuentes/abc123", "DELETE"),
    ("/api/esquema/refrescar", "POST"),
    ("/api/consumo", "GET"),
    ("/api/consumo", "DELETE"),
])
def test_rutas_solo_para_admin(ruta, metodo):
    assert acceso.exige_admin(ruta, metodo) is True


@pytest.mark.parametrize("ruta, metodo", [
    ("/api/chat", "POST"),
    ("/api/estado", "GET"),
    ("/api/memoria", "GET"),
    ("/api/herramienta", "POST"),
    ("/api/voz/sesion", "GET"),
    # Lo escribe el navegador durante la voz: bloquearlo dejaria sin registrar
    # el gasto de quien no es admin.
    ("/api/consumo/voz", "POST"),
    ("/", "GET"),
])
def test_rutas_abiertas_a_todos(ruta, metodo):
    assert acceso.exige_admin(ruta, metodo) is False
```

- [ ] **Step 2: Correr la prueba y ver que falla**

Run: `python -m pytest tests/test_acceso.py -q`
Expected: FAIL con `AttributeError: ... has no attribute 'exige_admin'`

- [ ] **Step 3: Implementar**

En `backend/acceso.py`, al final del bloque "Que se puede pedir sin haber entrado":

```python
def exige_admin(ruta: str, metodo: str) -> bool:
    """Que solo puede hacer quien administra Jarvis.

    Se decide aqui y lo aplica el middleware. Esconder el boton en la web es
    comodidad, no control de acceso.
    """
    if ruta.startswith("/api/fuentes"):
        return True
    if ruta == "/api/esquema/refrescar":
        return True
    # Solo el tablero de gasto. /api/consumo/voz no entra: lo escribe el
    # navegador de cualquiera durante la sesion de voz.
    if ruta == "/api/consumo" and metodo in ("GET", "DELETE"):
        return True
    return False
```

- [ ] **Step 4: Correr la prueba y ver que pasa**

Run: `python -m pytest tests/test_acceso.py -q`
Expected: PASS, 28 pruebas.

- [ ] **Step 5: Commit**

```bash
git add backend/acceso.py tests/test_acceso.py
git commit -m "Acceso: definir que rutas son de administracion"
```

---

## Task 6: La memoria pasa a ser por usuario

**Files:**
- Modify: `backend/memoria.py`
- Test: `tests/test_memoria.py`

- [ ] **Step 1: Escribir la prueba que falla**

`tests/test_memoria.py`:

```python
from backend import memoria


def test_los_hechos_de_cada_uno_no_se_mezclan():
    memoria.recordar("lucas", "Le gusta el cafe cargado", "preferencias")
    memoria.recordar("jorge", "Vive en Monterrey", "personal")

    de_lucas = [h["contenido"] for h in memoria.todos_los_hechos("lucas")]
    de_jorge = [h["contenido"] for h in memoria.todos_los_hechos("jorge")]

    assert de_lucas == ["Le gusta el cafe cargado"]
    assert de_jorge == ["Vive en Monterrey"]


def test_el_resumen_del_prompt_solo_trae_lo_propio():
    memoria.recordar("lucas", "Le gusta el cafe cargado", "preferencias")
    memoria.recordar("jorge", "Vive en Monterrey", "personal")

    assert "cafe" in memoria.resumen_para_prompt("lucas")
    assert "Monterrey" not in memoria.resumen_para_prompt("lucas")


def test_buscar_no_cruza_usuarios():
    memoria.recordar("lucas", "El proyecto Jarvis usa Supabase", "proyectos")
    assert memoria.buscar("lucas", "Jarvis") != []
    assert memoria.buscar("jorge", "Jarvis") == []


def test_olvidar_solo_alcanza_lo_propio():
    hecho = memoria.recordar("lucas", "Un dato cualquiera", "general")
    assert memoria.olvidar("jorge", hecho["id"]) is False
    assert memoria.olvidar("lucas", hecho["id"]) is True


def test_la_conversacion_es_de_cada_uno():
    memoria.guardar_conversacion("lucas", [{"role": "user", "content": "hola"}])
    assert memoria.cargar_conversacion("lucas") != []
    assert memoria.cargar_conversacion("jorge") == []

    memoria.borrar_conversacion("lucas")
    assert memoria.cargar_conversacion("lucas") == []
```

- [ ] **Step 2: Correr la prueba y ver que falla**

Run: `python -m pytest tests/test_memoria.py -q`
Expected: FAIL con `TypeError: recordar() takes from 1 to 2 positional arguments but 3 were given`

- [ ] **Step 3: Implementar**

En `backend/memoria.py`, reemplazar las dos funciones de ruta:

```python
def ARCHIVO_HECHOS(id_usuario: str) -> Path:
    return rutas.archivo(f"hechos-{id_usuario}.json")


def ARCHIVO_CONVERSACION(id_usuario: str) -> Path:
    return rutas.archivo(f"conversacion-{id_usuario}.json")
```

Y reemplazar todas las funciones públicas para que reciban el id primero:

```python
def todos_los_hechos(id_usuario: str) -> list[dict]:
    return _leer(ARCHIVO_HECHOS(id_usuario), [])


def recordar(id_usuario: str, contenido: str, categoria: str = "general") -> dict:
    """Guarda un hecho nuevo. Si ya existe uno casi identico, no lo duplica."""
    hechos = todos_los_hechos(id_usuario)

    normalizado = contenido.strip().lower()
    for hecho in hechos:
        if hecho["contenido"].strip().lower() == normalizado:
            return hecho

    hecho = {
        "id": uuid.uuid4().hex[:8],
        "contenido": contenido.strip(),
        "categoria": categoria,
        "creado": datetime.now().isoformat(timespec="seconds"),
    }
    hechos.append(hecho)
    _escribir(ARCHIVO_HECHOS(id_usuario), hechos)
    return hecho


def olvidar(id_usuario: str, id_hecho: str) -> bool:
    hechos = todos_los_hechos(id_usuario)
    quedan = [h for h in hechos if h["id"] != id_hecho]
    if len(quedan) == len(hechos):
        return False
    _escribir(ARCHIVO_HECHOS(id_usuario), quedan)
    return True


def buscar(id_usuario: str, consulta: str, limite: int = 10) -> list[dict]:
    """Busqueda por palabras. Suficiente para cientos de hechos.

    Si algun dia esto crece a miles, aqui es donde entra un embedding.
    """
    palabras = [p for p in consulta.lower().split() if len(p) > 2]
    if not palabras:
        return todos_los_hechos(id_usuario)[:limite]

    puntuados = []
    for hecho in todos_los_hechos(id_usuario):
        texto = f"{hecho['contenido']} {hecho['categoria']}".lower()
        puntos = sum(1 for p in palabras if p in texto)
        if puntos:
            puntuados.append((puntos, hecho))

    puntuados.sort(key=lambda par: par[0], reverse=True)
    return [hecho for _, hecho in puntuados[:limite]]


def resumen_para_prompt(id_usuario: str, maximo: int = 60) -> str:
    """Los hechos formateados para inyectarlos en el system prompt."""
    hechos = todos_los_hechos(id_usuario)[-maximo:]
    if not hechos:
        return "(Todavia no recuerdas nada sobre el usuario.)"

    por_categoria: dict[str, list[str]] = {}
    for hecho in hechos:
        por_categoria.setdefault(hecho["categoria"], []).append(hecho["contenido"])

    lineas = []
    for categoria, contenidos in por_categoria.items():
        lineas.append(f"[{categoria}]")
        lineas.extend(f"  - {c}" for c in contenidos)
    return "\n".join(lineas)


def cargar_conversacion(id_usuario: str) -> list[dict]:
    return _leer(ARCHIVO_CONVERSACION(id_usuario), [])


def guardar_conversacion(id_usuario: str, mensajes: list[dict], maximo: int = 40) -> None:
    """Guarda solo los ultimos mensajes para que el archivo no crezca sin fin."""
    _escribir(ARCHIVO_CONVERSACION(id_usuario), mensajes[-maximo:])


def borrar_conversacion(id_usuario: str) -> None:
    _escribir(ARCHIVO_CONVERSACION(id_usuario), [])
```

- [ ] **Step 4: Correr la prueba y ver que pasa**

Run: `python -m pytest tests/test_memoria.py -q`
Expected: PASS, 5 pruebas.

- [ ] **Step 5: Commit**

```bash
git add backend/memoria.py tests/test_memoria.py
git commit -m "Memoria: un archivo de hechos y conversacion por persona"
```

---

## Task 7: Migrar los archivos sueltos al admin

**Files:**
- Modify: `backend/memoria.py`
- Test: `tests/test_memoria.py`

- [ ] **Step 1: Escribir la prueba que falla**

Añadir a `tests/test_memoria.py`:

```python
import json


def _escribir_archivos_viejos(carpeta):
    (carpeta / "hechos.json").write_text(
        json.dumps([{"id": "aaa11111", "contenido": "Un recuerdo viejo",
                     "categoria": "general", "creado": "2026-01-01T00:00:00"}]),
        encoding="utf-8",
    )
    (carpeta / "conversacion.json").write_text(
        json.dumps([{"role": "user", "content": "hola de antes"}]),
        encoding="utf-8",
    )


def test_el_admin_hereda_los_archivos_sueltos(entorno_limpio):
    _escribir_archivos_viejos(entorno_limpio)

    memoria.migrar_archivos_sueltos("admin")

    assert memoria.todos_los_hechos("admin")[0]["contenido"] == "Un recuerdo viejo"
    assert memoria.cargar_conversacion("admin")[0]["content"] == "hola de antes"
    # Los viejos quedan como respaldo frio.
    assert (entorno_limpio / "hechos.json").exists()


def test_migrar_dos_veces_no_pisa_lo_nuevo(entorno_limpio):
    _escribir_archivos_viejos(entorno_limpio)
    memoria.migrar_archivos_sueltos("admin")

    memoria.recordar("admin", "Un recuerdo nuevo", "general")
    memoria.migrar_archivos_sueltos("admin")

    contenidos = [h["contenido"] for h in memoria.todos_los_hechos("admin")]
    assert "Un recuerdo nuevo" in contenidos
    assert len(contenidos) == 2


def test_sin_archivos_viejos_no_hace_nada():
    memoria.migrar_archivos_sueltos("admin")
    assert memoria.todos_los_hechos("admin") == []
```

- [ ] **Step 2: Correr la prueba y ver que falla**

Run: `python -m pytest tests/test_memoria.py -q`
Expected: FAIL con `AttributeError: module 'backend.memoria' has no attribute 'migrar_archivos_sueltos'`

- [ ] **Step 3: Implementar**

Al final de `backend/memoria.py`:

```python
# --------------------------------------------------------------------------
# Migracion
# --------------------------------------------------------------------------

def migrar_archivos_sueltos(id_admin: str) -> None:
    """Adjudica al admin la memoria de cuando habia un solo usuario.

    Se ejecuta al arrancar. Es idempotente: si el admin ya tiene su archivo,
    no toca nada, porque lo suyo es mas nuevo que lo que hubiera suelto.

    Los archivos viejos no se borran: quedan como respaldo frio por si algo
    salio mal.
    """
    for viejo, nuevo in (
        (rutas.archivo("hechos.json"), ARCHIVO_HECHOS(id_admin)),
        (rutas.archivo("conversacion.json"), ARCHIVO_CONVERSACION(id_admin)),
    ):
        if not viejo.exists() or nuevo.exists():
            continue
        nuevo.write_text(viejo.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"  Memoria migrada: {viejo.name} -> {nuevo.name}")
```

- [ ] **Step 4: Correr la prueba y ver que pasa**

Run: `python -m pytest tests/test_memoria.py -q`
Expected: PASS, 8 pruebas.

- [ ] **Step 5: Commit**

```bash
git add backend/memoria.py tests/test_memoria.py
git commit -m "Memoria: el admin hereda los archivos de cuando habia un solo usuario"
```

---

## Task 8: Las herramientas reciben el usuario sin exponerlo al modelo

**Files:**
- Modify: `backend/herramientas.py`
- Test: `tests/test_herramientas.py`

- [ ] **Step 1: Escribir la prueba que falla**

`tests/test_herramientas.py`:

```python
import json

from backend import herramientas, memoria


def test_el_parametro_usuario_no_aparece_en_el_esquema():
    esquema = next(
        e for e in herramientas.esquemas() if e["name"] == "recordar"
    )
    propiedades = esquema["parameters"]["properties"]
    assert "usuario" not in propiedades
    assert "usuario" not in esquema["parameters"]["required"]
    assert "contenido" in propiedades


def test_recordar_escribe_en_la_memoria_de_quien_habla():
    herramientas.ejecutar(
        "recordar", json.dumps({"contenido": "Le gusta el te"}), "jorge"
    )
    assert memoria.todos_los_hechos("jorge") != []
    assert memoria.todos_los_hechos("lucas") == []


def test_buscar_memoria_solo_ve_lo_propio():
    memoria.recordar("lucas", "El coche es azul", "general")
    de_lucas = herramientas.ejecutar("buscar_memoria", json.dumps({"consulta": "coche"}), "lucas")
    de_jorge = herramientas.ejecutar("buscar_memoria", json.dumps({"consulta": "coche"}), "jorge")
    assert "azul" in de_lucas
    assert "azul" not in de_jorge


def test_una_herramienta_sin_usuario_sigue_funcionando():
    resultado = herramientas.ejecutar("hora_actual", "{}", "jorge")
    assert "de" in resultado
```

- [ ] **Step 2: Correr la prueba y ver que falla**

Run: `python -m pytest tests/test_herramientas.py -q`
Expected: FAIL con `TypeError: ejecutar() takes 2 positional arguments but 3 were given`

- [ ] **Step 3: Implementar**

En `backend/herramientas.py`, dentro del decorador `herramienta`, reemplazar el bucle que arma las propiedades:

```python
        firma = inspect.signature(funcion)
        propiedades = {}
        requeridos = []

        for nombre, parametro in firma.parameters.items():
            # 'usuario' lo inyecta ejecutar(), no lo elige el modelo: si
            # apareciera en el esquema podria escribir en la memoria de otro.
            if nombre == "usuario":
                continue
            propiedades[nombre] = {
                "type": "string",
                "description": descripciones_de_parametros.get(nombre, nombre),
            }
            if parametro.default is inspect.Parameter.empty:
                requeridos.append(nombre)

        REGISTRO[funcion.__name__] = {
            "funcion": funcion,
            "necesita_usuario": "usuario" in firma.parameters,
            "esquema": {
```

Reemplazar `ejecutar`:

```python
def ejecutar(nombre: str, argumentos_json: str, usuario: str) -> str:
    """Corre una herramienta y devuelve siempre texto, incluso si falla.

    Un error aqui no debe tumbar la conversacion: se lo devolvemos al modelo
    como resultado para que lo explique o intente otra cosa.
    """
    entrada = REGISTRO.get(nombre)
    if entrada is None:
        return f"Error: no existe la herramienta '{nombre}'."

    try:
        argumentos = json.loads(argumentos_json or "{}")
        if entrada["necesita_usuario"]:
            argumentos["usuario"] = usuario
        resultado = entrada["funcion"](**argumentos)
        if isinstance(resultado, str):
            return resultado
        return json.dumps(resultado, ensure_ascii=False)
    except Exception as error:  # noqa: BLE001 - se lo pasamos al modelo a proposito
        return f"Error al ejecutar {nombre}: {error}"
```

Y las tres herramientas de memoria:

```python
def recordar(contenido: str, categoria: str = "general", usuario: str = "") -> str:
    hecho = memoria.recordar(usuario, contenido, categoria)
    return f"Guardado (id {hecho['id']}): {hecho['contenido']}"
```

```python
def buscar_memoria(consulta: str, usuario: str = "") -> str:
    resultados = memoria.buscar(usuario, consulta)
    if not resultados:
        return "No hay nada en la memoria sobre eso."
    return "\n".join(f"- ({h['categoria']}) {h['contenido']}" for h in resultados)
```

```python
def olvidar(id_hecho: str, usuario: str = "") -> str:
    return "Listo, lo olvide." if memoria.olvidar(usuario, id_hecho) else "No encontre ese hecho."
```

- [ ] **Step 4: Correr la prueba y ver que pasa**

Run: `python -m pytest tests/test_herramientas.py -q`
Expected: PASS, 4 pruebas.

- [ ] **Step 5: Commit**

```bash
git add backend/herramientas.py tests/test_herramientas.py
git commit -m "Herramientas: el usuario se inyecta y no lo ve el modelo"
```

---

## Task 9: El cerebro recibe el usuario

**Files:**
- Modify: `backend/cerebro.py:53`, `backend/cerebro.py:155`, `backend/cerebro.py:183`, `backend/cerebro.py:223`, `backend/cerebro.py:270`, `backend/cerebro.py:277`, `backend/cerebro.py:375-381`, `backend/cerebro.py:420-437`

- [ ] **Step 1: Cambiar `instrucciones` para que use el usuario**

Reemplazar la firma y las dos líneas que leen el nombre y la memoria:

```python
def instrucciones(usuario: acceso.Usuario, extra: str = "") -> str:
```

Dentro, reemplazar la línea 55:

```python
    nombre_usuario = usuario.nombre
```

y sustituir cada uso de la variable `usuario` que servía para el nombre por
`nombre_usuario`. La última línea (155) queda:

```python
    texto += (
        f"\n\nEsto es lo que ya sabes de {nombre_usuario}:\n"
        f"{memoria.resumen_para_prompt(usuario.id)}"
    )
```

Añadir el import arriba del archivo, junto a los demás:

```python
from . import acceso, conectores, consultas, esquema, fuentes, herramientas, memoria
```

- [ ] **Step 2: Cambiar `responder`**

```python
def responder(mensajes: list[dict], usuario: acceso.Usuario, extra: str = "") -> Iterator[dict]:
```

Línea 223:

```python
                instructions=instrucciones(usuario, extra),
```

Línea 270:

```python
            memoria.guardar_conversacion(usuario.id, mensajes)
```

Línea 277:

```python
            resultado = herramientas.ejecutar(
                llamada.name, llamada.arguments, usuario.id
            )
```

- [ ] **Step 3: Cambiar las funciones de voz**

```python
def configuracion_de_sesion(usuario: acceso.Usuario) -> dict:
```

y dentro, la línea que arma las instrucciones:

```python
        "instructions": instrucciones(usuario),
```

```python
def negociar_webrtc(sdp_oferta: str, usuario: acceso.Usuario) -> str:
```

y dentro:

```python
                "session": (None, json.dumps(configuracion_de_sesion(usuario))),
```

- [ ] **Step 4: Comprobar que el módulo importa y que nada quedó suelto**

Run: `python -c "from backend import cerebro; print('ok')"`
Expected: `ok`

Run: `grep -n "instrucciones()\|responder(mensajes)\|memoria.resumen_para_prompt()\|memoria.guardar_conversacion(mensajes)" backend/cerebro.py`
Expected: sin resultados (todas las llamadas viejas quedaron actualizadas).

- [ ] **Step 5: Commit**

```bash
git add backend/cerebro.py
git commit -m "Cerebro: el nombre y la memoria salen del usuario que habla"
```

---

## Task 10: El middleware resuelve la identidad y aplica los permisos

**Files:**
- Modify: `backend/main.py:44-93` (arranque, login y middleware)
- Test: `tests/test_permisos.py`

- [ ] **Step 1: Escribir la prueba que falla**

`tests/test_permisos.py`:

```python
import pytest
from fastapi.testclient import TestClient

# Se importa arriba del todo a proposito: backend.main llama a
# load_dotenv(override=True) al importarse (main.py:23). Si esa importacion
# ocurriera dentro de la prueba, el .env real de la maquina pisaria las
# contrasenas de prueba y los resultados dependerian de quien las corre.
from backend.main import app


@pytest.fixture
def cliente(entorno_limpio, monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setenv("JARVIS_PASSWORD_JORGE", "la-de-jorge")
    monkeypatch.setenv("JARVIS_CLAVE_SECRETA", "clave-de-pruebas-larga")
    return TestClient(app)


def _entrar(cliente, contrasena):
    """Deja la sesion abierta como esa persona.

    TestClient guarda las cookies entre peticiones, asi que despues de esto
    basta con llamar a cliente.get(...) sin pasar nada mas.
    """
    cliente.cookies.clear()
    respuesta = cliente.post(
        "/acceso", data={"clave": contrasena}, follow_redirects=False
    )
    assert respuesta.status_code == 303


def test_sin_cookie_la_api_responde_401(cliente):
    assert cliente.get("/api/estado").status_code == 401


def test_una_contrasena_mala_no_entra(cliente):
    respuesta = cliente.post(
        "/acceso", data={"clave": "no-es"}, follow_redirects=False
    )
    assert respuesta.status_code == 401


def test_el_admin_puede_con_las_fuentes(cliente):
    _entrar(cliente, "la-del-admin")
    assert cliente.get("/api/fuentes").status_code == 200


def test_un_usuario_normal_no_puede_con_las_fuentes(cliente):
    _entrar(cliente, "la-de-jorge")
    assert cliente.get("/api/fuentes").status_code == 403
    assert cliente.get("/api/consumo").status_code == 403


def test_un_usuario_normal_si_puede_conversar_y_anotar_voz(cliente):
    _entrar(cliente, "la-de-jorge")
    assert cliente.get("/api/estado").status_code == 200
    assert cliente.get("/api/memoria").status_code == 200
    assert cliente.post("/api/consumo/voz", json={"uso": {}}).status_code == 200


def test_cada_uno_ve_su_propio_estado(cliente):
    _entrar(cliente, "la-de-jorge")
    de_jorge = cliente.get("/api/estado").json()

    _entrar(cliente, "la-del-admin")
    del_admin = cliente.get("/api/estado").json()

    assert de_jorge["usuario"] == "Jorge"
    assert de_jorge["rol"] == "usuario"
    assert del_admin["rol"] == "admin"
```

- [ ] **Step 2: Correr la prueba y ver que falla**

Run: `python -m pytest tests/test_permisos.py -q`
Expected: FAIL — el login todavía no distingue personas y no hay campo `rol`.

- [ ] **Step 3: Cambiar el arranque, el login y el middleware**

En `backend/main.py`, dentro de `al_arrancar()`, después del aviso de contraseña, añadir:

```python
    acceso.avisar_de_contrasenas_repetidas()
    memoria.migrar_archivos_sueltos(acceso.por_defecto().id)
```

Reemplazar el cuerpo de `entrar`:

```python
@app.post("/acceso")
async def entrar(clave: str = Form("")):
    if not acceso.protegido():
        return RedirectResponse("/", status_code=303)

    usuario = acceso.quien_entra(clave)
    if usuario is None:
        return HTMLResponse(
            acceso.pagina_login("Contrasena incorrecta."), status_code=401
        )

    respuesta = RedirectResponse("/", status_code=303)
    respuesta.set_cookie(
        acceso.COOKIE,
        acceso.crear_token(usuario),
        max_age=acceso.DURACION,
        httponly=True,
        samesite="lax",
        secure=rutas.hospedado(),   # en local va por http, ahi no aplica
    )
    return respuesta
```

Reemplazar el middleware `guardia`:

```python
@app.middleware("http")
async def guardia(peticion: Request, siguiente):
    """Nadie pasa sin contrasena cuando esto corre en un servidor.

    Ademas deja en peticion.state.usuario quien es, para que las rutas puedan
    leerlo sin volver a validar la cookie.
    """
    ruta = peticion.url.path

    if acceso.es_libre(ruta):
        return await siguiente(peticion)

    if acceso.obligatorio():
        return HTMLResponse(acceso.pagina_sin_proteger(), status_code=503)

    if acceso.protegido():
        usuario = acceso.usuario_de_token(peticion.cookies.get(acceso.COOKIE))
        if usuario is None:
            # A la interfaz le mostramos el formulario; a la API, un 401 limpio.
            if ruta.startswith("/api/"):
                return JSONResponse(status_code=401, content={"error": "No autorizado."})
            return HTMLResponse(acceso.pagina_login(), status_code=401)
    else:
        # En local, sin contrasena, todo se atribuye al usuario por defecto.
        usuario = acceso.por_defecto()

    if acceso.exige_admin(ruta, peticion.method) and usuario.rol != "admin":
        return JSONResponse(
            status_code=403,
            content={"error": "Esto solo lo puede hacer quien administra Jarvis."},
        )

    peticion.state.usuario = usuario
    return await siguiente(peticion)
```

- [ ] **Step 4: Correr la prueba y ver qué queda**

Run: `python -m pytest tests/test_permisos.py -q`
Expected: pasan las de permisos y login; falla `test_cada_uno_ve_su_propio_estado` porque `/api/estado` todavía no devuelve `rol`. Se arregla en la tarea siguiente.

- [ ] **Step 5: Commit**

```bash
git add backend/main.py tests/test_permisos.py
git commit -m "Main: el middleware resuelve la identidad y aplica los permisos"
```

---

## Task 11: Las rutas usan el usuario de la petición

**Files:**
- Modify: `backend/main.py:141-186` y `backend/main.py:253-348`
- Test: `tests/test_permisos.py`

- [ ] **Step 1: Reemplazar las rutas que tocan memoria, conversación o voz**

```python
@app.get("/api/estado")
def estado(peticion: Request):
    clave = os.getenv("OPENAI_API_KEY", "").strip()
    usuario = peticion.state.usuario
    return {
        "nombre": os.getenv("JARVIS_NOMBRE", "Jarvis"),
        "usuario": usuario.nombre,
        "rol": usuario.rol,
        "modelo": os.getenv("OPENAI_MODEL", "gpt-5.6-terra"),
        "modelo_voz": os.getenv("OPENAI_MODELO_VOZ", "gpt-realtime-2.1-mini"),
        "clave_configurada": bool(clave) and not clave.startswith("sk-pon-tu-clave"),
        "hechos_recordados": len(memoria.todos_los_hechos(usuario.id)),
        "historial": memoria.cargar_conversacion(usuario.id),
        "conectores": conectores.resumen(),
        "esquema": esquema.info(),
        "version": version.info(),
    }
```

```python
@app.post("/api/chat")
def chat(peticion_http: Request, peticion: PeticionDeChat):
    # El usuario se resuelve aqui, no dentro del generador: para cuando el
    # generador corre, la peticion ya termino y su contexto puede haberse ido.
    usuario = peticion_http.state.usuario

    mensajes = memoria.cargar_conversacion(usuario.id)
    mensajes.append({"role": "user", "content": peticion.mensaje})

    extra = (
        "Respondes en la pantalla de un reloj y en voz alta: maximo dos frases, "
        "sin listas ni encabezados."
        if peticion.breve
        else ""
    )

    def flujo():
        for evento in cerebro.responder(mensajes, usuario, extra):
            yield cerebro.evento_sse(evento)

    return StreamingResponse(
        flujo(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

```python
@app.get("/api/voz/sesion")
def sesion_de_voz(peticion: Request):
    """Configuracion completa de la sesion de voz: instrucciones + herramientas.

    La usa el puente del reloj para levantar un modo de voz alterno (Gemini
    Live) con exactamente el mismo cerebro y las mismas herramientas que la voz
    de OpenAI. Es de solo lectura y no altera el flujo existente.
    """
    return cerebro.configuracion_de_sesion(peticion.state.usuario)
```

En `negociar_voz`, cambiar la llamada:

```python
        respuesta = cerebro.negociar_webrtc(oferta, peticion.state.usuario)
```

```python
@app.post("/api/herramienta")
def ejecutar_herramienta(peticion_http: Request, peticion: PeticionDeHerramienta):
    """Ejecuta una funcion local que pidio la sesion de voz.

    En modo voz el modelo habla directo con el navegador, asi que las
    herramientas que viven en este servidor pasan por aqui. Las de Supabase no:
    esas las resuelve OpenAI contra el MCP sin tocarnos.
    """
    return {
        "resultado": herramientas.ejecutar(
            peticion.nombre, peticion.argumentos, peticion_http.state.usuario.id
        )
    }
```

```python
@app.post("/api/conversacion/agregar")
def agregar_a_conversacion(peticion: Request, mensaje: MensajeSuelto):
    """Guarda un turno de voz para que texto y voz compartan historial."""
    id_usuario = peticion.state.usuario.id
    mensajes = memoria.cargar_conversacion(id_usuario)
    mensajes.append({"role": mensaje.role, "content": mensaje.content})
    memoria.guardar_conversacion(id_usuario, mensajes)
    return {"ok": True}
```

```python
@app.get("/api/memoria")
def ver_memoria(peticion: Request):
    return {"hechos": memoria.todos_los_hechos(peticion.state.usuario.id)}


@app.delete("/api/memoria/{id_hecho}")
def borrar_hecho(peticion: Request, id_hecho: str):
    return {"borrado": memoria.olvidar(peticion.state.usuario.id, id_hecho)}


@app.post("/api/conversacion/reiniciar")
def reiniciar_conversacion(peticion: Request):
    memoria.borrar_conversacion(peticion.state.usuario.id)
    return {"ok": True}
```

- [ ] **Step 2: Correr toda la suite**

Run: `python -m pytest tests/ -q`
Expected: PASS, todas.

- [ ] **Step 3: Comprobar que no quedó ninguna llamada vieja**

Run: `grep -n "memoria\.\(todos_los_hechos\|cargar_conversacion\|guardar_conversacion\|borrar_conversacion\|olvidar\|recordar\|buscar\|resumen_para_prompt\)()" backend/*.py`
Expected: sin resultados.

- [ ] **Step 4: Arrancar el servidor y ver que responde**

Run: `python -m uvicorn backend.main:app --port 8123 &` y luego `curl -s localhost:8123/api/salud`
Expected: `{"ok":true}`. Después parar el proceso.

- [ ] **Step 5: Commit**

```bash
git add backend/main.py
git commit -m "Main: cada ruta trabaja con la memoria de quien pide"
```

---

## Task 12: La web oculta lo que no corresponde

**Files:**
- Modify: `web/app.js`

- [ ] **Step 1: Ocultar los botones de admin**

En `web/app.js`, en el bloque que aplica el estado (alrededor de la línea 654,
justo después de `document.title = estado.nombre;`), añadir:

```javascript
  // Comodidad, no seguridad: el servidor ya devuelve 403 a quien no es admin.
  const esAdmin = estado.rol === "admin";
  $("btn-fuentes").hidden = !esAdmin;
  $("btn-consumo").hidden = !esAdmin;
```

Los dos ids existen en `web/index.html:24-25`. `$` es el atajo que ya usa el
archivo para `document.getElementById`.

- [ ] **Step 2: Comprobar a mano**

Arrancar con dos contraseñas configuradas, entrar con la de un usuario normal en una ventana privada, y comprobar que no aparecen los botones de Fuentes ni de Consumo.

- [ ] **Step 3: Commit**

```bash
git add web/app.js
git commit -m "Web: ocultar los botones de administracion a quien no es admin"
```

---

## Task 13: Documentar la configuración

**Files:**
- Modify: `.env.example`
- Modify: `README.md`

- [ ] **Step 1: Añadir el ejemplo de variables**

En `.env.example`, en la sección de personalización:

```
# --- Quien puede entrar ---
# Tu contrasena. Obligatoria al hospedar.
JARVIS_PASSWORD=

# Una variable por persona mas. El nombre sale del sufijo:
# JARVIS_PASSWORD_JORGE hace un usuario "jorge" que Jarvis llama "Jorge".
# Cada uno tiene su conversacion y su memoria; las fuentes son comunes.
# Solo quien entra con JARVIS_PASSWORD administra fuentes y consumo.
# JARVIS_PASSWORD_JORGE=

# Firma las sesiones. Al cambiarla, todos vuelven a entrar: es la forma de
# echar a alguien de inmediato.
JARVIS_CLAVE_SECRETA=
```

- [ ] **Step 2: Documentar en el README**

Añadir una sección después de la tabla de variables:

```markdown
### Varias personas

Cada persona tiene su propia contraseña, en su propia variable:

```
JARVIS_PASSWORD=...          # la tuya: administras Jarvis
JARVIS_PASSWORD_JORGE=...    # Jorge
```

La pantalla de login no pide usuario: la contraseña que escribes ya dice quién
eres. Cada uno tiene su conversación, su memoria y su nombre. Las fuentes de
datos, el esquema y las leyendas de tablas son comunes.

Quien entra con `JARVIS_PASSWORD` es el administrador y es el único que puede
tocar las fuentes, refrescar el esquema y ver el consumo. Los demás solo
conversan, aunque Jarvis sí consulta las bases en su nombre.

Para quitarle el acceso a alguien, borra su variable y vuelve a desplegar. Para
cerrar todas las sesiones a la vez, cambia `JARVIS_CLAVE_SECRETA`.

Dos personas con la misma contraseña son indistinguibles al entrar y
compartirían memoria: Jarvis lo avisa al arrancar.
```

- [ ] **Step 3: Commit**

```bash
git add .env.example README.md
git commit -m "Documentar como se agregan personas"
```

---

## Task 14: Verificación final

- [ ] **Step 1: Toda la suite en verde**

Run: `python -m pytest tests/ -q`
Expected: PASS, sin fallos ni errores.

- [ ] **Step 2: Comprobar que sin variables nuevas nada cambió**

Arrancar sin ninguna `JARVIS_PASSWORD_*`, entrar con la contraseña de siempre y
comprobar que la conversación anterior sigue ahí (la migración la adjudicó al
admin) y que el panel de fuentes funciona igual.

- [ ] **Step 3: Comprobar el aislamiento a mano**

Con dos contraseñas configuradas, entrar en dos navegadores distintos y
comprobar:

- Cada uno ve su propia conversación, no la del otro.
- Jarvis llama a cada uno por su nombre.
- Al que no es admin no le aparecen los botones de Fuentes ni Consumo, y
  `curl -b "jarvis_acceso=<su token>" localhost:8000/api/fuentes` devuelve 403.

- [ ] **Step 4: Commit final si quedó algo suelto**

```bash
git status
```
