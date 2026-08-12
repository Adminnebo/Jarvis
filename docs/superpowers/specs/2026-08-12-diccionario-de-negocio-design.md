# Diccionario de negocio para las fuentes de datos

Fecha: 2026-08-12
Estado: aprobado, pendiente de plan de implementación

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

Un módulo nuevo (`glosario.py`), dos archivos de datos nuevos
(`glosario.json` y el caché `esquema_fuentes.json`), y puntos de enganche en
código que ya existe. Ninguna función actual cambia de firma.

```
web/glosario.js  ──► /api/fuentes/{id}/glosario ──► backend/glosario.py
                                                          │
                                                    glosario.json
                                                          │
backend/herramientas.py                                   │
  ver_esquema_fuente ──► fuentes.esquema_de ──► glosario.anotar
  buscar_columna     ─────────────────────────► glosario.buscar
  consultar_fuente   ──► (al fallar) ──► fuentes.columnas_citadas ──┘
                                              │
                                        esquema_fuentes.json (caché)
```

`fuentes.columnas_citadas` y el caché son piezas nuevas dentro de `fuentes.py`.

## Componentes

### 1. `backend/glosario.py` (nuevo)

Único responsable de qué significa cada tabla y columna. No sabe conectarse a
ninguna base ni hablar con el modelo.

Persiste en `glosario.json`, en la carpeta de datos (`rutas.archivo`), junto a
`fuentes.json`. Estructura:

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

Se sigue el patrón ya establecido en `esquema.py` para la base principal:
archivo `esquema_fuentes.json` en la carpeta de datos, con `creado` por fuente y
una vigencia de 12 horas. Se añade `refrescar_esquema_de(id_fuente)` para
forzarlo, expuesto en la interfaz con un botón, porque el esquema de un ERP
cambia sin avisar.

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
| `glosario.json` corrupto o ilegible | Se trata como vacío. Jarvis funciona sin anotaciones, igual que hoy. Mismo criterio que `fuentes._leer`. |
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
  nada ante columnas sin patrón; no escribe en disco.
- **Persistencia**: guardar y releer conserva los datos; un archivo corrupto se
  lee como vacío; borrar la fuente borra su glosario.
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
- **Glosario para la base principal de Supabase.** Ahí el catálogo de consultas
  pre-escritas ya cumple esa función.
- **Autocompletar significados con el modelo.** El auto-relleno se limita a
  patrones evidentes; inventar significados de columnas es exactamente el error
  que este trabajo viene a eliminar.
