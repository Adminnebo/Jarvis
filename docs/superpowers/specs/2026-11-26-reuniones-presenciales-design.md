# Reuniones presenciales: grabar desde Jarvis (web y APK de Android)

Fecha: 2026-11-26. Sigue a `2026-11-24-bot-grabacion-meet-design.md`.

## Qué se quiere

Grabar una reunión en persona desde Jarvis y que termine igual que una de Meet:
transcripción con quién habla, resumen, puntos clave, tareas, aviso por WhatsApp y
búsqueda. Tres formas de grabar:

1. **Celular en el navegador** (Jarvis web, también en iPhone).
2. **Computadora** (mismo código que 1).
3. **APK de Android** que sigue grabando con la pantalla apagada o la app cerrada.

Fuera de alcance: app de iPhone (no hay cuenta de Apple), Zoom/Teams, grabar el
audio de una llamada del propio teléfono.

## Idea central: el aparato hace de bot

El pipeline del bot ya resuelve todo lo de después de grabar (pedazos de 5 min,
transcripción, cierre, aviso, retención de 90 días, «Grabando ahora»). Lo
presencial reutiliza su contrato tal cual: el aparato recibe un **token de subida
por reunión** (el mismo mecanismo `token_hash` del bot) y habla con las mismas rutas
libres de sesión:

- `POST /api/reuniones/{id}/audio?n=N&inicio_s=S` — un pedazo (cuerpo = audio).
- `POST /api/reuniones/{id}/eventos` — `{"tipo": "terminado", "motivo":
  "usuario"|"sacada"|"maximo"}` al terminar (no hay «admitido»: nace grabando).
- `POST /api/reuniones/{id}/hablantes` — `{"linea": []}` (no hay mosaicos).

Así el APK puede subir desde un servicio nativo sin la cookie de la web, y la web
y el APK no necesitan rutas distintas.

## Backend (Jarvis)

### Datos

Columnas nuevas (vía `_COLUMNAS_NUEVAS`, sin migraciones a mano):

| Tabla | Columna | Para qué |
|---|---|---|
| `reuniones` | `tipo TEXT` | `NULL`/`'meet'` o `'presencial'` |
| `reuniones` | `nombres TEXT` | JSON `{"Hablante 1": "Jorge"}`: renombres (IA + usuario) |
| `reunion_pedazos` | `formato TEXT` | `ogg`, `webm` o `mp4` (la extensión del archivo) |
| `reunion_pedazos` | `inicio_s INTEGER` | segundo de la reunión en que empieza el pedazo |

Una presencial se crea con `clave = "presencial:<uuid>"`, `meet_url = ""`,
`inicio = ahora`, `fin = ahora + 4 h` (tope), `estado = 'grabando'`,
`grabando_desde = ahora` e interesado = quien la crea.

### Rutas nuevas (con sesión)

- `POST /api/reuniones/presencial` `{titulo?}` → `{id, token, pedazo_s: 300, max_s: 14400}`.
  El token se devuelve solo esta vez (se guarda su hash). Título por defecto:
  «Reunión presencial de las HH:MM».
- `PUT /api/reuniones/{id}/nombres` `{de: "Hablante 2", a: "Lucas"}` → cambia la
  etiqueta en la transcripción, el resumen, los puntos y las tareas
  (`responsable`). Solo el interesado. `a` vacío vuelve a la etiqueta original.

### Cambios a lo existente

- **Audio**: la ruta del bot acepta el formato por `Content-Type`
  (`audio/ogg` → ogg, `audio/webm` → webm, `audio/mp4` → mp4; otro → 415) e
  `inicio_s` opcional. `ruta_pedazo`, `almacen_reuniones` y `transcribir` usan la
  extensión y el tipo guardados. Un pedazo repetido sigue dando 409, y el cliente
  lo toma como «ya subido».
- **La respuesta del audio** incluye `{"parar": true}` si la reunión ya no está
  `grabando` (la sacaron desde «Grabando ahora» o desde otro aparato). Así el
  aparato se entera sin consultar aparte.
- **`sacar`** para una presencial no llama al bot: pasa a `procesando` con
  `terminada = ahora` y `motivo = "sacada"`. Lo que el aparato suba en los
  120 s de gracia de `_lista_para_cerrar` entra igual.
- **`terminado`** de una presencial deja `linea = []` (no hay que esperar
  hablantes de nadie).
- **`en_curso`** ya la muestra (estado `grabando` con `grabando_desde`); la
  tarjeta dice «En persona» en vez del link de Meet y el botón dice «Terminar».
- **`con_nombres`** usa los tiempos de `inicio_s` cuando existen (si no,
  `(n-1)*300` como hoy).
- **Tope**: si una presencial sigue `grabando` pasadas 4 h + 10 min, el
  trabajador de fondo la cierra (por si el aparato murió sin avisar).

### Quién habla en una presencial

El modelo separa voces dentro de cada pedazo, pero «A» del pedazo 1 no es por
fuerza «A» del pedazo 2. Para que sigan siendo la misma persona:

1. Los pedazos de una presencial se transcriben **en orden** (el `n` siguiente
   espera a que el anterior esté `transcrito` o `fallido`).
2. Del primer pedazo en que aparece cada voz se recorta su segmento más largo
   entre 2 y 10 s con ffmpeg (wav mono 16 kHz) y se guarda en
   `reuniones/<id>/voces/Hablante N.wav`. Hasta 4 voces (límite del modelo).
3. Los pedazos siguientes se mandan con `known_speaker_names` y
   `known_speaker_references` (data URL) en `extra_body`. Las etiquetas que
   devuelve son esos nombres; una voz nueva (letra) pasa a ser el siguiente
   «Hablante N» y, si hay lugar, suma su referencia.
4. Al cerrar, el resumen pide además `"nombres": {"Hablante 1": "Jorge"}` con los
   nombres que se **dicen** en la conversación (nada inventado). Se guardan en
   `nombres` y se aplican a la transcripción y al resumen.
5. En el detalle, cada «Hablante N» (o nombre deducido) se toca para renombrarlo.

ffmpeg se agrega a la imagen de Jarvis (`apt-get install ffmpeg`). Si el recorte
falla, se sigue sin referencias (peor continuidad, nada se rompe).

## Web (celular y computadora)

En Reuniones, arriba de «Grabando ahora»: botón **Grabar reunión presencial** →
pide título opcional → pide el micrófono → pantalla de grabación con reloj,
medidor de nivel (para ver que el micrófono oye) y **Terminar**.

Módulo nuevo `web/apps/grabadora.js` (una sola responsabilidad: grabar y subir):

- `MediaRecorder` con el primer tipo que soporte el navegador
  (`audio/webm;codecs=opus`, `audio/ogg;codecs=opus`, `audio/mp4`), 24 kbps.
- **Un grabador nuevo cada 300 s** (parar y arrancar): cada pedazo es un archivo
  completo que el modelo puede leer solo. Los fragmentos de `timeslice` no sirven
  (solo el primero trae cabecera).
- Cada pedazo se guarda primero en **IndexedDB** y se sube; se borra al recibir
  200 o 409. Si falla, se reintenta con espera creciente y al volver la conexión.
  Lo que quede sin subir se sube al volver a abrir Reuniones.
- **Wake Lock** mientras graba (la pantalla no se apaga sola).
- Si la página se oculta (bloqueo, cambio de app) y el navegador corta el
  micrófono, al volver se avisa «La grabación estuvo en pausa N min» y sigue en
  un pedazo nuevo con su `inicio_s` real.
- Al llegar `parar: true` o a las 4 h, termina sola.
- Al cerrar la pestaña con algo grabando, el navegador pregunta antes
  (`beforeunload`).

El token de subida vive en IndexedDB junto a los pedazos de esa reunión.

## APK de Android

Carpeta `movil/` en el repo de Jarvis:

- **Capacitor** con `server.url = https://asistente.neboaiconsulting.com`: la
  app abre el Jarvis de siempre (la cookie de sesión funciona igual, mismo
  origen), así la interfaz se actualiza sin sacar otro APK.
- **Plugin nativo `GrabadoraPresencial`** (Kotlin, dentro de `movil/android/`,
  que sí se versiona porque lleva código propio):
  - `iniciar({reunionId, token, base, pedazoS, maxS})`, `terminar()` y
    `estado()`, que devuelve `{grabando, segundos, pendientes}`.
  - **Servicio en primer plano** de tipo `microphone`, con la notificación fija
    «Jarvis está grabando · 12:35» y el botón «Terminar». Lo exige Android y
    también hace que el sistema no lo mate.
  - `MediaRecorder` de Android → OGG/Opus mono 16 kHz 24 kbps (API 29+), un
    archivo cada 300 s.
  - El propio servicio sube cada archivo, con token y `inicio_s`, desde una
    carpeta de cola. Lo borra al recibir 200 o 409 y reintenta si no hay red.
    Si recibe `parar: true`, termina.
  - Permisos: `RECORD_AUDIO`, `FOREGROUND_SERVICE`,
    `FOREGROUND_SERVICE_MICROPHONE`, `POST_NOTIFICATIONS`, `INTERNET`.
    `minSdk 29`.
- `grabadora.js` detecta `window.Capacitor?.isNativePlatform()` y, si está el
  plugin, le pasa la reunión en vez de usar `MediaRecorder`. La pantalla de
  grabación consulta `estado()` para el reloj.
- **GitHub Actions** (`.github/workflows/apk.yml`): compila el APK de depuración
  en cada push a `main` que toque `movil/` (o a mano) y lo deja en Artifacts,
  como nebo-inbox-mobile. Sin firma de tienda.

## Errores y casos límite

| Caso | Qué pasa |
|---|---|
| Sin permiso de micrófono | Mensaje claro (el de `app.js`) y no se crea la reunión |
| Se cae internet | Los pedazos esperan en IndexedDB / en la cola nativa |
| Token inválido o reunión borrada | 401 → se descarta la cola de esa reunión y se avisa |
| Navegador sin `MediaRecorder` | Botón desactivado con «Este navegador no puede grabar» |
| Pedazo silencioso | El modelo devuelve 0 segmentos; si todo está vacío: «No se escuchó conversación» (ya existe) |
| Aparato muere sin «terminado» | Tope de 4 h + 10 min la cierra con lo que llegó |
| Más de 4 voces | La quinta en adelante sale como «Hablante N» por pedazo; se corrige a mano |

## Pruebas

- **Backend (pytest)**: crear presencial y token; audio webm/mp4/ogg y 415;
  `parar` en la respuesta; `sacar` presencial sin bot; transcripción en orden;
  referencias de voz (con ffmpeg y modelo simulados) y renombre de voces nuevas;
  `nombres` desde el resumen; `PUT nombres` en transcripción, resumen y tareas;
  tope de 4 h; columnas nuevas sobre una base vieja.
- **Web**: prueba en navegador local con micrófono falso de Chromium
  (`--use-fake-device-for-media-stream`). Se acorta el pedazo a 10 s para ver
  dos pedazos subidos, un corte de red (cola y reintento) y Terminar.
- **APK**: compila en Actions; prueba real en un Android por parte de Jorge
  (grabar, bloquear la pantalla 6 min, terminar desde la notificación).
- **Real**: una reunión presencial de 10-15 min con 2-3 personas para ver la
  continuidad de voces y los nombres deducidos.

## Entregas

1. **PR A — backend + web**: todo lo de arriba menos `movil/`.
2. **PR B — APK**: `movil/`, plugin, workflow y la detección en `grabadora.js`.
3. **Prueba real** y ajustes.
