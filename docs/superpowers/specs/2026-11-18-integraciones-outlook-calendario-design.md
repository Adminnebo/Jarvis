# Integraciones: Outlook (correo y calendario) por Zernio

Fecha: 2026-11-18 · Rama: `feat/integraciones-outlook` (sale de `main`, que ya trae Gmail y WhatsApp)

## Objetivo

Tercera app de la sección **Integraciones** (el "panel de conexiones" de Jarvis).
Cada persona conecta **su cuenta de Microsoft 365 / Outlook.com** y con eso Jarvis:

- busca, lee, redacta y responde sus correos de Outlook con las mismas
  herramientas que ya usa con Gmail (con confirmación por voz),
- avisa de los correos importantes con las mismas reglas de siempre,
- consulta su agenda y sus huecos libres,
- crea reuniones con enlace de Teams, con confirmación por voz,
- le avisa 15 minutos antes de cada reunión, con un resumen de quién es el invitado.

Es la primera de dos etapas. La segunda (proyecto aparte) es **grabar las
reuniones**; el aviso previo de esta etapa es el punto donde después se
engancha el bot de grabación.

## Decisiones

| Tema | Decisión | Por qué |
|---|---|---|
| Dónde vive | Dentro de Jarvis, en Integraciones; no un panel nuevo | Jarvis ya tiene login propio, Gmail, WhatsApp coexistencia, avisos y confirmación por voz (opción A de Jorge) |
| Proveedor | Zernio, cuenta de Nebo, `GET /v1/connect/microsoft?scopes=email,calendar` | Pedido de Jorge: Outlook por Zernio, sin app propia de Microsoft |
| Perfil de Zernio | El mismo perfil por persona que ya usa WhatsApp ("Jarvis · <nombre>") | Un perfil admite un solo WhatsApp, pero sí otras plataformas; no se crean perfiles de más |
| Correo | Una sola capa `correo.py` con dos proveedores; las herramientas no cambian de nombre | El modelo no elige entre herramientas casi iguales; misma lógica de borrador y avisos |
| Con Gmail y Outlook a la vez | Buscar en los dos; leer/responder por el proveedor del id; correo nuevo pregunta desde cuál | Lo natural para quien tiene dos buzones |
| Calendario | Consultar, ver huecos, crear con Teams con confirmación, avisar antes (opción A) | Pedido de Jorge; mover/cancelar/RSVP quedan fuera |
| Horario laboral | Por persona, por defecto L-V 8:00-18:00 `America/Santo_Domingo` | Los huecos libres sin horario no sirven |
| Aviso previo | 15 min antes (`JARVIS_AVISO_REUNION_MIN`), campanita + WhatsApp | Mismo canal que los avisos de correo y chat |
| Correo nuevo de Outlook | Webhook `message.received` de Zernio + barrido de respaldo cada 30 min | Igual que WhatsApp; llega en segundos |

## Lo que se acepta

- Al conectar, la pantalla de Microsoft muestra la app de Zernio, no "Jarvis".
- Algunas organizaciones de Microsoft 365 exigen que su administrador apruebe
  la app antes; esas personas no podrán conectar hasta que lo haga.
- Buzones en Exchange local (on-premises) no funcionan.
- Outlook guarda un solo recordatorio emergente por evento (límite de Zernio);
  no afecta porque el aviso lo da Jarvis.
- Si el tenant no tiene Teams, la reunión se crea sin enlace y Jarvis lo dice.

## API de Zernio que se usa (sacada de https://zernio.com/openapi.json, 2026-11-18)

| Para qué | Llamada |
|---|---|
| Conectar | `GET /v1/connect/microsoft?profileId&scopes=email,calendar&redirect_url` → `authUrl`; vuelve con `connected=microsoft`, `profileId`, `accountId`, `username` |
| Buscar / listar hilos | `GET /v1/email/threads?accountId&searchQueryNative&after&limit&sortOrder=desc` → `data[]` (`id`, `subject`, `snippet`, `participants`, `latestMessageReceivedAt`) |
| Leer hilo | `GET /v1/email/threads/{id}?accountId&clean=true` → `data.messages[]` (`id`, `from`, `to`, `subject`, `text`, `html`, `date`, `clean.text`) |
| Enviar | `POST /v1/email/messages` `{accountId, to:[{email}], subject, text}` + `Idempotency-Key` |
| Responder | `POST /v1/email/messages/{id}/reply` `{accountId, to, subject, text}` + `Idempotency-Key` |
| Agenda | `GET /v1/calendar/events?accountId&from&to&timezone&limit` → `data[]`, `pagination.nextCursor` |
| Huecos libres | `POST /v1/calendar/availability` `{participants:[{accountId, openHours:[{days (0=domingo), timezone, start, end}]}], from, to, durationMinutes}` → `data.timeSlots[]` |
| Crear reunión | `POST /v1/calendar/events` `{accountId, title, start, end, timezone, participants:[{email}], description, conferencing:"teams"}` → `data` con `conferencing.url` |
| Correo nuevo | webhook `message.received` con `account.platform = "microsoft"` y `account.accountId` |

Los campos del mensaje dentro del webhook de correo no están documentados, así
que el webhook **no se lee**: solo marca a la persona "por revisar" y el hilo de
Outlook lista los hilos nuevos desde su cursor.

## A verificar con la primera cuenta real

Jorge todavía no tiene un Outlook de prueba; todo se construye contra la API
documentada y Zernio simulado en pytest. Con la primera cuenta real (perfil
"Nebo" de Zernio) se comprueba: que leer correo no pida otro add-on, que el
webhook llegue con `account.platform = "microsoft"`, y que la reunión vuelva con
`conferencing.url`. Hasta entonces la rama no se fusiona a `main`.

## Arquitectura

```
contenedor jarvis (EC2 54.174.88.26)
  backend/zernio.py          + url_conexion_microsoft, email (buscar, hilo,
                               enviar, responder), calendario (eventos,
                               crear, disponibilidad si existe)
  backend/integraciones.py   + Outlook en _APPS; perfil_zernio() (antes
                               iniciar_whatsapp), guardar_outlook,
                               desconectar_outlook, horario laboral
  backend/outlook.py         NUEVO. Correo de Outlook vía zernio.py: buscar,
                               leer, enviar/responder; recibir() del webhook
                               → clasificar con reglas_aviso → aviso;
                               barrido de respaldo
  backend/correo.py          elige proveedor (Gmail / Outlook / ambos)
  backend/calendario.py      NUEVO. agenda, huecos libres, borrador y
                               confirmación de reunión; hilo del aviso previo
  backend/whatsapp_chats.py  recibir(): lo que no es WhatsApp se desvía a
                               outlook.recibir() en vez de descartarse
  backend/herramientas.py    descripciones de correo en neutro ("tu correo");
                               disponibles con Gmail O Outlook; + ver_agenda,
                               ver_disponibilidad, preparar_reunion,
                               confirmar_reunion
  backend/main.py            /integraciones/outlook/conectar, /callback,
                               DELETE /api/integraciones/outlook,
                               GET/PUT /api/integraciones/outlook/horario
  web/integraciones.js       tarjeta Outlook (conectar, estado, horario laboral)
```

## Conexión

1. La tarjeta **Outlook** ("Correo y calendario de Microsoft 365 / Outlook.com")
   aparece si `zernio.configurado()`.
2. **Conectar** → `/integraciones/outlook/conectar`:
   `zernio.asegurar_webhook(...)`, `integraciones.perfil_zernio(usuario)` y
   redirección a `GET /connect/microsoft` con `profileId`,
   `scopes=email,calendar` y `redirect_url=/integraciones/outlook/callback?estado=…`
   (mismo estado firmado que WhatsApp).
3. **Callback**: valida el estado y que `profileId` sea el de la persona;
   guarda `integraciones(app='outlook')` con `cuenta` = dirección de correo,
   `token` NULL y `cursor` = ahora (no avisa de correo viejo), y el `accountId`
   en una tabla nueva `outlook_cuentas(usuario_id PK, cuenta_id UNIQUE,
   actualizado)`. El `accountId` no es secreto (sin la clave de Zernio no sirve)
   y va en claro para poder buscar de quién es un webhook.
4. **Desconectar**: `zernio.desconectar_cuenta(accountId)`, se borra la fila de
   `outlook_cuentas` y `integraciones` queda en `desconectado`. El perfil se
   conserva (lo comparte WhatsApp).
5. **Pérdida de permiso**: `412 account_scope_missing`, 401/404 de la cuenta o
   evento `account.disconnected` de una cuenta de Outlook →
   `marcar_desconectado(usuario, motivo, app='outlook')` y aviso en la campanita
   "Tu Outlook se desconectó, reconéctalo en Integraciones".

## Correo

- **Ids con proveedor**: los de Outlook llevan `o:` delante y son siempre ids de
  **hilo**; los de Gmail quedan como hoy, sin prefijo (así siguen valiendo los
  avisos ya creados).
- **buscar**: consulta cada buzón conectado (`cuantos` por buzón) y, si hay dos,
  los muestra en dos bloques, `[Gmail]` y `[Outlook]`. En Outlook la consulta va
  como `searchQueryNative` (KQL: palabras, `from:carlos`, `subject:factura`).
- **leer**: por el prefijo. **Responder** en Outlook contesta al último mensaje
  del hilo que no mandó la persona.
- **correo nuevo** (sin `responder_a`): con un solo proveedor, sale de ese; con
  dos, `preparar_correo` devuelve "¿Lo mando desde Gmail (x@…) o desde Outlook
  (y@…)?" y acepta un parámetro nuevo opcional `desde` (`gmail`/`outlook`).
- El borrador y su vigencia (10 min) no cambian; el `Borrador` guarda el proveedor.
- **Avisos**: `outlook.recibir(evento)` solo anota a la persona como "por
  revisar". El hilo `avisos-outlook` (cada 30 s) revisa a quien esté anotado y,
  de respaldo, a todos cada 30 min: lista los hilos con
  `after = cursor`, salta los que no tienen mensajes nuevos de otros, clasifica
  el último mensaje con `avisos.clasificar(..., etiqueta="avisos-outlook")` y
  crea el aviso con `app='outlook'`, `ref = ol:<hilo>:<latestMessageReceivedAt>`
  (un mensaje nuevo en el mismo hilo es otro aviso) y `hilo = o:<hilo>`. Mismo
  manejo de reintentos que Gmail (`correos_vistos`, 3 intentos). El cursor solo
  avanza si todo salió bien.

## Calendario

Herramientas (disponibles si la persona tiene Outlook conectado):

- `ver_agenda(desde, hasta)`: por defecto hoy y mañana. Hora local, título,
  invitados, enlace de Teams.
- `ver_disponibilidad(desde, hasta, duracion)`: huecos libres dentro del horario
  laboral con `POST /calendar/availability` (Zernio ya descuenta lo ocupado).
  Devuelve hasta 8 huecos.
- `preparar_reunion(titulo, inicio, duracion, invitados, notas)`: valida, guarda
  borrador (10 min) y devuelve la frase para leer: "Reunión con Pedro el jueves
  20 de noviembre de 3:00 a 3:30, con Teams. ¿La creo?". No crea nada.
- `confirmar_reunion()`: `POST /calendar/events` con `conferencing: teams`,
  zona de la persona e invitados. Si vuelve sin enlace: "La creé, pero tu cuenta
  no tiene Teams". Borrador vencido o inexistente → no crea y lo dice.

Horario laboral: tabla nueva

```sql
CREATE TABLE IF NOT EXISTS horario_laboral (
    usuario_id TEXT PRIMARY KEY,
    inicio TEXT NOT NULL DEFAULT '08:00',
    fin TEXT NOT NULL DEFAULT '18:00',
    dias TEXT NOT NULL DEFAULT '1,2,3,4,5',   -- 1 = lunes
    zona TEXT NOT NULL DEFAULT 'America/Santo_Domingo'
);
```

Sin fila = valores por defecto. Se edita en la tarjeta de Outlook.

## Aviso antes de cada reunión

- Hilo `calendario.arrancar()` (se lanza junto a los de avisos y WhatsApp), cada
  5 min. Por cada persona con Outlook conectado: eventos de los próximos 30 min.
- Avisa cuando faltan ≤ `JARVIS_AVISO_REUNION_MIN` (15) minutos y todavía no
  existe el aviso `ref = reunion:<evento_id>@<inicio>` (la restricción UNIQUE de
  `avisos` ya impide duplicarlo; se consulta antes para no pagar la IA de más).
  Si la reunión se mueve, cambia `inicio` y vuelve a avisar.
- Se omiten eventos de todo el día, rechazados y cancelados.
- Aviso `tipo='reunion'`, `app='outlook'`: `remitente` = título, `asunto` =
  enlace de Teams, `resumen` = hora, título y, si hay invitados que no son la
  persona, un resumen de 2-3 líneas. En WhatsApp sale como "📅 …" con el enlace. Para cada invitado (máx. 3) se busca lo último en correo
  (`correo.buscar` por su dirección) y en WhatsApp (`whatsapp_chats.buscar` por
  nombre); la IA de avisos (`avisos.modelo()`) resume. Si no hay nada: "Sin
  historial con <invitado>".
- Se manda por WhatsApp con el mismo envío de `avisos.mandar_pendientes`
  (respeta `reglas_aviso.activo` y el número configurado).
- Un fallo con una persona se registra en el log y no frena a las demás.

## Errores

- Toda falla de Zernio llega a la persona como una frase clara (`ErrorCorreo` /
  `ErrorCalendario`), nunca como traza.
- 429 de Zernio: "Outlook no responde por ahora, intento en un momento"; el hilo
  reintenta en la vuelta siguiente.
- Pérdida de permiso: ver Conexión, punto 5.

## Pruebas (pytest, Zernio simulado como en los tests de WhatsApp)

- Conectar → callback → fila `outlook` con accountId cifrado; desconectar borra
  en Zernio y conserva el perfil.
- `buscar` con Gmail + Outlook une y marca origen; `leer`/`responder` van al
  proveedor del prefijo; id sin prefijo = Gmail.
- Correo nuevo con dos proveedores pide `desde`; con uno, no.
- Webhook `message.received` de Outlook crea aviso; uno de WhatsApp sigue yendo
  a WhatsApp; evento repetido no duplica.
- `412 account_scope_missing` marca Outlook desconectado y avisa.
- Huecos libres respetan horario, días y zona; ignoran eventos rechazados.
- `preparar_reunion` + `confirmar_reunion` crea con `conferencing: teams`;
  borrador vencido no crea; sin enlace de Teams lo dice.
- Aviso previo sale una vez; se repite si cambia `inicio`; no sale para eventos
  de todo el día.

## Fuera de esta etapa

- Mover, cancelar o responder invitaciones (RSVP).
- Google Calendar.
- Grabación y transcripción de reuniones (siguiente proyecto: bot externo tipo
  Recall.ai que entra a la reunión desde el aviso previo; no cabe correr la
  grabación en el t3.micro).

## Despliegue

Push a `main` = producción (timer `desplegar.sh` en el EC2). Antes: pytest en
verde y el paso 0 verificado. Variable nueva opcional:
`JARVIS_AVISO_REUNION_MIN` en `jarvis.env`.
