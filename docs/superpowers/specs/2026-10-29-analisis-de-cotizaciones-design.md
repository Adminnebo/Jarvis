# Análisis de márgenes y variantes de una cotización — diseño

Fecha: 2026-10-29
Repo: Adminnebo/Jarvis (rama de trabajo `feat/analisis-cotizaciones`; `main` despliega solo)

## Qué se quiere

Pedido del 2026-10-29 (nota de voz transcrita + mensajes):

> "En una cotización de 10 productos, por ejemplo: al producto 4 ponle el precio
> 45, el 5 es 35, pero dime de ese producto, con ese ajuste que hice, qué margen
> de ganancia tengo, pero compáramelo overall. Si yo sigo bajando precio, qué
> porcentaje de ganancia general tengo en esta cotización, porque al final se
> puede bajar el porcentaje de ganancia en un producto, pero no deberíamos dejar
> de ganar."

> "Jálame la cotización 1000 y dime qué tiene. [...] Genérame una con esos
> productos pero a costo y luego una con margen del 50 % desde el costo, y que
> me dé las 2. [...] Y el producto X que está en la cotización 1000, ¿cuál es mi
> margen actual de ganancia overall?"

En concreto, por voz o texto:

1. **Traer una cotización** (real de JH o JV) y decir qué tiene: productos,
   precios y margen.
2. **Sacar variantes** de esa cotización con los mismos productos: a costo, con
   X % sobre el costo, a un nivel... **varias a la vez**, y emitirlas juntas.
3. **Preguntar por el margen** de cualquiera de ellas, de un producto y de la
   cotización completa, sin perder las demás ("¿y el producto X en la 1000?").
4. **Cambiar precios producto por producto** en una variante y ver el antes y
   el después del producto y del total.
5. **Fijar un piso** en la conversación ("cuida un 18 %") y que Jarvis avise
   cuando se rompe y diga el precio más bajo posible sin romperlo.

## Decisiones del usuario (2026-10-29)

- **Jarvis es para la alta gerencia y los dueños.** Se puede poner cualquier
  precio, aunque rompa el piso o quede por debajo del costo. Jarvis **nunca
  bloquea**: avisa claro, solo en la conversación.
- **El porcentaje se cuenta sobre el costo.** "Margen del 50 % desde el costo"
  con costo RD$ 100 = **RD$ 150** (recargo), no RD$ 200.
- **El piso se dice en la conversación.** No hay piso por defecto ni panel.
- **Todos los usuarios de la organización JH** pueden ver costos y márgenes.
- **No hay compensación automática:** si se rompe el piso, Jarvis dice el
  precio mínimo y qué productos tienen más margen, pero no propone repartos.
- **Varias variantes, una confirmación:** Jarvis prepara las variantes, dice
  total y margen de cada una y pregunta "¿las emito?". Con un sí, salen todos
  los PDFs.

## Hallazgos en los datos (Base JH, consultado el 2026-10-29)

- `List_ProductosIA` tiene la columna **`costo`**, con valor en los 13 750
  productos. **No** existe `Coste`.
- Los niveles salen del costo con márgenes redondos **sobre la venta**:
  `Pn = costo / (1 − m)`. Por ejemplo, para el producto 6015, P1..P7 = 42, 39,
  36, 23, 21, 19 y 17 % de la venta. Por lo tanto, `costo` está en la **misma
  base que los precios (con ITBIS)**, y el margen se calcula directo con precio y
  costo.
  - Ojo: P1 de ese producto es 42 % de la venta, que es **72 % sobre el
    costo**. Al hablar de niveles, Jarvis usa siempre la cifra sobre el costo.
- `dCotizacionesWebIA` (detalle de las cotizaciones reales de JH) trae
  `precio` (con ITBIS) y `cantidad`, pero `costo = 0`. **El costo siempre sale
  del catálogo, con su valor de hoy.**
- En `jarvis_cotizaciones` (JV), las líneas guardan `precio_unitario`, y `coste`
  es 0 salvo en las cotizadas "al coste". Mismo criterio: el costo sale del
  catálogo.

## Definiciones

Para cada línea (precio unitario `p` con ITBIS, costo `c`, cantidad `q`):

- **Margen del producto** = `(p − c) / c`, sobre el costo. A RD$ 150 con costo
  100 → 50 %.
- **Ganancia del producto** (RD$) = `(p − c) · q`.

Para una cotización:

- **Costo total** `C = Σ c·q`, **venta** `V = Σ p·q`, **ganancia** `G = V − C`.
- **Margen general** = `G / C`. Queda ponderado solo: bajar un producto barato
  casi no lo mueve, y bajar uno caro sí.

Todo porcentaje que diga Jarvis lleva su base ("50 % sobre el costo"). Si
alguien pide una cifra "de la venta", Jarvis la da (`G / V`) diciendo que es
otra medida.

**Precio mínimo** de la línea *k* para no bajar del piso `f`, con las demás
líneas como están (`C'` y `G'` son el costo y la ganancia sin esa línea):

```
p_min = c_k + (f · (C' + c_k·q_k) − G') / q_k
```

Si sale menor que 0, cualquier precio cumple. Si `p_min` queda por debajo del
costo, se puede vender ese producto a pérdida y aun así cumplir el piso, y
Jarvis lo dice así.

## Cómo funciona

### La mesa de trabajo

Cada usuario tiene una **mesa** con varias cotizaciones a la vez:

- **La original**: la que trajo con `buscar_cotizacion` (la 1000 de JH, la
  JV-12...). Es de **solo lectura**: se analiza con los precios con que se
  cotizó, pero no se cambia.
- **Las variantes**: borradores que salen de la original o de
  `preparar_cotizacion`. Cada uno tiene un nombre corto que pone Jarvis según
  cómo se armó ("a costo", "costo + 50 %", "P5", "ajustada"). Estas sí se
  ajustan y se emiten.

Para referirse a una cotización, se acepta su número ("la 1000"), el nombre de
la variante ("la del 50") o "la original". Si no se dice, se usa **la última
que se tocó**. Si la referencia es ambigua, Jarvis pregunta.

Buscar otra cotización **reemplaza la mesa**: las variantes sin emitir de la
anterior se descartan, y Jarvis avisa si había alguna. Máximo 5 variantes por
mesa.

Las líneas se numeran **en el orden del PDF** (1..N) y se mantienen igual en
todas las variantes de una misma original. "El producto 4" es la línea 4 en
cualquiera de ellas. También se acepta el código o un pedazo de la descripción.

### El ejemplo del pedido, paso a paso

1. "Jálame la cotización 1000" → `buscar_cotizacion` → la original queda en la
   mesa. Jarvis dice cliente, fecha, total, cantidad de productos y **margen
   general actual** (precios de la 1000, costo de hoy). La lista de productos
   va en la web; por voz, solo si la piden.
2. "Genérame una a costo y otra con 50 % sobre el costo" →
   `crear_variantes([{base: costo, margen: 0}, {base: costo, margen: 50}])`.
   Jarvis responde: "Preparé dos: **a costo** RD$ X (0 %) y **costo + 50 %**
   RD$ Y (50 %). ¿Las emito?".
3. "Sí" → `emitir_cotizacion(cuales="todas")` → dos JV y dos PDFs.
4. "¿Y el producto X en la 1000, cuál es mi margen overall?" →
   `analizar_cotizacion(cotizacion="1000", producto="X")`: margen de X en la
   1000 y margen general de la 1000.

### Herramientas

**1. `buscar_cotizacion`** (existe): además de lo de hoy, carga la original en
la mesa con sus precios y devuelve el margen general.

**2. `crear_variantes(variantes, piso="")`** (nueva; `recotizar` pasa a ser un
caso de esta). Cada variante dice **una** base:

| base | ejemplo hablado | precio de cada línea |
|---|---|---|
| `costo` + `margen` | "a costo", "costo más 50" | `c · (1 + m)` |
| `nivel` | "a precio 5", "a 55" | igual que `recotizar` hoy (P1..P7 y la clave pegada de JH) |
| `original` + `descuento` | "la misma con 5 % menos" | `p · (1 − d)` |

Devuelve, por cada variante, su nombre, total y margen general, y pregunta si
se emiten.

**3. `ajustar_precios(cambios, cotizacion="", piso="")`** (nueva): cambia una
o varias líneas de **una variante** en una sola llamada ("al 4 ponle 45 y al 5,
35"). Cada cambio dice la línea y una de estas formas: `precio` (RD$ con ITBIS),
`margen` (% sobre el costo), `nivel`, `descuento` u `original` (vuelve al
precio con que nació la variante). Devuelve, por cada línea, el **antes →
después** de precio, margen y ganancia, y el margen general antes → después.
Si queda bajo el piso o a pérdida, **se aplica igual** y se avisa con la cifra
y el precio mínimo.

Si se pide ajustar la original, Jarvis crea una variante "ajustada" a partir de
ella y ajusta esa.

**4. `analizar_cotizacion(cotizacion="", producto="", piso="")`** (nueva): sin
cambiar nada, da el margen general (costo, venta, ganancia, %) y:

- con `producto`: el margen de ese producto y cuánto pesa en la ganancia;
- sin `producto`: lo que llama la atención: el de menos margen, los que están a
  pérdida y los que no tienen costo (que no entran en el cálculo);
- con `piso`: cuánto sobra o falta, y el precio mínimo de cada producto
  pedido.

También responde "¿hasta dónde puedo bajar el producto 4 sin bajar del 18 %?" y
"compárame las tres" (una línea por cotización: total y margen).

**5. `emitir_cotizacion(cuales="")`** (existe; se amplía): emite la variante
indicada, o todas con `cuales="todas"`. Cada una sale como **JV nueva** con su
PDF. Las cotizaciones de JH no se tocan nunca en JH. El PDF y WhatsApp **no**
llevan costos ni márgenes.

**El piso**: lo fija cualquiera de las herramientas con `piso` ("cuida un
18 %", sobre el costo). Vale para toda la mesa hasta que se cambie o se quite.

### Lo que dice Jarvis (sobre todo por voz)

- Después de un ajuste: el producto cambiado (precio y margen nuevo) y el
  margen general antes → después. Si se rompió el piso, decirlo en la misma
  frase. Nada más.
- Al analizar: margen general y ganancia en RD$, más lo que llama la atención.
  La tabla completa solo si la piden (en la web va como tabla en el chat).
- Porcentajes con un decimal y siempre con su base; la plata redondeada al
  hablar.
- Una vez por mesa: "con el costo de hoy del catálogo".

### Lo que se guarda al emitir

Sin cambiar el esquema de `jarvis_cotizaciones`: dentro de `productos` (jsonb),
cada línea agrega `costo`, `margen` (sobre el costo), `precio_original` y
`ajuste` (cómo salió el precio), y la cotización guarda de qué original salió.
Así se puede revisar después con qué margen se emitió, aunque cambie el costo en
el catálogo.

### Que no se pierda con un reinicio

Hoy los borradores y las cotizaciones encontradas viven en memoria (30 min).
Con el despliegue automático, cada push a `main` reinicia Jarvis y se pierde lo
que alguien estaba armando. La mesa pasa a la base SQLite del volumen (`/data`,
`basedatos.py`): una fila por usuario con la original, las variantes, el piso y
la última tocada. Vigencia: **2 horas desde el último uso**.

### La columna del costo

La columna del costo va fija en una variable (`JARVIS_COLUMNA_COSTO`, por
defecto `costo`), y el modelo no la elige: un nombre mal elegido daría márgenes
falsos sin que nadie lo note.

## Fuera de alcance

- Repartos automáticos para volver al piso.
- Un panel visual de análisis (en la web es una tabla dentro del chat).
- Piso por defecto o configuración en la web.
- Avisos a otras personas.
- Escribir en la Base JH (sigue siendo de solo lectura).
- El costo histórico: siempre se usa el de hoy.

## Abierto

- **La "utilidad" que ya existe usa la otra base.** Hoy "cotizar al coste con
  30 % de utilidad" (`preparar_cotizacion`) y la utilidad de `recotizar`
  ("precio 5 con un 6 %") calculan `c / (1 − %)`, sobre la venta: costo 1000 +
  30 → **1428.57**, no 1300. Esto se decidió a propósito (está comentado en el
  código), pero choca con la decisión de hoy. ¿Se pasa todo a "sobre el costo",
  o la clave de niveles de JH ("55") se queda como está porque es nomenclatura
  propia de JH?

## Pruebas

- El ejemplo del pedido: buscar → dos variantes (costo y +50 %) → emitir las dos
  → margen de un producto en la original.
- Margen por línea y general, comparado con cálculo a mano (incluido el audio:
  10 productos, el 4 a 45 y el 5 a 35).
- Las formas de variante y de ajuste, `original` y varios cambios en una
  llamada.
- Precio mínimo: caso normal, cualquier precio cumple, y se cumple aun a
  pérdida.
- Referencias: "la 1000", "la del 50", "la original", última tocada, ambigua.
- Ajustar la original crea una variante; la original no cambia.
- Línea sin costo (fuera del cálculo, avisada) y línea a pérdida.
- Cotización JH cargada con sus precios (no recalculados) y emitida como JV.
- La mesa sobrevive a un reinicio y vence a las 2 h sin uso; buscar otra
  reemplaza la mesa y avisa si había variantes sin emitir.
- El PDF y el mensaje de WhatsApp no contienen costos ni márgenes.

## Orden de trabajo

1. La mesa en SQLite (original + variantes + piso), reemplazando
   `_borradores` y `_encontradas`.
2. Cálculo puro (márgenes, precio mínimo, variantes, ajustes) con sus pruebas.
3. Cargar la original con sus precios (JH y JV).
4. Herramientas: `crear_variantes`, `ajustar_precios`, `analizar_cotizacion`,
   y ampliar `buscar_cotizacion` y `emitir_cotizacion`; textos para el modelo.
5. Guardar costo, margen, precio original y ajuste al emitir.
6. Prueba de punta a punta en la rama, con una cotización real de JH, sin
   emitir. Después, pasar a `main` (que despliega).
