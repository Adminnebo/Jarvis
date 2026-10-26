# Rediseño "Grafito minimal" — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cambiar el aspecto de toda la web de Jarvis al estilo Grafito minimal sin tocar la estructura ni la lógica.

**Architecture:** Solo CSS (más un menú "⋯" para el celular): `web/style.css` pasa a tokens nuevos y se reescriben los bloques de cada componente en su lugar; las páginas de `backend/acceso.py` y `web/privacidad.html` usan los mismos valores. Los `id` y clases que usa el JS no cambian. Se verifica con capturas (Electron) de un Jarvis local con datos de ejemplo.

**Tech Stack:** CSS, HTML, un poco de JS (menú del celular), Electron de `C:\Users\Jorge\monitor-ec2` para capturas, FastAPI local.

**Spec:** `docs/superpowers/specs/2026-10-26-rediseno-grafito-design.md`. **Rama:** `feat/rediseno-grafito` (sale de `feat/avatar-holograma`, lo que corre en el EC2).

**Regla de despliegue:** solo si `pytest` pasa, con `if .venv/Scripts/python.exe -m pytest -q >/dev/null 2>&1; then ...` (nunca leyendo la salida con `| tail`).

---

## Mapa de archivos

| Archivo | Cambio |
|---|---|
| `web/index.html` | Fuentes Inter/JetBrains Mono; botón "⋯" del menú del celular. |
| `web/style.css` | Tokens y estilos de todos los componentes. |
| `web/app.js` | Abrir/cerrar el menú "⋯" (10 líneas). |
| `backend/acceso.py` | `_ESTILO` de login/registro con los tokens nuevos. |
| `web/privacidad.html` | Colores y fuente. |
| `tests/test_ids_web.py` | Que todos los `$("id")` de `web/*.js` existan en `index.html`. |
| Scratchpad: `capturas/` | Servidor local con datos de ejemplo + script de capturas (no va al repo). |

---

### Task 1: Prueba de ids y capturas "antes"

**Files:**
- Create: `tests/test_ids_web.py`
- Create (scratchpad, fuera del repo): `capturas/iniciar.sh`, `capturas/capturar.cjs`

- [ ] **Step 1: Prueba de ids**

```python
"""Ningun id que busca el JS de la web puede desaparecer del HTML (rediseno sin romper nada)."""

import re
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"


def test_todos_los_ids_que_usa_el_js_existen():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    existentes = set(re.findall(r'id="([^"]+)"', html))
    usados = set()
    for js in WEB.glob("*.js"):
        texto = js.read_text(encoding="utf-8")
        usados |= set(re.findall(r'\$\$?\("([\w-]+)"\)', texto))
        usados |= set(re.findall(r'getElementById\("([\w-]+)"\)', texto))
    faltan = sorted(usados - existentes)
    assert not faltan, f"El JS busca ids que no estan en index.html: {faltan}"
```

Run: `.venv/Scripts/python.exe -m pytest tests/test_ids_web.py -v` → PASS hoy (si falla, anotar los ids que ya faltaban y excluirlos con una lista `CONOCIDOS` explicando por qué; no cambiar el JS).

- [ ] **Step 2: Servidor local con datos de ejemplo** (`capturas/iniciar.sh`, en el scratchpad)

```bash
#!/usr/bin/env bash
# Jarvis local para capturas: sin contrasena (usuario por defecto, admin), con una
# organizacion de paneles con foto y una conversacion de ejemplo.
set -e
DATOS="$(dirname "$0")/datos"
rm -rf "$DATOS" && mkdir -p "$DATOS"
cd /c/Users/Jorge/jarvis
export JARVIS_DATA_DIR="$DATOS" JARVIS_ORGANIZACION_PANELES="JH Electroalambres" JARVIS_NOMBRE="Nebo"
.venv/Scripts/python.exe - <<'PY'
import json, urllib.request
from backend import acceso, asistente, cuentas, memoria
cuentas.asegurar_organizacion_de_paneles()
asistente.guardar_nombre(cuentas.ID_PANELES, "Camila Reyes")
foto = urllib.request.urlopen("https://images.unsplash.com/photo-1544005313-94ddf0286df2?w=600&q=80").read()
asistente.guardar_foto(cuentas.ID_PANELES, foto)
memoria.guardar_conversacion(acceso.por_defecto().id, [
    {"role": "user", "content": "¿Cuántas ventas se hicieron hoy?"},
    {"role": "assistant", "content": "Hoy van 15 ventas. La más grande fue de 48.300 pesos, de Ferretería Ortiz."},
    {"role": "user", "content": "¿Y cuántos clientes activos tenemos?"},
    {"role": "assistant", "content": "Tienen 6.352 clientes activos."},
])
PY
exec .venv/Scripts/python.exe -m uvicorn backend.main:app --port 8765
```

- [ ] **Step 3: Script de capturas** (`capturas/capturar.cjs`)

```js
// Uso: node_modules/.bin/electron capturar.cjs <prefijo>   (desde C:\Users\Jorge\monitor-ec2, con ELECTRON_RUN_AS_NODE sin definir)
const { app, BrowserWindow } = require('electron');
const fs = require('fs'), path = require('path');
const espera = (ms) => new Promise((r) => setTimeout(r, ms));
const prefijo = process.argv[process.argv.length - 1];
const BASE = 'http://localhost:8765';
const PANTALLAS = [
  ['principal', null],
  ['fuentes', '#btn-fuentes'], ['consumo', '#btn-consumo'], ['asistente', '#btn-asistente'],
  ['organizacion', '#btn-organizacion'], ['dispositivos', '#btn-dispositivos'], ['memoria', '#btn-memoria'],
];
app.whenReady().then(async () => {
  for (const [ancho, alto, caso] of [[1400, 900, 'pc'], [390, 844, 'tel']]) {
    const win = new BrowserWindow({ width: ancho, height: alto, show: false, useContentSize: true });
    for (const [nombre, boton] of PANTALLAS) {
      await win.loadURL(BASE + '/');
      await espera(2500);
      if (boton) {
        await win.webContents.executeJavaScript(
          `(document.querySelector('${boton}')?.removeAttribute('hidden'), document.querySelector('${boton}')?.click())`);
        await espera(1800);
      }
      fs.writeFileSync(path.join(__dirname, `${prefijo}-${caso}-${nombre}.png`), (await win.webContents.capturePage()).toPNG());
    }
    await win.loadURL(BASE + '/acceso');
    await espera(800);
    fs.writeFileSync(path.join(__dirname, `${prefijo}-${caso}-login.png`), (await win.webContents.capturePage()).toPNG());
    win.destroy();
  }
  app.quit();
});
```

- [ ] **Step 4: Capturas "antes"**: iniciar el servidor en segundo plano, correr `env -u ELECTRON_RUN_AS_NODE node_modules/.bin/electron <scratchpad>/capturas/capturar.cjs antes` desde `C:\Users\Jorge\monitor-ec2`, mirar 2–3 capturas con Read para confirmar que el arnés funciona.

- [ ] **Step 5: Commit** (solo la prueba): `git add tests/test_ids_web.py && git commit -m "Prueba: los ids que usa el JS siguen en index.html"`

---

### Task 2: Tokens, fuentes y base

**Files:** `web/index.html` (head), `web/style.css:1-23`

- [ ] **Step 1: Fuentes** — en `web/index.html`, antes del `<link rel="stylesheet" href="/style.css">`:

```html
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
```

- [ ] **Step 2: Reemplazar `:root` y `body`** (líneas 1–23) por:

```css
:root {
  /* Grafito minimal: una sola superficie oscura, bordes de 1 px y un solo acento. */
  --fondo: #0a0a0b;
  --superficie: #111113;
  --superficie-2: #16161a;
  --panel: var(--superficie);          /* nombre viejo: lo usan reglas y JS */
  --borde: #232327;
  --borde-fuerte: #2e2e34;
  --texto: #ececf0;
  --tenue: #7d7d86;
  --muy-tenue: #55555c;
  --acento: #4da3ff;
  --acento-suave: rgba(77, 163, 255, 0.12);
  --peligro: #ff6b6b;
  --ok: #3ddc84;
  --aviso: #f5b84d;
  --claro: #ededf0;                    /* botones principales */
  --radio: 8px;
  --radio-chico: 6px;
  --fuente: "Inter", system-ui, -apple-system, "Segoe UI", sans-serif;
  --mono: "JetBrains Mono", ui-monospace, Consolas, monospace;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--fondo);
  color: var(--texto);
  font: 14px/1.55 var(--fuente);
  -webkit-font-smoothing: antialiased;
}

::selection { background: var(--acento-suave); }
```

- [ ] **Step 3:** reemplazar en todo el archivo `ui-monospace, Consolas, monospace` y `ui-monospace, monospace` por `var(--mono)`; los `rgba(7, 9, 14, 0.92)` por `rgba(10, 10, 11, 0.92)`.

- [ ] **Step 4:** pytest pasa; commit "Grafito: tokens, Inter y fondo plano".

---

### Task 3: Barra superior y botones de texto

**Files:** `web/style.css` (bloques `.barra` → `.boton-texto`, ~27–147)

- [ ] **Step 1:** reemplazar `.barra`, `.marca h1`, `.punto`, `.bombillo`, `.meta`, `.nombre-usuario`, `#btn-volver`, `.boton-texto` por:

```css
.barra {
  position: sticky;
  top: 0;
  z-index: 30;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 20px;
  border-bottom: 1px solid var(--borde);
  background: rgba(10, 10, 11, 0.92);
  backdrop-filter: blur(8px);
  flex-wrap: wrap;
}

.marca { display: flex; align-items: center; gap: 10px; }

.marca h1 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: -0.01em;
}

.punto {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: var(--muy-tenue);
  transition: background 0.3s;
}
.punto.ok       { background: var(--ok); }
.punto.problema { background: var(--peligro); }

.bombillo {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 8px;
  margin-left: 4px;
  border-radius: var(--radio-chico);
  border: 1px solid var(--borde);
  background: transparent;
  color: var(--tenue);
  font: 11px var(--mono);
  cursor: default;
}
```

(los `.led*` y `@keyframes parpadeo` quedan como están; `.bombillo.recargable` igual)

```css
.acciones { display: flex; align-items: center; gap: 4px; }

.meta { color: var(--tenue); font-size: 12px; margin-right: 8px; }

.nombre-usuario {
  color: var(--texto);
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  margin-right: 8px;
}

#btn-volver { color: var(--acento); }

.boton-texto {
  background: none;
  border: none;
  border-radius: var(--radio-chico);
  color: var(--tenue);
  font: 13px var(--fuente);
  cursor: pointer;
  padding: 6px 9px;
  transition: color 0.15s, background 0.15s;
}
.boton-texto:hover { color: var(--texto); background: var(--superficie-2); }
```

- [ ] **Step 2:** capturas (`electron capturar.cjs paso3`) y mirar `paso3-pc-principal.png`. Commit "Grafito: barra superior".

---

### Task 4: Entrada (campo, micrófono, manos libres, voz en vivo)

**Files:** `web/style.css` (bloques "Barra de entrada" y "Voz en vivo", ~373–462)

- [ ] **Step 1:** reemplazar `.entrada`, `#campo`, `.boton-microfono` (+`:hover`, `.activo`), `.interruptor`, `.boton-vivo` (+`:hover`, `.activo`) por:

```css
/* Una sola caja con todo adentro: el campo de texto sin borde propio. */
.entrada {
  position: sticky;
  top: var(--alto-barra, 52px);
  z-index: 3;
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 14px auto 0;
  width: min(780px, calc(100% - 32px));
  padding: 5px 5px 5px 14px;
  border: 1px solid var(--borde);
  border-radius: 10px;
  background: var(--superficie);
  flex-wrap: wrap;
  transition: border-color 0.15s;
}
.entrada:focus-within { border-color: var(--acento); }

#campo {
  flex: 1;
  min-width: 160px;
  padding: 8px 0;
  border: none;
  background: transparent;
  color: var(--texto);
  font: 14px var(--fuente);
  outline: none;
}
#campo::placeholder { color: var(--muy-tenue); }

.boton-microfono {
  width: 32px; height: 32px;
  flex: none;
  border-radius: 7px;
  border: none;
  background: var(--claro);
  color: #0a0a0b;
  display: grid;
  place-items: center;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.boton-microfono:hover { background: #fff; }
.boton-microfono.activo { background: var(--acento); color: #04121f; }
.boton-microfono svg { width: 17px; height: 17px; }

.interruptor {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--tenue);
  font-size: 12px;
  cursor: pointer;
  white-space: nowrap;
}
.interruptor input { accent-color: var(--acento); cursor: pointer; }

.boton-vivo {
  flex: none;
  padding: 6px 11px;
  border-radius: var(--radio-chico);
  border: 1px solid var(--borde-fuerte);
  background: transparent;
  color: var(--texto);
  font: 12.5px var(--fuente);
  cursor: pointer;
  white-space: nowrap;
  transition: border-color 0.15s, color 0.15s;
}
.boton-vivo:hover { border-color: var(--tenue); }
.boton-vivo.activo {
  border-color: var(--peligro);
  color: #ffc9c9;
  animation: respirar 2.2s ease-in-out infinite;
}
```

(`.boton-microfono[hidden]`, los `svg path`, `:disabled` y `@keyframes respirar` quedan.)

Como `.entrada` ya no ocupa todo el ancho, el `<input type="file">` y el botón de imagen (`#btn-imagen`, clase `boton-microfono`) siguen dentro: el de imagen toma el estilo del micrófono, que es lo correcto.

- [ ] **Step 2:** capturas, mirar. Commit "Grafito: campo de entrada".

---

### Task 5: Escena y conversación

**Files:** `web/style.css` (`.pie-orbe` ~216, "Conversacion" ~258–367)

- [ ] **Step 1:** `.pie-orbe`:

```css
.pie-orbe {
  margin: 0;
  color: var(--tenue);
  font-size: 11px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  min-height: 18px;
  text-align: center;
}
```

- [ ] **Step 2:** reemplazar `.conversacion`, `.mensaje`, `.mensaje.usuario`, `.mensaje.jarvis`, `.mensaje.error` por:

```css
.conversacion {
  flex: 1;
  overflow-y: auto;
  padding: 0 20px 32px;
  display: flex;
  flex-direction: column-reverse;
  justify-content: flex-end;
  gap: 16px;
  max-width: 780px;
  width: 100%;
  margin: 0 auto;
}

/* Sin burbujas: tus mensajes en gris con "Tú", las respuestas en blanco con
   una linea de acento a la izquierda. */
.mensaje {
  max-width: 100%;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  line-height: 1.6;
  animation: aparecer 0.25s ease;
}

.mensaje.usuario { align-self: stretch; color: var(--tenue); }
.mensaje.usuario::before {
  content: "Tú";
  display: block;
  margin-bottom: 2px;
  color: var(--muy-tenue);
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.mensaje.jarvis {
  align-self: stretch;
  color: var(--texto);
  border-left: 2px solid var(--acento);
  padding-left: 12px;
}

.mensaje.error {
  align-self: stretch;
  color: #ffc9c9;
  border-left: 2px solid var(--peligro);
  padding-left: 12px;
  font-size: 13px;
}
```

(`.mensaje.imagen`, adjuntos y `.nota` quedan; en `.adjunto-ficha` y `.mensaje.imagen img` cambiar `border-radius: 10px` por `var(--radio)`.)

- [ ] **Step 3:** capturas, mirar la conversación. Commit "Grafito: conversación sin burbujas".

---

### Task 6: Paneles, modales, tablas, formularios, chips

**Files:** `web/style.css` (~466–1061)

- [ ] **Step 1: Insignia, panel, cabecera, cerrar**

```css
.insignia {
  padding: 2px 8px;
  border-radius: var(--radio-chico);
  border: 1px solid var(--borde);
  color: var(--tenue);
  font-size: 11px;
  white-space: nowrap;
}
.insignia::before { content: ""; display: inline-block; width: 6px; height: 6px; margin-right: 6px;
  border-radius: 50%; background: var(--ok); vertical-align: 1px; }
.insignia.insignia-alerta::before { background: var(--peligro); }

.panel {
  position: fixed;
  top: var(--alto-barra, 52px);
  right: 0; bottom: 0;
  z-index: 20;
  width: min(420px, 92vw);
  background: var(--superficie);
  border-left: 1px solid var(--borde);
  padding: 16px 18px;
  overflow-y: auto;
  box-shadow: -24px 0 48px rgba(0, 0, 0, 0.45);
}

.panel-barra {
  position: sticky;
  top: 0;
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: -16px -18px 14px;
  padding: 12px 18px;
  background: var(--superficie);
  border-bottom: 1px solid var(--borde);
}
.panel-barra h2 { margin: 0; font-size: 13px; font-weight: 600; letter-spacing: 0.01em; }

.boton-cerrar {
  flex: none;
  width: 28px; height: 28px;
  border-radius: var(--radio-chico);
  border: none;
  background: transparent;
  color: var(--tenue);
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
  display: grid;
  place-items: center;
}
.boton-cerrar:hover { color: var(--texto); background: var(--superficie-2); }
```

- [ ] **Step 2: Tarjetas y listas** — en `.hecho`, `.fuente`, `.organizacion-consumo`, `.tarjeta`, `.codigo-vinculo`, `.asistente-video`, `.acceso-propuesta`: `border-radius` → `var(--radio)`, quitar fondos con `rgba(255,255,255,.02)`/`rgba(77,163,255,.06)` (dejar `transparent`), `.etiqueta` en `color: var(--tenue)` (no acento). `.tarjeta.destacada`: `border-color: var(--borde-fuerte); background: var(--superficie-2);` y `.tarjeta-valor` siempre `var(--texto)`.

- [ ] **Step 3: Chips y estados** — reemplazar `.chip*`:

```css
.chip {
  padding: 2px 8px;
  border-radius: var(--radio-chico);
  font-size: 11px;
  border: 1px solid var(--borde);
  color: var(--tenue);
  white-space: nowrap;
}
.chip-tipo    { color: var(--texto); }
.chip-ok::before, .chip-alerta::before { content: ""; display: inline-block; width: 6px; height: 6px;
  margin-right: 5px; border-radius: 50%; vertical-align: 1px; }
.chip-ok::before     { background: var(--ok); }
.chip-alerta::before { background: var(--peligro); }
.chip-apagado { opacity: 0.6; }
```

- [ ] **Step 4: Botones** — `.boton-mini`, `.boton-primario`, `.boton-secundario`:

```css
.boton-mini {
  padding: 5px 10px;
  border-radius: var(--radio-chico);
  border: 1px solid var(--borde);
  background: transparent;
  color: var(--texto);
  font: 12.5px var(--fuente);
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}
.boton-mini:hover { background: var(--superficie-2); border-color: var(--borde-fuerte); }
.boton-mini.peligro:hover { border-color: var(--peligro); color: var(--peligro); }

.boton-primario, .boton-secundario {
  padding: 8px 16px;
  border-radius: var(--radio-chico);
  font: 500 13px var(--fuente);
  cursor: pointer;
  border: 1px solid transparent;
}
.boton-primario { background: var(--claro); color: #0a0a0b; }
.boton-primario:hover { background: #fff; }
.boton-secundario { background: transparent; border-color: var(--borde); color: var(--texto); }
.boton-secundario:hover { background: var(--superficie-2); }
```

- [ ] **Step 5: Formularios** — en `.campo label` `font-size: 12px`; los campos (`.campo input…`, `#consola-sql-texto`, `.leyenda-tabla`, `.filtros select`, `.diccionario input/textarea`, `.acceso-propuesta …`, `.acceso-nuevo input`) con:

```css
  border-radius: var(--radio-chico);
  border: 1px solid var(--borde);
  background: var(--fondo);
```

y un foco común al final del archivo:

```css
.campo input:focus, .campo select:focus, #consola-sql-texto:focus, .leyenda-tabla:focus,
.filtros select:focus, .diccionario input:focus, .diccionario textarea:focus,
.acceso-propuesta input:focus, .acceso-propuesta textarea:focus, .acceso-nuevo input:focus {
  outline: none;
  border-color: var(--acento);
  box-shadow: 0 0 0 3px var(--acento-suave);
}
```

y borrar la regla duplicada `.campo select { background: var(--fondo); … }` del bloque del asistente (queda cubierta).

- [ ] **Step 6: Modal y tablas**

```css
.modal { background: rgba(0, 0, 0, 0.6); backdrop-filter: blur(2px); }   /* se suma a la regla existente */
.modal-caja { background: var(--superficie); border-radius: 12px; }      /* idem */
.modal-caja .panel-barra { border-radius: 12px 12px 0 0; }

.tabla-scroll { border-radius: var(--radio); }
.tabla-scroll table { font-size: 12.5px; font-variant-numeric: tabular-nums; }
.tabla-scroll th {
  background: var(--superficie);
  color: var(--tenue);
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.tabla-scroll tbody tr:hover { background: var(--superficie-2); }
```

- [ ] **Step 7:** capturas de todos los paneles, mirar. pytest. Commit "Grafito: paneles, tablas y formularios".

---

### Task 7: Login, registro y privacidad

**Files:** `backend/acceso.py` (`_ESTILO`), `web/privacidad.html` (`<style>`)

- [ ] **Step 1:** reemplazar `_ESTILO` por:

```python
_ESTILO = """
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
  body { margin:0; min-height:100vh; display:grid; place-items:center; background:#0a0a0b;
         color:#ececf0; font:14px/1.55 "Inter",system-ui,sans-serif; -webkit-font-smoothing:antialiased; }
  .caja { width:min(360px,92vw); padding:28px; border:1px solid #232327; border-radius:12px; background:#111113; }
  h1 { margin:0 0 4px; font-size:15px; font-weight:600; }
  p { color:#7d7d86; font-size:13px; }
  a { color:#4da3ff; text-decoration:none; } a:hover { text-decoration:underline; }
  input { width:100%; box-sizing:border-box; margin-top:12px; padding:9px 12px; border-radius:6px;
          border:1px solid #232327; background:#0a0a0b; color:#ececf0; font:inherit; outline:none; }
  input:focus { border-color:#4da3ff; box-shadow:0 0 0 3px rgba(77,163,255,.12); }
  button { width:100%; margin-top:14px; padding:9px; border:none; border-radius:6px; background:#ededf0;
           color:#0a0a0b; font:inherit; font-weight:500; cursor:pointer; }
  button:hover { background:#fff; }
  code { background:#0a0a0b; padding:2px 6px; border:1px solid #232327; border-radius:4px; color:#ececf0;
         font:12.5px "JetBrains Mono",ui-monospace,monospace; }
  .mal { color:#ffc9c9; font-size:13px; margin-top:14px; }
  .bien { color:#9be9a8; font-size:13px; margin-top:14px; }
  ol { color:#7d7d86; font-size:13px; padding-left:20px; }
  li { margin-bottom:8px; }
"""
```

- [ ] **Step 2:** en `web/privacidad.html`, en su `<style>`, cambiar los colores de fondo/texto/bordes por los tokens (`#0a0a0b`, `#111113`, `#232327`, `#ececf0`, `#7d7d86`, acento `#4da3ff`) y la fuente del cuerpo a Inter (agregar el `<link>` de Google Fonts del Task 2).

- [ ] **Step 3:** pytest (hay pruebas que leen el HTML de login: deben seguir pasando). Capturas del login. Commit "Grafito: login, registro y privacidad".

---

### Task 8: Celular — menú "⋯" y entrada abajo

**Files:** `web/index.html` (barra), `web/app.js`, `web/style.css`

- [ ] **Step 1:** en `index.html`, dentro de `.acciones`, como **primer** hijo:

```html
      <button id="btn-menu" class="boton-texto boton-menu" type="button" aria-label="Más opciones"
              aria-expanded="false">⋯</button>
```

- [ ] **Step 2:** en `web/app.js`, junto a los otros `addEventListener` de la barra:

```js
// Celular: los accesos de la barra se pliegan en un menu "⋯".
$("btn-menu").addEventListener("click", (e) => {
  const abierto = document.querySelector(".acciones").classList.toggle("abierto");
  e.currentTarget.setAttribute("aria-expanded", String(abierto));
});
document.querySelector(".acciones").addEventListener("click", (e) => {
  if (e.target.closest(".boton-texto:not(#btn-menu)")) document.querySelector(".acciones").classList.remove("abierto");
});
```

- [ ] **Step 3:** reemplazar el `@media (max-width: 620px)` existente por:

```css
.boton-menu { display: none; font-size: 18px; line-height: 1; }

@media (max-width: 720px) {
  .barra { padding: 10px 14px; }
  .escena { padding-top: 16px; }
  .orbe { width: 88px; height: 88px; }
  .orbe .nucleo { width: 36px; height: 36px; }
  .interruptor span { display: none; }

  /* Los accesos de admin, plegados en "⋯". */
  .acciones { position: relative; }
  .boton-menu { display: block; }
  .acciones > .boton-texto:not(.boton-menu) { display: none; }
  .acciones.abierto > .boton-texto:not(.boton-menu):not([hidden]) {
    display: block; position: relative; width: 100%; text-align: left;
  }
  .acciones.abierto {
    flex-direction: column; align-items: stretch;
    position: absolute; top: 100%; right: 10px; z-index: 40;
    min-width: 180px; padding: 6px; border: 1px solid var(--borde); border-radius: var(--radio);
    background: var(--superficie); box-shadow: 0 12px 32px rgba(0, 0, 0, 0.5);
  }

  /* La entrada abajo, para el pulgar. */
  .entrada {
    position: sticky; top: auto; bottom: 0; order: 10;
    width: 100%; margin: 0; border-radius: 0; border-width: 1px 0 0;
    background: var(--fondo); padding: 8px 10px calc(8px + env(safe-area-inset-bottom));
  }
  .entrada:focus-within { border-color: var(--borde); }
  .panel { width: 100vw; }
}
```

(`order: 10` funciona porque `body` es flex en columna: la entrada pasa al final sin mover el HTML.)

- [ ] **Step 4:** pytest (incluye `test_ids_web.py`). Capturas `tel`. Commit "Grafito: celular con menú ⋯ y entrada abajo".

---

### Task 9: Revisión final y despliegue

- [ ] **Step 1:** capturas finales (`final`) de todo, en pc y celular; compararlas con `antes`. Corregir lo que se vea mal (desbordes, contrastes, algo que quedó con el estilo viejo).
- [ ] **Step 2:** pytest completo; push de `feat/rediseno-grafito`.
- [ ] **Step 3:** desplegar al EC2 con la regla de la cabecera:

```bash
if .venv/Scripts/python.exe -m pytest -q >/dev/null 2>&1; then
  git archive HEAD backend web requirements.txt Procfile | ssh ec2 'sudo sh -c "cd /opt/jarvis/jarvis && rm -rf backend web && tar xf - && cd .. && docker compose build -q jarvis && docker builder prune -af >/dev/null && docker compose up -d jarvis"'
fi
```

y comprobar `https://asistente.neboaiconsulting.com/api/salud`.
- [ ] **Step 4:** mostrarle a Jorge las capturas finales (pc y celular).
