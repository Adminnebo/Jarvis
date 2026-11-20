# Apps — WhatsApp: plan de implementación

> Spec: `docs/superpowers/specs/2026-11-20-apps-whatsapp-design.md`. Rama `feat/apps-whatsapp`.
> Pruebas: `.venv/Scripts/python.exe -m pytest -q`. TDD en cada tarea: prueba que falla → código → pasa → commit.

Datos comprobados contra el Evolution real (v2.3.7, solo lectura, 2026-11-20):
- `findMessages` devuelve `records` del más nuevo al más viejo y acepta `page`.
- Cada registro: `key {id, fromMe, remoteJid, remoteJidAlt?}`, `pushName`, `messageType`,
  `message {<tipo>Message: {...}}`, `messageTimestamp`, `contextInfo {stanzaId, quotedMessage, participant}`,
  `MessageUpdate: [{status}]` (SERVER_ACK / DELIVERY_ACK / READ / PLAYED).
- Archivos: `fileLength {low, high}`, `mimetype`, `fileName`, `caption`, `seconds`, `ptt`, `jpegThumbnail` (base64).
- Un solo proceso de uvicorn en el contenedor: el canal en vivo puede vivir en memoria.

## Tareas

1. **`evolution_wa`: mensajes ricos.** `normalizar_mensaje(registro)` → `{id, jid, entrante, nombre, momento,
   tipo, texto, estado, cita, archivo}`; `mensajes(..., pagina)`; `chats` con `ultimo_estado`/`ultimo_tipo`.
   Pruebas: un registro de cada tipo (texto, extendido, imagen con miniatura, video, nota, audio, documento,
   sticker, reacción → se omite), estado por `MessageUpdate`, cita por `contextInfo`, página.
2. **`evolution_wa`: acciones.** `archivo`, `foto_perfil`, `marcar_leido`, `enviar(..., cita)`,
   `enviar_archivo`, `enviar_nota`, `asegurar_eventos`; `crear` con los eventos nuevos.
   Pruebas: ruta y cuerpo de cada llamada.
3. **`apps_whatsapp`: canal en vivo y caché.** `suscribir/desuscribir/publicar` (asyncio.Queue por navegador,
   seguro entre hilos), `foto` con caché de 1 día, `instancia_de(usuario)` (409 si no hay) y
   `asegurar_eventos` una vez por proceso. `whatsapp_chats.recibir_evolution` publica `mensaje`, `estado`,
   `conexion`. Pruebas: publicar llega solo al dueño; el webhook publica cada tipo de evento.
4. **Rutas.** Las de la tabla del spec + `GET /apps/whatsapp`. Pruebas con TestClient: sin instancia → 409,
   grupo → 400, número nuevo → jid, enviar texto/archivo/nota, archivo de un mensaje, foto, SSE (primer
   evento), página servida.
5. **Interfaz.** `web/apps.html`, `web/apps/whatsapp.js`, `web/apps/whatsapp.css`, botón en el menú.
   Revisión con un Evolution falso con datos de ejemplo y capturas en 1280 y 400 px.
6. **Despliegue y prueba real** (con OK de Jorge).
