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

### Variables a configurar

| Variable | |
|---|---|
| `OPENAI_API_KEY` | Obligatoria |
| `JARVIS_PASSWORD` | Obligatoria al hospedar |
| `JARVIS_DATA_DIR` | Ruta del volumen persistente |
| `JARVIS_CLAVE_SECRETA` | Fija la clave de cifrado |
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
