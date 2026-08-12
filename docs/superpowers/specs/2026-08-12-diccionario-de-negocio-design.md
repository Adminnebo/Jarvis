# Diccionario de negocio para las fuentes de datos

Fecha: 2026-08-12
Estado: aprobado, pendiente de plan de implementación

El trabajo va en dos fases. La **fase 1** mueve la configuración de Jarvis del
disco a Postgres; la **fase 2** construye el diccionario. Son independientes —
la fase 1 sirve por sí sola — pero van en este orden para que el glosario nazca
guardado en la base y no haya que migrarlo después.

---

# Fase 1 — La configuración vive en Postgres

## Problema

Jarvis está hospedado y el sistema de archivos es efímero: cada despliegue
empieza de cero. Se pierden las fuentes, la memoria, el caché del esquema y
—lo más grave— `clave.key`, sin la cual **las credenciales guardadas quedan
indescifrables**. El README ya lo advierte en "El disco se borra".

El fallo además es silencioso: `secretos.descifrar` devuelve cadena vacía cuando
no puede descifrar, así que tras un redespliegue las fuentes siguen apareciendo
en el panel pero fallan con "usuario o contraseña incorrectos". Parece un
problema de red y en realidad es la clave perdida.

## Decisión

La configuración se guarda en el **Supabase que Jarvis ya usa**, en un esquema
`jarvis` separado de `public`. Cero infraestructura nueva y respaldo automático.

Descartado montar un volumen persistente: resuelve el mismo problema con cero
código, pero no da respaldo ni portabilidad entre hostings, y el glosario de la
fase 2 es trabajo manual que no se quiere rehacer nunca.

**Lo que Postgres no resuelve.** `JARVIS_CLAVE_SECRETA` sigue siendo obligatoria.
Las credenciales se guardan cifradas igual que hoy, y la clave que las descifra
tiene que vivir en una variable de entorno. Postgres reemplaza el volumen, no
la clave.

**Por qué siguen cifradas dentro de la base.** Jarvis tiene acceso de lectura a
ese mismo Supabase. Si la tabla guardara las contraseñas en claro, Jarvis podría
leerlas con un `select` y recitarlas en voz alta. Cifradas, lo peor que puede
leer es texto inútil. El esquema `jarvis` además queda fuera de lo que Jarvis
lista como consultable.

## Componentes

### `backend/almacen.py` (nuevo)

Un almacén de clave → JSON. No sabe qué guarda; solo dónde.

| Función | Qué hace |
|---|---|
| `leer(clave)` | Devuelve el JSON guardado, o `None`. |
| `escribir(clave, valor)` | Guarda (upsert). |
| `borrar(clave)` | Elimina la entrada. |
| `iniciar()` | Crea el esquema y la tabla si faltan, y migra lo que haya en disco. |
| `estado()` | Si está usando Postgres o disco, y el último error. |

Dos respaldos, elegidos por configuración:

- **Postgres** cuando `JARVIS_CONFIG_DB_URL` tiene valor. Si está vacía, cae a
  `SUPABASE_DB_URL`.
- **Disco** cuando ninguna de las dos existe. Es el comportamiento actual y
  mantiene el arranque local sin configurar nada, que es como funciona hoy
  `iniciar.bat`.

Tabla:

```sql
create schema if not exists jarvis;
create table if not exists jarvis.config (
    clave       text primary key,
    valor       jsonb not null,
    actualizado timestamptz not null default now()
);
```

Claves usadas: `fuentes`, `glosario`, `memoria`, `conversacion`, `esquema`,
`esquema_fuentes`.

**Conexión de escritura.** `esquema.consultar_directo` abre sus conexiones con
`read_only = True`. El almacén necesita escribir, así que abre la suya propia
sin ese modo. Es la misma cadena de conexión con distinto modo de transacción,
y es deliberado: la vía por la que Jarvis consulta datos sigue siendo incapaz de
escribir.

### Migración desde disco

En `iniciar()`, para cada clave: si no existe en Postgres y sí existe el archivo
en disco, se importa. Idempotente — al segundo arranque no hace nada. Los
archivos de disco no se borran: quedan como respaldo frío.

`clave.key` **no** se migra. Es la clave de cifrado y no debe vivir en la misma
base que lo cifrado. Va en `JARVIS_CLAVE_SECRETA`.

### Fallar ruidosamente

Si hay cadena de conexión configurada y la base no responde, Jarvis **no** cae
de vuelta al disco. Un disco vacío haría parecer que las fuentes se borraron.
En su lugar:

- `iniciar()` registra el error y el almacén queda marcado como caído.
- Toda lectura o escritura lanza un error claro en vez de devolver vacío.
- `/api/estado` reporta el fallo y la interfaz lo muestra como aviso visible.

Jarvis arranca igual y sigue respondiendo lo que no necesita configuración
(hora, clima, conversación), pero dice sin ambigüedad que no puede leer su
configuración.

### Puntos de enganche

`fuentes.py`, `memoria.py` y el caché de `esquema.py` dejan de usar
`rutas.archivo(...)` directamente y pasan por `almacen`. Sus interfaces públicas
no cambian, así que ni las rutas de la API ni la web se enteran.

Además hay que esconder el esquema nuevo de lo que Jarvis puede consultar:
`fuentes.SQL_TABLAS["supabase"]` y `fuentes.SQL_COLUMNAS["supabase"]` filtran una
lista de esquemas del servicio, y hay que añadir `jarvis` a esa lista. La base
principal no necesita cambio: `esquema.SQL_ESQUEMA` ya filtra por
`nspname = 'public'`.

### Variables de entorno

| Variable | Papel |
|---|---|
| `JARVIS_CLAVE_SECRETA` | **Obligatoria al hospedar.** Descifra las credenciales. Sin ella, cada despliegue las inutiliza. |
| `JARVIS_CONFIG_DB_URL` | Dónde guardar la configuración. Si está vacía se usa `SUPABASE_DB_URL`. |
| `JARVIS_DATA_DIR` | Sigue existiendo para el respaldo en disco y el uso local. |

`.env.example` y el README se actualizan con las dos primeras.

## Pruebas de la fase 1

- **Respaldo en disco**: escribir, leer y borrar conserva y elimina los datos.
- **Migración**: con archivos en disco y tabla vacía, `iniciar()` los importa;
  al segundo arranque no los duplica ni los pisa.
- **Sin fallback silencioso**: con la base caída, leer lanza error en vez de
  devolver vacío.
- **Selección de respaldo**: sin variables usa disco; con `JARVIS_CONFIG_DB_URL`
  usa Postgres; con solo `SUPABASE_DB_URL` usa Postgres.
- **Aislamiento**: el esquema `jarvis` no aparece en `esquema.indice()` ni en el
  listado de tablas de una fuente Supabase.

La parte de Postgres se prueba contra la base real. Solo toca la tabla
`jarvis.config`: nunca se borran tablas, solo filas de prueba con una clave
propia.

## Verificación manual

Redesplegar dos veces seguidas y comprobar con el botón "Probar" que las fuentes
siguen conectando. Ese es el fallo que esta fase existe para eliminar.

---

# Fase 2 — El diccionario

## Problema

Jarvis consulta las fuentes externas (PostgreSQL, SQL Server, otro Supabase)
escribiendo SQL a mano. Lo único que sabe de esas bases son los nombres crudos
de tabla y columna que saca de `information_schema`.

En la base de productos las columnas de precio se llaman `p1`, `p2`, `p3`. Un
humano nunca pregunta por `p1`: pregunta por "el precio 1", "el precio uno",
"el primer precio", "el de lista". Jarvis no tiene forma de saber que son la
misma cosa, así que inventa columnas, elige la tabla equivocada, o pregunta en
vez de responder. Lo mismo pasa con cualquier otra columna de nombre críptico.

Cuatro fallos concretos a corregir:

1. Inventa o se equivoca de columna y de tabla.
2. Pregunta en vez de asumir lo razonable y contestar.
3. No reconoce variantes de un mismo término ("precio uno" / "p1" / "PRECIO 1").
4. Responde en formato de pantalla cuando la respuesta se lee en voz alta.

## Decisión de fondo: cómo le llega el diccionario al modelo

**Elegido: anotar el esquema.** El diccionario no vive en el prompt. Enriquece
la salida de `ver_esquema_fuente`, que el modelo ya llama antes de escribir SQL.
El modelo pasa de leer `p1 numeric` a leer
`p1 numeric — Precio 1 (precio uno, primer precio, lista)`.
Coste en el prompt: cero. Escala a cientos de columnas.

Descartadas:

- **Todo en el prompt del sistema.** Paga el peso en cada petición y en cada
  sesión de voz. El propio código ya rechazó esta idea: `esquema.indice()`
  documenta que volcar todas las columnas costaba ~1600 tokens y duplicaba la
  latencia de decisión.
- **Traducir la pregunta antes de que el modelo la vea.** Reescribir
  "precio 1" → "p1" en el texto del usuario es frágil ante cualquier paráfrasis,
  y deja al modelo sin saber *qué es* p1: respondería "el p1 es 340" en lugar de
  "el precio 1 es 340".

## Arquitectura

Un módulo nuevo (`glosario.py`), dos claves nuevas en el almacén de la fase 1
(`glosario` y el caché `esquema_fuentes`), y puntos de enganche en código que ya
existe. Ninguna función actual cambia de firma.

```
web/glosario.js  ──► /api/fuentes/{id}/glosario ──► backend/glosario.py
                                                          │
                                                    almacen["glosario"]
                                                          │
backend/herramientas.py                                   │
  ver_esquema_fuente ──► fuentes.esquema_de ──► glosario.anotar
  buscar_columna     ─────────────────────────► glosario.buscar
  consultar_fuente   ──► (al fallar) ──► fuentes.columnas_citadas ──┘
                                              │
                                    almacen["esquema_fuentes"] (caché)
```

`fuentes.columnas_citadas` y el caché son piezas nuevas dentro de `fuentes.py`.

## Componentes

### 1. `backend/glosario.py` (nuevo)

Único responsable de qué significa cada tabla y columna. No sabe conectarse a
ninguna base ni hablar con el modelo.

Persiste bajo la clave `glosario` del almacén de la fase 1. Estructura:

```json
{
  "a1b2c3d4": {
    "tablas": {
      "PRODUCTOS": "Catálogo de artículos con sus precios"
    },
    "columnas": {
      "PRODUCTOS.p1": {
        "significado": "Precio 1 (lista)",
        "sinonimos": ["precio 1", "precio uno", "primer precio", "lista"]
      }
    }
  }
}
```

La clave exterior es el id de la fuente. Las claves de columna son
`TABLA.COLUMNA`, comparadas sin distinguir mayúsculas.

Interfaz pública:

| Función | Qué hace |
|---|---|
| `leer(id_fuente)` | El glosario de una fuente, o vacío si no tiene. |
| `guardar(id_fuente, datos)` | Valida y escribe. Descarta entradas sin significado ni sinónimos. |
| `borrar_fuente(id_fuente)` | Limpia el glosario al borrar la fuente. |
| `anotar(id_fuente, tablas)` | Recibe la lista de tablas de `fuentes.esquema_de` y devuelve la misma lista con los significados intercalados. |
| `buscar(id_fuente, termino)` | Devuelve las columnas cuyo significado o sinónimos coinciden con el término. |
| `sugerencias(tablas)` | Detecta patrones (`p1..pN`) y propone entradas prerrellenadas, sin guardarlas. |

**Normalización** (resuelve el fallo 3). Antes de comparar, tanto el término
buscado como los sinónimos guardados pasan por: minúsculas, sin acentos, sin
signos, espacios colapsados, y los números escritos en palabra convertidos a
dígito (`uno`→`1` … `diez`→`10`, más `primer`/`primero`→`1`, `segundo`→`2`,
`tercero`→`3`). Así "el Precio Uno" y "precio 1" son la misma clave.

**Escritura concurrente.** Mismo patrón que `fuentes.py`: un `threading.Lock` a
nivel de módulo alrededor de leer-modificar-escribir.

### 2. Caché del esquema de fuentes

Hoy `fuentes.esquema_de` va a la base en cada llamada y trae hasta 5000 filas de
`information_schema`. Con el diccionario el modelo va a consultar el esquema
mucho más seguido, así que se cachea.

Se sigue el patrón ya establecido en `esquema.py` para la base principal: clave
`esquema_fuentes` en el almacén, con `creado` por fuente y una vigencia de 12
horas. Se añade `refrescar_esquema_de(id_fuente)` para forzarlo, expuesto en la
interfaz con un botón, porque el esquema de un ERP cambia sin avisar.

Guardar o borrar una fuente invalida su entrada de caché.

### 3. Herramienta `buscar_columna(fuente, termino)` (nueva)

El atajo para cuando la pregunta usa una palabra del negocio. Devuelve las
columnas que coinciden, con su tabla:

```
PRODUCTOS.p1 — Precio 1 (lista)
```

Si no hay coincidencia, lo dice y sugiere pedir el esquema completo. Si hay
varias, las lista todas: elegir es trabajo del modelo, no del diccionario.

### 4. Errores que enseñan (resuelve el fallo 1)

Cuando `consultar_fuente` falla porque una columna o tabla no existe, hoy
devuelve el mensaje crudo del motor. Pasará a devolver el error **más las
columnas reales** de las tablas mencionadas en el SQL, tomadas del esquema
cacheado y ya anotadas con el glosario.

El modelo se corrige en el mismo turno en lugar de reintentar a ciegas. Lo
implementa `fuentes.columnas_citadas(id_fuente, sql)`: extrae los nombres de
tabla del SQL con una expresión regular sobre `from` y `join`, y los busca en el
esquema cacheado. Si no reconoce ninguna tabla, devuelve la lista de tablas de la
fuente.

### 5. Panel "Diccionario" en la web

Botón nuevo en cada tarjeta de fuente, junto a "Tablas" y "Consultar". Abre un
modal (mismo patrón que la consola SQL) con:

- Las tablas y columnas **reales** de la fuente, del esquema cacheado.
- Por tabla: un campo de texto para su significado.
- Por columna: significado y sinónimos (los sinónimos separados por comas).
- Un botón **"Detectar precios"** que rellena las entradas propuestas por
  `sugerencias()` sin guardarlas. El usuario revisa y guarda.
- Buscador para filtrar columnas por nombre: en un ERP hay demasiadas para
  recorrerlas a mano.

Las columnas sin significado ni sinónimos no se guardan y no existen para el
glosario. Un diccionario a medias es lo normal y funciona bien: solo se anota lo
que la gente nombra en voz alta.

### 6. Ajustes al prompt (`cerebro.instrucciones`)

En el bloque de "Otras fuentes de datos conectadas":

- Antes de escribir SQL a una fuente, pedir siempre `ver_esquema_fuente`. Nunca
  inventar nombres de tabla ni de columna.
- Muchas columnas traen su significado anotado entre guiones. Ese significado
  manda sobre el nombre técnico.
- Si la pregunta usa una palabra del negocio que no aparece en el esquema, usar
  `buscar_columna` antes de suponer.
- **Traducir hacia dentro, responder hacia fuera**: buscar en `p1`, pero
  contestar "el precio 1 es 340", nunca "el p1 es 340". El usuario no conoce los
  nombres técnicos y no tiene por qué oírlos.

Y se refuerza lo que ya está pero no se cumple (fallos 2 y 4):

- Ante una pregunta ambigua, elegir la interpretación más razonable, responder, y
  decir en una frase qué se asumió. No preguntar antes de consultar.
- Los resultados se leen en voz alta: dar el total y lo relevante, redondear las
  cifras grandes, no leer listas largas ni identificadores.

## Flujo de datos

Pregunta: *"¿cuál es el precio 2 del producto ABC?"*

1. El modelo ve en el prompt que existe la fuente `a1b2c3d4` "ERP producción".
2. Llama `ver_esquema_fuente("a1b2c3d4")`. Recibe el esquema **anotado**:
   `PRODUCTOS — Catálogo de artículos: codigo varchar, p1 numeric — Precio 1
   (precio uno, lista), p2 numeric — Precio 2 (precio dos, mayoreo), ...`
3. Escribe `select codigo, p2 from PRODUCTOS where codigo = 'ABC'`.
4. Responde: *"El precio 2 del ABC es 340 pesos."*

Si en el paso 2 el esquema fuera enorme y el modelo prefiriera el atajo, llama
`buscar_columna("a1b2c3d4", "precio 2")` y recibe `PRODUCTOS.p2 — Precio 2`.

## Manejo de errores

| Situación | Comportamiento |
|---|---|
| Glosario ilegible o con formato inesperado | Se trata como vacío. Jarvis funciona sin anotaciones, igual que hoy. Mismo criterio que `fuentes._leer`. |
| El almacén está caído | El panel del diccionario muestra el aviso de la fase 1. No se guarda a medias ni se pierde lo ya escrito en pantalla. |
| Fuente sin glosario | `anotar` devuelve el esquema tal cual. Sin ruido. |
| Glosario con una tabla que ya no existe | Se ignora al anotar. El panel la marca como huérfana para que el usuario la borre. |
| No se puede leer el esquema de la fuente | El panel muestra el error de `fuentes.explicar`; el glosario guardado no se pierde. |
| SQL con columna inexistente | Error del motor + columnas reales de las tablas citadas. |
| `buscar_columna` sin coincidencias | Texto claro y sugerencia de pedir el esquema completo. |

## Pruebas

`glosario.py` es lógica pura sobre diccionarios: se prueba sin base de datos ni
red, que es la razón de separarlo de `fuentes.py`.

- **Normalización**: "Precio Uno", "precio 1", "PRECIO  1" y "el precio uno"
  colapsan a la misma clave.
- **Búsqueda**: encuentra por significado y por sinónimo; devuelve varias
  coincidencias cuando las hay; devuelve vacío sin inventar.
- **Anotado**: una columna con glosario sale anotada, una sin glosario sale
  intacta, y una entrada de glosario sin columna real no aparece.
- **Sugerencias**: detecta `p1..p5` y propone "Precio 1".."Precio 5"; no propone
  nada ante columnas sin patrón; no persiste nada por su cuenta.
- **Persistencia**: guardar y releer conserva los datos; un valor con formato
  inesperado se lee como vacío; borrar la fuente borra su glosario.
- **Extracción de tablas del SQL**: reconoce `from`, `join`, alias y nombres con
  esquema (`dbo.PRODUCTOS`).

Verificación manual al final: conectar la fuente real, anotar `p1..p3`, y
comprobar por texto y por voz que "precio 2" llega a `p2` y que la respuesta
dice "precio 2".

## Convenciones del proyecto

- Python sin acentos en comentarios, docstrings y nombres; la web con acentos.
  Es lo que hace el código actual y se mantiene.
- Nombres en español, como el resto del proyecto (`glosario`, `anotar`,
  `sugerencias`).
- Los formularios de la web se dibujan desde datos del backend siempre que se
  pueda, siguiendo lo que ya hace `fuentes.js`.
- Los comentarios explican **por qué**, no qué. El código actual es consistente
  en esto y hay que respetarlo.

## Fuera de alcance

Decidido explícitamente, no por olvido:

- **Búsqueda difusa sobre los datos** (encontrar un producto por nombre parcial o
  mal escrito). Es otro problema: este diccionario describe el esquema, no el
  contenido.
- **Reglas de negocio libres por fuente** ("los precios no llevan IVA").
  Descartado al elegir el alcance del diccionario.
- **Mover `clave.key` a la base.** La clave de cifrado no puede vivir en el mismo
  sitio que lo que cifra. Va en `JARVIS_CLAVE_SECRETA`.
- **Panel web para administrar el almacén.** La fase 1 se configura con variables
  de entorno; su estado se ve en `/api/estado` y en el aviso de la interfaz.
- **Glosario para la base principal de Supabase.** Ahí el catálogo de consultas
  pre-escritas ya cumple esa función.
- **Autocompletar significados con el modelo.** El auto-relleno se limita a
  patrones evidentes; inventar significados de columnas es exactamente el error
  que este trabajo viene a eliminar.
