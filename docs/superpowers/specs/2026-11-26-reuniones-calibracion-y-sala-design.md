# Reuniones presenciales: calibración de voces y sala con varios teléfonos

Fecha: 2026-11-26. Sigue a `2026-11-26-reuniones-presenciales-design.md` (ya en producción).

## Qué se quiere

En Meet los nombres salen de la pantalla. En persona no hay de dónde sacarlos, así que:

- **A. Calibración (un solo aparato graba).** Antes de arrancar se dice cuántas personas
  hay; cada una escribe su nombre y lee en voz alta una frase que sale en pantalla. Con eso
  la transcripción sale con nombres.
- **B. Sala (cada uno en su teléfono).** Quien organiza crea una sala; los demás entran con
  un link/QR (invitados, sin cuenta) o desde una invitación dentro de Jarvis (equipo).
  Cada teléfono ayuda a saber quién habla.

## A. Calibración

### Flujo (web y APK)

«Grabar reunión presencial» → título → **«¿Cuántas personas?»** (1 a 10, o «Saltar»: queda
como hoy) → por cada persona: nombre + frase en pantalla + **Grabar muestra** (6 s con cuenta
regresiva y la barrita) + Repetir / Siguiente → **Empezar a grabar**.

El micrófono se pide una vez y sirve para las muestras y la grabación. En el APK, el
micrófono de la página se suelta antes de que arranque el servicio nativo.

### Backend

- `POST /api/reuniones/{id}/voces?nombre=X` (token de subida, como el audio; ruta libre):
  el cuerpo es la muestra (webm/ogg/mp4). ffmpeg la pasa a wav mono 16 kHz de hasta 10 s y
  queda como voz conocida con ese nombre (`reuniones_voces.guardar_muestra`). Nombre vacío,
  repetido o más de 10 voces → 400.
- `reuniones_voces` deja de suponer que toda voz conocida se llama «Hablante N»: las
  conocidas son las de `voces.json` (calibradas o recortadas); una letra nueva del modelo
  pasa a ser el siguiente «Hablante N».
- **Más de 4 voces**: el modelo acepta 4 por llamada. Con más, cada pedazo se transcribe
  una vez por grupo de hasta 4 (7 → 4 + 3) y se unen: la primera llamada da los segmentos;
  a uno que quedó con letra se le pone el nombre conocido del segmento que más se le cruza
  en el tiempo en las otras llamadas. Cuesta una transcripción por grupo (7 personas ≈
  US$1,50/h).
- En el detalle de una presencial se pueden renombrar todas las voces, no solo las genéricas.

## B. Sala

### Idea

Un solo aparato graba el audio (el de quien organiza): la transcripción se paga una vez.
Los demás teléfonos solo mandan **cuánto oye su micrófono** (4 veces por segundo, en
paquetes cada 2 s). Quien habla está cerca de su teléfono: en cada segundo, el micrófono que
más oye (con margen sobre el segundo) dice quién habla. Eso arma la misma `linea`
`[{t, nombres}]` que usa el bot de Meet, y `con_nombres` ya sabe qué hacer con ella.

### Datos

- `reuniones.sala TEXT` (columna nueva): código de la sala (12 caracteres aleatorios).
- `reunion_participantes (id, reunion_id, nombre, usuario_id, token_hash, unido, visto)`.
- `reunion_niveles (reunion_id, participante_id, segundo, nivel, PK(reunion_id, participante_id, segundo))`:
  el máximo de cada segundo (≈ 25.000 filas por hora con 7 teléfonos). Se borran al cerrar.

### Rutas

Con sesión (quien organiza):
- `POST /api/reuniones/presencial {titulo, sala: true}` → además `sala`, `link`
  (`https://asistente.neboaiconsulting.com/sala/<codigo>`) y el `participante` + token del
  propio organizador (su teléfono también manda niveles).
- `GET /api/reuniones/{id}/sala` → participantes (nombre, visto hace N s).
- `GET /api/reuniones/{id}/sala/qr.svg` → el QR del link (`segno`, SVG).
- `GET /api/reuniones/equipo` → con quién se puede invitar: quienes usaron Jarvis en la
  misma organización en los últimos 60 días (tabla `consumo`) + los miembros de una cuenta
  de organización; sin uno mismo ni los puentes.
- `POST /api/reuniones/{id}/invitar {usuarios: [...]}` → un aviso (campanita + WhatsApp)
  «Jorge te invitó a la reunión presencial «X»» con el link.

Libres (las revisa la ruta, no la sesión):
- `GET /sala/{codigo}` → página del participante (`web/sala.html`, `web/apps/sala.js`).
- `GET /api/salas/{codigo}` → `{titulo, abierta, nombre}`; `nombre` viene de la cookie de
  Jarvis si la hay (los del equipo no escriben su nombre).
- `POST /api/salas/{codigo}/unirse {nombre}` → `{participante, token, ahora_ms}`. Si hay
  sesión se guarda su `usuario_id` y pasa a ser interesado de la reunión (le llega el
  resumen). Los invitados externos no reciben nada.
- `POST /api/salas/{codigo}/niveles {participante, token, desde_ms, niveles: [..]}` (cada
  nivel = 250 ms, hora del servidor) → `{seguir}`; `false` cuando la reunión ya no graba.

### Quién habla

Al cerrar una reunión con sala: `linea` = para cada segundo con niveles, el participante
con el nivel más alto si es ≥ 0,02 y ≥ 1,5 veces el segundo más alto. Los tiempos son
`(hora del servidor − grabando_desde)`; cada teléfono corrige su reloj con `ahora_ms` al
unirse.

### Pantallas

- Reuniones: dos botones, **Grabar en persona** (A) y **Crear sala** (B). La tarjeta de la
  sala muestra el QR, el link (Copiar), **Invitar del equipo** y quién está conectado.
- Participante: título, «Esta reunión se está grabando», nombre (si no hay sesión),
  **Entrar**, después la barrita y «Deja esta pantalla abierta». Termina sola cuando la
  reunión termina.

## Fuera de alcance

Que cada teléfono suba su propio audio; sala desde el APK para participantes (usan el
navegador, la pantalla tiene que quedar prendida); sala + calibración a la vez.

## Pruebas

pytest: muestras de voz (formato, límites), grupos de más de 4 y su unión, renombre de
todas las voces; sala: crear, unirse con y sin sesión, niveles con token, `seguir`, línea
de quién habla (umbral y margen), invitaciones (aviso), equipo, QR. Navegador local: la
calibración con micrófono falso y una sala con dos pestañas.
