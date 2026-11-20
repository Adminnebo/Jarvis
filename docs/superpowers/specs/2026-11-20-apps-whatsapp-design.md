# Apps dentro de Jarvis — 1: WhatsApp

Fecha: 2026-11-20 · Rama: `feat/apps-whatsapp` (sale de `main`)
Antes: `2026-11-19-whatsapp-evolution-design.md` (instancia de Evolution por persona).

## Objetivo

Que la persona use su WhatsApp **dentro de Jarvis** sin notar diferencia con
WhatsApp Web (computadora) o la app (celular): chats, mensajes en tiempo real,
fotos, notas de voz, documentos, responder citando, checks. Es la primera de
tres "apps" (después Gmail y Calendario), que vivirán como pestañas de la
misma vista.

## Decisiones

| Tema | Decisión |
|---|---|
| Orden | WhatsApp primero (datos ya disponibles, nadie tiene que reconectar) |
| Pantallas | Computadora (> 900 px): dos paneles como WhatsApp Web. Celular: lista ↔ chat como la app |
| Estilo | El modo oscuro de WhatsApp Web (paleta, burbujas con piquito, checks, fondo con patrón tenue). **Sin** logos ni marca de WhatsApp: la barra dice "WhatsApp · +1 809…" en la barra de Jarvis |
| Datos | Jarvis hace de intermediario con Evolution; el navegador nunca ve la clave; cada persona solo su instancia |
| Tiempo real | Server-Sent Events: Jarvis reenvía al navegador los eventos del webhook de Evolution |
| Archivos | Se piden a Evolution al verlos (base64) y no se guardan en Jarvis; fotos de perfil en caché 1 día (memoria) |
| Dónde | Vista nueva a pantalla completa `/apps/whatsapp` (archivo `web/apps.html` + `web/apps/whatsapp.js`), botón "WhatsApp" en el menú de Jarvis, barra fina de Jarvis arriba para volver |
| Tecnología | JS sin framework, como el resto de Jarvis |

## Primera versión

- Lista de chats: foto, nombre, hora, último mensaje ("Tú:" + checks si es
  propio), contador verde de no leídos, búsqueda por nombre/número/texto.
- Conversación: burbujas, separadores Hoy/Ayer/fecha, hora y checks
  (reloj → ✓ → ✓✓ → ✓✓ azul), mensajes nuevos en tiempo real, cargar
  anteriores al subir.
- Ver/escuchar: foto (abre en grande), video, nota de voz y audio
  (reproductor con avance y duración), documento (ícono, nombre, tamaño,
  descarga), sticker sin burbuja.
- Enviar: texto con emojis, foto/video/documento (≤ 16 MB, con pie opcional),
  nota de voz grabada en el navegador.
- Responder citando (flecha al pasar el mouse; deslizar en celular).
- Marcar como leído al abrir el chat (se refleja en el teléfono).
- Nuevo chat escribiendo un número.

Fuera (segunda versión): reacciones, reenviar, borrar/editar, destacados,
grupos (siguen ignorados), estados, llamadas, "escribiendo…".

## Servidor

### `backend/evolution_wa.py` (se amplía)

| Función | Evolution |
|---|---|
| `mensajes(instancia, jid, limite, pagina)` | `POST /chat/findMessages` con `page`; cada mensaje normalizado lleva además `tipo` (texto/imagen/video/audio/nota/documento/sticker), `estado` (pendiente/enviado/entregado/leido), `cita` (id y texto del citado), `archivo` (nombre, mime, tamaño, duración, miniatura base64 si la trae) |
| `chats(...)` | igual que hoy + `ultimo_estado` y `ultimo_tipo` |
| `archivo(instancia, id_mensaje)` | `POST /chat/getBase64FromMediaMessage` → `{mime, nombre, base64}` |
| `foto_perfil(instancia, jid)` | `POST /chat/fetchProfilePictureUrl` → URL o None |
| `marcar_leido(instancia, jid, ids)` | `POST /chat/markMessageAsRead` |
| `enviar(instancia, jid, texto, cita=None)` | `sendText` con `quoted` |
| `enviar_archivo(instancia, jid, tipo, mime, nombre, base64, pie, cita)` | `sendMedia` |
| `enviar_nota(instancia, jid, base64, cita)` | `sendWhatsAppAudio` |
| `asegurar_eventos(instancia, webhook)` | `POST /webhook/set` con `MESSAGES_UPSERT`, `MESSAGES_UPDATE`, `SEND_MESSAGE`, `CONNECTION_UPDATE`, `QRCODE_UPDATED` (las instancias nuevas se crean ya con estos) |

### `backend/apps_whatsapp.py` (nuevo)

La lógica de la vista, sobre la instancia de quien la pide (la de
`whatsapp_chats._instancia`; sin instancia conectada → 409 y la vista muestra
el QR de vincular).

- Canal en vivo por persona: una cola en memoria por cada navegador abierto
  (`suscribir(usuario) → cola`, `publicar(usuario, evento)`), con latido cada
  25 s. `whatsapp_chats.recibir_evolution` publica cada evento normalizado:
  `mensaje` (nuevo, entrante o propio), `estado` (cambio de checks),
  `conexion`.
- Caché de fotos de perfil (1 día).
- La primera vez que alguien abre la vista en este proceso se llama a
  `asegurar_eventos` para su instancia.

### Rutas (todas con la sesión de la persona)

| Ruta | Qué |
|---|---|
| `GET /apps/whatsapp` | la página |
| `GET /api/apps/whatsapp/chats` | lista |
| `GET /api/apps/whatsapp/chats/{jid}/mensajes?pagina=` | mensajes (30 por página) |
| `POST /api/apps/whatsapp/chats/{jid}/leido` | marcar leído |
| `POST /api/apps/whatsapp/chats/{jid}/mensajes` | enviar texto `{texto, cita}` |
| `POST /api/apps/whatsapp/chats/{jid}/archivo` | enviar archivo (multipart: archivo, pie, cita) |
| `POST /api/apps/whatsapp/chats/{jid}/nota` | enviar nota de voz (multipart: audio) |
| `GET /api/apps/whatsapp/archivo/{id_mensaje}?jid=` | el archivo de un mensaje (bytes con su tipo) |
| `GET /api/apps/whatsapp/foto/{jid}` | foto de perfil (redirige a la URL, o 404) |
| `GET /api/apps/whatsapp/eventos` | Server-Sent Events |

Un número nuevo (`jid` = dígitos) se normaliza con `whatsapp.normalizar_numero`
y se convierte en `<numero>@s.whatsapp.net`. Todo `jid` que no sea chat
personal (grupo, broadcast) → 400.

## Interfaz (`web/apps.html`, `web/apps/whatsapp.js`, `web/apps/whatsapp.css`)

- Barra de Jarvis (alto 40 px): volver, "WhatsApp · número".
- Computadora: panel izquierdo 30 % (mín. 340 px) con cabecera, buscador y
  lista; derecho con cabecera del chat, mensajes y barra de escribir.
- Celular (≤ 900 px): una sola columna; abrir chat empuja la conversación;
  `history.pushState` para que "atrás" del teléfono vuelva a la lista.
- Barra de escribir: emoji (selector propio, sin librerías), adjuntar,
  texto (Enter envía, Shift+Enter salto), micrófono/enviar.
- Nota de voz con `MediaRecorder` (webm/ogg-opus); computadora: clic para
  empezar y clic para enviar; celular: mantener presionado; descartar.
- Envío optimista: la burbuja aparece con reloj; si falla, ícono rojo y
  "Reintentar".
- Franja "Reconectando…" si se corta el canal en vivo; al volver, recarga la
  lista y el chat abierto.
- Sin instancia conectada: el QR/código de vincular dentro de la vista
  (reusa `/api/integraciones/whatsapp/vincular`).

## Pruebas

- `evolution_wa`: cada llamada nueva con MockTransport (ruta, cuerpo) y la
  normalización de cada tipo de mensaje, estados y citas.
- `apps_whatsapp` y rutas: permisos (sin sesión, sin instancia, jid de grupo),
  envío de texto/archivo/nota, archivo de un mensaje, canal en vivo (publicar
  llega solo a esa persona), webhook → evento publicado.
- Interfaz: capturas en 1280 px y 400 px con un Evolution falso con datos de
  ejemplo (lista, chat con todos los tipos, cita, grabando, sin conexión).
- Prueba real con el número de Jorge.
