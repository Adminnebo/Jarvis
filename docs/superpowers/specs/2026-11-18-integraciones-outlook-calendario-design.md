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

## A verificar antes de construir (paso 0 del plan)

Con una cuenta de prueba conectada al perfil "Nebo" de Zernio:

1. Rutas exactas de email: listar/buscar hilos, leer mensaje, enviar, responder.
   La doc solo nombra `/email/list-email-threads`; envío ya probado en
   correo-servicio (`POST /v1/email/messages`).
2. Si leer correo exige el add-on de Inbox (ya contratado para WhatsApp; confirmar).
3. Forma del webhook `message.received` para correo: `platform`, id de cuenta,
   id de hilo/mensaje.
4. Rutas de calendario: `GET /v1/calendar/events` y `POST /v1/calendar/events`
   confirmadas en la doc; buscar si hay endpoint de free-busy/disponibilidad y
   los nombres de campos del cuerpo de creación (`participants`, `timezone`,
   `start`/`end`, `conferencing`).

Lo que salga de aquí se anota en este spec antes de seguir.

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
3. **Callback**: valida el estado, guarda `integraciones(app='outlook')` con
   `cuenta` = dirección de correo y `token` = `accountId` de Zernio cifrado con
   `secretos.cifrar`. Sin cambios de esquema en `integraciones`.
4. **Desconectar**: `zernio.desconectar_cuenta(accountId)` y fila en
   `desconectado`. El perfil se conserva (lo comparte WhatsApp).
5. **Pérdida de permiso**: `412 account_scope_missing`, 401/404 de la cuenta o
   evento `account.disconnected` de una cuenta de Outlook →
   `marcar_desconectado(usuario, motivo, app='outlook')` y aviso en la campanita
   "Tu Outlook se desconectó, reconéctalo en Integraciones".

## Correo

- **Ids con proveedor**: `correo.py` antepone `g:` (Gmail) u `o:` (Outlook) a los
  ids que devuelve. Un id sin prefijo se toma como Gmail (compatibilidad con
  avisos ya creados).
- **buscar**: consulta todos los proveedores conectados; une por fecha
  (más reciente primero), respeta `cuantos` en total y marca cada línea con
  `[Gmail]` / `[Outlook]`. La consulta va como texto libre; los operadores de
  Gmail (`from:`, `subject:`) solo aplican a Gmail.
- **leer / responder**: por el prefijo del id.
- **correo nuevo** (sin `responder_a`): con un solo proveedor, sale de ese; con
  dos, `preparar_correo` devuelve "¿Lo mando desde Gmail (x@…) o desde Outlook
  (y@…)?" y acepta un parámetro nuevo opcional `desde` (`gmail`/`outlook`).
- El borrador y su vigencia (10 min) no cambian; el `Borrador` guarda el proveedor.
- **Avisos**: `outlook.recibir(evento)` toma `message.received` de correo,
  descarta lo enviado por la persona, clasifica con `avisos.clasificar(reglas,
  correo, usuario, etiqueta="avisos-outlook")` y crea el aviso con
  `app='outlook'`. `zernio_eventos` ya evita procesar dos veces.
- **Barrido de respaldo** cada 30 min por persona conectada: hilos recibidos
  desde el último visto (cursor en `integraciones.cursor`), mismo filtro.

## Calendario

Herramientas (disponibles si la persona tiene Outlook conectado):

- `ver_agenda(desde, hasta)`: por defecto hoy y mañana. Hora local, título,
  invitados, enlace de Teams.
- `ver_disponibilidad(desde, hasta, duracion)`: huecos libres dentro del horario
  laboral. Usa el endpoint de disponibilidad de Zernio si existe; si no, resta
  los eventos (no los rechazados ni los marcados "libre") al horario.
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
- Avisa cuando faltan ≤ `JARVIS_AVISO_REUNION_MIN` (15) minutos y no hay fila en:

```sql
CREATE TABLE IF NOT EXISTS reuniones_avisadas (
    usuario_id TEXT NOT NULL,
    evento_id TEXT NOT NULL,
    inicio TEXT NOT NULL,
    avisado TEXT NOT NULL,
    PRIMARY KEY (usuario_id, evento_id, inicio)
);
```

  Si la reunión se mueve, cambia `inicio` y vuelve a avisar. Filas de más de
  7 días se podan.
- Se omiten eventos de todo el día, rechazados y cancelados.
- Aviso `tipo='reunion'`, `app='outlook'`, `ref=evento_id@inicio`: hora, título,
  enlace de Teams y, si hay invitados que no son la persona, un resumen de 2-3
  líneas. Para cada invitado (máx. 3) se busca lo último en correo
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
