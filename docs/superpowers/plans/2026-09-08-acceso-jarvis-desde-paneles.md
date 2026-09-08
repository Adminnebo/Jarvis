# Acceso a Jarvis desde los paneles — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que el super admin marque quién usa Jarvis desde el panel de usuarios que ya existe, y que esa persona entre de un clic desde cualquiera de los tres paneles, sin escribir contraseña.

**Architecture:** El catálogo de permisos compartido gana un grupo `jarvis`. Los paneles muestran un acceso directo a quien tenga `jarvis.usar`. Al pulsarlo, Jarvis recibe el token de sesión de Supabase por el fragmento de la URL, lo valida contra Supabase, lee `profiles` por su conexión directa a Postgres y emite su propia cookie. Revalida el perfil cada 60 segundos para que quitar el permiso surta efecto rápido.

**Tech Stack:** Node/Express y JS de navegador en los paneles; React en cobranzas; Python 3.12 + FastAPI en Jarvis.

**Spec:** `docs/superpowers/specs/2026-09-08-acceso-jarvis-desde-paneles-design.md`

---

## Los cuatro repositorios

| Alias | Carpeta local | Repo |
|---|---|---|
| **inbox** | `C:\Users\Jorge\dashboard-ws-dinamico` | `Adminnebo/whatsapp-dashboard` |
| **cotizaciones** | `C:\Users\Jorge\whatsapp-analytics` | `Adminnebo/Cotizacionesdashboard` |
| **cobranzas** | `C:\Users\Jorge\cobranzas-dashboard` | `Adminnebo/cobranzasdashboard` |
| **jarvis** | `C:\Users\Jorge\jarvis` | `Adminnebo/Jarvis` |

**Antes de tocar nada, en cada repo que vayas a modificar:** creá una rama
`feat/jarvis-sso` y trabajá ahí. `main` tiene auto-despliegue.

```bash
cd <carpeta del repo>
git checkout -b feat/jarvis-sso
```

En Jarvis, para cualquier comando de Python usá `.venv/Scripts/python.exe`. El
`python` del PATH es un alias roto de la Microsoft Store.

## Estructura de archivos

| Archivo | Responsabilidad |
|---|---|
| `inbox/auth/permcatalog.js` (modificar) | Catálogo canónico. Grupo `jarvis` y tapar el respaldo. |
| `inbox/public/js/permcatalog.js` (modificar) | Gemelo de navegador. Solo el grupo; no tiene `permisosDe`. |
| `inbox/test/permcatalog.test.js` (crear) | Prueba de que el respaldo no regala Jarvis. |
| `jarvis/backend/supabase_sesion.py` (crear) | Validar el token, leer el perfil, cachear. No sabe de HTTP ni de cookies. |
| `jarvis/backend/acceso.py` (modificar) | Convertir un perfil en `Usuario`. Abrir `/entrar` y `/acceso/supabase`. |
| `jarvis/backend/main.py` (modificar) | Las dos rutas nuevas y la revalidación en el middleware. |
| `jarvis/tests/test_supabase_sesion.py` (crear) | Pruebas del puente, con Supabase sustituido por dobles. |

`backend/memoria.py`, `cerebro.py` y `herramientas.py` **no se tocan**: ya
trabajan con el id del usuario, sea cual sea su origen.

---

# Fase A — El catálogo

## Task 1: El grupo `jarvis` en el catálogo canónico

**Files:**
- Modify: `C:\Users\Jorge\dashboard-ws-dinamico\auth\permcatalog.js`
- Test: `C:\Users\Jorge\dashboard-ws-dinamico\test\permcatalog.test.js`

- [ ] **Step 1: Escribir la prueba que falla**

Crear `test/permcatalog.test.js`. Sigue el estilo del repo: un script plano con
`assert`, sin framework, como `test/wahash.test.js`.

```javascript
/* Test del catalogo de permisos. Correr: node test/permcatalog.test.js

   Lo que protege: a Jarvis se entra solo si alguien lo concedio a proposito.
   permisosDe() tiene respaldos para no romper usuarios viejos, y ninguno de
   ellos puede regalar acceso al asistente. */
'use strict';
const assert = require('assert');
const PERMS = require('../auth/permcatalog');

const jarvis = k => String(k).startsWith('jarvis.');

let fallos = 0;
function prueba(nombre, fn) {
  try { fn(); console.log(`ok   ${nombre}`); }
  catch (e) { fallos++; console.error(`MAL  ${nombre}\n     ${e.message}`); }
}

prueba('el grupo jarvis existe con sus dos permisos', () => {
  assert.ok(PERMS.PLATAFORMAS.includes('jarvis'));
  assert.ok(PERMS.ALL_KEYS.includes('jarvis.usar'));
  assert.ok(PERMS.ALL_KEYS.includes('jarvis.admin'));
});

prueba('un perfil sin nada definido NO recibe jarvis', () => {
  // Este es el respaldo "no romper": da acceso total a los demas, pero
  // regalar el asistente seria una fuga.
  const perms = PERMS.permisosDe({ role: 'agent' });
  assert.strictEqual(perms.filter(jarvis).length, 0);
  assert.ok(perms.includes('inbox.conversations'));
});

prueba('un perfil viejo con platforms NO recibe jarvis', () => {
  const perms = PERMS.permisosDe({
    role: 'agent', permissions: null,
    platforms: ['inbox', 'cotizaciones', 'cobranzas'],
  });
  assert.strictEqual(perms.filter(jarvis).length, 0);
});

prueba('super_admin y admin si reciben jarvis', () => {
  for (const role of ['super_admin', 'admin']) {
    assert.ok(PERMS.permisosDe({ role }).includes('jarvis.usar'), role);
    assert.ok(PERMS.permisosDe({ role }).includes('jarvis.admin'), role);
  }
});

prueba('un agente con el permiso explicito lo conserva', () => {
  const perms = PERMS.permisosDe({ role: 'agent', permissions: ['jarvis.usar'] });
  assert.deepStrictEqual(perms, ['jarvis.usar']);
});

prueba('tener jarvis.usar da acceso a la plataforma jarvis', () => {
  const plats = PERMS.plataformasDe({ role: 'agent', permissions: ['jarvis.usar'] });
  assert.ok(plats.includes('jarvis'));
});

if (fallos) { console.error(`\n${fallos} fallaron`); process.exit(1); }
console.log('\nTodo correcto.');
```

- [ ] **Step 2: Correr la prueba y ver que falla**

Run: `cd C:\Users\Jorge\dashboard-ws-dinamico && node test/permcatalog.test.js`
Expected: FALLA. El grupo no existe todavía y el respaldo regala Jarvis.

- [ ] **Step 3: Añadir el grupo y tapar el respaldo**

En `auth/permcatalog.js`, cambiar la línea de plataformas:

```javascript
const PLATAFORMAS = ['inbox', 'cotizaciones', 'cobranzas', 'jarvis'];
```

Añadir este grupo al final del array `GRUPOS`, después del de cobranzas:

```javascript
  {
    platform: 'jarvis', label: 'Jarvis — Asistente',
    perms: [
      { key: 'jarvis.usar',  label: 'Usar Jarvis' },
      { key: 'jarvis.admin', label: 'Administrar Jarvis (fuentes, credenciales, consumo)',
        sensible: true }
    ]
  }
```

Y reemplazar el final de `permisosDe` (la línea
`return ALL_KEYS.slice();   // sin nada definido: acceso total (no romper)`):

```javascript
  // Sin nada definido: acceso total para no romper a nadie, PERO sin Jarvis.
  // El asistente lee bases de datos y gasta creditos: se entra solo si alguien
  // lo concedio a proposito.
  return ALL_KEYS.filter(k => platformDeKey(k) !== 'jarvis');
```

- [ ] **Step 4: Correr la prueba y ver que pasa**

Run: `cd C:\Users\Jorge\dashboard-ws-dinamico && node test/permcatalog.test.js`
Expected: `Todo correcto.` con las 6 pruebas en `ok`.

- [ ] **Step 5: Commit**

```bash
cd C:\Users\Jorge\dashboard-ws-dinamico
git add auth/permcatalog.js test/permcatalog.test.js
git commit -m "Permisos: grupo Jarvis, que no se concede por respaldo"
```

---

## Task 2: El gemelo de navegador

**Files:**
- Modify: `C:\Users\Jorge\dashboard-ws-dinamico\public\js\permcatalog.js`

La copia de navegador **no tiene `permisosDe`**: recibe la lista ya resuelta
desde `/api/auth/me`. Solo hay que darle las mismas claves para que el panel de
usuarios dibuje las casillas.

- [ ] **Step 1: Añadir la plataforma y el grupo**

En `public/js/permcatalog.js`, cambiar:

```javascript
  const PLATAFORMAS = ['inbox', 'cotizaciones', 'cobranzas', 'jarvis'];
```

Y añadir al final del array `GRUPOS`, después del de cobranzas:

```javascript
    {
      platform: 'jarvis', label: 'Jarvis — Asistente',
      perms: [
        { key: 'jarvis.usar',  label: 'Usar Jarvis' },
        { key: 'jarvis.admin', label: 'Administrar Jarvis (fuentes, credenciales, consumo)',
          sensible: true }
      ]
    }
```

- [ ] **Step 2: Comprobar que las claves de las dos copias coinciden**

Run:

```bash
cd C:\Users\Jorge\dashboard-ws-dinamico
node -e "const s=require('./auth/permcatalog');const src=require('fs').readFileSync('public/js/permcatalog.js','utf8');const faltan=s.ALL_KEYS.filter(k=>!src.includes(\"'\"+k+\"'\"));console.log(faltan.length?'FALTAN: '+faltan:'las dos copias tienen las mismas claves')"
```

Expected: `las dos copias tienen las mismas claves`

- [ ] **Step 3: Commit**

```bash
cd C:\Users\Jorge\dashboard-ws-dinamico
git add public/js/permcatalog.js
git commit -m "Permisos: el gemelo de navegador tambien conoce Jarvis"
```

---

## Task 3: Replicar a los otros dos repos

Las tres copias de servidor y las dos de navegador eran **idénticas byte a
byte** antes de este trabajo. Se replican copiando, y se verifica que siguen
idénticas: es la única defensa contra que se desincronicen.

**Files:**
- Modify: `C:\Users\Jorge\whatsapp-analytics\permcatalog.js`
- Modify: `C:\Users\Jorge\whatsapp-analytics\public\js\permcatalog.js`
- Modify: `C:\Users\Jorge\cobranzas-dashboard\server\permcatalog.js`

- [ ] **Step 1: Crear la rama en los dos repos**

```bash
cd C:\Users\Jorge\whatsapp-analytics && git checkout -b feat/jarvis-sso
cd C:\Users\Jorge\cobranzas-dashboard && git checkout -b feat/jarvis-sso
```

- [ ] **Step 2: Copiar**

```bash
cd C:\Users\Jorge
cp dashboard-ws-dinamico/auth/permcatalog.js whatsapp-analytics/permcatalog.js
cp dashboard-ws-dinamico/auth/permcatalog.js cobranzas-dashboard/server/permcatalog.js
cp dashboard-ws-dinamico/public/js/permcatalog.js whatsapp-analytics/public/js/permcatalog.js
```

- [ ] **Step 3: Verificar que quedaron idénticas**

```bash
cd C:\Users\Jorge
diff -q dashboard-ws-dinamico/auth/permcatalog.js whatsapp-analytics/permcatalog.js
diff -q dashboard-ws-dinamico/auth/permcatalog.js cobranzas-dashboard/server/permcatalog.js
diff -q dashboard-ws-dinamico/public/js/permcatalog.js whatsapp-analytics/public/js/permcatalog.js
```

Expected: sin salida en los tres (idénticas).

- [ ] **Step 4: Comprobar que cada servidor sigue cargando su copia**

```bash
cd C:\Users\Jorge\whatsapp-analytics && node -e "console.log(require('./permcatalog').ALL_KEYS.filter(k=>k.startsWith('jarvis')))"
cd C:\Users\Jorge\cobranzas-dashboard && node -e "console.log(require('./server/permcatalog').ALL_KEYS.filter(k=>k.startsWith('jarvis')))"
```

Expected en ambos: `[ 'jarvis.usar', 'jarvis.admin' ]`

- [ ] **Step 5: Commit en los dos repos**

```bash
cd C:\Users\Jorge\whatsapp-analytics
git add permcatalog.js public/js/permcatalog.js
git commit -m "Permisos: replicar el grupo Jarvis del catalogo"

cd C:\Users\Jorge\cobranzas-dashboard
git add server/permcatalog.js
git commit -m "Permisos: replicar el grupo Jarvis del catalogo"
```

---

# Fase B — Jarvis acepta sesiones de Supabase

## Task 4: Validar el token y leer el perfil

**Files:**
- Create: `C:\Users\Jorge\jarvis\backend\supabase_sesion.py`
- Test: `C:\Users\Jorge\jarvis\tests\test_supabase_sesion.py`

- [ ] **Step 1: Escribir la prueba que falla**

`tests/test_supabase_sesion.py`:

```python
import pytest

from backend import supabase_sesion


@pytest.fixture
def configurado(monkeypatch):
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-de-prueba")
    monkeypatch.setenv("SUPABASE_PROJECT_REF", "abcdefghijklmnopqrst")
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://x:y@z:5432/postgres")


def test_sin_variables_el_puente_esta_apagado():
    assert supabase_sesion.configurado() is False


def test_con_las_tres_variables_esta_encendido(configurado):
    assert supabase_sesion.configurado() is True


def test_falta_la_cadena_de_postgres(configurado, monkeypatch):
    # Sin conexion directa, leer el perfil iria por MCP y costaria mas de un
    # segundo en cada revalidacion.
    monkeypatch.delenv("SUPABASE_DB_URL")
    assert supabase_sesion.configurado() is False


def test_la_url_del_proyecto_sale_de_la_referencia(configurado):
    assert supabase_sesion.url_proyecto() == "https://abcdefghijklmnopqrst.supabase.co"


def test_un_uuid_invalido_no_llega_a_la_base(configurado):
    # El uuid se interpola en el SQL, asi que tiene que estar comprobado antes.
    with pytest.raises(ValueError):
        supabase_sesion.perfil("'; drop table profiles; --")
```

- [ ] **Step 2: Correr la prueba y ver que falla**

Run: `cd C:\Users\Jorge\jarvis && .venv/Scripts/python.exe -m pytest tests/test_supabase_sesion.py -q`
Expected: FALLA con `ModuleNotFoundError: No module named 'backend.supabase_sesion'`

- [ ] **Step 3: Escribir el modulo**

Crear `backend/supabase_sesion.py`:

```python
"""El puente con los paneles.

Los tres paneles comparten un directorio de usuarios en Supabase. Aqui se
valida el token de sesion de una persona, se lee su perfil y se decide si
puede usar Jarvis y con que rol.

Este modulo no sabe de HTTP ni de cookies: solo traduce un token en un
usuario. Lo de arriba lo hace acceso.py.
"""

import os
import re
import threading
import time

import httpx

# Los ids de quienes vienen de los paneles llevan este prefijo, para no chocar
# con los que salen de los sufijos de las variables de entorno.
PREFIJO = "sb-"

# Cuanto vale un perfil ya leido. La cookie de Jarvis dura 30 dias; sin
# revalidar, quitarle el permiso a alguien no surtiria efecto hasta entonces.
VIGENCIA = 60

# Si la base no responde, cuanto se conserva el ultimo perfil conocido. Un
# corte breve no debe echar a nadie a mitad de una conversacion.
GRACIA = 300

UUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def configurado() -> bool:
    """Si falta algo, el puente queda apagado y solo entran las contrasenas.

    SUPABASE_DB_URL cuenta: sin conexion directa, leer el perfil iria por MCP
    y pondria mas de un segundo en el camino de cada peticion.
    """
    return all(
        os.getenv(variable, "").strip()
        for variable in ("SUPABASE_ANON_KEY", "SUPABASE_PROJECT_REF", "SUPABASE_DB_URL")
    )


def url_proyecto() -> str:
    referencia = os.getenv("SUPABASE_PROJECT_REF", "").strip()
    return f"https://{referencia}.supabase.co"


def id_de_token(token: str) -> str | None:
    """Valida el token contra Supabase y devuelve el uuid de quien lo trajo.

    Se le pregunta a Supabase en vez de verificar la firma aqui: asi no hace
    falta guardar el secreto de firma del proyecto, y un token revocado deja
    de valer de inmediato.
    """
    if not token or not configurado():
        return None

    respuesta = httpx.get(
        f"{url_proyecto()}/auth/v1/user",
        headers={
            "Authorization": f"Bearer {token}",
            "apikey": os.getenv("SUPABASE_ANON_KEY", "").strip(),
        },
        timeout=10,
    )
    if respuesta.status_code != 200:
        return None
    return respuesta.json().get("id")


def perfil(uuid: str) -> dict | None:
    """El perfil de esa persona en la tabla que comparten los paneles."""
    if not UUID.match(uuid or ""):
        # El uuid se interpola en el SQL. Viene de Supabase, pero comprobarlo
        # aqui es lo que garantiza que nunca entre otra cosa.
        raise ValueError("El identificador no es un uuid.")

    from . import esquema

    filas = esquema.consultar_directo(
        "select id, email, full_name, role, permissions, platforms "
        f"from profiles where id = '{uuid}' limit 1;"
    )
    return filas[0] if filas else None


# --------------------------------------------------------------------------
# Cache de perfiles
# --------------------------------------------------------------------------

_cache: dict[str, tuple[float, dict | None]] = {}
_candado = threading.Lock()


def perfil_cacheado(uuid: str) -> dict | None:
    """El perfil, releido como mucho una vez por minuto.

    Devuelve el ultimo conocido si la base no responde, hasta GRACIA segundos.
    Pasado eso propaga el error: preferimos dejar a alguien fuera antes que
    mantener viva una sesion que ya no podemos comprobar.
    """
    ahora = time.monotonic()

    with _candado:
        guardado = _cache.get(uuid)
    if guardado and ahora - guardado[0] < VIGENCIA:
        return guardado[1]

    try:
        fresco = perfil(uuid)
    except Exception:  # noqa: BLE001 - la base puede no responder
        if guardado and ahora - guardado[0] < GRACIA:
            return guardado[1]
        raise

    with _candado:
        _cache[uuid] = (ahora, fresco)
    return fresco


def limpiar_cache() -> None:
    with _candado:
        _cache.clear()
```

- [ ] **Step 4: Correr la prueba y ver que pasa**

Run: `cd C:\Users\Jorge\jarvis && .venv/Scripts/python.exe -m pytest tests/test_supabase_sesion.py -q`
Expected: PASS, 5 pruebas.

- [ ] **Step 5: Commit**

```bash
cd C:\Users\Jorge\jarvis
git add backend/supabase_sesion.py tests/test_supabase_sesion.py
git commit -m "Jarvis: validar un token de Supabase y leer el perfil"
```

---

## Task 5: De un perfil a un usuario de Jarvis

**Files:**
- Modify: `C:\Users\Jorge\jarvis\backend\supabase_sesion.py`
- Test: `C:\Users\Jorge\jarvis\tests\test_supabase_sesion.py`

- [ ] **Step 1: Escribir la prueba que falla**

Anadir a `tests/test_supabase_sesion.py`:

```python
def perfil_de(role="agent", permissions=None, platforms=None, nombre="Ana Perez"):
    return {
        "id": "11111111-2222-3333-4444-555555555555",
        "email": "ana@empresa.com",
        "full_name": nombre,
        "role": role,
        "permissions": permissions,
        "platforms": platforms,
    }


def test_con_jarvis_usar_entra_como_usuario():
    usuario = supabase_sesion.usuario_de_perfil(perfil_de(permissions=["jarvis.usar"]))
    assert usuario.rol == "usuario"
    assert usuario.nombre == "Ana Perez"
    assert usuario.id == "sb-11111111-2222-3333-4444-555555555555"


def test_con_jarvis_admin_entra_como_admin():
    usuario = supabase_sesion.usuario_de_perfil(perfil_de(permissions=["jarvis.admin"]))
    assert usuario.rol == "admin"


@pytest.mark.parametrize("role", ["super_admin", "admin"])
def test_los_administradores_de_la_plataforma_son_admin(role):
    assert supabase_sesion.usuario_de_perfil(perfil_de(role=role)).rol == "admin"


def test_sin_permiso_de_jarvis_no_entra():
    assert supabase_sesion.usuario_de_perfil(perfil_de(permissions=["inbox.send"])) is None


def test_un_perfil_viejo_sin_permisos_no_entra():
    # permissions en NULL y platforms de las tres viejas: el catalogo ya no
    # concede jarvis por respaldo, y aqui tampoco.
    sin_migrar = perfil_de(
        permissions=None, platforms=["inbox", "cotizaciones", "cobranzas"]
    )
    assert supabase_sesion.usuario_de_perfil(sin_migrar) is None


def test_sin_nombre_se_usa_la_parte_del_correo():
    anonimo = perfil_de(permissions=["jarvis.usar"], nombre=None)
    assert supabase_sesion.usuario_de_perfil(anonimo).nombre == "ana"


def test_un_perfil_inexistente_no_entra():
    assert supabase_sesion.usuario_de_perfil(None) is None
```

- [ ] **Step 2: Correr la prueba y ver que falla**

Run: `cd C:\Users\Jorge\jarvis && .venv/Scripts/python.exe -m pytest tests/test_supabase_sesion.py -q`
Expected: FALLA con `AttributeError: module 'backend.supabase_sesion' has no attribute 'usuario_de_perfil'`

- [ ] **Step 3: Implementar**

Anadir al final de `backend/supabase_sesion.py`:

```python
# --------------------------------------------------------------------------
# De perfil a usuario de Jarvis
# --------------------------------------------------------------------------

def usuario_de_perfil(datos: dict | None):
    """El usuario de Jarvis que corresponde a ese perfil, o None si no entra.

    Aqui NO se replica todo permcatalog.js. Solo importan las claves de
    Jarvis, y ningun respaldo del catalogo las concede: un perfil sin permisos
    explicitos no llega nunca al asistente. Con mirar el rol y la lista
    explicita alcanza.
    """
    from . import acceso

    if not datos:
        return None

    rol_plataforma = (datos.get("role") or "").strip()
    permisos = datos.get("permissions") or []

    if rol_plataforma in ("super_admin", "admin"):
        rol = "admin"
    elif "jarvis.admin" in permisos:
        rol = "admin"
    elif "jarvis.usar" in permisos:
        rol = "usuario"
    else:
        return None

    correo = (datos.get("email") or "").strip()
    nombre = (datos.get("full_name") or "").strip() or correo.split("@")[0] or "Alguien"

    return acceso.Usuario(f"{PREFIJO}{datos['id']}", nombre, rol)
```

- [ ] **Step 4: Correr la prueba y ver que pasa**

Run: `cd C:\Users\Jorge\jarvis && .venv/Scripts/python.exe -m pytest tests/test_supabase_sesion.py -q`
Expected: PASS, 13 pruebas.

- [ ] **Step 5: Commit**

```bash
cd C:\Users\Jorge\jarvis
git add backend/supabase_sesion.py tests/test_supabase_sesion.py
git commit -m "Jarvis: el rol sale de los permisos del panel"
```

---
## Task 6: Entrar y revalidar, de punta a punta

**Files:**
- Modify: `C:\Users\Jorge\jarvis\backend\supabase_sesion.py`
- Test: `C:\Users\Jorge\jarvis\tests\test_supabase_sesion.py`

- [ ] **Step 1: Escribir la prueba que falla**

Anadir a `tests/test_supabase_sesion.py`:

```python
def test_entrar_con_un_token_bueno(configurado, monkeypatch):
    monkeypatch.setattr(supabase_sesion, "id_de_token",
                        lambda t: "11111111-2222-3333-4444-555555555555")
    monkeypatch.setattr(supabase_sesion, "perfil_cacheado",
                        lambda u: perfil_de(permissions=["jarvis.usar"]))
    assert supabase_sesion.entrar("un-token").rol == "usuario"


def test_entrar_con_un_token_invalido(configurado, monkeypatch):
    monkeypatch.setattr(supabase_sesion, "id_de_token", lambda t: None)
    assert supabase_sesion.entrar("un-token") is None


def test_si_supabase_falla_no_entra_nadie(configurado, monkeypatch):
    def revienta(_):
        raise RuntimeError("Supabase no responde")

    monkeypatch.setattr(supabase_sesion, "id_de_token", revienta)
    # Nunca modo abierto: un fallo deja fuera, no deja pasar.
    assert supabase_sesion.entrar("un-token") is None


def test_con_el_puente_apagado_no_entra_nadie():
    assert supabase_sesion.entrar("un-token") is None


def test_revalidar_devuelve_none_si_le_quitaron_el_permiso(configurado, monkeypatch):
    previo = supabase_sesion.usuario_de_perfil(perfil_de(permissions=["jarvis.usar"]))
    monkeypatch.setattr(supabase_sesion, "perfil_cacheado",
                        lambda u: perfil_de(permissions=["inbox.send"]))
    assert supabase_sesion.revalidar(previo) is None


def test_revalidar_actualiza_el_rol(configurado, monkeypatch):
    previo = supabase_sesion.usuario_de_perfil(perfil_de(permissions=["jarvis.usar"]))
    monkeypatch.setattr(supabase_sesion, "perfil_cacheado",
                        lambda u: perfil_de(permissions=["jarvis.admin"]))
    assert supabase_sesion.revalidar(previo).rol == "admin"


def test_revalidar_ignora_a_los_de_contrasena(configurado):
    from backend import acceso

    de_variable = acceso.Usuario("admin", "Lucas", "admin")
    # No lleva el prefijo: no se toca la base por el.
    assert supabase_sesion.revalidar(de_variable) is de_variable


def test_el_perfil_se_cachea_un_minuto(configurado, monkeypatch):
    llamadas = []

    def contar(uuid):
        llamadas.append(uuid)
        return perfil_de(permissions=["jarvis.usar"])

    supabase_sesion.limpiar_cache()
    monkeypatch.setattr(supabase_sesion, "perfil", contar)

    uuid = "11111111-2222-3333-4444-555555555555"
    supabase_sesion.perfil_cacheado(uuid)
    supabase_sesion.perfil_cacheado(uuid)
    supabase_sesion.perfil_cacheado(uuid)

    # Tres consultas seguidas, una sola ida a la base.
    assert len(llamadas) == 1
```

- [ ] **Step 2: Correr la prueba y ver que falla**

Run: `cd C:\Users\Jorge\jarvis && .venv/Scripts/python.exe -m pytest tests/test_supabase_sesion.py -q`
Expected: FALLA con `AttributeError: module 'backend.supabase_sesion' has no attribute 'entrar'`

- [ ] **Step 3: Implementar**

Anadir al final de `backend/supabase_sesion.py`:

```python
def entrar(token: str):
    """El usuario que corresponde a un token de panel, o None.

    Cualquier fallo devuelve None. Un problema con Supabase deja a la gente
    fuera; nunca la deja pasar.
    """
    if not configurado():
        return None

    try:
        uuid = id_de_token(token)
        if not uuid:
            return None
        return usuario_de_perfil(perfil_cacheado(uuid))
    except Exception:  # noqa: BLE001 - no poder comprobar es no entrar
        return None


def revalidar(usuario):
    """Comprueba que quien vino de un panel sigue teniendo permiso.

    Los usuarios de contrasena por variable pasan intactos: su permiso vive en
    el entorno, no en la base.
    """
    if not usuario or not usuario.id.startswith(PREFIJO):
        return usuario

    if not configurado():
        return None

    try:
        return usuario_de_perfil(perfil_cacheado(usuario.id[len(PREFIJO):]))
    except Exception:  # noqa: BLE001
        return None
```

- [ ] **Step 4: Correr toda la suite**

Run: `cd C:\Users\Jorge\jarvis && .venv/Scripts/python.exe -m pytest tests/ -q`
Expected: PASS, todas.

- [ ] **Step 5: Commit**

```bash
cd C:\Users\Jorge\jarvis
git add backend/supabase_sesion.py tests/test_supabase_sesion.py
git commit -m "Jarvis: entrar y revalidar con la sesion del panel"
```

---

## Task 7: La pagina de entrada, su ruta y la revalidacion

**Files:**
- Modify: `C:\Users\Jorge\jarvis\backend\acceso.py`
- Modify: `C:\Users\Jorge\jarvis\backend\main.py`
- Test: `C:\Users\Jorge\jarvis\tests\test_permisos.py`

- [ ] **Step 1: Escribir la prueba que falla**

Anadir a `tests/test_permisos.py`:

```python
def test_la_pagina_de_entrada_es_libre(cliente):
    # Se pide sin sesion: es justo la que la crea.
    assert cliente.get("/entrar").status_code == 200


def test_entrar_con_un_token_bueno_deja_cookie(cliente, monkeypatch):
    from backend import acceso, supabase_sesion

    monkeypatch.setattr(supabase_sesion, "entrar",
                        lambda t: acceso.Usuario("sb-abc", "Ana", "usuario"))
    cliente.cookies.clear()
    respuesta = cliente.post("/acceso/supabase", json={"token": "loquesea"})
    assert respuesta.status_code == 200
    assert acceso.COOKIE in respuesta.cookies


def test_entrar_sin_permiso_da_403(cliente, monkeypatch):
    from backend import supabase_sesion

    monkeypatch.setattr(supabase_sesion, "entrar", lambda t: None)
    cliente.cookies.clear()
    assert cliente.post("/acceso/supabase", json={"token": "x"}).status_code == 403


def test_la_sesion_del_panel_sirve_para_la_api(cliente, monkeypatch):
    from backend import acceso, supabase_sesion

    ana = acceso.Usuario("sb-abc", "Ana", "usuario")
    monkeypatch.setattr(supabase_sesion, "entrar", lambda t: ana)
    monkeypatch.setattr(supabase_sesion, "revalidar", lambda u: ana)

    cliente.cookies.clear()
    cliente.post("/acceso/supabase", json={"token": "loquesea"})

    estado = cliente.get("/api/estado").json()
    assert estado["usuario"] == "Ana"
    assert estado["rol"] == "usuario"
    # Sin jarvis.admin no toca la configuracion.
    assert cliente.get("/api/fuentes").status_code == 403


def test_si_le_quitan_el_permiso_queda_fuera(cliente, monkeypatch):
    from backend import acceso, supabase_sesion

    ana = acceso.Usuario("sb-abc", "Ana", "usuario")
    monkeypatch.setattr(supabase_sesion, "entrar", lambda t: ana)
    monkeypatch.setattr(supabase_sesion, "revalidar", lambda u: ana)
    cliente.cookies.clear()
    cliente.post("/acceso/supabase", json={"token": "loquesea"})
    assert cliente.get("/api/estado").status_code == 200

    # El super admin le quita la casilla.
    monkeypatch.setattr(supabase_sesion, "revalidar", lambda u: None)
    assert cliente.get("/api/estado").status_code == 401


def test_los_de_contrasena_no_pasan_por_supabase(cliente, monkeypatch):
    from backend import supabase_sesion

    def no_deberia(_):
        raise AssertionError("no se revalida a quien entro por contrasena")

    _entrar(cliente, "la-del-admin")
    monkeypatch.setattr(supabase_sesion, "perfil_cacheado", no_deberia)
    assert cliente.get("/api/estado").status_code == 200
```

- [ ] **Step 2: Correr la prueba y ver que falla**

Run: `cd C:\Users\Jorge\jarvis && .venv/Scripts/python.exe -m pytest tests/test_permisos.py -q`
Expected: FALLA. `/entrar` devuelve 401 y `/acceso/supabase` no existe.

- [ ] **Step 3: Abrir las dos rutas y anadir la pagina**

En `backend/acceso.py`, reemplazar la constante de rutas libres:

```python
LIBRES = ("/acceso", "/api/salud", "/api/version", "/entrar", "/acceso/supabase")
```

Y anadir al final del bloque de paginas, despues de `pagina_sin_proteger()`:

```python
def pagina_de_entrada() -> str:
    """Recibe el token del panel y lo convierte en una sesion de Jarvis.

    El token llega en el fragmento de la URL, no en la query: el fragmento no
    se manda al servidor, asi que no queda en los logs de acceso ni se filtra
    por la cabecera Referer. Se borra de la barra en cuanto se lee, para que
    tampoco quede en el historial.

    El POST es al mismo origen porque la cookie es SameSite=Lax y no se
    guardaria en un POST venido de otro sitio.
    """
    guion = """
(async () => {
  const mensaje = document.getElementById('mensaje');
  const token = new URLSearchParams(location.hash.slice(1)).get('t');
  history.replaceState(null, '', location.pathname);

  if (!token) {
    mensaje.textContent = 'Falta el token. Vuelve a entrar desde el panel.';
    return;
  }

  try {
    const r = await fetch('/acceso/supabase', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: token }),
    });
    if (r.ok) { location.replace('/'); return; }
    const datos = await r.json().catch(() => ({}));
    mensaje.textContent = datos.error || 'No se pudo entrar.';
  } catch (e) {
    mensaje.textContent = 'No se pudo contactar con Jarvis.';
  }
})();
"""
    return f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Jarvis</title><style>{_ESTILO}</style></head><body>
<div class="caja">
  <h1>Jarvis</h1>
  <p id="mensaje">Entrando...</p>
</div>
<script>{guion}</script>
</body></html>"""
```

El guion va en su propia variable y no dentro de la f-string: si estuviera
dentro, cada llave de JavaScript habria que escribirla doble y el codigo seria
ilegible.

- [ ] **Step 4: Anadir las rutas y la revalidacion en main.py**

En `backend/main.py`, anadir `supabase_sesion` a la lista de modulos que se
importan del proyecto.

Anadir estas dos rutas justo despues de `entrar`:

```python
@app.get("/entrar")
def pagina_de_entrada():
    """Donde aterriza quien llega desde un panel."""
    return HTMLResponse(acceso.pagina_de_entrada())


@app.post("/acceso/supabase")
def entrar_con_supabase(datos: dict):
    """Cambia un token de sesion de los paneles por una cookie de Jarvis."""
    usuario = supabase_sesion.entrar((datos.get("token") or "").strip())

    if usuario is None:
        return JSONResponse(
            status_code=403,
            content={"error": "No tienes acceso a Jarvis. Pideselo a quien administra."},
        )

    respuesta = JSONResponse(content={"ok": True, "usuario": usuario.nombre})
    respuesta.set_cookie(
        acceso.COOKIE,
        acceso.crear_token(usuario),
        max_age=acceso.DURACION,
        httponly=True,
        samesite="lax",
        secure=rutas.hospedado(),
    )
    return respuesta
```

Y dentro de `guardia`, justo despues del bloque que resuelve `usuario` y antes
de la comprobacion de admin:

```python
    # Quien vino de un panel se revalida contra profiles: si le quitaron el
    # permiso, su cookie deja de valer sin esperar a que caduque.
    usuario = supabase_sesion.revalidar(usuario)
    if usuario is None:
        if ruta.startswith("/api/"):
            return JSONResponse(status_code=401, content={"error": "No autorizado."})
        return HTMLResponse(acceso.pagina_login(), status_code=401)
```

- [ ] **Step 5: Correr toda la suite**

Run: `cd C:\Users\Jorge\jarvis && .venv/Scripts/python.exe -m pytest tests/ -q`
Expected: PASS, todas.

- [ ] **Step 6: Commit**

```bash
cd C:\Users\Jorge\jarvis
git add backend/acceso.py backend/main.py tests/test_permisos.py
git commit -m "Jarvis: entrar desde un panel y revalidar en cada peticion"
```

---

## Task 8: Avisar al arrancar y documentar

**Files:**
- Modify: `C:\Users\Jorge\jarvis\backend\main.py`
- Modify: `C:\Users\Jorge\jarvis\.env.example`
- Modify: `C:\Users\Jorge\jarvis\README.md`

- [ ] **Step 1: Avisar si el puente esta apagado**

En `backend/main.py`, dentro de `al_arrancar()`, despues de la llamada a
`acceso.avisar_de_contrasenas_repetidas()`:

```python
    if not supabase_sesion.configurado():
        print(
            "\n  AVISO: nadie puede entrar desde los paneles.\n"
            "  Faltan SUPABASE_ANON_KEY, SUPABASE_PROJECT_REF o SUPABASE_DB_URL.\n"
            "  Las contrasenas de JARVIS_PASSWORD* siguen funcionando.\n"
        )
```

- [ ] **Step 2: Anadir la variable al ejemplo**

En `.env.example`, en la seccion de Supabase, despues de `SUPABASE_DB_URL`:

```
# Clave publica del proyecto (Settings > API > anon public). Hace falta para
# que la gente entre a Jarvis desde los paneles con su sesion de Supabase.
# Sin ella ese acceso queda apagado y solo sirven las contrasenas de arriba.
SUPABASE_ANON_KEY=
```

- [ ] **Step 3: Documentar en el README**

Anadir despues de la seccion "Varias personas":

```markdown
### Entrar desde los paneles

Quien use el inbox, cotizaciones o cobranzas puede entrar a Jarvis de un clic,
sin escribir contraseña. El super admin lo concede marcando **Usar Jarvis** en
el panel de usuarios; **Administrar Jarvis** le da además fuentes, esquema y
consumo.

Jarvis valida la sesión de Supabase del panel y relee el perfil cada minuto, así
que quitar la casilla deja fuera a la persona enseguida, sin esperar a que
caduque su cookie.

Necesita `SUPABASE_ANON_KEY` y `SUPABASE_DB_URL`. Si falta alguna, este acceso
queda apagado —se avisa al arrancar— y las contraseñas por variable siguen
funcionando.
```

Y en la tabla de variables, anadir la fila:

```markdown
| `SUPABASE_ANON_KEY` | Clave pública. Habilita entrar desde los paneles |
```

- [ ] **Step 4: Comprobar el aviso**

Run: `cd C:\Users\Jorge\jarvis && .venv/Scripts/python.exe -c "from backend import main"`
Expected: sin errores de importacion.

- [ ] **Step 5: Commit**

```bash
cd C:\Users\Jorge\jarvis
git add backend/main.py .env.example README.md
git commit -m "Documentar el acceso desde los paneles y avisar si esta apagado"
```

---
# Fase C — El acceso directo en los paneles

Las tres tareas son independientes entre sí. Ninguna sirve de nada hasta que
Jarvis esté desplegado con la Fase B.

**Antes de empezar**, averigua la URL pública de Jarvis (el dominio del servicio
en Railway) y úsala en lugar de `https://JARVIS_URL` en las tres tareas.

## Task 9: El botón en el inbox

**Files:**
- Modify: `C:\Users\Jorge\dashboard-ws-dinamico\public\index.html`

- [ ] **Step 1: Localizar la barra y el atajo del token**

Run: `cd C:\Users\Jorge\dashboard-ws-dinamico && grep -n "currentToken" public/js/auth.js | head -5`
Expected: aparece `Auth.currentToken`, que es el token de Supabase de la sesión.

Run: `cd C:\Users\Jorge\dashboard-ws-dinamico && grep -n 'id="btn-' public/index.html | head -8`
Expected: la lista de botones de la barra superior, para saber dónde insertar.

- [ ] **Step 2: Añadir el botón**

En `public/index.html`, junto a los demás botones de la barra superior:

```html
<button id="btn-jarvis" class="boton-texto" data-perm="jarvis.usar"
        title="Abrir Jarvis">Jarvis</button>
```

Y donde se enganchan los eventos de esos botones:

```javascript
// El token va en el fragmento: no llega al servidor de Jarvis dentro de la
// URL, asi que no queda en sus logs ni se filtra por la cabecera Referer.
document.getElementById('btn-jarvis').addEventListener('click', () => {
  window.open(
    'https://JARVIS_URL/entrar#t=' + encodeURIComponent(Auth.currentToken),
    '_blank'
  );
});
```

No hace falta nada más para ocultarlo: `PERMS.aplicar()` ya esconde cualquier
elemento con `data-perm` que el usuario no tenga.

- [ ] **Step 3: Comprobar a mano**

Arrancar el inbox, entrar con un usuario **sin** `jarvis.usar` y comprobar que
el botón no aparece. Concedérselo desde `users.html`, recargar, y comprobar que
aparece y que abre Jarvis ya dentro, sin pedir contraseña.

- [ ] **Step 4: Commit**

```bash
cd C:\Users\Jorge\dashboard-ws-dinamico
git add public/index.html
git commit -m "Acceso directo a Jarvis desde el inbox"
```

---

## Task 10: El botón en cotizaciones

**Files:**
- Modify: `C:\Users\Jorge\whatsapp-analytics\public\index.html`

- [ ] **Step 1: Localizar la barra y el atajo del token**

Run: `cd C:\Users\Jorge\whatsapp-analytics && grep -rn "currentToken\|PERMS.aplicar" public/js/*.js | head -8`
Expected: el mismo patrón que el inbox (`Auth.currentToken` y `PERMS.aplicar`).
Si el atajo del token tiene otro nombre en este repo, usa el que salga aquí.

Run: `cd C:\Users\Jorge\whatsapp-analytics && grep -n 'id="btn-\|data-perm' public/index.html | head -8`
Expected: la barra superior y algún ejemplo de `data-perm` ya en uso.

- [ ] **Step 2: Añadir el botón**

En `public/index.html`, junto a los demás botones de la barra:

```html
<button id="btn-jarvis" class="boton-texto" data-perm="jarvis.usar"
        title="Abrir Jarvis">Jarvis</button>
```

Y donde se enganchan los eventos:

```javascript
// El token va en el fragmento: no llega al servidor de Jarvis dentro de la
// URL, asi que no queda en sus logs ni se filtra por la cabecera Referer.
document.getElementById('btn-jarvis').addEventListener('click', () => {
  window.open(
    'https://JARVIS_URL/entrar#t=' + encodeURIComponent(Auth.currentToken),
    '_blank'
  );
});
```

- [ ] **Step 3: Comprobar a mano**

Entrar sin el permiso y comprobar que no aparece; concederlo y comprobar que
abre Jarvis ya dentro.

- [ ] **Step 4: Commit**

```bash
cd C:\Users\Jorge\whatsapp-analytics
git add public/index.html
git commit -m "Acceso directo a Jarvis desde cotizaciones"
```

---

## Task 11: El botón en cobranzas

**Files:**
- Modify: `C:\Users\Jorge\cobranzas-dashboard\client\src\App.jsx`

Cobranzas es React y no usa el catálogo en el navegador: el servidor le manda la
lista de permisos ya resuelta.

- [ ] **Step 1: Ver cómo llegan los permisos y el token**

Run: `cd C:\Users\Jorge\cobranzas-dashboard && grep -n "permissions" client/src/App.jsx | head -10`
Expected: el estado donde se guarda el array de permisos.

Run: `cd C:\Users\Jorge\cobranzas-dashboard && grep -rn "access_token\|session\b" client/src/*.js client/src/*.jsx | head -8`
Expected: de dónde sale el token de la sesión de Supabase en este frontend.

- [ ] **Step 2: Añadir el botón**

En `client/src/App.jsx`, junto a los demás elementos de la barra superior,
usando los nombres reales que hayas visto en el Step 1:

```jsx
{permissions.includes('jarvis.usar') && (
  <button
    className="boton-texto"
    title="Abrir Jarvis"
    onClick={() => window.open(
      // El token va en el fragmento: no llega al servidor de Jarvis dentro de
      // la URL, asi que no queda en sus logs ni se filtra por Referer.
      'https://JARVIS_URL/entrar#t=' + encodeURIComponent(token),
      '_blank'
    )}
  >
    Jarvis
  </button>
)}
```

- [ ] **Step 3: Comprobar que compila**

Run: `cd C:\Users\Jorge\cobranzas-dashboard\client && npm run build`
Expected: build sin errores.

- [ ] **Step 4: Comprobar a mano**

Entrar sin el permiso y comprobar que no aparece; concederlo y comprobar que
abre Jarvis ya dentro.

- [ ] **Step 5: Commit**

```bash
cd C:\Users\Jorge\cobranzas-dashboard
git add client/src/App.jsx
git commit -m "Acceso directo a Jarvis desde cobranzas"
```

---

# Fase D — Cierre

## Task 12: Verificación final

- [ ] **Step 1: Las pruebas de los dos lados**

```bash
cd C:\Users\Jorge\jarvis && .venv/Scripts/python.exe -m pytest tests/ -q
cd C:\Users\Jorge\dashboard-ws-dinamico && node test/permcatalog.test.js
```

Expected: todo en verde.

- [ ] **Step 2: Las seis copias del catálogo siguen idénticas**

Son **seis** archivos en **cinco** repos. La copia de la app móvil
(`nebo-inbox-mobile`) no aparecía en la primera versión de este plan: se
descubrió al implementar, leyendo el encabezado del propio catálogo.

```bash
cd C:\Users\Jorge
diff -q dashboard-ws-dinamico/auth/permcatalog.js whatsapp-analytics/permcatalog.js
diff -q dashboard-ws-dinamico/auth/permcatalog.js cobranzas-dashboard/server/permcatalog.js
diff -q dashboard-ws-dinamico/public/js/permcatalog.js whatsapp-analytics/public/js/permcatalog.js
diff -q dashboard-ws-dinamico/public/js/permcatalog.js nebo-inbox-mobile/www/js/permcatalog.js
```

Expected: sin salida en los cuatro.

La app móvil no lleva botón de Jarvis —no se pidió— pero su copia se mantiene
sincronizada: si se dejara atrás, la próxima replicación en sentido contrario
borraría el grupo de los demás paneles.

- [ ] **Step 3: Que nada cambió para quien ya entraba**

Arrancar Jarvis sin `SUPABASE_ANON_KEY` y comprobar que se entra con la
contraseña de siempre y que avisa por consola de que el acceso desde los paneles
está apagado.

- [ ] **Step 4: La prueba de verdad, con una persona real**

Con todo desplegado:

1. Marcarle **Usar Jarvis** a alguien en `users.html`.
2. Que entre desde los tres paneles y comprobar que Jarvis lo saluda por su
   nombre y que su conversación está vacía, no la de otro.
3. Comprobar que **no** le aparecen Fuentes ni Consumo.
4. Marcarle también **Administrar Jarvis**, recargar, y comprobar que ahora sí.
5. Quitarle las dos casillas y comprobar que en un minuto queda fuera.
