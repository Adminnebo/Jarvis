# Recotizar desde una cotización existente — diseño

Fecha: 2026-10-28
Repo: Adminnebo/Jarvis (rama `feat/rediseno-grafito`)

## Qué se quiere

Que el usuario pueda, por voz o texto:

1. Pedir **la última cotización de un cliente** dando cualquier identificador
   ("dame la última cotización de Ferretería Eliam", "del cliente 6177", "del
   RNC 131-xxxxx", "la JV-12"), y que Jarvis le diga **cuál es** (número,
   cliente, fecha, total y la lista de productos).
2. Luego **re-cotizar esos mismos productos** a un nivel de precio que el
   usuario elige ("ahora los quiero a precio 7", "precio 5 con un 6%"),
   generando una **cotización nueva** (nuevo JV + PDF) para el mismo cliente,
   sin tocar la vieja.

La cotización vieja sirve sobre todo como **fuente de la lista de productos**:
el usuario no la vuelve a dictar.

## Contexto del código actual

- Las cotizaciones emitidas se guardan completas en Supabase
  `jarvis_cotizaciones`: `numero`, `creada_at`, `usuario`, `cliente` (jsonb:
  nombre, rnc, codigo, direccion, email, telefono, nivel, factor, ciudad,
  contacto…), `productos` (jsonb: líneas con codigo, referencia, descripcion,
  unidad, cantidad, coste, precio_unitario, TipoItbis, precio_bruto,
  itbis_linea, subtotal_linea), `subtotal`, `itbis`, `total`, `pdf_ruta`,
  `estado`.
- Flujo de emisión en `backend/cotizaciones.py`: `preparar()` arma un
  `Borrador` en memoria (por usuario, vigencia 30 min) y `emitir()` lo numera,
  genera el PDF (pdfjh) y lo sube al bucket privado.
- Cálculo de precios (`calcular_linea`): dos modos.
  - **Nivel del cliente:** `precio = round(Pn * factor, 2)` (sin utilidad).
  - **Coste:** `precio = round(coste / (1 - utilidad/100), 2)` (margen sobre
    precio de venta, no recargo; no usa factor).
- Recuperación hoy: solo `buscar_emitida(numero)` por número exacto (para
  reenviar por WhatsApp). **No** hay búsqueda por cliente ni "la última de X".
- Búsqueda de clientes en la Base JH: `buscar_cliente(texto)` acepta código,
  RNC/cédula o nombre y corrige un RNC mal oído por una cifra
  (`clientes_con_rnc_parecido`). Solo lectura.

## Alcance

Dos herramientas nuevas que reusan el mecanismo de borrador/emisión existente.
**No** cambia el esquema de `jarvis_cotizaciones`, **no** cambia el cálculo
actual de `preparar`/`emitir`, y la Base JH sigue siendo solo lectura.

### 1. `buscar_cotizacion(consulta)` — encontrar la cotización

Entrada: texto libre (lo que dijo el usuario).

Detección del identificador, en este orden:

1. **Número JV** (`JV-\d+` o algo que normalice a eso): va directo a esa fila
   por `numero`, `estado = emitida`.
2. **Cualquier otro** (código, RNC/cédula, teléfono, nombre): se resuelve
   primero contra la Base JH con `buscar_cliente` para obtener el **código**
   del cliente; luego se consulta `jarvis_cotizaciones` por
   `cliente->>codigo = <código>`, `estado = emitida`, orden `numero` desc.
   - Teléfono: `buscar_cliente` hoy no busca por teléfono. Si el texto parece
     teléfono y `buscar_cliente` no lo resuelve, se cae al paso de nombre /
     o se avisa que no se encontró. (El teléfono se marcó como aceptable pero
     "puede no ser único"; no es la vía principal.)
   - Si `buscar_cliente` devuelve varios clientes, se le muestran al usuario
     para que elija, igual que hace `preparar` hoy.
3. **Contado** (cotizaciones con `codigo = ""`): no se pueden resolver por
   Base JH. Se buscan por nombre dentro de `jarvis_cotizaciones`
   (`cliente->>nombre ilike`) como respaldo.

Resultado: la última emitida (o una lista corta de candidatas si hay
ambigüedad real, ej. varias cotizaciones del mismo cliente o varios clientes).
Se devuelve un resumen legible: **número JV, cliente, fecha, total y la lista
de productos** (código, descripción, cantidad, precio actual de esa cotización).

Estado: la fila encontrada (su `cliente` y sus `productos`) se guarda en un
estado por usuario `_encontradas[id_usuario]` con vigencia 30 min, para que
`recotizar` la use sin que el modelo vuelva a cargar nada.

### 2. `recotizar(nivel, utilidad="")` — re-cotizar a un nivel elegido

Precondición: que exista una cotización encontrada vigente para ese usuario
(si no, se pide buscarla primero).

Pasos:

1. Toma los **códigos y cantidades** de la cotización encontrada (mismos
   productos, mismas cantidades).
2. Re-consulta el **catálogo actual** (`productos_del_catalogo`) para leer el
   precio del nivel pedido — precios frescos, no los guardados.
3. Calcula cada línea:
   - `nivel` = el que pidió el usuario (P1…P7), validado contra `NIVELES`.
   - Base = **Pn crudo del catálogo, SIN factor del cliente**
     (decisión tomada: "precio 7" = el número de la columna P7 tal cual).
   - Con `utilidad` (>0): `precio = round(base / (1 - utilidad/100), 2)` —
     misma fórmula de margen que hoy. Sin utilidad: `precio = base`.
   - Tope de utilidad reusa el actual (`MAX_UTILIDAD = 95`).
   - Si algún producto no tiene precio en ese nivel (Pn vacío/0), se dice cuáles
     y no se cotiza, igual que hoy en `preparar`.
4. Cliente = el mismo de la cotización encontrada (se reusa el jsonb `cliente`
   guardado; no hace falta re-buscar en Base JH).
5. Arma un `Borrador` (mismo dataclass y estado que `preparar`) y devuelve el
   resumen para confirmar, indicando el nivel usado y, si hubo, el % de
   utilidad.
6. `emitir_cotizacion` (sin cambios) emite una **JV nueva** y su PDF tras el
   "sí". La cotización vieja no se toca.

### Cambios internos previstos

- `calcular_linea`: admitir un tercer caso — base desde un nivel elegido (Pn
  sin factor) con utilidad opcional. Se puede generalizar el parámetro `coste`
  actual a un "origen de precio" {tipo: nivel|coste, nombre, utilidad} o
  agregar un caso paralelo; lo decide el plan de implementación.
- Nuevo estado `_encontradas: dict[str, <fila>]` con su candado y vigencia,
  espejo de `_borradores`.
- Funciones de consulta a Supabase para buscar por `cliente->>codigo`,
  `cliente->>nombre` y por `numero`, reusando `_supabase()`/`_cabeceras()`.
- Tools nuevas en `backend/herramientas.py`: `buscar_cotizacion` y `recotizar`,
  ambas con `disponible=_cotizaciones_disponibles`. Descripciones que dejen
  claro al modelo: no inventar precios ni productos, no leer en voz el número
  completo salvo que lo pidan.

## Casos de borde

- No existe cotización para ese cliente → se dice, y se ofrece prepararla
  desde cero con `preparar_cotizacion`.
- Identificador ambiguo (varios clientes, o teléfono repetido) → se listan las
  opciones para elegir.
- La cotización encontrada venció (>30 min) al llamar `recotizar` → se pide
  buscarla de nuevo.
- Producto de la cotización vieja que ya no está en el catálogo, o sin precio
  en el nivel pedido → se nombra y no se cotiza.
- Nivel inválido (no P1…P7) → error claro pidiendo un nivel válido.

## Pruebas

En `tests/test_cotizaciones.py`, con el catálogo y Supabase ya mockeados:

- `buscar_cotizacion` por número JV, por código, por RNC (incluida la
  corrección a una cifra), por nombre; y el caso de varias candidatas.
- `recotizar` reusa productos y cantidades, aplica el nivel pedido sin factor,
  aplica la utilidad con la fórmula de margen, y rechaza nivel inválido o
  producto sin precio en ese nivel.
- El borrador de `recotizar` lo emite `emitir_cotizacion` como una JV nueva,
  dejando la vieja intacta.
- Sin configurar (`configurado()` falso), las dos herramientas no se ofrecen.

## Fuera de alcance (YAGNI)

- Editar la lista de productos (quitar/agregar/cambiar cantidades) dentro de
  `recotizar`: si hace falta, se ajusta en otra vuelta con `preparar_cotizacion`.
- Re-cotizar a un cliente distinto del de la cotización encontrada.
- Darle a `preparar_cotizacion` un nivel explícito para cotizaciones desde
  cero (se puede sumar después si se quiere; el cálculo del nivel elegido
  queda compartido y listo para ello).

## Ampliación (2026-10-28): también las cotizaciones reales de JH

Pedido: que `buscar_cotizacion` no solo vea las JV de Jarvis, sino también las
cotizaciones reales de JH (las de Camila, numeradas tipo 3807).

**Fuente (ya existe, solo lectura).** La Base JH ya le expone a Jarvis dos vistas
`…IA` (el login de Jarvis solo ve vistas `List_*IA`/`*WebIA`, no las tablas
crudas):

- `dbo.iCotizacionesWebIA` — cabecera, una fila por cotización. Columnas que se
  usan: `nfactura` (número), `cliente` (código del cliente, entero),
  `clientenombre`, `RNC`, `Telefono`, `Direccion`, `Correo`, `Ciudad`, `Sector`,
  `Contacto`, `fecha`, `total`, `confirmada` (bit), `pago` (bit).
- `dbo.dCotizacionesWebIA` — líneas. Columnas que se usan: `nfactura` (une con la
  cabecera), `codigo` (del producto, coincide con `List_ProductosIA.Codigo`),
  `cantidad`, `Descripcion`, `Und`. Algunas líneas son `ProductoManual` (código
  que no está en el catálogo): esas no se pueden re-preciar; se nombran y se avisa.

**`buscar_cotizacion` ampliada.** Detección:

1. `JV-…` → `jarvis_cotizaciones` (como ya está).
2. Número pelado (ej. 3807) → se prueba como `iCotizacionesWebIA.nfactura`; si
   existe, es esa de JH. Si no existe, se sigue como identificador de cliente.
3. Código / RNC / nombre / teléfono → se resuelve el cliente contra la Base JH
   (`buscar_cliente`) para sacar su **código** (entero), y se consulta **las dos
   fuentes**: JH (`iCotizacionesWebIA where cliente = <código>`) y JV
   (`jarvis_cotizaciones where cliente->>codigo = <código>`).
   - Si solo una fuente tiene → se devuelve la última de esa y se guarda.
   - Si ambas tienen → se muestra la última de cada una (número, fecha, total,
     fuente) y se pide elegir; el usuario responde con el número (3807 o JV-…),
     que entra por los caminos 1/2. No se guarda ninguna hasta que elija.
   - Si ninguna → se dice y se ofrece preparar una nueva.

Todo se resuelve a **enteros** (código, nfactura) antes de armar el SQL, así que
no entra texto crudo del usuario a la consulta.

**Estado `Encontrada`** gana un campo `fuente` ("jh" | "jv") para el texto del
resumen; el número se muestra como `nfactura` (JH) o `JV-xxxxx` (JV).

**`recotizar` no cambia**: ya opera sobre `encontrada.productos`
(`[{codigo, cantidad, descripcion, unidad}]`), que se arma igual desde las líneas
de JH que desde las de JV. Emite una **JV nueva**; las de JH no se tocan.

**Límite:** la lista de líneas de una cotización de JH se lee con el mismo tope
`MAX_LINEAS` (60) que ya rige las cotizaciones; una de JH con más de 60 líneas
quedaría recortada (caso raro, se asume fuera de alcance).

**"La última en general" (ajuste post-prueba):** sin cliente ni número,
`buscar_cotizacion` trae la **última real de JH** (`iCotizacionesWebIA` ordenada
por fecha/nfactura desc) y menciona cuál es la última JV. Se eligió priorizar JH
en vez de "la más reciente por fecha" porque las JV de prueba/manuales son a
menudo más nuevas y tapaban la cotización real que se busca. Para la última de
Jarvis se pide explícitamente ("la última JV").

## Ampliación (2026-10-29): mandar una cotización de JH por WhatsApp

Pedido: poder enviar por WhatsApp las cotizaciones reales de JH (ej. la 3813), no
solo las JV. Antes el envío (`whatsapp._archivo_de_cotizacion`) exigía un número
JV con PDF en el bucket.

- Nuevo `cotizaciones.archivo_para_envio(numero)` resuelve el PDF a mandar: si el
  número lleva "JV" usa el PDF ya emitido (`buscar_emitida`); si es un número
  pelado intenta primero JH (`iCotizacionesWebIA`) y, si no, JV.
- Para JH se **genera el PDF al vuelo** con los precios reales:
  `iCotizacionesWebIA` (cabecera) + `dCotizacionesWebIA` (líneas con `precio`,
  `porItbis`, `Descripcion`, `Und`), se arma con la misma plantilla
  (`cotizacion_html.generar`, número = nfactura) y se sube a `jh-<nfactura>.pdf`.
  No re-cotiza: reproduce la cotización tal cual, incluidas las líneas
  `ProductoManual`.
- `whatsapp.py` delega en `archivo_para_envio`; el resto del flujo (firmar + enviar
  por Evolution, dos pasos con confirmación) no cambia.

## Ampliación (2026-10-29): clave pegada de JH para el nivel + utilidad

JH expresa nivel y utilidad en un número pegado: la **primera cifra es el nivel**
(1–7) y el **resto el % de utilidad** ("55" = P5 5%, "47" = P4 7%, "550" = P5 50%).
`recotizar` acepta ese número tal cual en `nivel`: `_nivel_y_utilidad(nivel,
utilidad)` lo descompone, pero solo cuando no vino la utilidad por separado (así
"P5"/"5" con utilidad aparte sigue igual). La primera cifra fuera de 1–7 es error.
