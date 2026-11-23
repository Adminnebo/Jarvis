# Apps dentro de Jarvis — 3: Calendario (Google)

Fecha: 2026-11-23 · Rama: `feat/apps-calendario` (sale de `main`)
Antes: `2026-11-20-apps-whatsapp-design.md`, `2026-11-23-apps-correo-design.md`.

## Objetivo

El Google Calendar de cada persona **dentro de Jarvis**, lo más parecido a Google
Calendar (computadora) y a su app (celular): todos sus calendarios, vistas de
día, semana, mes y agenda, crear, mover, estirar, editar, borrar y responder
invitaciones.

## Decisiones

| Tema | Decisión |
|---|---|
| Permisos | Se suma `https://www.googleapis.com/auth/calendar.calendarlist.readonly` (lista de calendarios) a los que ya pide Gmail (`calendar.events` para leer y escribir eventos en todos ellos). Una reconexión por persona |
| Sin la lista | Si la persona dio `calendar.events` pero no la lista, se muestra solo el calendario principal con una franja "Reconectar" |
| Sin calendario | Sin `calendar.events` (o sin Gmail): pantalla "Conectar tu calendario de Google" |
| Outlook | Segunda versión (Zernio no permite mover ni borrar eventos) |
| Datos | Jarvis hace de intermediario con la API de Google Calendar; el token no sale del servidor |
| Dónde | `/apps/calendario` (`web/apps-calendario.html`, `web/apps/calendario.js`, `web/apps/calendario.css`); tercera pestaña junto a WhatsApp y Correo |
| Horas | La vista trabaja en la zona del navegador y manda ISO con desfase; los de todo el día van como fechas (fin exclusivo, como Google) |
| Al día | Cada 60 s se vuelve a pedir el rango visible |
| Recurrentes | Editar o borrar pregunta "solo este evento" o "todos los eventos"; "todos" cambia el evento madre (si cambió la hora, se corre la madre lo mismo que se corrió la instancia) |
| Avisos a invitados | Crear, cambiar y borrar con `sendUpdates=all` |
| Estilo | El de Google Calendar en modo oscuro, sin logos ni marca |

## Primera versión

- Vistas Día, Semana (de entrada en computadora), Mes y Agenda; Hoy, ‹ ›; línea
  de la hora actual; mini calendario; Mis calendarios con color y casilla
  (recordada en el navegador).
- Ver: tarjeta con título, cuándo, ubicación, Meet, invitados con su respuesta,
  descripción, calendario; botones editar, borrar, y Sí/No/Quizás si es
  invitación.
- Crear: clic o arrastre en un hueco → tarjeta rápida (título, guardar, "Más
  opciones"); editor completo: título, fecha/hora o todo el día, calendario,
  invitados, agregar Meet, ubicación, descripción, aviso previo.
- Mover arrastrando y cambiar la duración estirando (computadora).
- Celular: entra en Agenda; Día y 3 días; ☰; botón flotante +; mover = editar.

Fuera: Outlook, crear repeticiones, buscar eventos, tareas, zona por evento.

## Servidor

### `backend/gmail.py`
`CALENDARIOS = .../calendar.calendarlist.readonly` en `PERMISOS`.

### `backend/apps_calendario.py` (nuevo, habla con Google Calendar)

- `calendarios(token)` → `[{id, nombre, color, texto, principal, puede_editar}]`
  (`calendarList`; solo los de la lista).
- `eventos(token, calendario, desde, hasta)` → normalizados:
  `{id, calendario, titulo, inicio, fin, todo_el_dia, ubicacion, descripcion,
  color, meet, invitados[{correo, nombre, estado, yo, organizador}],
  mi_respuesta, recurrente, puede_editar, aviso_min, enlace}`.
- `eventos_de(token, calendarios, desde, hasta)` en paralelo (hasta 8); un
  calendario que falla se salta.
- `crear(token, calendario, datos)`, `cambiar(token, calendario, id, datos,
  todos=False)`, `borrar(token, calendario, id, todos=False)`,
  `responder(token, calendario, id, respuesta)`.
- `colores(token)` (paleta de `colorId`, en caché).

### Rutas (`backend/rutas_apps_calendario.py`, con sesión)

| Ruta | Qué |
|---|---|
| `GET /apps/calendario` | la página |
| `GET /api/apps/calendario/estado` | conectado, cuenta, si tiene la lista, zona |
| `GET /api/apps/calendario/calendarios` | lista (o solo el principal) |
| `GET /api/apps/calendario/eventos?desde=&hasta=&calendarios=a,b` | eventos del rango |
| `POST /api/apps/calendario/eventos` | crear `{calendario, titulo, inicio, fin, todo_el_dia, invitados, meet, ubicacion, descripcion, aviso_min}` |
| `PATCH /api/apps/calendario/eventos/{calendario}/{id}?todos=` | cambiar (los campos que vengan) |
| `DELETE /api/apps/calendario/eventos/{calendario}/{id}?todos=` | borrar |
| `POST /api/apps/calendario/eventos/{calendario}/{id}/respuesta` | `{respuesta: si/no/quizas}` |

Sin calendario → 409 `{conectar: true}`. Rango máximo 62 días.

## Pruebas

`apps_calendario` con MockTransport (normalización, todo el día, Meet,
invitados, permisos de edición, recurrentes "todos" con corrimiento,
respuesta), rutas con TestClient (409, rango, crear, cambiar, borrar,
responder), capturas en 1366 y 400 px con un Google falso. Prueba real con la
cuenta de Jorge.
