# Diccionario de datos y accesos directos — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que el super admin documente cada tabla/vista de una fuente (diccionario) y guarde preguntas frecuentes como accesos directos con variables, asistido por la IA, para que Jarvis responda rápido y bien.

**Architecture:** El diccionario amplía la config por tabla que ya existe en `fuentes.json` (`activa`, `leyenda` → + `columnas`, `reglas`). Los accesos directos viven en `jarvis.db` (módulo `accesos.py`), se ejecutan con parámetros del driver a través de `fuentes.consultar` y el modelo los usa con una herramienta nueva. La redacción asistida (diccionario y accesos) está en `redactor.py`, que llama al modelo de Jarvis y devuelve borradores sin guardar.

**Tech Stack:** Python 3.12, FastAPI, sqlite3, pymssql/psycopg (paramstyle `%(nombre)s`), OpenAI Responses API (`cerebro.cliente()`), pytest; web vanilla JS.

**Spec:** `docs/superpowers/specs/2026-10-26-diccionario-accesos-directos-design.md`.

**Rama:** crear `feat/accesos-directos` desde `origin/main`. En el EC2 corre `feat/avatar-holograma` (todavía sin mergear): para desplegar, mergear esta rama en esa (ver Task 11).

**Pruebas:** `.venv/Scripts/python.exe -m pytest -q` desde `C:\Users\Jorge\jarvis`. Puente: `node --test test/*.test.js` en `C:\Users\Jorge\jarvis-puentes\puente-android` (y `puente-reloj`).

---

## Mapa de archivos

| Archivo | Qué | Responsabilidad |
|---|---|---|
| `backend/fuentes.py` | Modificar | Guardar/leer `columnas` y `reglas` por tabla; motores y `consultar` aceptan `parametros`; el prompt muestra el diccionario; `borrar` borra los accesos de la fuente. |
| `backend/accesos.py` | Crear | Accesos directos: guardar, listar, borrar, validar parámetros, ejecutar con caché, catálogo para el prompt. |
| `backend/redactor.py` | Crear | Borradores con IA: diccionario de una tabla y acceso directo a partir de una pregunta. |
| `backend/basedatos.py` | Modificar | Tabla `accesos_directos`. |
| `backend/herramientas.py` | Modificar | Herramienta `usar_acceso_directo`. |
| `backend/cerebro.py` | Modificar | Catálogo de accesos en las instrucciones. |
| `backend/acceso.py` | Modificar | `/api/accesos` exige admin. |
| `backend/main.py` | Modificar | Rutas del diccionario y de los accesos. |
| `web/fuentes.js`, `web/style.css`, `web/index.html` | Modificar | Diccionario en el panel de tablas; pantalla de accesos directos. |
| `tests/test_diccionario.py`, `tests/test_accesos.py`, `tests/test_redactor.py` | Crear | Pruebas. |
| `jarvis-puentes/puente-*/src/gemini.js` | Modificar | Conservar las líneas de accesos en el prompt de voz. |

---

### Task 1: Diccionario en la config de la fuente

**Files:**
- Modify: `backend/fuentes.py` (`guardar_config_tablas` ~1311, `esquema_con_estado` ~1337)
- Test: `tests/test_diccionario.py`

- [ ] **Step 1: Escribir las pruebas que fallan**

```python
"""Diccionario por tabla: leyenda, significado de columnas y reglas."""

import pytest

from backend import fuentes

ESQUEMA = {"fuente": "ERP", "tipo": "mssql", "tablas": [
    {"tabla": "List_ClientesIA", "columnas": "Codigo varchar, Nombre varchar, Estado char"},
]}


@pytest.fixture
def fuente(monkeypatch):
    guardadas = [{"id": "erp", "nombre": "ERP", "tipo": "mssql", "activa": True, "config": {}, "tablas": {}}]
    monkeypatch.setattr(fuentes, "_leer", lambda: guardadas)
    monkeypatch.setattr(fuentes, "_escribir", lambda lista: guardadas.__setitem__(slice(None), lista))
    monkeypatch.setattr(fuentes, "esquema_de", lambda _id, refrescar=False: ESQUEMA)
    monkeypatch.setattr(fuentes, "contar_filas", lambda *_: None)
    return guardadas


def test_se_guardan_columnas_y_reglas(fuente):
    fuentes.guardar_config_tablas("erp", {"List_ClientesIA": {
        "activa": True, "leyenda": " clientes ",
        "columnas": {"Estado": " 'A' = activo ", "Inventada": "no existe", "Nombre": ""},
        "reglas": " Activo es Estado = 'A'. ",
    }})
    cfg = fuente[0]["tablas"]["List_ClientesIA"]
    assert cfg == {"activa": True, "leyenda": "clientes",
                   "columnas": {"Estado": "'A' = activo"}, "reglas": "Activo es Estado = 'A'."}


def test_los_textos_largos_se_recortan(fuente):
    fuentes.guardar_config_tablas("erp", {"List_ClientesIA": {
        "columnas": {"Estado": "x" * 500}, "reglas": "y" * 5000}})
    cfg = fuente[0]["tablas"]["List_ClientesIA"]
    assert len(cfg["columnas"]["Estado"]) == 200 and len(cfg["reglas"]) == 1000


def test_el_panel_recibe_el_diccionario(fuente):
    fuentes.guardar_config_tablas("erp", {"List_ClientesIA": {
        "leyenda": "clientes", "columnas": {"Estado": "'A' = activo"}, "reglas": "r"}})
    tabla = fuentes.esquema_con_estado("erp")["tablas"][0]
    assert tabla["columnas_significado"] == {"Estado": "'A' = activo"}
    assert tabla["reglas"] == "r"
```

- [ ] **Step 2: Correrlas y ver que fallan**

Run: `.venv/Scripts/python.exe -m pytest tests/test_diccionario.py -v`
Expected: FAIL — el dict guardado no trae `columnas`/`reglas`.

- [ ] **Step 3: Implementar en `backend/fuentes.py`**

Reemplazar el cuerpo del bucle de `guardar_config_tablas` y agregar el helper arriba de la función:

```python
LARGO_COLUMNA = 200
LARGO_REGLAS = 1000


def _nombres_de_columnas(id_fuente: str, tabla: str) -> set[str]:
    """Las columnas reales de una tabla, para no guardar significados de columnas inventadas."""
    try:
        for entrada in esquema_de(id_fuente)["tablas"]:
            if entrada["tabla"] == tabla:
                return {c.strip().split(" ")[0] for c in entrada["columnas"].split(",") if c.strip()}
    except Exception:  # noqa: BLE001 - sin esquema se guarda lo que venga
        return set()
    return set()
```

```python
    limpio = {}
    for nombre, cfg in (config_tablas or {}).items():
        cfg = cfg or {}
        reales = _nombres_de_columnas(id_fuente, str(nombre))
        columnas = {
            str(col): str(texto).strip()[:LARGO_COLUMNA]
            for col, texto in (cfg.get("columnas") or {}).items()
            if str(texto).strip() and (not reales or str(col) in reales)
        }
        limpio[str(nombre)] = {
            "activa": bool(cfg.get("activa", True)),
            "leyenda": (cfg.get("leyenda") or "").strip(),
            "columnas": columnas,
            "reglas": (cfg.get("reglas") or "").strip()[:LARGO_REGLAS],
        }
```

El dict de cada tabla siempre lleva las cuatro claves (`activa`, `leyenda`, `columnas`, `reglas`).

En `esquema_con_estado`, dentro del `tablas.append({...})`, agregar:

```python
            "columnas_significado": cfg.get("columnas", {}),
            "reglas": cfg.get("reglas", ""),
```

- [ ] **Step 4: Correr las pruebas**

Run: `.venv/Scripts/python.exe -m pytest tests/test_diccionario.py -v` → PASS. Después la suite completa → todo pasa.

- [ ] **Step 5: Commit**

```bash
git add backend/fuentes.py tests/test_diccionario.py
git commit -m "Diccionario: significado de columnas y reglas por tabla en la config de la fuente"
```

---

### Task 2: El diccionario llega al prompt

**Files:**
- Modify: `backend/fuentes.py` (`resumen_para_prompt`, función interna `con_leyenda` y el armado de `detalle`)
- Test: `tests/test_diccionario.py`

- [ ] **Step 1: Prueba que falla**

```python
def test_el_prompt_lleva_columnas_y_reglas(fuente, monkeypatch):
    monkeypatch.setattr(fuentes, "activas", lambda: fuente)
    fuentes.guardar_config_tablas("erp", {"List_ClientesIA": {
        "leyenda": "clientes", "columnas": {"Estado": "'A' = activo"}, "reglas": "Activo es Estado = 'A'."}})
    texto = fuentes.resumen_para_prompt()
    assert "List_ClientesIA (clientes)" in texto
    assert "Estado: 'A' = activo" in texto
    assert "Reglas: Activo es Estado = 'A'." in texto
```

- [ ] **Step 2: Correrla** → FAIL (no aparece "Estado: 'A' = activo").

- [ ] **Step 3: Implementar**

En `resumen_para_prompt`, reemplazar el armado de `detalle` por:

```python
        def diccionario(nombre: str, cfg=config_tablas) -> str:
            datos = cfg.get(nombre, {})
            lineas = [f"      {col}: {texto}" for col, texto in (datos.get("columnas") or {}).items()]
            if datos.get("reglas"):
                lineas.append(f"      Reglas: {datos['reglas']}")
            return ("\n" + "\n".join(lineas)) if lineas else ""

        detalle = "\n".join(
            f"    {con_leyenda(t['tabla'])}: {t['columnas']}{diccionario(t['tabla'])}"
            for t in tablas_activas
        )
```

(El recorte por `TOPE_ESQUEMA_EN_PROMPT` que sigue queda igual: si se pasa, vuelve a la lista corta.)

- [ ] **Step 4: Correr** → PASS, y la suite completa.

- [ ] **Step 5: Commit**

```bash
git add backend/fuentes.py tests/test_diccionario.py
git commit -m "El diccionario de cada tabla activa va a las instrucciones de Jarvis"
```

---

### Task 3: Consultar con parámetros

**Files:**
- Modify: `backend/fuentes.py` (`consultar_postgres`, `consultar_mssql`, `consultar_supabase`, `consultar`)
- Test: `tests/test_accesos.py`

- [ ] **Step 1: Prueba que falla**

Crear `tests/test_accesos.py`:

```python
import json

import pytest

from backend import fuentes


@pytest.fixture
def motor(monkeypatch):
    """Un motor de mentira que anota lo que recibe."""
    vistos = []

    def falso(config, sql, limite, id_fuente=None, parametros=None):
        vistos.append({"sql": sql, "parametros": parametros, "limite": limite})
        return [{"n": 1}]

    monkeypatch.setitem(fuentes.MOTORES, "mssql", falso)
    monkeypatch.setattr(fuentes, "obtener", lambda _id: {
        "id": "erp", "nombre": "ERP", "tipo": "mssql", "activa": True, "solo_lectura": True, "config": {}})
    return vistos


def test_consultar_pasa_los_parametros_al_motor(motor):
    fuentes.consultar("erp", "select count(*) n from v where f >= %(desde)s", 10, parametros={"desde": "2026-10-26"})
    assert motor[0]["parametros"] == {"desde": "2026-10-26"}


def test_sin_parametros_sigue_como_antes(motor):
    fuentes.consultar("erp", "select 1", 10)
    assert motor[0]["parametros"] is None
```

- [ ] **Step 2: Correr** → FAIL (`consultar() got an unexpected keyword argument 'parametros'`).

- [ ] **Step 3: Implementar**

`consultar`:

```python
def consultar(id_fuente: str, sql: str, limite: int = 200, parametros: dict | None = None) -> list[dict]:
    ...  # lo de antes hasta validar_solo_lectura
    return MOTORES[fuente["tipo"]](fuente["config"], sql, limite, id_fuente, parametros=parametros)
```

En `consultar_postgres` y `consultar_mssql`: firma `(config, sql, limite, id_fuente=None, parametros=None)` y en su `ejecutar`, `cursor.execute(sql, parametros)` si `parametros` no es `None`, si no `cursor.execute(sql)` (en psycopg y pymssql, pasar `None` cambia el tratamiento de `%` literales; por eso solo se pasa cuando hay):

```python
    def ejecutar(conexion):
        with conexion.cursor(as_dict=True) as cursor:        # en postgres: row_factory=dict_row
            if parametros is None:
                cursor.execute(sql)
            else:
                cursor.execute(sql, parametros)
            return [dict(f) for f in cursor.fetchmany(limite)]
```

`consultar_supabase`: firma igual; si llegan `parametros`, `raise ValueError("Esta fuente (Supabase por MCP) no acepta consultas con variables.")`.

- [ ] **Step 4: Correr** → PASS, suite completa.

- [ ] **Step 5: Commit**

```bash
git add backend/fuentes.py tests/test_accesos.py
git commit -m "Las fuentes aceptan consultas con parametros del driver (%(nombre)s)"
```

---

### Task 4: Accesos directos — guardar, validar, listar, borrar

**Files:**
- Modify: `backend/basedatos.py` (`_ESQUEMA`)
- Create: `backend/accesos.py`
- Test: `tests/test_accesos.py`

- [ ] **Step 1: Pruebas que fallan** (agregar a `tests/test_accesos.py`)

```python
from backend import accesos  # noqa: E402

VENTAS = {
    "id": "ventas_por_periodo",
    "pregunta": "¿Cuántas ventas se hicieron hoy?",
    "descripcion": "Cantidad y monto de ventas entre dos fechas.",
    "sql": "select count(*) as ventas from List_OrdenVentasIA where Fecha >= %(desde)s and Fecha < %(hasta)s",
    "parametros": {
        "desde": {"tipo": "fecha", "descripcion": "Desde (incluida)", "por_defecto": "2026-10-26"},
        "hasta": {"tipo": "fecha", "descripcion": "Hasta (excluida)", "por_defecto": "2026-10-27"},
    },
}


def test_guardar_y_listar(motor):
    accesos.guardar("erp", VENTAS)
    [a] = accesos.listar("erp")
    assert a["id"] == "ventas_por_periodo" and a["parametros"]["desde"]["tipo"] == "fecha"
    assert a["activo"] is True and a["ultimo_error"] is None


def test_el_sql_tiene_que_ser_de_solo_lectura(motor):
    with pytest.raises(accesos.ErrorDeAcceso, match="solo lectura"):
        accesos.guardar("erp", {**VENTAS, "sql": "delete from List_ClientesIA"})


def test_los_placeholders_tienen_que_coincidir(motor):
    with pytest.raises(accesos.ErrorDeAcceso, match="hasta"):
        accesos.guardar("erp", {**VENTAS, "sql": "select 1 where f >= %(desde)s"})


def test_el_nombre_es_corto_y_sin_espacios(motor):
    with pytest.raises(accesos.ErrorDeAcceso):
        accesos.guardar("erp", {**VENTAS, "id": "ventas de hoy!"})


def test_tipos_de_variable(motor):
    p = {"tipo": "entero", "descripcion": "Cuantos", "por_defecto": 5, "minimo": 1, "maximo": 50}
    assert accesos.valor(p, "7") == 7
    with pytest.raises(accesos.ErrorDeAcceso):
        accesos.valor(p, 500)
    assert accesos.valor({"tipo": "fecha"}, "2026-10-26") == "2026-10-26"
    with pytest.raises(accesos.ErrorDeAcceso):
        accesos.valor({"tipo": "fecha"}, "26/10/2026")
    with pytest.raises(accesos.ErrorDeAcceso):
        accesos.valor({"tipo": "texto"}, "x" * 101)


def test_borrar_y_desactivar(motor):
    accesos.guardar("erp", VENTAS)
    accesos.activar("ventas_por_periodo", False)
    assert accesos.listar("erp")[0]["activo"] is False
    assert accesos.borrar("ventas_por_periodo") is True
    assert accesos.listar("erp") == []


def test_borrar_la_fuente_borra_sus_accesos(motor):
    accesos.guardar("erp", VENTAS)
    accesos.borrar_de_fuente("erp")
    assert accesos.listar("erp") == []
```

- [ ] **Step 2: Correr** → FAIL (`cannot import name 'accesos'`).

- [ ] **Step 3: Tabla en `basedatos.py`** (al final de `_ESQUEMA`)

```sql
    -- Accesos directos: preguntas frecuentes con su consulta lista, por fuente.
    -- fuente_id apunta a fuentes.json (no a una tabla). Ver accesos.py.
    CREATE TABLE IF NOT EXISTS accesos_directos (
        id TEXT PRIMARY KEY,
        fuente_id TEXT NOT NULL,
        pregunta TEXT NOT NULL,
        descripcion TEXT NOT NULL,
        sql TEXT NOT NULL,
        parametros TEXT NOT NULL,
        activo INTEGER NOT NULL DEFAULT 1,
        ultimo_error TEXT,
        creado TEXT NOT NULL,
        actualizado TEXT NOT NULL
    );
```

- [ ] **Step 4: Crear `backend/accesos.py`**

```python
"""Accesos directos: preguntas frecuentes con su consulta ya escrita, por fuente.

Existen por velocidad y por acierto, como el catalogo de consultas.py, pero los
carga el super admin desde la interfaz (asistido por redactor.py). Las variables
viajan como parametros del driver (%(nombre)s): nunca se pegan en el SQL.
"""

import json
import re
from datetime import date, datetime, timezone

from . import basedatos, fuentes

NOMBRE = re.compile(r"^[a-z][a-z0-9_]{2,59}$")
PLACEHOLDER = re.compile(r"%\((\w+)\)s")
TIPOS = ("fecha", "entero", "texto")


class ErrorDeAcceso(ValueError):
    """Algo del acceso directo no sirve. El mensaje es para quien lo carga."""


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def valor(spec: dict, crudo):
    """Convierte y valida el valor de una variable segun su tipo."""
    tipo = spec.get("tipo")
    if tipo == "fecha":
        try:
            return date.fromisoformat(str(crudo)).isoformat()
        except ValueError:
            raise ErrorDeAcceso(f"'{crudo}' no es una fecha AAAA-MM-DD.") from None
    if tipo == "entero":
        try:
            numero = int(crudo)
        except (TypeError, ValueError):
            raise ErrorDeAcceso(f"'{crudo}' no es un numero entero.") from None
        minimo, maximo = int(spec.get("minimo", 1)), int(spec.get("maximo", 500))
        if not minimo <= numero <= maximo:
            raise ErrorDeAcceso(f"{numero} esta fuera de {minimo}-{maximo}.")
        return numero
    if tipo == "texto":
        texto = str(crudo or "").strip()
        if len(texto) > 100:
            raise ErrorDeAcceso("El texto puede tener hasta 100 caracteres.")
        return texto
    raise ErrorDeAcceso(f"Tipo de variable desconocido: {tipo}.")


def validar(datos: dict) -> dict:
    """Lo que se guarda, ya limpio. Lanza ErrorDeAcceso si algo no sirve."""
    nombre = str(datos.get("id") or "").strip()
    if not NOMBRE.match(nombre):
        raise ErrorDeAcceso("El nombre va en minusculas, con guiones bajos, sin espacios (p. ej. ventas_por_periodo).")
    sql = str(datos.get("sql") or "").strip().rstrip(";")
    try:
        fuentes.validar_solo_lectura(sql)
    except ValueError as error:
        raise ErrorDeAcceso(f"La consulta tiene que ser de solo lectura: {error}") from None
    parametros = datos.get("parametros") or {}
    usados, declarados = set(PLACEHOLDER.findall(sql)), set(parametros)
    if usados != declarados:
        faltan = sorted(usados ^ declarados)
        raise ErrorDeAcceso(f"Las variables de la consulta y las declaradas no coinciden: {', '.join(faltan)}.")
    for nombre_p, spec in parametros.items():
        if spec.get("tipo") not in TIPOS:
            raise ErrorDeAcceso(f"La variable {nombre_p} tiene un tipo invalido.")
        if spec.get("por_defecto") is not None:
            valor(spec, spec["por_defecto"])
    descripcion = " ".join(str(datos.get("descripcion") or "").split())
    if not descripcion:
        raise ErrorDeAcceso("Falta la descripcion de que responde.")
    return {"id": nombre, "pregunta": str(datos.get("pregunta") or "").strip()[:300],
            "descripcion": descripcion[:400], "sql": sql, "parametros": parametros}


def guardar(fuente_id: str, datos: dict) -> dict:
    limpio = validar(datos)
    with basedatos.conexion() as con:
        con.execute(
            "INSERT INTO accesos_directos (id, fuente_id, pregunta, descripcion, sql, parametros, "
            "creado, actualizado) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (id) DO UPDATE SET fuente_id = excluded.fuente_id, pregunta = excluded.pregunta, "
            "descripcion = excluded.descripcion, sql = excluded.sql, parametros = excluded.parametros, "
            "ultimo_error = NULL, actualizado = excluded.actualizado",
            (limpio["id"], fuente_id, limpio["pregunta"], limpio["descripcion"], limpio["sql"],
             json.dumps(limpio["parametros"], ensure_ascii=False), _ahora(), _ahora()),
        )
    _cache.clear()
    return obtener(limpio["id"])


def _fila(f) -> dict:
    return {"id": f["id"], "fuente_id": f["fuente_id"], "pregunta": f["pregunta"],
            "descripcion": f["descripcion"], "sql": f["sql"], "parametros": json.loads(f["parametros"]),
            "activo": bool(f["activo"]), "ultimo_error": f["ultimo_error"]}


def obtener(id_acceso: str) -> dict | None:
    with basedatos.conexion() as con:
        f = con.execute("SELECT * FROM accesos_directos WHERE id = ?", (id_acceso,)).fetchone()
    return _fila(f) if f else None


def listar(fuente_id: str | None = None) -> list[dict]:
    with basedatos.conexion() as con:
        filas = con.execute(
            "SELECT * FROM accesos_directos" + (" WHERE fuente_id = ?" if fuente_id else "") + " ORDER BY id",
            (fuente_id,) if fuente_id else (),
        ).fetchall()
    return [_fila(f) for f in filas]


def activar(id_acceso: str, activo: bool) -> None:
    with basedatos.conexion() as con:
        con.execute("UPDATE accesos_directos SET activo = ?, actualizado = ? WHERE id = ?",
                    (1 if activo else 0, _ahora(), id_acceso))


def borrar(id_acceso: str) -> bool:
    with basedatos.conexion() as con:
        return con.execute("DELETE FROM accesos_directos WHERE id = ?", (id_acceso,)).rowcount > 0


def borrar_de_fuente(fuente_id: str) -> None:
    with basedatos.conexion() as con:
        con.execute("DELETE FROM accesos_directos WHERE fuente_id = ?", (fuente_id,))


_cache: dict = {}
```

- [ ] **Step 5: Correr** → PASS. Suite completa.

- [ ] **Step 6: Commit**

```bash
git add backend/basedatos.py backend/accesos.py tests/test_accesos.py
git commit -m "Accesos directos: guardar, validar variables y solo lectura, listar y borrar"
```

---

### Task 5: Ejecutar un acceso, caché y catálogo para el prompt

**Files:**
- Modify: `backend/accesos.py`, `backend/fuentes.py` (`borrar`)
- Test: `tests/test_accesos.py`

- [ ] **Step 1: Pruebas que fallan**

```python
def test_ejecutar_usa_los_parametros_y_los_por_defecto(motor):
    accesos.guardar("erp", VENTAS)
    r = accesos.ejecutar("ventas_por_periodo", {"desde": "2026-10-01"})
    assert r["filas"] == [{"n": 1}]
    assert motor[0]["parametros"] == {"desde": "2026-10-01", "hasta": "2026-10-27"}


def test_el_resultado_se_cachea_30_segundos(motor):
    accesos.guardar("erp", VENTAS)
    accesos.ejecutar("ventas_por_periodo", {})
    accesos.ejecutar("ventas_por_periodo", {})
    assert len(motor) == 1


def test_un_fallo_queda_anotado_y_dice_como_seguir(motor, monkeypatch):
    accesos.guardar("erp", VENTAS)

    def rompe(*a, **k):
        raise RuntimeError("Invalid object name 'List_OrdenVentasIA'")
    monkeypatch.setitem(fuentes.MOTORES, "mssql", rompe)
    r = accesos.ejecutar("ventas_por_periodo", {})
    assert "consultar_fuente" in r["error"]
    assert "Invalid object name" in accesos.obtener("ventas_por_periodo")["ultimo_error"]


def test_uno_desactivado_o_inexistente_no_se_ejecuta(motor):
    accesos.guardar("erp", VENTAS)
    accesos.activar("ventas_por_periodo", False)
    assert "error" in accesos.ejecutar("ventas_por_periodo", {})
    assert "error" in accesos.ejecutar("no_existe", {})


def test_catalogo_para_el_prompt(motor, monkeypatch):
    monkeypatch.setattr(fuentes, "activas", lambda: [{"id": "erp", "nombre": "ERP"}])
    accesos.guardar("erp", VENTAS)
    texto = accesos.catalogo_para_prompt()
    assert texto.startswith("- acceso ventas_por_periodo(desde, hasta) [fuente erp]:")


def test_borrar_la_fuente_borra_sus_accesos_desde_fuentes(motor, monkeypatch):
    accesos.guardar("erp", VENTAS)
    monkeypatch.setattr(fuentes, "_leer", lambda: [{"id": "erp"}])
    monkeypatch.setattr(fuentes, "_escribir", lambda lista: None)
    fuentes.borrar("erp")
    assert accesos.listar("erp") == []
```

- [ ] **Step 2: Correr** → FAIL.

- [ ] **Step 3: Implementar en `backend/accesos.py`**

```python
import time

VIGENCIA = 30  # segundos


def _valores(acceso: dict, recibidos: dict) -> dict:
    valores = {}
    for nombre, spec in acceso["parametros"].items():
        crudo = recibidos.get(nombre, spec.get("por_defecto"))
        if crudo is None:
            raise ErrorDeAcceso(f"Falta la variable {nombre}: {spec.get('descripcion', '')}.")
        valores[nombre] = valor(spec, crudo)
    return valores


def _anotar_error(id_acceso: str, texto: str | None) -> None:
    with basedatos.conexion() as con:
        con.execute("UPDATE accesos_directos SET ultimo_error = ? WHERE id = ?",
                    (texto[:300] if texto else None, id_acceso))


def ejecutar(id_acceso: str, recibidos: dict | None = None, limite: int = 100) -> dict:
    """{'filas': [...]} o {'error': texto para el modelo}."""
    acceso = obtener(id_acceso)
    if not acceso or not acceso["activo"]:
        return {"error": f"No hay un acceso directo activo llamado '{id_acceso}'. Usa consultar_fuente."}
    try:
        valores = _valores(acceso, recibidos or {})
    except ErrorDeAcceso as error:
        return {"error": str(error)}
    clave = (id_acceso, json.dumps(valores, sort_keys=True))
    guardado = _cache.get(clave)
    if guardado and time.monotonic() - guardado[0] < VIGENCIA:
        return {"filas": guardado[1]}
    try:
        filas = fuentes.consultar(acceso["fuente_id"], acceso["sql"], limite, parametros=valores or None)
    except Exception as error:  # noqa: BLE001 - p. ej. cambio la vista
        explicacion = fuentes.explicar(error)
        _anotar_error(id_acceso, explicacion)
        return {"error": f"El acceso directo fallo ({explicacion}). Responde con consultar_fuente."}
    if acceso["ultimo_error"]:
        _anotar_error(id_acceso, None)
    _cache[clave] = (time.monotonic(), filas)
    return {"filas": filas}


def catalogo_para_prompt() -> str:
    """Una linea por acceso activo de una fuente activa. Prefijo fijo: el puente lo busca."""
    ids_activas = {f["id"] for f in fuentes.activas()}
    lineas = []
    for a in listar():
        if a["activo"] and a["fuente_id"] in ids_activas:
            variables = ", ".join(a["parametros"])
            lineas.append(f"- acceso {a['id']}({variables}) [fuente {a['fuente_id']}]: {a['descripcion']}")
    return "\n".join(lineas)
```

(`fuentes.explicar(error)` ya existe: lo usa `herramientas.consultar_fuente`.)

En `backend/fuentes.py`, `borrar`, después de `olvidar_esquema(id_fuente)`:

```python
    from . import accesos   # import tardio: accesos importa fuentes
    accesos.borrar_de_fuente(id_fuente)
```

- [ ] **Step 4: Correr** → PASS, suite completa.

- [ ] **Step 5: Commit**

```bash
git add backend/accesos.py backend/fuentes.py tests/test_accesos.py
git commit -m "Accesos directos: ejecutar con variables y cache de 30 s, catalogo para el prompt"
```

---

### Task 6: Herramienta y lugar en las instrucciones

**Files:**
- Modify: `backend/herramientas.py`, `backend/cerebro.py`
- Test: `tests/test_accesos.py`

- [ ] **Step 1: Pruebas que fallan**

```python
def test_la_herramienta_usa_el_acceso(motor):
    from backend import herramientas

    accesos.guardar("erp", VENTAS)
    texto = herramientas.usar_acceso_directo("ventas_por_periodo", '{"desde": "2026-10-20"}')
    assert json.loads(texto) == [{"n": 1}]
    assert "JSON" in herramientas.usar_acceso_directo("ventas_por_periodo", "{no es json")


def test_las_instrucciones_listan_los_accesos(motor, monkeypatch):
    from backend import acceso, cerebro

    monkeypatch.setattr(fuentes, "activas", lambda: [{"id": "erp", "nombre": "ERP"}])
    monkeypatch.setattr(fuentes, "resumen_para_prompt", lambda: "- id \"erp\": ERP")
    accesos.guardar("erp", VENTAS)
    texto = cerebro.instrucciones(acceso.Usuario("u", "Ana", "usuario"))
    assert "- acceso ventas_por_periodo(desde, hasta)" in texto
    assert "usar_acceso_directo" in texto
```

- [ ] **Step 2: Correr** → FAIL.

- [ ] **Step 3: Herramienta en `backend/herramientas.py`** (después de `consultar_fuente`)

```python
@herramienta(
    "Responde una pregunta frecuente con un acceso directo: una consulta ya "
    "escrita y probada para una fuente. Es la via mas rapida: si la pregunta "
    "encaja con uno de los accesos directos de tus instrucciones, usalo antes "
    "de escribir SQL. Pasa solo las variables (fechas AAAA-MM-DD, numeros, textos).",
    nombre="El nombre del acceso directo, tal como aparece en tus instrucciones",
    parametros='Las variables en JSON, por ejemplo {"desde": "2026-10-26", "hasta": "2026-10-27"}. Omitelo para usar las de por defecto.',
)
def usar_acceso_directo(nombre: str, parametros: str = "{}") -> str:
    from . import accesos

    try:
        valores = json.loads(parametros) if parametros else {}
    except json.JSONDecodeError:
        return "Error: 'parametros' no es JSON valido."
    if not isinstance(valores, dict):
        return "Error: 'parametros' debe ser un objeto JSON."
    resultado = accesos.ejecutar(nombre, valores)
    if "error" in resultado:
        return resultado["error"]
    if not resultado["filas"]:
        return "El acceso directo no devolvio resultados."
    return json.dumps(resultado["filas"], ensure_ascii=False, default=str)[:6000]
```

- [ ] **Step 4: Instrucciones en `backend/cerebro.py`**

Agregar `accesos` al import de módulos. En `instrucciones`, justo después del bloque `if otras:` que agrega "Otras fuentes de datos conectadas…", agregar:

```python
    directos = accesos.catalogo_para_prompt()
    if directos:
        texto += f"""

Accesos directos (preguntas frecuentes ya resueltas; usalos con `usar_acceso_directo`
antes de escribir SQL si la pregunta encaja; "hoy", "ayer", "este mes" se pasan como
fechas desde/hasta, con hasta excluida):
{directos}"""
```

- [ ] **Step 5: Correr** → PASS, suite completa.

- [ ] **Step 6: Commit**

```bash
git add backend/herramientas.py backend/cerebro.py tests/test_accesos.py
git commit -m "Jarvis usa los accesos directos con la herramienta usar_acceso_directo"
```

---

### Task 7: Redactor con IA (diccionario y accesos)

**Files:**
- Create: `backend/redactor.py`
- Test: `tests/test_redactor.py`

- [ ] **Step 1: Pruebas que fallan**

```python
import json

import pytest

from backend import accesos, fuentes, redactor

ESQUEMA = {"fuente": "ERP", "tipo": "mssql", "tablas": [
    {"tabla": "List_OrdenVentasIA", "columnas": "Numero int, Fecha datetime, Vendedor varchar, Total money"},
]}


class _Modelo:
    """Reemplaza a cerebro.cliente(): devuelve lo que se le diga y anota lo que recibio."""

    def __init__(self, salida):
        self.salida, self.pedidos = salida, []
        self.responses = self

    def create(self, **kw):
        self.pedidos.append(kw)
        return type("R", (), {"output_text": json.dumps(self.salida), "usage": None})()


@pytest.fixture
def base(monkeypatch):
    monkeypatch.setattr(fuentes, "obtener", lambda _id: {
        "id": "erp", "nombre": "ERP", "tipo": "mssql", "activa": True, "solo_lectura": True,
        "config": {}, "tablas": {}})
    monkeypatch.setattr(fuentes, "esquema_de", lambda _id, refrescar=False: ESQUEMA)
    filas = []
    monkeypatch.setitem(fuentes.MOTORES, "mssql",
                        lambda c, sql, lim, idf=None, parametros=None: filas.append((sql, parametros)) or [{"ventas": 12}])
    return filas


def test_proponer_diccionario_lee_filas_de_ejemplo_y_no_guarda(base, monkeypatch):
    modelo = _Modelo({"leyenda": "ordenes de venta", "columnas": {"Total": "monto con ITBIS"}, "reglas": ""})
    monkeypatch.setattr(redactor, "_cliente", lambda: modelo)
    borrador = redactor.proponer_diccionario("erp", "List_OrdenVentasIA")
    assert borrador == {"leyenda": "ordenes de venta", "columnas": {"Total": "monto con ITBIS"}, "reglas": ""}
    assert base[0][0].lower().startswith("select top 5 *")
    assert "List_OrdenVentasIA" in modelo.pedidos[0]["input"]


def test_proponer_acceso_lo_valida_y_lo_corre_sin_guardar(base, monkeypatch):
    modelo = _Modelo({
        "id": "ventas_por_periodo", "descripcion": "Ventas entre dos fechas.",
        "sql": "select count(*) as ventas from List_OrdenVentasIA where Fecha >= %(desde)s and Fecha < %(hasta)s",
        "parametros": {"desde": {"tipo": "fecha", "descripcion": "desde", "por_defecto": "2026-10-26"},
                       "hasta": {"tipo": "fecha", "descripcion": "hasta", "por_defecto": "2026-10-27"}}})
    monkeypatch.setattr(redactor, "_cliente", lambda: modelo)
    r = redactor.proponer_acceso("erp", "¿Cuántas ventas hoy?")
    assert r["propuesta"]["id"] == "ventas_por_periodo"
    assert r["resultado"] == [{"ventas": 12}] and r["error"] is None
    assert base[-1][1] == {"desde": "2026-10-26", "hasta": "2026-10-27"}
    assert accesos.listar("erp") == []


def test_una_propuesta_invalida_devuelve_el_motivo(base, monkeypatch):
    modelo = _Modelo({"id": "borra", "descripcion": "x", "sql": "delete from t", "parametros": {}})
    monkeypatch.setattr(redactor, "_cliente", lambda: modelo)
    r = redactor.proponer_acceso("erp", "borra todo")
    assert r["resultado"] is None and "solo lectura" in r["error"]


def test_la_correccion_viaja_al_modelo(base, monkeypatch):
    modelo = _Modelo({"id": "x_y", "descripcion": "d", "sql": "select 1 as n", "parametros": {}})
    monkeypatch.setattr(redactor, "_cliente", lambda: modelo)
    redactor.proponer_acceso("erp", "p", correccion="solo las no anuladas", anterior={"sql": "select 2"})
    assert "solo las no anuladas" in modelo.pedidos[0]["input"] and "select 2" in modelo.pedidos[0]["input"]
```

- [ ] **Step 2: Correr** → FAIL (`cannot import name 'redactor'`).

- [ ] **Step 3: Crear `backend/redactor.py`**

```python
"""Borradores con IA para el super admin: diccionario de una tabla y accesos directos.

Nada de aca guarda: devuelve propuestas que la persona revisa y aprueba en la
interfaz. Usa el mismo modelo de Jarvis; el gasto queda en el consumo de quien pide.
"""

import json
import os

from . import accesos, cerebro, fuentes

DIALECTO = {"mssql": "SQL Server (TOP N, nunca LIMIT)", "postgres": "PostgreSQL (LIMIT N, nunca TOP)"}


def _cliente():
    return cerebro.cliente()


def _modelo() -> str:
    return os.getenv("OPENAI_MODEL", "gpt-5.6-terra")


def _pedir(instrucciones: str, entrada: str, usuario=None) -> dict:
    respuesta = _cliente().responses.create(
        model=_modelo(), instructions=instrucciones, input=entrada,
        text={"format": {"type": "json_object"}},
    )
    cerebro.anotar_consumo(_modelo(), getattr(respuesta, "usage", None), usuario)
    return json.loads(respuesta.output_text or "{}")


def _tabla(id_fuente: str, tabla: str) -> dict:
    for entrada in fuentes.esquema_de(id_fuente)["tablas"]:
        if entrada["tabla"] == tabla:
            return entrada
    raise ValueError(f"No existe la tabla '{tabla}' en esa fuente.")


def _muestra(id_fuente: str, tabla: str) -> list[dict]:
    fuente = fuentes.obtener(id_fuente)
    sql = (f"select top 5 * from {tabla}" if fuente["tipo"] == "mssql" else f"select * from {tabla} limit 5")
    try:
        return fuentes.consultar(id_fuente, sql, 5)
    except Exception:  # noqa: BLE001 - sin muestra el borrador sale igual, solo menos preciso
        return []


def proponer_diccionario(id_fuente: str, tabla: str, usuario=None) -> dict:
    entrada = _tabla(id_fuente, tabla)
    filas = _muestra(id_fuente, tabla)
    datos = _pedir(
        "Documentas tablas de una base de datos de empresa para un asistente que responde preguntas "
        "de negocio. Devuelve JSON con: leyenda (una frase corta: que contiene la tabla), columnas "
        "(objeto columna -> significado, solo las columnas que no se entienden por el nombre o cuyos "
        "valores son codigos, p. ej. Estado: 'A' = activo) y reglas (texto: como se cuentan o filtran "
        "cosas habituales, p. ej. 'un cliente activo es Estado = A'). En espanol. No inventes: si no "
        "se deduce de las columnas y las filas de ejemplo, no lo pongas.",
        f"Tabla: {tabla}\nColumnas: {entrada['columnas']}\n"
        f"Filas de ejemplo:\n{json.dumps(filas, ensure_ascii=False, default=str)[:4000]}",
        usuario,
    )
    columnas = datos.get("columnas") if isinstance(datos.get("columnas"), dict) else {}
    return {"leyenda": str(datos.get("leyenda") or "").strip(),
            "columnas": {str(k): str(v).strip() for k, v in columnas.items() if str(v).strip()},
            "reglas": str(datos.get("reglas") or "").strip()}


def proponer_acceso(id_fuente: str, pregunta: str, correccion: str = "", anterior: dict | None = None,
                    usuario=None) -> dict:
    """{'propuesta': {...}, 'resultado': filas|None, 'error': texto|None}"""
    fuente = fuentes.obtener(id_fuente)
    if fuente is None:
        raise ValueError(f"No existe la fuente '{id_fuente}'.")
    contexto = fuentes.resumen_de(id_fuente)
    pedido = f"Pregunta: {pregunta}\n\nEsquema y diccionario de la fuente:\n{contexto}"
    if anterior:
        pedido += f"\n\nPropuesta anterior:\n{json.dumps(anterior, ensure_ascii=False)}"
    if correccion:
        pedido += f"\n\nCorreccion pedida: {correccion}"
    propuesta = _pedir(
        "Conviertes una pregunta de negocio en una consulta SQL reutilizable de solo lectura para "
        f"{DIALECTO.get(fuente['tipo'], fuente['tipo'])}. Devuelve JSON con: id (nombre corto en "
        "minusculas con guiones bajos que describa la pregunta general, p. ej. ventas_por_periodo), "
        "descripcion (que responde, en una o dos frases: la lee un asistente para elegirla), sql (usa "
        "variables %(nombre)s para fechas, cantidades y textos que cambian; para periodos usa desde "
        "incluida y hasta excluida) y parametros (objeto nombre -> {tipo: fecha|entero|texto, "
        "descripcion, por_defecto}; las fechas por defecto son las de hoy, AAAA-MM-DD). Usa solo "
        "tablas y columnas del esquema y respeta el diccionario y sus reglas.",
        pedido, usuario,
    )
    propuesta["pregunta"] = pregunta
    try:
        limpio = accesos.validar(propuesta)
        valores = {n: accesos.valor(s, s.get("por_defecto")) for n, s in limpio["parametros"].items()}
        filas = fuentes.consultar(id_fuente, limpio["sql"], 50, parametros=valores or None)
        return {"propuesta": limpio, "resultado": filas, "error": None}
    except accesos.ErrorDeAcceso as error:
        return {"propuesta": propuesta, "resultado": None, "error": str(error)}
    except Exception as error:  # noqa: BLE001 - el error de la base se muestra para corregir
        return {"propuesta": propuesta, "resultado": None, "error": fuentes.explicar(error)}
```

`fuentes.resumen_de(id_fuente)` no existe: agregarlo en `backend/fuentes.py`, sacando el armado por fuente de `resumen_para_prompt` a una función reutilizable:

```python
def resumen_de(id_fuente: str) -> str:
    """El bloque de una sola fuente tal como lo ve el modelo (esquema activo + diccionario)."""
    fuente = obtener(id_fuente)
    if fuente is None:
        return ""
    return _bloque_de_fuente(fuente)
```

y en `resumen_para_prompt` reemplazar el cuerpo del `for fuente in lista:` por `bloques.append(_bloque_de_fuente(fuente))`, moviendo ese cuerpo (cabecera, esquema, `con_leyenda`, `diccionario`, `detalle`) a `def _bloque_de_fuente(fuente: dict) -> str` que **devuelve** el bloque en vez de hacer `append` (los `continue` pasan a ser `return cabecera`).

- [ ] **Step 4: Correr** `tests/test_redactor.py` y la suite completa (incluido `test_diccionario.py::test_el_prompt_lleva_columnas_y_reglas`) → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/redactor.py backend/fuentes.py tests/test_redactor.py
git commit -m "Redactor con IA: borradores del diccionario y de accesos directos, probados antes de guardar"
```

---

### Task 8: Rutas de la API

**Files:**
- Modify: `backend/acceso.py` (`exige_admin`), `backend/main.py`
- Test: `tests/test_accesos.py`

- [ ] **Step 1: Pruebas que fallan**

```python
def test_rutas_de_accesos_solo_admin(motor, monkeypatch):
    from fastapi.testclient import TestClient

    from backend import cuentas
    from backend.main import app

    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setenv("JARVIS_CLAVE_SECRETA", "clave-de-pruebas-larga")
    admin = TestClient(app)
    admin.post("/acceso", data={"clave": "la-del-admin"}, follow_redirects=False)
    r = admin.post("/api/fuentes/erp/accesos", json=VENTAS)
    assert r.status_code == 200 and r.json()["id"] == "ventas_por_periodo"
    assert [a["id"] for a in admin.get("/api/fuentes/erp/accesos").json()["accesos"]] == ["ventas_por_periodo"]
    assert admin.post("/api/accesos/ventas_por_periodo/probar", json={"parametros": {}}).json()["filas"] == [{"n": 1}]
    assert admin.put("/api/accesos/ventas_por_periodo", json={"activo": False}).status_code == 200
    assert admin.post("/api/fuentes/erp/accesos", json={**VENTAS, "sql": "drop table x"}).status_code == 400

    cuentas.crear_organizacion("JH", "Ana", "ana@jh.com", "una-clave-larga")
    ana = TestClient(app)
    ana.post("/acceso/cuenta", data={"email": "ana@jh.com", "password": "una-clave-larga"}, follow_redirects=False)
    assert ana.get("/api/fuentes/erp/accesos").status_code == 403
    assert ana.delete("/api/accesos/ventas_por_periodo").status_code == 403
    assert admin.delete("/api/accesos/ventas_por_periodo").json() == {"ok": True}
```

- [ ] **Step 2: Correr** → FAIL (404).

- [ ] **Step 3: `exige_admin`** (`/api/fuentes` ya exige admin): agregar

```python
    if ruta.startswith("/api/accesos"):
        return True
```

- [ ] **Step 4: Rutas en `backend/main.py`** (antes del `app.mount`; agregar `accesos` y `redactor` al import de módulos)

```python
@app.get("/api/fuentes/{id_fuente}/accesos")
def listar_accesos(id_fuente: str):
    return {"accesos": accesos.listar(id_fuente)}


@app.post("/api/fuentes/{id_fuente}/accesos")
def guardar_acceso(id_fuente: str, datos: dict):
    if fuentes.obtener(id_fuente) is None:
        return JSONResponse(status_code=404, content={"error": "No existe esa fuente."})
    try:
        return accesos.guardar(id_fuente, datos)
    except accesos.ErrorDeAcceso as error:
        return JSONResponse(status_code=400, content={"error": str(error)})


@app.post("/api/fuentes/{id_fuente}/accesos/proponer")
def proponer_acceso(id_fuente: str, datos: dict, peticion: Request):
    try:
        return redactor.proponer_acceso(id_fuente, str(datos.get("pregunta") or ""),
                                        str(datos.get("correccion") or ""), datos.get("anterior"),
                                        peticion.state.usuario)
    except ValueError as error:
        return JSONResponse(status_code=400, content={"error": str(error)})


@app.post("/api/fuentes/{id_fuente}/tablas/{tabla}/proponer")
def proponer_diccionario(id_fuente: str, tabla: str, peticion: Request):
    try:
        return redactor.proponer_diccionario(id_fuente, tabla, peticion.state.usuario)
    except ValueError as error:
        return JSONResponse(status_code=400, content={"error": str(error)})


@app.put("/api/accesos/{id_acceso}")
def editar_acceso(id_acceso: str, datos: dict):
    actual = accesos.obtener(id_acceso)
    if actual is None:
        return JSONResponse(status_code=404, content={"error": "No existe ese acceso directo."})
    if "activo" in datos and len(datos) == 1:
        accesos.activar(id_acceso, bool(datos["activo"]))
        return accesos.obtener(id_acceso)
    try:
        if datos.get("id", id_acceso) != id_acceso:
            accesos.borrar(id_acceso)
        return accesos.guardar(actual["fuente_id"], {**actual, **datos})
    except accesos.ErrorDeAcceso as error:
        return JSONResponse(status_code=400, content={"error": str(error)})


@app.post("/api/accesos/{id_acceso}/probar")
def probar_acceso(id_acceso: str, datos: dict):
    return accesos.ejecutar(id_acceso, datos.get("parametros") or {}, limite=50)


@app.delete("/api/accesos/{id_acceso}")
def borrar_acceso(id_acceso: str):
    return {"ok": accesos.borrar(id_acceso)}
```

En la prueba, `accesos.ejecutar` cachea: `probar` vuelve con las filas del motor de mentira.

- [ ] **Step 5: Correr** → PASS, suite completa.

- [ ] **Step 6: Commit**

```bash
git add backend/acceso.py backend/main.py tests/test_accesos.py
git commit -m "API de accesos directos y de borradores con IA (solo super admin)"
```

---

### Task 9: Web — diccionario en el panel de tablas

**Files:**
- Modify: `web/fuentes.js` (`verEsquema`, ~300-427), `web/style.css`

- [ ] **Step 1: Guardar el diccionario junto con lo demás**

En `guardarTablas`, cada tabla manda también su diccionario:

```js
      tablas[c.tabla] = {
        activa: c.check.checked,
        leyenda: c.leyenda.value.trim(),
        columnas: c.columnas(),
        reglas: c.reglas.value.trim(),
      };
```

- [ ] **Step 2: Bloque "Diccionario" por tabla**

Dentro del `for (const tabla of datos.tablas)`, después de crear `leyenda` y antes de `fila.append(...)`:

```js
    const dicc = document.createElement("details");
    dicc.className = "diccionario";
    const tieneAlgo = Object.keys(tabla.columnas_significado || {}).length || tabla.reglas;
    dicc.innerHTML = `<summary>Diccionario${tieneAlgo ? " ✓" : ""}</summary>`;

    const nombresColumnas = String(tabla.columnas).split(",").map((c) => c.trim().split(" ")[0]).filter(Boolean);
    const filasCol = document.createElement("div");
    filasCol.className = "diccionario-columnas";
    const camposCol = {};
    for (const col of nombresColumnas) {
      const etiqueta = document.createElement("label");
      etiqueta.textContent = col;
      const campo = document.createElement("input");
      campo.type = "text";
      campo.placeholder = "Qué significa (opcional)";
      campo.value = (tabla.columnas_significado || {})[col] || "";
      campo.addEventListener("input", guardarPronto);
      campo.addEventListener("blur", guardarTablas);
      camposCol[col] = campo;
      filasCol.append(etiqueta, campo);
    }

    const reglas = document.createElement("textarea");
    reglas.rows = 3;
    reglas.placeholder = "Reglas: cómo se cuenta o filtra (ej. un cliente activo es Estado = 'A')";
    reglas.value = tabla.reglas || "";
    reglas.addEventListener("input", guardarPronto);
    reglas.addEventListener("blur", guardarTablas);

    const proponer = boton("Proponer con IA", async () => {
      proponer.disabled = true;
      proponer.textContent = "Pensando…";
      try {
        const r = await fetch(`/api/fuentes/${id}/tablas/${encodeURIComponent(tabla.tabla)}/proponer`, { method: "POST" });
        const b = await r.json();
        if (!r.ok) throw new Error(b.error || "No se pudo proponer");
        if (!leyenda.value) leyenda.value = b.leyenda;
        for (const [col, texto] of Object.entries(b.columnas || {})) {
          if (camposCol[col] && !camposCol[col].value) camposCol[col].value = texto;
        }
        if (!reglas.value) reglas.value = b.reglas;
        estado.textContent = " · borrador de la IA: revisalo; se guarda al salir de un campo";
      } catch (e) {
        estado.textContent = " · " + e.message;
      } finally {
        proponer.disabled = false;
        proponer.textContent = "Proponer con IA";
      }
    });

    dicc.append(proponer, filasCol, reglas);
```

y cambiar `fila.append(cab, leyenda, columnas);` por `fila.append(cab, leyenda, dicc, columnas);` y el `controles.push(...)` por:

```js
    controles.push({
      tabla: tabla.tabla, check, leyenda, reglas,
      columnas: () => Object.fromEntries(
        Object.entries(camposCol).map(([c, campo]) => [c, campo.value.trim()]).filter(([, v]) => v)),
    });
```

El borrador **no se guarda solo**: completa los campos vacíos y se guarda cuando la persona sale de un campo (como la leyenda hoy).

- [ ] **Step 3: Estilos** (al final de `web/style.css`)

```css
.diccionario { margin: 4px 0 6px; font-size: 13px; }
.diccionario summary { cursor: pointer; color: var(--tenue); }
.diccionario-columnas { display: grid; grid-template-columns: max-content 1fr; gap: 4px 8px; margin: 8px 0; align-items: center; }
.diccionario-columnas label { font-family: ui-monospace, monospace; font-size: 12px; color: var(--tenue); }
.diccionario input, .diccionario textarea { width: 100%; box-sizing: border-box; background: var(--fondo);
  color: var(--texto); border: 1px solid var(--borde); border-radius: 6px; padding: 6px 8px; font: inherit; }
```

- [ ] **Step 4: Probar a mano** con la fuente del ERP de JH en el servidor (Task 11): abrir Fuentes → Tablas → una vista → Diccionario → "Proponer con IA" → aparecen borradores → salir de un campo → "guardado ✓" → recargar el panel y siguen ahí.

- [ ] **Step 5: Commit**

```bash
git add web/fuentes.js web/style.css
git commit -m "Web: diccionario por tabla (columnas y reglas) con borrador de la IA"
```

---

### Task 10: Web — pantalla de accesos directos

**Files:**
- Modify: `web/fuentes.js` (`tarjetaDeFuente`, funciones nuevas), `web/style.css`

- [ ] **Step 1: Botón en cada fuente**

En `tarjetaDeFuente`, en `acciones.append(...)`, después de "Tablas":

```js
    boton("Accesos directos", () => verAccesos(fuente, estado)),
```

(no se muestra para fuentes `supabase`: `fuente.tipo === "supabase" ? null : boton(...)`, filtrando `null` antes del `append`.)

- [ ] **Step 2: Funciones nuevas en `web/fuentes.js`**

```js
// --------------------------------------------------------------------------
// Accesos directos
// --------------------------------------------------------------------------

async function pedirJson(url, opciones = {}) {
  const r = await fetch(url, { headers: { "Content-Type": "application/json" }, ...opciones });
  const datos = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(datos.error || `Error ${r.status}`);
  return datos;
}

async function verAccesos(fuente, nodo) {
  nodo.className = "fuente-estado";
  nodo.innerHTML = "";
  const caja = document.createElement("div");
  caja.className = "accesos";
  caja.innerHTML = `
    <h4>Accesos directos</h4>
    <p class="esquema-ayuda">Escribí una pregunta frecuente. Jarvis arma la consulta, la prueba y te muestra el resultado. Si está bien, guardala.</p>
    <div class="acceso-nuevo">
      <input type="text" class="acceso-pregunta" placeholder="Ej.: ¿Cuántas ventas se hicieron hoy?">
      <button class="boton-texto acceso-proponer">Proponer</button>
    </div>
    <div class="acceso-borrador"></div>
    <div class="acceso-lista"></div>`;
  nodo.appendChild(caja);
  const pregunta = caja.querySelector(".acceso-pregunta");
  const borrador = caja.querySelector(".acceso-borrador");
  caja.querySelector(".acceso-proponer").onclick = () => proponerAcceso(fuente, pregunta.value, borrador, caja);
  await listarAccesos(fuente, caja);
}

async function listarAccesos(fuente, caja) {
  const lista = caja.querySelector(".acceso-lista");
  const { accesos } = await pedirJson(`/api/fuentes/${fuente.id}/accesos`);
  lista.innerHTML = accesos.length ? "" : '<p class="vacio">Todavía no hay accesos directos.</p>';
  for (const a of accesos) {
    const fila = document.createElement("div");
    fila.className = "acceso" + (a.activo ? "" : " apagado");
    const vars = Object.keys(a.parametros).join(", ");
    fila.innerHTML = `<strong></strong> <code></code><p></p>`;
    fila.querySelector("strong").textContent = a.id;
    fila.querySelector("code").textContent = vars ? `(${vars})` : "";
    fila.querySelector("p").textContent = a.descripcion + (a.ultimo_error ? ` — con error: ${a.ultimo_error}` : "");
    if (a.ultimo_error) fila.classList.add("con-error");
    const salida = document.createElement("div");
    fila.append(
      boton("Probar", async () => {
        const valores = {};
        for (const [n, s] of Object.entries(a.parametros)) {
          const v = prompt(`${n} (${s.tipo}) — ${s.descripcion || ""}`, s.por_defecto ?? "");
          if (v === null) return;
          valores[n] = v;
        }
        const r = await pedirJson(`/api/accesos/${a.id}/probar`, { method: "POST", body: JSON.stringify({ parametros: valores }) });
        salida.innerHTML = "";
        salida.appendChild(r.error ? Object.assign(document.createElement("p"), { className: "mal", textContent: r.error }) : tabla(r.filas));
      }),
      // Editar: la IA la rehace partiendo de la guardada; despues se puede tocar la consulta a mano y guardar.
      boton("Editar", () => proponerAcceso(fuente, a.pregunta || a.descripcion, caja.querySelector(".acceso-borrador"), caja,
        "Mantene el mismo nombre y la misma idea; mejorala solo si hace falta.", a)),
      boton(a.activo ? "Desactivar" : "Activar", async () => {
        await pedirJson(`/api/accesos/${a.id}`, { method: "PUT", body: JSON.stringify({ activo: !a.activo }) });
        listarAccesos(fuente, caja);
      }),
      boton("Borrar", async () => {
        if (!confirm(`Borrar el acceso directo ${a.id}?`)) return;
        await pedirJson(`/api/accesos/${a.id}`, { method: "DELETE" });
        listarAccesos(fuente, caja);
      }, "peligro"),
      salida,
    );
    lista.appendChild(fila);
  }
}

async function proponerAcceso(fuente, pregunta, borrador, caja, correccion = "", anterior = null) {
  if (!pregunta.trim()) return;
  borrador.innerHTML = '<p class="vacio">Pensando la consulta…</p>';
  let r;
  try {
    r = await pedirJson(`/api/fuentes/${fuente.id}/accesos/proponer`, {
      method: "POST", body: JSON.stringify({ pregunta, correccion, anterior }),
    });
  } catch (e) {
    borrador.innerHTML = "";
    borrador.appendChild(Object.assign(document.createElement("p"), { className: "mal", textContent: e.message }));
    return;
  }
  const p = r.propuesta;
  borrador.innerHTML = `
    <div class="acceso-propuesta">
      <label>Nombre <input class="ap-id"></label>
      <label>Qué responde <textarea class="ap-desc" rows="2"></textarea></label>
      <label>Consulta <textarea class="ap-sql" rows="5" spellcheck="false"></textarea></label>
      <p class="ap-vars"></p>
      <div class="ap-resultado"></div>
      <div class="ap-acciones">
        <input class="ap-correccion" placeholder="¿Algo para corregir? Ej.: solo las facturas no anuladas">
        <button class="boton-texto ap-rehacer">Rehacer</button>
        <button class="boton-texto ap-guardar">Guardar</button>
      </div>
    </div>`;
  borrador.querySelector(".ap-id").value = p.id || "";
  borrador.querySelector(".ap-desc").value = p.descripcion || "";
  borrador.querySelector(".ap-sql").value = p.sql || "";
  const vars = Object.entries(p.parametros || {}).map(([n, s]) => `${n} (${s.tipo}, ej. ${s.por_defecto})`).join(" · ");
  borrador.querySelector(".ap-vars").textContent = vars ? `Variables: ${vars}` : "Sin variables";
  const res = borrador.querySelector(".ap-resultado");
  res.appendChild(r.error
    ? Object.assign(document.createElement("p"), { className: "mal", textContent: r.error })
    : tabla(r.resultado));
  borrador.querySelector(".ap-rehacer").onclick = () => proponerAcceso(
    fuente, pregunta, borrador, caja, borrador.querySelector(".ap-correccion").value, p);
  const guardar = borrador.querySelector(".ap-guardar");
  guardar.disabled = Boolean(r.error);
  guardar.onclick = async () => {
    try {
      await pedirJson(`/api/fuentes/${fuente.id}/accesos`, { method: "POST", body: JSON.stringify({
        ...p, id: borrador.querySelector(".ap-id").value.trim(),
        descripcion: borrador.querySelector(".ap-desc").value.trim(),
        sql: borrador.querySelector(".ap-sql").value.trim(), pregunta,
      }) });
      borrador.innerHTML = '<p class="bien">Guardado. Jarvis ya lo usa.</p>';
      listarAccesos(fuente, caja);
    } catch (e) {
      res.prepend(Object.assign(document.createElement("p"), { className: "mal", textContent: e.message }));
    }
  };
}
```

(`tabla(filas)` ya existe en `fuentes.js`: es la que pinta los resultados de la consola SQL.)

- [ ] **Step 3: Estilos** (al final de `web/style.css`)

```css
.accesos h4 { margin: 8px 0 4px; }
.acceso-nuevo { display: flex; gap: 8px; margin: 8px 0; }
.acceso-nuevo input { flex: 1; }
.acceso-propuesta { display: grid; gap: 8px; background: var(--panel); border: 1px solid var(--borde);
  border-radius: 10px; padding: 10px; margin: 8px 0; }
.acceso-propuesta label { display: grid; gap: 4px; font-size: 13px; color: var(--tenue); }
.acceso-propuesta textarea, .acceso-propuesta input, .acceso-nuevo input { background: var(--fondo); color: var(--texto);
  border: 1px solid var(--borde); border-radius: 6px; padding: 6px 8px; font: inherit; }
.ap-sql { font-family: ui-monospace, monospace; font-size: 12px; }
.ap-acciones { display: flex; gap: 8px; }
.ap-acciones input { flex: 1; }
.acceso { border-top: 1px solid var(--borde); padding: 8px 0; font-size: 13px; }
.acceso p { margin: 4px 0; color: var(--tenue); }
.acceso.apagado { opacity: 0.55; }
.acceso.con-error p { color: var(--peligro); }
```

- [ ] **Step 4: Probar a mano** (Task 11).

- [ ] **Step 5: Commit**

```bash
git add web/fuentes.js web/style.css
git commit -m "Web: accesos directos por fuente (proponer con IA, probar, guardar, desactivar, borrar)"
```

---

### Task 11: Puente de los lentes y despliegue

**Files:**
- Modify: `C:\Users\Jorge\jarvis-puentes\puente-android\src\gemini.js`, `...\puente-reloj\src\gemini.js`
- Test: `puente-*/test/nombre.test.js` (agregar)

- [ ] **Step 1: Prueba que falla** (en los dos `test/nombre.test.js`)

```js
test("el prompt de voz conserva los accesos directos", () => {
  const p = construirPromptVoz(
    "Eres Nebo, el asistente personal de Ana.\n- acceso ventas_por_periodo(desde, hasta) [fuente erp]: Ventas entre dos fechas.\n");
  assert.match(p, /- acceso ventas_por_periodo\(desde, hasta\) \[fuente erp\]: Ventas entre dos fechas\./);
});
```

- [ ] **Step 2: Correr** (`node --test test/nombre.test.js`) → FAIL.

- [ ] **Step 3: En `construirPromptVoz`**, dentro del `for (const cruda of texto.split("\n"))`, antes del `if (/^- id "/...)`:

```js
    if (/^- acceso /.test(l.trim())) {
      accesosDirectos.push(l.trim()); // preguntas frecuentes ya resueltas (usar_acceso_directo)
      continue;
    }
```

con `const accesosDirectos = [];` antes del `for`, y en el texto devuelto, después del bloque de fuentes:

```js
${accesosDirectos.length ? `\nAccesos directos (preguntas frecuentes ya resueltas: si la pregunta encaja, usa usar_acceso_directo antes de escribir SQL):\n${accesosDirectos.join("\n")}\n` : ""}
```

- [ ] **Step 4: Correr** las pruebas de los dos puentes → PASS. Commit y push en `jarvis-puentes`:

```bash
git add puente-reloj puente-android
git commit -m "Voz: el prompt de Gemini conserva los accesos directos de Jarvis"
git push
```

- [ ] **Step 5: Desplegar Jarvis**

```bash
cd /c/Users/Jorge/jarvis
git checkout feat/avatar-holograma && git merge --no-edit feat/accesos-directos
.venv/Scripts/python.exe -m pytest -q
git archive HEAD backend web requirements.txt Procfile | ssh ec2 'sudo sh -c "cd /opt/jarvis/jarvis && rm -rf backend web && tar xf - && cd .. && docker compose build -q jarvis && docker builder prune -af >/dev/null && docker compose up -d jarvis"'
curl -s https://asistente.neboaiconsulting.com/api/salud
```

Y los puentes: `tar czf - -C <puente> src | ssh ec2 "sudo sh -c 'cd /opt/jarvis/<puente> && rm -rf src && tar xzf -'"` para cada uno y `docker compose build -q puente-reloj puente-android && docker compose up -d puente-reloj puente-android`.

- [ ] **Step 6: Prueba real con el ERP de JH**

En `https://asistente.neboaiconsulting.com` como super admin: Fuentes → ERP de JH → Tablas → "Proponer con IA" en `List_ClientesIA`, `List_OrdenVentasIA`, `List_ProductosIA` (revisar y corregir). Después Accesos directos → crear: "¿cuántos clientes activos tenemos?", "¿cuántas ventas se hicieron hoy?", "¿quién es el vendedor que más ha vendido este mes?", "¿cuál es el producto con menos inventario?". En el chat, preguntar esas cuatro cosas y variantes ("ventas de ayer"): debe responder usando `usar_acceso_directo` (se ve en el consumo/log como una sola herramienta, sin SQL a mano).

- [ ] **Step 7: Mergear `feat/accesos-directos` a `main`** y anotar en memoria.
