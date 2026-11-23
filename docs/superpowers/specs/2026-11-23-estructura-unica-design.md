# Una sola estructura para Jarvis y sus apps, con Jarvis en todas partes

Fecha: 2026-11-23 · Rama: `feat/estructura` (sale de `main`)
Antes: las apps `/apps/whatsapp`, `/apps/correo`, `/apps/calendario` (specs del 20 y 23 de noviembre).

## Problema

Arriba de Jarvis hay 11 enlaces de texto que mezclan lo de todos (WhatsApp,
Correo, Calendario, Integraciones) con lo de administración (Consumo, Fuentes,
Asistente, Dispositivos, Memoria, Reiniciar). Cada app es otra página con su
barra; cambiar de una a otra recarga todo, y Jarvis no sabe qué tiene abierto
la persona.

## Decisiones

| Tema | Decisión |
|---|---|
| Estilo | Las apps conservan su estilo (WhatsApp, Gmail, Google Calendar); lo común (barra, menús, avisos) es igual |
| Navegación | Computadora: barra lateral de íconos (Jarvis, WhatsApp, Correo, Calendario; abajo avisos, Ajustes, Jarvis rápido). Celular: barra de pestañas abajo (Jarvis, WhatsApp, Correo, Calendario, Más) |
| Cómo se cargan | `/` es la estructura; cada vista va en un `<iframe>` que se crea la primera vez y queda vivo. La pantalla de siempre pasa a `/asistente` (iframe con permiso de micrófono) |
| Dirección | `/#whatsapp`, `/#correo`, `/#calendario`, `/` = Jarvis. La consulta de `/` (`?integraciones=gmail`, `?volver=…`) pasa al asistente |
| Páginas viejas | `/apps/…` abiertas fuera de la estructura redirigen a `/#app` |
| Ajustes | Menú con Integraciones; para super admin también Consumo, Fuentes, Organización (si es admin de org), Asistente, Dispositivos, Memoria, Reiniciar. Abre el panel de siempre dentro del asistente (`postMessage`) |
| Contadores | `GET /api/apps/resumen` (caché 45 s): WhatsApp sin leer, Recibidos sin leer, próximo evento de hoy |
| Jarvis rápido | Computadora: orbe en la barra y Ctrl+J → panel derecho (380 px) para escribir o dictar. Celular: la pestaña Jarvis muestra el chip "Sobre: …" |
| Contexto | Cada app manda a la estructura (`postMessage {tipo: "contexto", app, texto}`) lo que tiene abierto; la estructura lo pasa al panel y al asistente; `/api/chat` acepta `contexto` (≤ 600 caracteres) y se lo da a Jarvis como instrucción de ese turno |
| Conversación | La misma de siempre (memoria por persona): el panel y el asistente la comparten |
| Herramientas nuevas | `mover_evento` y `cancelar_evento` (preparan) + `confirmar_cambio_evento` (hace), sobre Google Calendar; `ver_agenda` muestra el id de cada evento de Google |
| Refrescar | Cuando Jarvis usó herramientas, la estructura avisa a las apps abiertas (`{tipo: "refrescar"}`) |

## Piezas

- `web/estructura.html`, `web/estructura.js`, `web/estructura.css` (la estructura).
- `web/index.html` + `web/app.js`: en modo embebido esconde su menú de arriba,
  escucha `abrir-panel` y `contexto`, manda `contexto` en `/api/chat` y muestra el
  chip; avisa a la estructura cuando usó herramientas.
- Las tres apps: en modo embebido esconden su barra, mandan el contexto,
  responden a `refrescar` y, solas, redirigen a la estructura.
- `backend/main.py`: `/` → estructura, `/asistente` → la pantalla de siempre,
  `contexto` en `PeticionDeChat`, `GET /api/apps/resumen`.
- `backend/acciones_calendario.py` + herramientas.

## Pruebas

Servidor: `/` y `/asistente`, contexto en la instrucción del turno, resumen (con y
sin cada integración), herramientas de mover/cancelar en dos pasos, `ver_agenda`
con id. Interfaz: capturas de la estructura en 1366 y 400 px con cada vista y el
panel de Jarvis abierto. Prueba real con Jorge.
