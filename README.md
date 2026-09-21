# Jarvis

Asistente personal con voz, memoria persistente y acceso directo a tu base de
datos de Supabase.

## Arrancarlo

1. Doble clic en `iniciar.bat`. La primera vez instala todo solo.
2. Se abre en http://127.0.0.1:8123

El punto junto al nombre está verde cuando la clave de OpenAI está bien puesta.

## Desplegarlo en un servidor

Railway (u otro con Railpack) detecta FastAPI, pero busca `main.py` en la raíz
y el nuestro está en `backend/`. Por eso hay un [railpack.json](railpack.json)
que fija el arranque:

```
uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

### Contraseña obligatoria

**Si Jarvis detecta que corre hospedado y no hay `JARVIS_PASSWORD`, no sirve
nada.** Muestra una página explicando cómo configurarla y devuelve 503.

Es deliberado. Sin ella, cualquiera con la URL podría consultar tus bases de
datos, leer tus recuerdos y gastar tus créditos de OpenAI. Un despliegue que no
arranca es mejor que uno abierto.

En local no cambia nada: sin la variable, funciona como siempre.

La sesión es una cookie firmada con HMAC, `HttpOnly` y `Secure` en servidor.
No hay estado en memoria, así que sobrevive a los reinicios.

### Varias personas

Cada persona tiene su propia contraseña, en su propia variable:

```
JARVIS_PASSWORD=...          # la tuya: administras Jarvis
JARVIS_PASSWORD_JORGE=...    # Jorge
```

La pantalla de acceso no pide usuario: **la contraseña que escribes ya dice
quién eres**, así que tienen que ser distintas entre sí. Si dos coinciden,
Jarvis avisa al arrancar, porque serían indistinguibles y compartirían memoria.

Cada uno tiene su conversación, su memoria y su nombre —que sale del sufijo de
la variable—. Las fuentes de datos, el esquema y las leyendas de tablas son
comunes: son de la empresa, no de la persona.

Quien entra con `JARVIS_PASSWORD` es el administrador y el único que puede
tocar las fuentes, refrescar el esquema y ver el consumo. Los demás solo
conversan, aunque Jarvis sí consulta las bases en su nombre.

Para quitarle el acceso a alguien, borra su variable y vuelve a desplegar. Para
cerrar todas las sesiones a la vez, cambia `JARVIS_CLAVE_SECRETA`.

La memoria de cuando había un solo usuario se adjudica sola al administrador la
primera vez que arranca. Los archivos viejos no se borran.

### Entrar desde los paneles

Quien use el inbox, cotizaciones o cobranzas puede entrar a Jarvis de un clic,
sin escribir contraseña. El super admin lo concede marcando **Usar Jarvis** en
el panel de usuarios; **Administrar Jarvis** le da además fuentes, esquema y
consumo.

Jarvis valida la sesión de Supabase del panel y relee el perfil cada minuto, así
que quitar la casilla deja fuera a la persona enseguida, sin esperar a que
caduque su cookie.

Necesita `SUPABASE_ANON_KEY` y `SUPABASE_DB_URL`. Si falta alguna, este acceso
queda apagado —se avisa al arrancar— y las contraseñas por variable siguen
funcionando.

Para cobrarle a la empresa dueña de los paneles lo que consume su gente:

```
JARVIS_ORGANIZACION_PANELES=JH Electroalambres
```

Al arrancar se crea esa organización, y todo el que entra desde un panel queda
adentro con el login que ya tiene: no hace falta crearle otra cuenta. Su id
es fijo, `paneles`, así que se puede renombrar sin partirle el historial y
nadie que se registre con el mismo nombre se queda con ella. Su margen propio,
si lo necesita, va en `JARVIS_MARGEN_PANELES`. Sin la variable, quien entra
desde los paneles es de la casa, como hasta ahora.

Quién es miembro lo sigue decidiendo el panel de usuarios de Supabase (la
casilla **Usar Jarvis**), no el botón **Organización** de Jarvis.

### Organizaciones

Además de las contraseñas por variable, hay cuentas con correo y contraseña
agrupadas en organizaciones. **Solo quien administra Jarvis las crea**, desde
*Nueva organización* en el tablero de **Consumo** (o en `/registro`): se carga
la organización con la primera persona que la administra, y esa persona entra
después con su correo en `/acceso/cuenta` y suma al resto desde
**Organización** en la barra.

El registro no es abierto a propósito. Las fuentes de datos son comunes a
todo el que entra, así que un registro abierto dejaba que cualquiera con la
URL se creara una cuenta y consultara los datos del negocio.

Una cuenta de organización nunca toca Fuentes, Esquema o Consumo —eso sigue
siendo de quien administra Jarvis—. Vive en `data/jarvis.db` (SQLite, sin
dependencias nuevas), no en variables de entorno.

Sirve para atribuir el consumo: cada registro guarda qué organización lo
generó, así el tablero de **Consumo** muestra cuánto gastó cada una.

### Cuánto consumió cada una

El tablero de **Consumo** tiene una tabla por organización: consultas, costo
real, margen, lo cobrado en el periodo y lo consumido en total. La
organización ve lo suyo en **Organización**.

El margen es un porcentaje sobre lo que cobra OpenAI, por variable de entorno:

```
JARVIS_MARGEN=30                      # a todas: costo mas un 30%
JARVIS_MARGEN_51512a3363c7f591=50     # a esta, 50%. El id sale en el tablero
```

Sin variable, se cobra al costo. Acepta `30`, `30%` o `12,5`; un valor que no
sea un porcentaje de 0 en adelante se ignora y **se avisa al arrancar**, igual
que un `JARVIS_MARGEN_<id>` que no corresponda a ninguna organización. Mejor
enterarse en el log que descubrir a fin de mes que alguien se facturó al
costo.

El cliente ve solo lo que paga, con el margen ya adentro. El costo real y el
porcentaje no salen en su respuesta: con esos dos sacaría cuánto se le gana.
Esas cifras están solo en el tablero de **Consumo**, que es del admin.

**No hay corte por consumo**: esto mide y deja el número listo para facturar,
pero nadie se queda sin servicio. Quien entra por `JARVIS_PASSWORD` o desde un
panel no tiene organización, así que no se le mide nada: es de la casa, no un
cliente.

**Lo que esto no resuelve**: el consumo de la voz en vivo lo reporta el
navegador (`POST /api/consumo/voz`), no el servidor. Sirve para medir, pero
alguien que modifique su cliente podría no reportarlo. Para cobrar voz sin
confiar en el cliente habría que reconciliar contra la API de uso de OpenAI,
o cobrar por minuto de sesión, que sí lo mide el servidor. El modo texto no
tiene ese problema: el costo se calcula acá.

### Vincular un reloj

Desde **Dispositivos**, cualquiera ya logueado —por contraseña, por panel o
por una cuenta de organización— genera un código de 6 caracteres. Se escribe
en el reloj, vale 10 minutos y sirve una sola vez: a cambio, el reloj recibe
un token propio que manda como `Authorization: Bearer <token>` en cada pedido,
sin volver a pedir nada. Cada reloj queda con su propia identidad —su
conversación, su memoria, su gasto— en vez de compartir la sesión del admin.

### Variables a configurar

| Variable | |
|---|---|
| `OPENAI_API_KEY` | Obligatoria |
| `JARVIS_PASSWORD` | Obligatoria al hospedar. Quien entra con ella administra |
| `JARVIS_PASSWORD_<NOMBRE>` | Una por cada persona más que pueda entrar |
| `JARVIS_DATA_DIR` | Ruta del volumen persistente |
| `JARVIS_CLAVE_SECRETA` | Cifra las credenciales y firma las sesiones |
| `JARVIS_MARGEN` | Porcentaje sobre OpenAI que se cobra a las organizaciones |
| `JARVIS_MARGEN_<id>` | El de una organización en particular. Pisa al general |
| `JARVIS_ORGANIZACION_PANELES` | Organización de quienes entran desde los paneles |
| `SUPABASE_ANON_KEY` | Clave pública. Habilita entrar desde los paneles |
| `SUPABASE_*` | Las mismas de la sección de Supabase |

### El disco se borra

En Railway el sistema de archivos es efímero: cada despliegue empieza de cero.
Sin un volumen perderías los recuerdos, el caché del esquema y —lo más
molesto— `clave.key`, sin la cual **las credenciales guardadas de tus fuentes
quedan indescifrables**.

Monta un volumen y apunta `JARVIS_DATA_DIR` ahí. Si prefieres no usarlo, al
menos fija `JARVIS_CLAVE_SECRETA` para que la clave de cifrado sea estable
entre despliegues.

### La voz necesita HTTPS

El micrófono del navegador solo funciona en contextos seguros. Railway da
HTTPS por defecto, así que funciona; en local funciona porque `127.0.0.1`
cuenta como seguro. Un servidor propio sin certificado se queda sin voz.

## Los dos modos

| | Modo texto | Voz en vivo |
|---|---|---|
| Modelo | `gpt-5.6-terra` | `gpt-realtime-2.1-mini` |
| Cómo hablas | Escribes, o dictas con el micrófono | Conversación de audio continua |
| Latencia | Segundos | Inmediata, puedes interrumpirlo |
| Costo | ~1 centavo por consulta | ~$0.03 por minuto |

**Texto** es el de diario. El micrófono usa el reconocimiento del navegador
(gratis) y Jarvis responde con voz sintetizada. Con "Manos libres" escucha
todo el tiempo y solo atiende lo que digas después de la palabra *"Jarvis"*.

**Voz en vivo** (botón rojo) abre un canal de audio con OpenAI por WebRTC. Es
voz-a-voz real: no transcribe a texto, oye tono e interrupciones. Cuesta por
minuto, así que actívalo cuando quieras hablar de verdad y córtalo al terminar.

Ambos comparten la misma memoria, el mismo historial y las mismas herramientas.

### Imágenes en voz en vivo

Con la voz en vivo abierta aparece un clip junto al botón rojo. La imagen que
elijas —en el teléfono, también la cámara— entra a la conversación y Jarvis la
tiene delante, pero **no la comenta por su cuenta**: pregúntale lo que quieras
saber de ella, hablando o escribiendo.

El navegador la reduce a 1024 px de lado antes de mandarla, y más si no cabe en
el canal de WebRTC. En el historial queda `[Imagen adjunta]`, no la foto.

### Fotos de los lentes

El puente de los lentes (`puente-android`, repo `jarvis-lentes`) tiene dos
caminos:

- **Dentro de la voz**: el modelo pide `tomar_foto` y el puente mete la imagen
  en su propia sesion de Realtime. Jarvis no interviene.
- **Sin voz** (el botón de la app que saca foto con el teléfono): el puente la
  manda a `POST /api/fotos` con `JARVIS_FOTO_RUTA=/api/fotos`. Jarvis la lee con
  el modelo de texto y contesta `{"lectura": "..."}`. En el historial quedan
  `[Foto del telefono] <motivo>` y la lectura; la foto no se guarda.

Acepta JPEG, PNG y WebP de hasta 2 MB, y comprueba la firma de los bytes, no
solo el mime.

Cada imagen cuesta unos cientos de tokens; el tablero de consumo los muestra en
**Imagen in**. Si `data/precios.json` no trae `imagen_entrada` para el modelo,
se cobran al precio del texto de entrada.

Necesitas **Chrome o Edge**, y dar permiso al micrófono.

## Supabase

Jarvis consulta tu base de datos real por MCP. Para conectarlo, en `.env`:

```
SUPABASE_ACCESS_TOKEN=sbp-...     # supabase.com/dashboard/account/tokens
SUPABASE_PROJECT_REF=abcdefgh     # el id del proyecto, en la URL del dashboard
SUPABASE_SOLO_LECTURA=true
```

Con `SUPABASE_SOLO_LECTURA=true` todas las consultas corren como usuario
read-only de Postgres: Jarvis puede leer lo que sea pero es **incapaz** de
modificar o borrar. Con voz esto importa — una frase mal entendida no puede
tocar datos. La insignia en la barra superior muestra en qué modo está, y se
pone roja si le diste escritura.

`SUPABASE_PROJECT_REF` acota a un solo proyecto y además apaga las herramientas
de administración de cuenta (crear o pausar proyectos). Si lo dejas vacío,
Jarvis ve toda tu organización.

Puede: listar tablas, ejecutar SQL, ver migraciones y extensiones, leer logs,
consultar advisors de seguridad y rendimiento, generar tipos de TypeScript y
buscar en la documentación de Supabase.

### Cómo funciona

No hay cliente MCP en este proyecto y no hace falta Node. Le declaramos el
servidor MCP a OpenAI y **sus servidores hablan directo con Supabase**. La
contrapartida: tu token de Supabase viaja a OpenAI en cada petición (no lo
almacenan, pero pasa por ahí). Si eso no te sirve, habría que escribir un
cliente MCP local.

### Base de conocimiento de consultas

[backend/consultas.py](backend/consultas.py) tiene **32 consultas SQL ya
escritas y probadas** sobre tus tablas reales, agrupadas por área: cartera y
deuda, llamadas, promesas de pago, WhatsApp, clientes, y operación.

El modelo no escribe SQL: elige una por nombre y le pasa parámetros.

```
consultar_datos("top_deudores", {"limite": 5})
consultar_datos("cartera_tendencia", {"dias": 30})
consultar_datos("buscar_deudor", {"texto": "MID CORP"})
```

Por qué existe: escribir SQL cuesta segundos de generación y se equivoca con
los nombres de columnas. Con el catálogo la consulta ya está resuelta y
probada. Además cada resultado se cachea entre 30 y 300 segundos según lo
volátil que sea el dato, así que repetir una pregunta es instantáneo.

Si ninguna consulta encaja, el modelo pide las columnas con `ver_esquema` y
escribe SQL con `execute_sql`. Es la vía lenta, y es a propósito el último
recurso.

**Los parámetros nunca llegan crudos al SQL**: los enteros se acotan a un
rango, los textos se filtran a caracteres de nombre y teléfono, las fechas
tienen que ser `AAAA-MM-DD`.

Para agregar una consulta, una entrada en `CATALOGO`. El campo `descripcion` es
lo único que ve el modelo, así que tiene que decir con precisión qué responde.

### Dos vías de ejecución

| | Latencia | Requiere |
|---|---|---|
| MCP (por defecto) | ~1.2s | Nada más |
| Postgres directo | ~0.15s | `SUPABASE_DB_URL` |

El MCP viaja por los servidores de OpenAI y de Supabase; tiene un piso de
~1.2s incluso para `select 1`. Con `SUPABASE_DB_URL` configurada, Jarvis se
conecta directo.

Esa conexión se abre **siempre en transacción de solo lectura**
(`conexion.read_only = True`), así que aunque la credencial tenga permisos de
escritura, por ahí no se puede escribir.

### El esquema va cacheado

[backend/esquema.py](backend/esquema.py) lee la estructura de la base al
arrancar y la guarda en `data/esquema.json` (12 horas de vigencia). Ese esquema
se inyecta en el prompt.

Sin esto, cada pregunta sobre los datos costaba un `list_tables` previo: un
viaje extra y una respuesta enorme. En voz eso son segundos de silencio que el
modelo rellena diciendo *"déjame buscarlo"*. Con el esquema cargado va directo
al `execute_sql`: una sola consulta.

Si cambias la estructura de la base y Jarvis sigue viendo la vieja:

```
curl -X POST http://127.0.0.1:8123/api/esquema/refrescar
```

## Imágenes y fichas técnicas

Si le pides la foto o la ficha técnica de un producto, Jarvis la busca y la
manda al chat: la imagen con su miniatura y la ficha como tarjeta que abre el
PDF. Solo manda lo que pediste; si el producto no tiene ese archivo lo dice, y
nunca manda el de uno parecido.

Los archivos viven en Supabase Storage y **se llaman como el `Codigo` del
catálogo** (`305400.png`, `305400.pdf`). No hay tabla que los una: al arrancar
Jarvis lista los buckets y arma un índice código → archivo, que guarda en
`data/archivos.json` y renueva cada 6 horas. Si piden un código que no está,
vuelve a listar en segundo plano (como mucho cada 10 minutos), por si se subió
hace poco. Las copias sueltas (`0774 - copia.png`, `11815 (2).png`) cuentan
como el mismo código, y gana el original.

| Variable | |
|---|---|
| `SUPABASE_SERVICE_ROLE_KEY` | Solo para listar los buckets. No sale del servidor |
| `JARVIS_BUCKET_IMAGENES` | p. ej. `Lucas_imagenes` |
| `JARVIS_BUCKET_FICHAS` | p. ej. `Lucas_fichas_tecnicas` |

Si el bucket es público se usa la URL pública; si es privado, un enlace firmado
que dura una hora.

Funciona en texto, en voz en vivo y queda en el historial. `/api/herramienta`
devuelve los archivos en `adjuntos`, así que el puente de los lentes también los
recibe cuando se piden por voz.

## Cotizaciones

Jarvis arma cotizaciones con el mismo PDF que las de Camila, pero **aparte de
JH**: numeración propia (`JV-00001`), sin tocar la Base JH, la numeración de
Camila ni el panel. Se pueden conectar con JH más adelante: la tabla guarda
cliente, líneas y totales completos.

Siempre en dos pasos:

1. **`preparar_cotizacion`** busca al cliente en `List_ClientesIA` (por nombre,
   RNC o código) y los productos en `List_ProductosIA`, y calcula. **Los
   precios los pone el servidor**, con el nivel del cliente (P1–P7) por su
   factor; el modelo nunca los escribe. De contado va a P1. Devuelve un
   resumen y Jarvis pregunta si la emite.
2. **`emitir_cotizacion`**, solo tras un "sí": inserta la fila en
   `jarvis_cotizaciones` (que da el número), arma el HTML
   ([backend/cotizacion_html.py](backend/cotizacion_html.py), port del nodo de
   n8n), lo convierte con PDF.co y lo sube al bucket privado. Llega al chat como
   tarjeta y a los lentes como documento.

El PDF lleva RNC, dirección y teléfono, así que el bucket es privado. La web lo
abre por `/api/cotizaciones/JV-00001.pdf`, que exige sesión y firma un enlace de
5 minutos; a la app de los lentes le llega uno de 24 horas.

Si falla el PDF, la fila queda con `estado = 'fallida'` y el borrador sigue
disponible para reintentar (con otro número).

| Variable | |
|---|---|
| `JARVIS_FUENTE_CATALOGO` | Id de la fuente con el catálogo y los clientes (Base JH) |
| `JARVIS_BUCKET_COTIZACIONES` | `jarvis_cotizaciones` |
| `PDFCO_API_KEY` | La de PDF.co |

Además usa `SUPABASE_SERVICE_ROLE_KEY` y `SUPABASE_PROJECT_REF`. Tabla y bucket:

```sql
create table public.jarvis_cotizaciones (
  numero bigint generated always as identity primary key,
  creada_at timestamptz not null default now(),
  usuario text not null, cliente jsonb not null, productos jsonb not null,
  subtotal numeric(14,2) not null, itbis numeric(14,2) not null,
  total numeric(14,2) not null, pdf_ruta text,
  estado text not null default 'emitida'
);
alter table public.jarvis_cotizaciones enable row level security;
insert into storage.buckets (id, name, public)
values ('jarvis_cotizaciones', 'jarvis_cotizaciones', false);
```

## Enviar por WhatsApp

Jarvis puede mandar la foto o la ficha técnica de un producto, o una cotización
JV, a un número de WhatsApp: "mándale la cotización JV-00002 al 809…".

Va por Evolution API (`/message/sendMedia`) desde el número conectado a la
instancia de `EVOLUTION_INSTANCIA`. Siempre en dos pasos: `preparar_envio_whatsapp`
arma el envío y Jarvis lee el número y lo que va; `confirmar_envio_whatsapp` lo
manda solo tras un "sí". Un mensaje enviado no se deshace, y por voz un número
mal oído le llegaría a otra persona.

- Los números de RD de diez dígitos (809, 829, 849) reciben el 1 delante; los
  demás tienen que venir con código de país.
- Tope de 20 envíos por hora: Evolution maneja el número como WhatsApp Web, y
  WhatsApp bloquea a quien manda mucho a gente que no le escribió.
- Las cotizaciones salen con un enlace firmado de 10 minutos que Evolution
  descarga en el momento; el bucket sigue privado.
- Cada envío queda en `data/envios_whatsapp.jsonl`: quién, a qué número, qué y
  si salió.

| Variable | |
|---|---|
| `EVOLUTION_URL` | URL del servidor de Evolution |
| `EVOLUTION_API_KEY` | Su API key |
| `EVOLUTION_INSTANCIA` | La instancia (el número) que envía |
| `EVOLUTION_INSTANCIA_RESPALDO` | Opcional: otra instancia. Si la principal da cualquier error, cada archivo se reintenta por esta; si las dos fallan, Jarvis explica el motivo y el envío queda preparado para reintentar |

## Fuentes de datos

El botón **Fuentes** abre el panel para conectar bases de datos sin tocar
archivos. Soporta **PostgreSQL**, **Microsoft SQL Server** y **Supabase**.

Cada fuente tiene: prueba de conexión con latencia y número de tablas,
explorador de tablas y columnas, y una consola SQL con los resultados en
tabla.

### Credenciales

Se guardan cifradas en `data/fuentes.json`. La clave se genera sola en
`data/clave.key`, o puedes fijar la tuya con `JARVIS_CLAVE_SECRETA` en `.env`.

Alcance real de esa protección: el archivo de fuentes no revela nada si se
copia, se sincroniza a la nube o se comparte por error. **No** protege contra
alguien que ya tenga acceso a tu usuario de Windows, porque la clave está en la
misma máquina.

La interfaz nunca recibe las credenciales completas, solo `sb••••••••ba`. Al
editar, dejar un campo secreto vacío conserva el valor guardado.

### Solo lectura

Activado por defecto. Dos capas:

1. **Filtro de sentencias**: solo pasa lo que empieza por `SELECT` o `WITH`.
   Bloquea `INSERT`, `UPDATE`, `DELETE`, `DROP`, `EXEC`, `sp_`, `xp_` y
   cualquier intento de encadenar una segunda sentencia con `;`.
2. **Transacción de solo lectura** en PostgreSQL (`conexion.read_only`), que es
   la garantía dura: la impone Postgres, no nuestro código.

SQL Server no tiene un equivalente limpio a la transacción de solo lectura, así
que ahí la protección es la primera capa.

### Cómo las usa Jarvis

Las fuentes activas aparecen en su prompt con su id y sus notas. Usa
`ver_esquema_fuente` para conocer las tablas y `consultar_fuente` para
consultar. Las notas son importantes: son lo que le permite elegir la fuente
correcta cuando no se lo dices.

### Agregar otro motor

Una entrada en `CATALOGO_TIPOS` de [backend/fuentes.py](backend/fuentes.py) con
sus campos, y una función de consulta en `MOTORES`. **La interfaz no se toca**:
los formularios se dibujan a partir de esa definición.

## Agregar más servicios

Una función decorada en [backend/herramientas.py](backend/herramientas.py). El
esquema se arma solo desde la firma, y queda disponible en **ambos** modos:

```python
@herramienta(
    "Manda un correo.",
    para="Direccion del destinatario",
    asunto="Asunto del correo",
)
def enviar_correo(para: str, asunto: str) -> str:
    ...
    return "Correo enviado."
```

Para servicios que ya tengan MCP remoto, se agregan en
[backend/conectores.py](backend/conectores.py) igual que Supabase.

## Estructura

```
backend/
  main.py           servidor y API
  cerebro.py        Responses API (texto) y sesiones Realtime (voz)
  conectores.py     servidores MCP remotos
  herramientas.py   funciones locales
  memoria.py        persistencia
web/
  index.html
  app.js            interfaz y modo texto
  voz.js            WebRTC con Realtime
  style.css
data/               hechos.json y conversacion.json
```

La API usa **Responses**, no Chat Completions: es la única que acepta
servidores MCP remotos.

## Configuración

| Variable | Para qué |
|---|---|
| `OPENAI_API_KEY` | Tu clave (obligatoria) |
| `OPENAI_MODEL` | Modelo de texto. `gpt-5.6-terra` |
| `OPENAI_MODELO_VOZ` | Modelo de voz. `gpt-realtime-2.1-mini` |
| `JARVIS_VOZ` | Voz de Realtime (`marin`, `cedar`, `alloy`...) |
| `SUPABASE_ACCESS_TOKEN` | Token de Supabase (opcional) |
| `SUPABASE_PROJECT_REF` | Acota a un proyecto |
| `SUPABASE_SOLO_LECTURA` | `true` impide toda escritura |
| `JARVIS_NOMBRE` / `JARVIS_USUARIO` / `JARVIS_CIUDAD` | Personalización |
