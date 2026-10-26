# Asistente configurable: nombre y avatar holograma por organización

Fecha: 2026-10-26. Estado: diseño aprobado por Jorge, pendiente de plan.

## Qué se quiere

Que cada organización tenga su asistente con **nombre propio** y un **avatar animado** generado a
partir de una foto, que se ve como un **holograma** en la web de Jarvis. Hoy el nombre es uno solo
para todo Jarvis (`JARVIS_NOMBRE`, hoy "Nebo") y el centro de la pantalla es un orbe abstracto.

## Decisiones tomadas

| Tema | Decisión |
|---|---|
| Alcance | Un asistente por organización (nombre, foto, videos). |
| Quién lo edita | Solo el **super admin** de Nebo, para cada organización. Los clientes no lo tocan. |
| Dónde llega el nombre | Web (título), personalidad de Jarvis (texto y voz en vivo) y puentes del reloj y los lentes. |
| Animación | **Videos generados con Higgsfield** a partir de la foto: tres bucles (reposo, escuchando, hablando). |
| Holograma | Efecto aplicado **en el navegador** sobre videos normales, estilo **sutil** (colores casi naturales, velo azul, líneas finas, brillo en el borde). |
| Generación | **Todo desde la interfaz** de Jarvis: el servidor llama a la API de Higgsfield. |
| Ubicación | El avatar **reemplaza al orbe** en el centro de la pantalla. |
| Sin videos | Foto animada en el navegador (detección de cara con MediaPipe: respira, parpadea, boca con el volumen) con el mismo efecto. Sin foto: el orbe de siempre. |

Fuera de alcance (para después): boca sincronizada palabra por palabra (avatar en tiempo real tipo
HeyGen/Simli), que cada organización edite su propio asistente, avatar en la pantalla del reloj.

## 1. Datos y configuración

Tabla nueva en `jarvis.db` (`basedatos.py`):

```sql
CREATE TABLE IF NOT EXISTS asistentes (
    organizacion_id TEXT PRIMARY KEY REFERENCES organizaciones(id),
    nombre TEXT,                 -- NULL: se usa JARVIS_NOMBRE
    foto TEXT,                   -- nombre de archivo dentro de avatares/<org>/
    actualizado TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS asistente_videos (
    organizacion_id TEXT NOT NULL REFERENCES organizaciones(id),
    estado TEXT NOT NULL CHECK (estado IN ('reposo', 'escuchando', 'hablando')),
    archivo TEXT,                -- el video listo que se muestra (NULL si nunca hubo)
    trabajo_id TEXT,             -- trabajo de Higgsfield en curso (NULL si no hay)
    trabajo_estado TEXT,         -- 'generando' | 'listo' | 'error'
    error TEXT,
    creditos REAL,               -- lo que costó el último trabajo
    actualizado TEXT NOT NULL,
    PRIMARY KEY (organizacion_id, estado)
);
```

- Archivos en `rutas.datos() / "avatares" / <organizacion_id> /`: la foto (`foto-<ts>.jpg`,
  achicada a 1024 px de lado mayor) y los videos (`<estado>-<ts>.mp4`). Nombres con marca de tiempo:
  el navegador los puede cachear para siempre; al regenerar cambia el nombre.
- Un video nuevo reemplaza al anterior **solo cuando terminó bien**; mientras tanto se sigue
  mostrando el viejo. El archivo viejo se borra después de reemplazarlo.
- Nombre efectivo: `asistentes.nombre` de la organización del usuario; si es NULL, o el usuario no
  tiene organización (contraseñas por variable), `JARVIS_NOMBRE`; si tampoco, "Jarvis".
- Módulo nuevo `backend/asistente.py`: leer/guardar la configuración, nombre efectivo, rutas de
  archivos. `cerebro.py` y `main.py` dejan de leer `JARVIS_NOMBRE` directamente y le piden el nombre a
  este módulo.

## 2. Generación con Higgsfield

Módulo nuevo `backend/higgsfield.py` (solo habla con la API) y la orquestación en `asistente.py`.

- **Credenciales:** `HIGGSFIELD_API_KEY_ID` y `HIGGSFIELD_API_KEY_SECRET` en `jarvis.env` (Nebo ya
  tiene una clave de la API: la usa la función `generar-media` del menú digital contra
  `https://api.higgsfield.ai`; conviene una clave aparte para Jarvis). Sin ellas, el botón
  "Generar" se muestra deshabilitado con el motivo.
- **Modelo:** image-to-video, configurable con `JARVIS_AVATAR_MODELO` (la ruta del modelo en la API).
  El plan fija el valor por defecto después de probar cuál da mejor resultado con caras.
- **Prompts** fijos por estado, en inglés (rinden mejor en estos modelos), todos con "plain dark
  background, looking at the camera, head and shoulders, same person as the image":
  - reposo: breathing calmly, natural blinking, very slight head movement, mouth closed.
  - escuchando: attentive expression, slight nod as if listening, mouth closed.
  - hablando: talking naturally as if explaining something, mouth moving, subtle head gestures.
- **Flujo:**
  1. `POST /api/asistente/<org>/foto` (super admin): guarda la foto.
  2. `GET /api/asistente/<org>/costo`: créditos estimados de generar los 3 (o uno).
  3. `POST /api/asistente/<org>/generar` con `{"estados": [...]}`: crea un trabajo por estado,
     guarda `trabajo_id` y `trabajo_estado='generando'`.
  4. Un hilo de fondo (como los de `creditos.py`/`fuentes.py`) consulta cada 15 s los trabajos en
     `generando`. Al terminar: descarga el mp4, lo guarda, actualiza `archivo` y `trabajo_estado='listo'`.
     Si falla: `trabajo_estado='error'` y `error` con el motivo de Higgsfield.
  5. Al arrancar, el hilo retoma los trabajos que quedaron en `generando`.
- Un trabajo que lleva más de 30 min en `generando` se marca como error ("Higgsfield no respondió").
- No se cobra a la organización: lo paga Nebo (es configuración que hace el super admin). Los
  créditos de cada trabajo quedan anotados en `creditos`.

## 3. La web

- **Pantalla "Asistente"** (botón nuevo en la barra, `data-super-admin`), archivo nuevo
  `web/asistente.js`: elegir organización → nombre → foto (subir y vista previa) → los 3 videos con
  vista previa, estado y botones "Generar" / "Regenerar", con el costo antes de confirmar. Mientras
  haya trabajos en curso, consulta el estado cada 5 s.
- **Avatar** (archivo nuevo `web/avatar.js`), reemplaza al orbe cuando hay videos o foto:
  - Tres `<video muted loop playsinline>` precargados, dibujados en un `<canvas>` que aplica el
    holograma **sutil**: la imagen original, un tinte azul por luminancia al 35 %, líneas
    horizontales finas que se desplazan, un barrido suave y un resplandor (`drop-shadow`) cuyo
    tamaño sigue el volumen de la voz del asistente. Bordes desvanecidos (sin recuadro).
  - Estado: reposo / escuchando (micrófono abierto, manos libres o voz en vivo mientras habla la
    persona) / hablando (mientras suena la respuesta). Se toma de los mismos eventos que hoy animan
    el orbe en `app.js`. Cambio de estado con fundido de 300 ms.
  - Bucle sin salto: en los últimos 400 ms de cada clip se funde con su propio comienzo.
  - Sin videos pero con foto: foto animada en el canvas (MediaPipe Face Landmarker desde el CDN,
    versión fija 0.10.14; respira, parpadea, boca con el volumen), mismo holograma.
  - Si el dispositivo no da los cuadros (más de 2 s por debajo de 20 fps), se apaga el efecto y se
    muestra el video tal cual.
- `/api/estado` agrega `asistente: {nombre, foto, videos: {reposo, escuchando, hablando}}` con las
  URLs (`/avatares/<org>/<archivo>`, servidas solo a usuarios de esa organización o super admin).
- Título de la página y de la pestaña: el nombre del asistente.

## 4. El nombre en la personalidad y en los puentes

- `cerebro.instrucciones()` usa el nombre efectivo de la organización del usuario ("Eres {nombre}…").
- La sesión de voz en vivo (`/api/voz/sesion`, la que usan la web y los puentes) devuelve también
  `nombre`.
- Puente de los lentes (`puente-android`): `gemini.js` deja de decir "Eres Jarvis" fijo y usa el
  `nombre` que manda Jarvis (si no llega, "Jarvis"). El puente del reloj, igual donde corresponda.
- El código de los dos puentes hoy solo existe en el EC2 (`/opt/jarvis/puente-*`, copiado de lo que
  corría en Railway): se sube a un repo antes de tocarlo.

## Errores y casos borde

- Foto sin cara detectable: se acepta igual (Higgsfield puede manejarla), pero la foto animada de
  respaldo no se muestra (queda el orbe) y la pantalla avisa.
- Higgsfield sin créditos o clave inválida: el error de la API se muestra tal cual en el estado del
  video; nada de lo que ya funcionaba se rompe.
- Organización borrada: sus archivos se borran con ella.
- Un usuario que no es super admin no puede ni leer ni escribir `/api/asistente/*` (403).

## Pruebas

- Backend (pytest): configuración por organización y nombre efectivo con sus respaldos; permisos de
  `/api/asistente/*`; flujo de generación con Higgsfield simulado (creado, en curso, terminado, error,
  vencido, retomado al arrancar, reemplazo del video viejo solo al terminar); `/api/estado` y
  `instrucciones()` con el nombre de la organización; `/avatares/` no sirve archivos de otra
  organización.
- Puentes (node --test): el prompt usa el nombre que llega y cae en "Jarvis" sin él.
- A mano con Higgsfield real (gasta créditos, se muestra el costo antes): generar los 3 videos de una
  foto de prueba y ver el avatar en la web en cada estado, en PC y en el celular.
- Despliegue al EC2 a mano (Railway está desconectado del repo).
