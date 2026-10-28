# Recotizar desde una cotización existente — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que Jarvis pueda buscar la última cotización emitida de un cliente (por JV, código, RNC, nombre o teléfono) y re-cotizar sus mismos productos a un nivel de precio elegido (Pn sin factor, con utilidad opcional), emitiendo una JV nueva.

**Architecture:** Dos herramientas nuevas en `backend/herramientas.py` (`buscar_cotizacion`, `recotizar`) sobre dos funciones nuevas en `backend/cotizaciones.py`. Se reusa el mecanismo de `Borrador`/`emitir` actual sin tocarlo: `recotizar` deja un `Borrador` en el estado existente y `emitir_cotizacion` lo emite igual que hoy. Se agrega un estado por usuario `_encontradas` (espejo de `_borradores`) para recordar la cotización hallada entre una llamada y la otra.

**Tech Stack:** Python, FastAPI, httpx, Supabase REST (PostgREST), pytest.

**Spec:** `docs/superpowers/specs/2026-10-28-recotizar-desde-cotizacion-design.md`

---

## Nota de pruebas

Las pruebas **no tocan Supabase ni la Base JH reales**: todo se mockea
(`_consultar`, `_filas_emitidas`, y los servicios de emisión). En esta Windows
no hay Python local; correlas donde esté el entorno del proyecto (un venv con
`httpx`/`fastapi`/`pytest`, o dentro del contenedor). Comando base:

```bash
python -m pytest tests/test_cotizaciones.py -v
```

## Estructura de archivos

- **Modificar** `backend/cotizaciones.py`: `calcular_linea` (nuevo modo
  nivel-elegido + utilidad), `_leer_utilidad` (extraído), estado `Encontrada` /
  `_encontradas` / `encontrada_de`, helpers `_filas_emitidas`, `_normalizar_jv`,
  `_fecha_corta`, y funciones `buscar` y `recotizar`.
- **Modificar** `backend/herramientas.py`: tools `buscar_cotizacion` y
  `recotizar`.
- **Modificar** `tests/test_cotizaciones.py`: fixtures y pruebas nuevas; ampliar
  `test_sin_configurar_no_se_ofrecen`.
- **Modificar** `README.md`: documentar las dos herramientas en la sección de
  cotizaciones.

---

## Task 1: `calcular_linea` admite nivel elegido con utilidad

**Files:**
- Modify: `backend/cotizaciones.py` (función `calcular_linea`, ~línea 369)
- Test: `tests/test_cotizaciones.py`

- [ ] **Step 1: Escribir la prueba que falla**

Agregar al final de `tests/test_cotizaciones.py` (usa el catálogo mockeado):

```python
def test_calcular_linea_nivel_elegido_sin_factor_con_utilidad(catalogo):
    fila = PRODUCTOS["9681"]
    # P7 pelado, sin factor: 11.5 tal cual
    linea = cotizaciones.calcular_linea(fila, 100, "P7", 1.0)
    assert linea["precio_unitario"] == 11.5
    # P5 (12.5) con 6% de utilidad: 12.5 / (1 - 0.06) = 13.2978 -> 13.30
    con_util = cotizaciones.calcular_linea(fila, 100, "P5", 1.0, utilidad_nivel=6)
    assert con_util["precio_unitario"] == 13.30
```

- [ ] **Step 2: Correr la prueba y verla fallar**

Run: `python -m pytest tests/test_cotizaciones.py::test_calcular_linea_nivel_elegido_sin_factor_con_utilidad -v`
Expected: FAIL con `TypeError: calcular_linea() got an unexpected keyword argument 'utilidad_nivel'`.

- [ ] **Step 3: Implementar el cambio mínimo**

En `backend/cotizaciones.py`, cambiar la firma y el bloque de precio de
`calcular_linea`. La firma pasa de:

```python
def calcular_linea(fila: dict, cantidad: float, nivel: str, factor: float,
                   coste: dict | None = None) -> dict:
```

a:

```python
def calcular_linea(fila: dict, cantidad: float, nivel: str, factor: float,
                   coste: dict | None = None, utilidad_nivel: float = 0.0) -> dict:
```

Y el bloque:

```python
    if coste is None:
        precio = round(float(fila.get(nivel) or 0) * factor, 2)
        base = 0.0
```

pasa a:

```python
    if coste is None:
        # Precio del nivel. Con utilidad_nivel (recotizar a un nivel elegido) se
        # le aplica el mismo margen que al coste: PV = base / (1 - %/100).
        precio = round(float(fila.get(nivel) or 0) * factor, 2)
        if utilidad_nivel:
            precio = round(precio / (1 - utilidad_nivel / 100), 2)
        base = 0.0
```

- [ ] **Step 4: Correr la prueba y verla pasar**

Run: `python -m pytest tests/test_cotizaciones.py::test_calcular_linea_nivel_elegido_sin_factor_con_utilidad -v`
Expected: PASS.

- [ ] **Step 5: Verificar que no rompí las pruebas de precios existentes**

Run: `python -m pytest tests/test_cotizaciones.py -k "precio or nivel or coste" -v`
Expected: PASS (el default `utilidad_nivel=0.0` no cambia nada de lo de antes).

- [ ] **Step 6: Commit**

```bash
git add backend/cotizaciones.py tests/test_cotizaciones.py
git commit -m "Cotizaciones: calcular_linea admite un nivel elegido con utilidad"
```

---

## Task 2: `_leer_utilidad` extraído y reusado

**Files:**
- Modify: `backend/cotizaciones.py` (`_leer_coste`, ~línea 427)
- Test: `tests/test_cotizaciones.py`

Esto deja una sola validación del porcentaje (0..MAX_UTILIDAD) para reusar en
`recotizar`.

- [ ] **Step 1: Escribir la prueba que falla**

```python
def test_leer_utilidad_valida_el_rango():
    assert cotizaciones._leer_utilidad("6") == 6.0
    assert cotizaciones._leer_utilidad("") == 0.0
    with pytest.raises(cotizaciones.ErrorCotizacion):
        cotizaciones._leer_utilidad("99")      # > MAX_UTILIDAD
    with pytest.raises(cotizaciones.ErrorCotizacion):
        cotizaciones._leer_utilidad("abc")
```

- [ ] **Step 2: Correr y ver fallar**

Run: `python -m pytest tests/test_cotizaciones.py::test_leer_utilidad_valida_el_rango -v`
Expected: FAIL con `AttributeError: module ... has no attribute '_leer_utilidad'`.

- [ ] **Step 3: Implementar**

En `backend/cotizaciones.py`, justo antes de `_leer_coste`, agregar:

```python
def _leer_utilidad(utilidad) -> float:
    """El porcentaje de utilidad, validado. Es la parte del precio de venta."""
    try:
        por_ciento = float(utilidad or 0)
    except (TypeError, ValueError):
        raise ErrorCotizacion(f"El porcentaje de utilidad no es un numero: '{utilidad}'.") from None
    if not 0 <= por_ciento <= MAX_UTILIDAD:
        raise ErrorCotizacion(
            f"El porcentaje de utilidad tiene que estar entre 0 y {MAX_UTILIDAD:g}. "
            "Es la parte del precio de venta, no lo que se le suma al coste."
        )
    return por_ciento
```

Y reescribir `_leer_coste` para que lo use:

```python
def _leer_coste(columna: str, utilidad) -> dict | None:
    """Los datos para cotizar desde el coste, o None para usar los niveles."""
    if not (columna or "").strip():
        return None
    return {"columna": columna.strip(), "utilidad": _leer_utilidad(utilidad)}
```

- [ ] **Step 4: Correr y ver pasar (incluidas las de coste)**

Run: `python -m pytest tests/test_cotizaciones.py -k "utilidad or coste" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/cotizaciones.py tests/test_cotizaciones.py
git commit -m "Cotizaciones: una sola validacion del porcentaje de utilidad"
```

---

## Task 3: Estado de la cotización encontrada

**Files:**
- Modify: `backend/cotizaciones.py` (junto a `Borrador`/`_borradores`, ~línea 246)
- Test: `tests/test_cotizaciones.py`

- [ ] **Step 1: Escribir la prueba que falla**

```python
def test_encontrada_se_guarda_y_vence(catalogo):
    cotizaciones._encontradas.clear()
    cotizaciones._encontradas["admin"] = cotizaciones.Encontrada(
        cliente={"nombre": "X"}, productos=[], numero="JV-00007", total=10.0,
    )
    assert cotizaciones.encontrada_de("admin").numero == "JV-00007"
    cotizaciones._encontradas["admin"].creado -= cotizaciones.VIGENCIA_BORRADOR + 1
    assert cotizaciones.encontrada_de("admin") is None
```

- [ ] **Step 2: Correr y ver fallar**

Run: `python -m pytest tests/test_cotizaciones.py::test_encontrada_se_guarda_y_vence -v`
Expected: FAIL con `AttributeError: ... 'Encontrada'`.

- [ ] **Step 3: Implementar**

En `backend/cotizaciones.py`, justo después del bloque de `Borrador`
(después de `_borradores: dict[str, Borrador] = {}` y `_candado = threading.Lock()`),
agregar:

```python
@dataclass
class Encontrada:
    """La ultima cotizacion emitida que se busco, para recotizarla despues."""
    cliente: dict
    productos: list[dict]
    numero: str
    total: float
    creado: float = field(default_factory=time.time)


_encontradas: dict[str, Encontrada] = {}


def encontrada_de(id_usuario: str) -> Encontrada | None:
    with _candado:
        encontrada = _encontradas.get(id_usuario)
    if encontrada and time.time() - encontrada.creado > VIGENCIA_BORRADOR:
        return None
    return encontrada
```

- [ ] **Step 4: Correr y ver pasar**

Run: `python -m pytest tests/test_cotizaciones.py::test_encontrada_se_guarda_y_vence -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/cotizaciones.py tests/test_cotizaciones.py
git commit -m "Cotizaciones: estado de la cotizacion encontrada"
```

---

## Task 4: Buscar la cotización (`buscar` + tool `buscar_cotizacion`)

**Files:**
- Modify: `backend/cotizaciones.py` (helpers + `buscar`, cerca de `buscar_emitida`)
- Modify: `backend/herramientas.py` (tool `buscar_cotizacion`)
- Test: `tests/test_cotizaciones.py`

- [ ] **Step 1: Escribir las pruebas que fallan**

Agregar al final de `tests/test_cotizaciones.py`:

```python
FILA_EMITIDA = {
    "numero": 12, "creada_at": "2026-10-20T14:00:00+00:00", "total": 1150.0,
    "cliente": {"codigo": "6177", "nombre": "FERRETERIA ELIAM MAX EIRL",
                "rnc": "131832334", "nivel": "P4", "factor": 1.0},
    "productos": [{"codigo": "9681", "descripcion": "KEYARD ALAMBRE THHN #12 ROJO",
                   "unidad": "PIES", "cantidad": 100, "precio_unitario": 13.0}],
}


@pytest.fixture
def emitidas(catalogo, monkeypatch):
    cotizaciones._encontradas.clear()

    def filas(params):
        if "numero" in params:
            return [FILA_EMITIDA] if params["numero"] == "eq.12" else []
        if params.get("cliente->>codigo") == "eq.6177":
            return [FILA_EMITIDA]
        if "cliente->>nombre" in params:
            return [FILA_EMITIDA] if "ELIAM" in params["cliente->>nombre"].upper() else []
        return []

    monkeypatch.setattr(cotizaciones, "_filas_emitidas", filas)


def _buscar(consulta, usuario="admin"):
    return herramientas.ejecutar("buscar_cotizacion", json.dumps({"consulta": consulta}), usuario)


def test_busca_por_codigo_y_la_guarda(emitidas):
    texto = _buscar("6177")
    assert "JV-00012" in texto and "KEYARD" in texto
    assert cotizaciones.encontrada_de("admin").numero == "JV-00012"


def test_busca_por_numero_jv(emitidas):
    assert "JV-00012" in _buscar("la JV-12")


def test_busca_por_rnc(emitidas):
    assert "JV-00012" in _buscar("131832334")


def test_varios_clientes_pide_elegir(emitidas):
    texto = _buscar("FERRETERIA")
    assert "varios clientes" in texto.lower()
    assert cotizaciones.encontrada_de("admin") is None


def test_sin_cotizaciones_lo_dice(emitidas):
    assert "No encontr" in _buscar("4926")   # cliente existe pero sin cotizaciones
```

- [ ] **Step 2: Correr y ver fallar**

Run: `python -m pytest tests/test_cotizaciones.py -k "busca or varios_clientes or sin_cotizaciones" -v`
Expected: FAIL (`'buscar_cotizacion'` no existe / `_filas_emitidas` no existe).

- [ ] **Step 3: Implementar los helpers y `buscar`**

En `backend/cotizaciones.py`, agregar cerca de `buscar_emitida` (después de ella):

```python
_SELECT_ENCONTRADA = "numero,creada_at,cliente,productos,total"


def _filas_emitidas(params: dict) -> list[dict]:
    """Filas de jarvis_cotizaciones segun los filtros de PostgREST que se pasen."""
    respuesta = httpx.get(
        f"{_supabase()}/rest/v1/jarvis_cotizaciones",
        headers=_cabeceras(), params=params, timeout=20,
    )
    respuesta.raise_for_status()
    return respuesta.json()


def _normalizar_jv(texto: str) -> str | None:
    """"JV-12", "la jv 12" -> "JV-00012". None si no se dijo un numero JV."""
    limpio = texto.strip().upper().replace(" ", "")
    encontrado = re.search(r"JV-?(\d+)", limpio)
    return formato(int(encontrado.group(1))) if encontrado else None


def _fecha_corta(iso) -> str:
    try:
        momento = datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(ZONA)
        return fecha_de_documento(momento)
    except Exception:  # noqa: BLE001 - sin fecha legible, mejor no decir nada
        return ""


def _guardar_y_resumir(id_usuario: str, fila: dict, nota: str = "") -> str:
    cliente = fila["cliente"]
    productos = fila["productos"]
    numero = formato(int(fila["numero"]))
    with _candado:
        _encontradas[id_usuario] = Encontrada(cliente, productos, numero, float(fila["total"]))
    detalle = "; ".join(
        f"{_cantidad(float(l['cantidad']))} {l.get('unidad') or 'UND'} de "
        f"{l.get('descripcion') or l.get('codigo')} (cod {l.get('codigo')})"
        for l in productos
    )
    fecha = _fecha_corta(fila.get("creada_at"))
    return (
        f"{nota}Cotizacion {numero} de {cliente.get('nombre')}"
        + (f" ({fecha})" if fecha else "")
        + f", total RD$ {_num(float(fila['total']))}. {len(productos)} producto(s): {detalle}. "
        "Para recotizarla a otro nivel, di el nivel (P1 a P7) y, si quieres, el % de utilidad. "
        "No leas el numero completo ni los precios salvo que lo pidan."
    )


def buscar(id_usuario: str, consulta: str) -> str:
    """Encuentra la ultima cotizacion emitida para mostrarla y recordarla."""
    texto = (consulta or "").strip()
    if not texto:
        raise ErrorCotizacion("Dime de que cliente o que numero JV busco la cotizacion.")

    numero = _normalizar_jv(texto)
    if numero:
        filas = _filas_emitidas({
            "numero": f"eq.{int(numero[len(PREFIJO):])}",
            "estado": "eq.emitida", "select": _SELECT_ENCONTRADA,
        })
        if not filas:
            raise ErrorCotizacion(f"No encontre la cotizacion {numero} emitida.")
        return _guardar_y_resumir(id_usuario, filas[0])

    clientes = buscar_cliente(texto)
    if len(clientes) > 1:
        opciones = "; ".join(f"{_texto(c['nombre'])} (codigo {c['codigo']})" for c in clientes[:5])
        raise ErrorCotizacion(
            f"Hay varios clientes que coinciden: {opciones}. Dime cual es y busco su ultima cotizacion."
        )
    if clientes:
        codigo = _texto(clientes[0].get("codigo"))
        filas = _filas_emitidas({
            "cliente->>codigo": f"eq.{codigo}", "estado": "eq.emitida",
            "order": "numero.desc", "limit": "5", "select": _SELECT_ENCONTRADA,
        })
        if filas:
            nota = f"(hay {len(filas)} de este cliente; esta es la ultima) " if len(filas) > 1 else ""
            return _guardar_y_resumir(id_usuario, filas[0], nota)
        raise ErrorCotizacion(
            f"No encontre cotizaciones de {_texto(clientes[0].get('nombre'))}. "
            "Si quieres, preparo una nueva con preparar_cotizacion."
        )

    # Respaldo: por nombre dentro de las emitidas (sirve para clientes de contado).
    filas = _filas_emitidas({
        "cliente->>nombre": f"ilike.*{texto}*", "estado": "eq.emitida",
        "order": "numero.desc", "limit": "5", "select": _SELECT_ENCONTRADA,
    })
    if not filas:
        raise ErrorCotizacion(
            f"No encontre cotizaciones de '{texto}'. Si quieres, preparo una nueva con preparar_cotizacion."
        )
    nota = f"(hay {len(filas)}; esta es la ultima) " if len(filas) > 1 else ""
    return _guardar_y_resumir(id_usuario, filas[0], nota)
```

En `backend/herramientas.py`, agregar después de `emitir_cotizacion` (antes de la
sección de WhatsApp, ~línea 445):

```python
@herramienta(
    "Busca una cotizacion YA EMITIDA para mostrarla y recordarla: dale lo que diga "
    "el usuario (numero JV, codigo de cliente, RNC/cedula, nombre o telefono) y trae "
    "la ultima de ese cliente. Usala cuando pidan 'dame/busca la ultima cotizacion "
    "de ...'. No leas en voz el numero completo ni los precios salvo que lo pidan.",
    disponible=_cotizaciones_disponibles,
    consulta="Lo que dijo el usuario: numero JV (JV-00012), codigo, RNC/cedula, nombre o telefono del cliente",
)
def buscar_cotizacion(consulta: str, usuario: str = "") -> str:
    from . import cotizaciones

    try:
        return cotizaciones.buscar(usuario, consulta)
    except cotizaciones.ErrorCotizacion as error:
        return str(error)
```

- [ ] **Step 4: Correr y ver pasar**

Run: `python -m pytest tests/test_cotizaciones.py -k "busca or varios_clientes or sin_cotizaciones" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/cotizaciones.py backend/herramientas.py tests/test_cotizaciones.py
git commit -m "Cotizaciones: buscar la ultima cotizacion de un cliente"
```

---

## Task 5: Re-cotizar (`recotizar` + tool `recotizar`)

**Files:**
- Modify: `backend/cotizaciones.py` (`_normalizar_nivel` + `recotizar`)
- Modify: `backend/herramientas.py` (tool `recotizar`)
- Test: `tests/test_cotizaciones.py`

- [ ] **Step 1: Escribir las pruebas que fallan**

```python
def _recotizar(nivel, utilidad="", usuario="admin"):
    return herramientas.ejecutar(
        "recotizar", json.dumps({"nivel": nivel, "utilidad": utilidad}), usuario
    )


def test_recotizar_usa_el_nivel_sin_factor(emitidas):
    _buscar("6177")
    texto = _recotizar("7")
    borrador = cotizaciones.borrador_de("admin")
    assert borrador.lineas[0]["precio_unitario"] == 11.5     # P7 crudo, sin factor
    assert borrador.totales["total"] == 1150.0
    assert "aun NO emitido" in texto and "precio P7" in texto


def test_recotizar_con_utilidad(emitidas):
    _buscar("6177")
    _recotizar("5", "6")
    borrador = cotizaciones.borrador_de("admin")
    assert borrador.lineas[0]["precio_unitario"] == 13.30    # P5=12.5 / 0.94


def test_recotizar_sin_encontrada_lo_dice(emitidas):
    cotizaciones._encontradas.clear()
    assert "Busca" in _recotizar("7") or "busca" in _recotizar("7")


def test_recotizar_nivel_invalido(emitidas):
    _buscar("6177")
    assert "P1 a P7" in _recotizar("banana")
```

- [ ] **Step 2: Correr y ver fallar**

Run: `python -m pytest tests/test_cotizaciones.py -k "recotizar" -v`
Expected: FAIL (`'recotizar'` no existe).

- [ ] **Step 3: Implementar**

En `backend/cotizaciones.py`, agregar (después de `recotizar` no existe aún; ponlo
después de `buscar`):

```python
def _normalizar_nivel(texto: str) -> str:
    """"7", "P7", "precio 7" -> "P7". Error si no es P1..P7."""
    encontrado = re.search(r"[1-7]", str(texto or ""))
    if not encontrado:
        raise ErrorCotizacion("El nivel tiene que ser de P1 a P7. ¿A que nivel la quieres?")
    return f"P{encontrado.group(0)}"


def recotizar(id_usuario: str, nivel: str, utilidad=0) -> str:
    """Rearma un borrador con los productos de la cotizacion encontrada, al nivel pedido."""
    encontrada = encontrada_de(id_usuario)
    if encontrada is None:
        raise ErrorCotizacion(
            "No hay una cotizacion encontrada (o paso media hora). Busca primero con buscar_cotizacion."
        )
    nivel_elegido = _normalizar_nivel(nivel)
    por_ciento = _leer_utilidad(utilidad)

    pedidos = [(_texto(l["codigo"]).upper(), float(l["cantidad"])) for l in encontrada.productos]
    catalogo = productos_del_catalogo([codigo for codigo, _ in pedidos])
    faltan = [codigo for codigo, _ in pedidos if codigo not in catalogo]
    if faltan:
        raise ErrorCotizacion(
            f"Ya no estan en el catalogo: {', '.join(faltan)}. No puedo recotizar esos productos."
        )

    lineas = [
        calcular_linea(catalogo[codigo], cantidad, nivel_elegido, 1.0,
                       coste=None, utilidad_nivel=por_ciento)
        for codigo, cantidad in pedidos
    ]
    sin_precio = [l["descripcion"] or l["codigo"] for l in lineas if l["precio_unitario"] <= 0]
    if sin_precio:
        raise ErrorCotizacion(
            f"Sin precio {nivel_elegido} en el catalogo: {', '.join(sin_precio)}. "
            "No se puede cotizar asi; dilo."
        )

    totales = totalizar(lineas)
    with _candado:
        _borradores[id_usuario] = Borrador(encontrada.cliente, lineas, totales)

    detalle = "; ".join(
        f"{_cantidad(l['cantidad'])} {l['unidad'] or 'UND'} de {l['descripcion']} "
        f"a {_num(l['precio_unitario'])} = {_num(l['subtotal_linea'])}"
        for l in lineas
    )
    extra = f" con {_cantidad(por_ciento)}% de utilidad" if por_ciento else ""
    return (
        f"Borrador listo (aun NO emitido). Cliente: {encontrada.cliente['nombre']} "
        f"(precio {nivel_elegido}{extra}). {len(lineas)} producto(s): {detalle}. "
        f"Total RD$ {_num(totales['total'])}, ITBIS incluido RD$ {_num(totales['itbis'])}. "
        "Resume cliente, cantidad de productos y total, y pregunta si la emite. "
        "Llama a emitir_cotizacion solo si dice que si."
    )
```

En `backend/herramientas.py`, agregar después de `buscar_cotizacion`:

```python
@herramienta(
    "Recotiza los productos de la ultima cotizacion encontrada con buscar_cotizacion, "
    "a un nivel de precio que elige el usuario. Arma un BORRADOR (no lo emite): mismos "
    "productos y cantidades, precio del nivel pedido (P1..P7) y, si lo piden, un % de "
    "utilidad encima. Despues emite con emitir_cotizacion solo si el usuario confirma.",
    disponible=_cotizaciones_disponibles,
    nivel="El nivel de precio que pidieron, P1 a P7 ('a precio 7' es P7)",
    utilidad="Opcional: % de utilidad encima del nivel ('precio 5 con 6' es 6). Vacio o 0 = el nivel pelado.",
)
def recotizar(nivel: str, utilidad: str = "", usuario: str = "") -> str:
    from . import cotizaciones

    try:
        return cotizaciones.recotizar(usuario, nivel, utilidad or 0)
    except cotizaciones.ErrorCotizacion as error:
        return str(error)
```

- [ ] **Step 4: Correr y ver pasar**

Run: `python -m pytest tests/test_cotizaciones.py -k "recotizar" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/cotizaciones.py backend/herramientas.py tests/test_cotizaciones.py
git commit -m "Cotizaciones: recotizar los productos encontrados a un nivel elegido"
```

---

## Task 6: La re-cotización emite una JV nueva (integración)

**Files:**
- Test: `tests/test_cotizaciones.py`

Confirma que el borrador de `recotizar` lo emite `emitir_cotizacion` sin cambios,
dando una JV nueva, y que no toca la vieja.

- [ ] **Step 1: Escribir la prueba que falla**

Necesita a la vez los servicios de emisión y las emitidas mockeadas:

```python
@pytest.fixture
def servicios_y_emitidas(servicios, emitidas):
    return servicios


def test_recotizar_y_emitir_saca_una_jv_nueva(servicios_y_emitidas):
    _buscar("6177")
    _recotizar("7")
    texto, adjuntos = herramientas.ejecutar_completo("emitir_cotizacion", "{}", "admin")
    assert "JV-00007" in texto                      # _insertar mock devuelve 7
    fila = servicios_y_emitidas["insertar"][0]
    assert fila["cliente"]["codigo"] == "6177"
    assert fila["productos"][0]["codigo"] == "9681"
    assert fila["productos"][0]["precio_unitario"] == 11.5   # el nivel P7 recotizado
    assert fila["total"] == 1150.0
    assert adjuntos[0]["numero"] == "JV-00007"
```

- [ ] **Step 2: Correr y ver (puede pasar directo)**

Run: `python -m pytest tests/test_cotizaciones.py::test_recotizar_y_emitir_saca_una_jv_nueva -v`
Expected: PASS — `emitir_cotizacion` ya funciona sobre cualquier `Borrador`. Si
falla, es señal de un desajuste entre lo que deja `recotizar` y lo que espera
`emitir`; revisar ahí antes de seguir.

- [ ] **Step 3: Commit**

```bash
git add tests/test_cotizaciones.py
git commit -m "Cotizaciones: prueba de recotizar + emitir una JV nueva"
```

---

## Task 7: Herramientas escondidas sin configurar + README

**Files:**
- Modify: `tests/test_cotizaciones.py` (`test_sin_configurar_no_se_ofrecen`)
- Modify: `README.md` (sección de cotizaciones)

- [ ] **Step 1: Ampliar la prueba existente**

Cambiar en `tests/test_cotizaciones.py` el assert de
`test_sin_configurar_no_se_ofrecen` de:

```python
    assert not {"preparar_cotizacion", "emitir_cotizacion"} & nombres
```

a:

```python
    assert not {"preparar_cotizacion", "emitir_cotizacion",
                "buscar_cotizacion", "recotizar"} & nombres
```

- [ ] **Step 2: Correr y ver pasar**

Run: `python -m pytest tests/test_cotizaciones.py::test_sin_configurar_no_se_ofrecen -v`
Expected: PASS (las dos nuevas tienen `disponible=_cotizaciones_disponibles`).

- [ ] **Step 3: Documentar en README**

En `README.md`, en la sección de cotizaciones (después del párrafo que describe
`preparar_cotizacion`/`emitir_cotizacion`, ~línea 585), agregar:

```markdown
Además puede **retomar una cotización ya emitida** y re-cotizarla a otro precio:

1. **`buscar_cotizacion`**: "dame la última cotización de Ferretería Eliam" / "del
   cliente 6177" / "del RNC 131…" / "la JV-12". Resuelve el cliente contra la Base
   JH y trae la última emitida (número, cliente, fecha, total y productos).
2. **`recotizar`**: "ahora los quiero a precio 7" o "precio 5 con un 6%". Toma los
   mismos productos y cantidades y los re-cotiza al nivel elegido (Pn crudo del
   catálogo, sin factor del cliente) con la utilidad opcional encima
   (`precio = Pn / (1 − utilidad/100)`). Arma un borrador; `emitir_cotizacion` saca
   una JV nueva tras el "sí". La vieja queda intacta.
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_cotizaciones.py README.md
git commit -m "Cotizaciones: documentar buscar/recotizar y esconderlas sin configurar"
```

---

## Cierre

- [ ] **Correr toda la suite de cotizaciones**

Run: `python -m pytest tests/test_cotizaciones.py -v`
Expected: PASS todas.

- [ ] **Desplegar** (lo corre Jorge; el clasificador bloquea deploys de producción)

En Git Bash desde `C:\Users\Jorge\jarvis`:

```
git archive HEAD backend web requirements.txt Procfile | ssh ec2 'sudo sh -c "cd /opt/jarvis/jarvis && rm -rf backend web && tar xf - && python3 -m py_compile backend/fuentes.py backend/main.py backend/cotizaciones.py backend/herramientas.py && echo SINTAXIS_OK && cd .. && docker compose build jarvis && docker compose up -d jarvis && echo DEPLOY_OK"'
```

- [ ] **Probar en vivo:** "dame la última cotización del cliente 6177" → "ahora
  a precio 7" → confirmar → que salga una JV nueva con el PDF.
