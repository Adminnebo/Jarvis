# Bot de grabación de reuniones de Google Meet

Fecha: 2026-11-24 · Rama: `feat/bot-grabacion-meet` (sale de `main`)
Antes: `2026-11-18-integraciones-outlook-calendario-design.md` (el aviso previo
es el punto de enganche que ese diseño dejó anotado).

## Objetivo

Un bot propio, al estilo de Fathom, que entra a las reuniones de Google Meet de
la agenda de cada persona, graba el audio y le deja a la persona, dentro de
Jarvis, la transcripción con nombres, el resumen y las tareas. A WhatsApp le
llega el resumen corto. Un solo sistema, sin pagar Fathom por persona.

## Decisiones

| Tema | Decisión | Por qué |
|---|---|---|
| Plataformas | Solo Google Meet | Pedido de Jorge; cada plataforma tiene su propio mantenimiento |
| Cuándo entra | Interruptor por persona «Grabar siempre»; si está apagado, el aviso previo pregunta «Grabar» | Opciones 1 y 2 de Jorge |
| Qué reuniones | Eventos de Google Calendar u Outlook con un link `meet.google.com/xxx-xxxx-xxx` en la videollamada, la ubicación o la descripción | Son las únicas a las que el bot sabe entrar |
| Resultado | Todo en la sección **Reuniones** de Jarvis + resumen corto por WhatsApp con link | Opción 1 de Jorge |
| Video | No se graba; solo audio | Costo de máquina y almacenamiento |
| Cuenta del bot | Una cuenta de Google de Nebo (p. ej. `notas@neboaiconsulting.com`, nombre «Jarvis · Notas») | Pedido de Jorge |
| Técnica | Chromium manejado por Playwright (Python) + ffmpeg grabando el audio de la tarjeta de sonido virtual (opción A) | La más robusta: si Google cambia la página se rompe entrar, no la grabación |
| Dónde corre | EC2 nuevo y aparte, t3.small (2 GB) para 1–2 bots a la vez; se sube a t3.medium si la medición no alcanza | Un Chrome colgado no tumba Jarvis ni nebocore |
| Código | Carpeta `bot-meet/` en este repo, Docker propio, despliegue propio | Comparte pruebas y contrato con Jarvis sin compartir máquina |
| Transcripción | En Jarvis, por la API de OpenAI, modelo con hablantes (`gpt-4o-transcribe-diarize`), configurable con `JARVIS_MODELO_REUNIONES` | El bot no hace trabajo pesado; el modelo actual se retira en 2027 |
| Audio guardado | Bucket privado `reuniones` en Supabase Storage, se borra a los 90 días; el texto queda | Jarvis ya guarda archivos allí |

## Lo que se acepta

- La cuenta del bot es externa a JH: el anfitrión tiene que admitirlo desde la
  sala de espera, salvo que la reunión deje entrar a cualquiera con el link.
- Google no autoriza oficialmente los bots en Meet. Puede cambiar la página o
  pedir verificar la cuenta, y entonces hay que darle mantenimiento al bot.
- Los participantes saben que se graba porque el bot aparece en la lista y
  escribe un aviso en el chat. No hay una aprobación formal de cada uno.
- Más de 2 reuniones grabadas a la vez: la tercera recibe «no hay bot libre».

## Componentes

### 1. Bot de Meet (`bot-meet/`, EC2 nuevo)

Un servicio chico en Python (FastAPI) que en reposo no abre ningún Chrome.

- `POST /v1/sesiones`: agenda una sesión `{id, meet_url, inicio, fin,
  token_subida, url_jarvis}`. El pedido va firmado con HMAC-SHA256 usando
  `BOT_MEET_SECRETO`, compartido con Jarvis. Responde `202` si la acepta, `409
  sin_bot_libre` si ya hay 2 sesiones que se cruzan en esa franja y `400` si
  el link no es de Meet.
- `DELETE /v1/sesiones/{id}`: cancela una sesión agendada o saca al bot de la
  reunión.
- `GET /v1/salud`: estado, sesiones activas, RAM y CPU.
- Las sesiones agendadas se guardan en un archivo JSON en disco y se retoman
  al reiniciar.

**Al llegar la hora** (1 minuto antes del inicio):

1. Abre Chromium con un perfil persistente donde está la sesión de Google del
   bot. Flags: `--headless=new` (si no sale audio, respaldo con Xvfb a
   640×360), `--disable-gpu`, `--use-fake-ui-for-media-stream`,
   `--use-fake-device-for-media-stream`, sin extensiones ni sincronización.
2. Entra al link con cámara y micrófono apagados y espera hasta 10 minutos a
   que lo admitan.
3. Ya adentro, pone en los ajustes de Meet «Resolución de recepción: Solo
   audio» y escribe en el chat: «Jarvis está grabando esta reunión para tomar
   notas».
4. ffmpeg graba el monitor de PulseAudio en Opus, mono, 16 kHz, 24 kbps, y lo
   corta en pedazos de 5 minutos.
5. Cada segundo lee de la página quién aparece hablando y lo anota en la línea
   de tiempo `[{t, nombres}]`.
6. **Sale** cuando queda solo, cuando pasan 15 minutos de la hora de fin sin
   que nadie hable, o a las 3 horas de haber entrado.

**Subida a Jarvis** (con `Authorization: Bearer <token_subida>`):

- `POST {url_jarvis}/api/reuniones/{id}/eventos` con `{tipo}`: `esperando`,
  `admitido`, `rechazado`, `fallo` (con el motivo), `terminado`.
- `POST {url_jarvis}/api/reuniones/{id}/audio?n=<número>` con cada pedazo. Se
  guarda en disco y se borra solo cuando Jarvis responde `200`. Si no
  responde, se reintenta con espera creciente.
- `POST {url_jarvis}/api/reuniones/{id}/hablantes` con la línea de tiempo,
  al terminar.

**Iniciar sesión con la cuenta del bot:** el script `bot-meet/iniciar-sesion.sh`
abre el navegador del perfil en modo visible por VNC o túnel, se inicia sesión
a mano una vez y el perfil queda guardado.

### 2. Jarvis

**Configuración por persona:** el interruptor «Grabar siempre», en
Integraciones, junto al calendario. Por defecto está apagado.

**Aviso previo** (el que ya sale 15 minutos antes, `JARVIS_AVISO_REUNION_MIN`),
solo en eventos con link de Meet:

- Con «Grabar siempre»: «Voy a grabar esta reunión», con el botón **No grabar**.
- Sin él: el botón **Grabar**. En WhatsApp es un link firmado que abre Jarvis
  y confirma con un toque.

**Reunión compartida:** la clave es el código de Meet (`xxx-xxxx-xxx`) más la
fecha de inicio. Si dos personas de Jarvis piden grabar la misma reunión, se
agenda una sola sesión y las dos quedan como interesadas.

**Orden al bot:** Jarvis la manda en cuanto alguien confirma, o con «Grabar
siempre» en el momento del aviso. Si el bot responde `409`, la persona recibe
«No hay bot libre para grabar X».

**Recepción:**

- Cada pedazo se guarda en Storage y se transcribe apenas llega. Se ignoran
  los números repetidos. Si llegan fuera de orden, se reordenan por número.
  Si falla la transcripción, se reintenta 3 veces y, si sigue fallando, el
  pedazo queda marcado.
- **Nombres:** a cada frase con hablante («A», «B») se le asigna el nombre que
  más tiempo aparece hablando en la línea de tiempo durante esa frase. Dentro
  de un pedazo, la misma letra se queda con el nombre de mayor coincidencia.
  Si no hay coincidencia, queda «Participante».
- **Al recibir `terminado`:** se arma la transcripción, el modelo de texto de
  Jarvis genera `{resumen, puntos_clave[], tareas[{quien, que, cuando}]}`, y
  cada interesado recibe por WhatsApp el resumen corto con el link.

**Estados de una reunión:** `agendada` → `esperando` → `grabando` →
`procesando` → `lista`. Las salidas posibles son `rechazada` (no la
admitieron), `fallida` (no pudo entrar) o `incompleta` (se cortó a la mitad:
se resume lo que hay).

**Sección Reuniones** (`/apps/reuniones`, otra pestaña junto a WhatsApp,
Correo y Calendario): una lista con fecha, título, duración y estado. Cada
reunión se abre con el resumen, las tareas, la transcripción con nombres y un
reproductor de audio con URL firmada de Storage. La ven solo los interesados
y el admin.

**Herramienta nueva para el modelo:** `buscar_reuniones(texto, desde, hasta)`
busca en los resúmenes y las transcripciones de las reuniones que la persona
puede ver.

**Retención:** una tarea diaria borra de Storage el audio con más de 90 días.
El texto se queda.

**Consumo:** la transcripción y el resumen se registran con
`consumo.registrar` como el dictado, a nombre de la persona que pidió grabar.
Si son varias, a nombre de la primera.

**Variables:** `BOT_MEET_URL`, `BOT_MEET_SECRETO`, `JARVIS_MODELO_REUNIONES`
(por defecto `gpt-4o-transcribe-diarize`). Si falta `BOT_MEET_URL`, el botón
Grabar no aparece y Jarvis lo avisa al arrancar.

## Fallas

| Qué pasa | Qué hace |
|---|---|
| Nadie lo admite en 10 min | Evento `rechazado`; WhatsApp «No me dejaron entrar a X» |
| No encuentra los botones (Google cambió la página) | Captura de pantalla en el EC2, evento `fallo` con el motivo; aviso en Jarvis y en el monitor |
| Google pide verificar la cuenta o se cierra la sesión | Igual, con motivo `sesion_google`; se arregla con `iniciar-sesion.sh` |
| Chrome se cuelga a mitad | Reintenta entrar una vez; si no puede, `terminado` con `incompleta` |
| Red caída o Jarvis no responde | Los pedazos se quedan en disco y se reintentan hasta 24 h |
| Falla la transcripción de un pedazo | 3 reintentos; queda el hueco marcado y se puede reprocesar desde la reunión |
| Pedazo repetido | Se ignora por número |
| Se reinicia el bot | Retoma las sesiones agendadas desde el disco |

## Pruebas

- **Jarvis (pytest):** detectar el link de Meet en el evento, las reglas del
  aviso con y sin «Grabar siempre», la reunión compartida, la firma HMAC y los
  tokens de subida, los pedazos repetidos o fuera de orden, la asignación de
  nombres desde la línea de tiempo, el armado del resumen con la API simulada,
  los estados y la retención.
- **Bot (pytest):** agendar, el límite de 2 sesiones, la persistencia al
  reiniciar, los reintentos de subida y las reglas de salida, con una página
  de Meet simulada servida en local.
- **Meet real** antes de usarlo en producción: una reunión de prueba donde
  Jorge admite al bot, 10 minutos de conversación, revisión del resumen y
  medición de RAM y CPU en el t3.small.

## Fuera de esta versión

Zoom y Teams; video; resumen por correo o a los invitados; entrar sin
calendario pegando un link; extensión de Chrome y botón de grabación
presencial (proyecto aparte, reutiliza la misma recepción de pedazos).
