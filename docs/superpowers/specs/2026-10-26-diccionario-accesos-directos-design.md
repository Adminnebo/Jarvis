# Diccionario de datos y accesos directos por fuente

Fecha: 2026-10-26. Estado: diseño aprobado por Jorge, pendiente de plan.

## Qué se quiere

Que Jarvis responda rápido y bien preguntas de negocio sobre una fuente de datos ("¿cuántos clientes
activos tenemos?", "¿cuántas ventas se hicieron hoy?", "¿quién es el vendedor que más vendió?",
"¿qué producto tiene menos inventario?"). Caso de uso inmediato: el ERP de JH (SQL Server 2008 R2,
`gemelo-kpi.jhelectroalambres.com:5033`, base `sim`, 14 vistas `List_*IA` de solo lectura).

## Lo que ya existe y se aprovecha

- En el panel de Fuentes, por tabla: interruptor **activa** y **leyenda** (pista corta). Se guardan en
  la configuración de la fuente (`fuentes.json`, clave `tablas`, vía `fuentes.guardar_config_tablas`)
  y van al prompt en `fuentes.resumen_para_prompt` (solo las activas, con su leyenda).
- `consultas.py`: catálogo de consultas SQL ya escritas que el modelo usa por nombre (más rápido que
  escribir SQL). Pero está **en el código** y es para la base de mensajes/cobranzas.
- Guardia de solo lectura `fuentes.validar_solo_lectura` y `fuentes.consultar` (con caché de
  conexiones y reintento).

## Decisiones tomadas

| Tema | Decisión |
|---|---|
| Cómo se cargan | **Asistido por la IA**: se escribe la pregunta en lenguaje normal, Jarvis arma la consulta, la corre y muestra el resultado; se guarda con OK. El diccionario lo propone la IA mirando columnas y filas de ejemplo. |
| Variantes | Los accesos directos tienen **variables** (fechas, números, textos): "ventas de hoy" sirve también para ayer, la semana o el mes. |
| Quién edita | Solo el **super admin** (rol `admin`). Usarlos, todos. |
| Enfoque | **Ampliar lo que existe**: el diccionario crece sobre la leyenda por tabla; los accesos directos son un catálogo editable por fuente, usado con una herramienta propia. |

Descartado: un "manual del negocio" de texto libre (no gana velocidad) y recordar respuestas
automáticamente (difícil de controlar).

## 1. Diccionario

En la configuración de cada tabla, junto a `activa` y `leyenda`:

```json
"List_ClientesIA": {
  "activa": true,
  "leyenda": "clientes de JH",
  "columnas": {"Estado": "'A' = activo, 'I' = inactivo", "Vendedor": "codigo del vendedor asignado"},
  "reglas": "Un cliente activo es Estado = 'A'."
}
```

- `guardar_config_tablas` conserva y limpia `columnas` (dict columna → texto, solo columnas que
  existen, texto hasta 200 caracteres) y `reglas` (texto hasta 1000).
- **Proponer con IA** (`POST /api/fuentes/{id}/tablas/{tabla}/proponer`): lee las columnas del esquema
  y 5 filas de ejemplo (`select top 5 *` / `limit 5`), le pide al modelo un borrador
  `{leyenda, columnas, reglas}` en JSON y lo devuelve **sin guardar**. La web lo muestra editable.
- En el prompt (`resumen_para_prompt`): cada tabla activa lleva su leyenda (como hoy), y debajo las
  columnas con significado y las reglas, con tope de tamaño (si el bloque de la fuente supera el tope
  actual se recorta primero el detalle de columnas, igual que hoy).
- La web: en la vista de tablas de cada fuente, cada tabla gana un "Diccionario" desplegable con
  leyenda, columnas (solo las que tienen texto, más un "agregar columna") y reglas, y el botón
  "Proponer con IA".

## 2. Accesos directos

Tabla nueva en `jarvis.db`:

```sql
CREATE TABLE IF NOT EXISTS accesos_directos (
    id TEXT PRIMARY KEY,                 -- nombre corto, p. ej. ventas_por_periodo
    fuente_id TEXT NOT NULL,
    pregunta TEXT NOT NULL,              -- como la escribio el super admin
    descripcion TEXT NOT NULL,           -- que responde: es lo que lee el modelo para elegir
    sql TEXT NOT NULL,                   -- con parametros %(nombre)s
    parametros TEXT NOT NULL,            -- JSON {nombre: {tipo, descripcion, por_defecto}}
    activo INTEGER NOT NULL DEFAULT 1,
    ultimo_error TEXT,
    creado TEXT NOT NULL,
    actualizado TEXT NOT NULL
);
```

- `fuente_id` apunta a `fuentes.json` (no a una tabla): al borrar una fuente se borran sus accesos
  directos desde `fuentes.borrar`.
- Tipos de variable: `fecha` (YYYY-MM-DD), `entero` (con mínimo y máximo, por defecto 1–500),
  `texto` (hasta 100 caracteres). Placeholders `%(nombre)s`, que entienden pymssql y psycopg; los
  valores viajan como parámetros del driver, nunca pegados en el SQL.
- Módulo nuevo `backend/accesos.py`: crear/editar/listar/borrar, validar parámetros, ejecutar con
  caché de 30 s por (acceso, valores), catálogo para el prompt.
- Para ejecutar con parámetros hace falta que los motores de `fuentes.py` acepten `parametros`
  (hoy reciben solo `sql`): se agrega el argumento opcional a `consultar` y a los motores
  postgres/mssql. Supabase por MCP queda **fuera** (no acepta parámetros): sus fuentes no muestran
  accesos directos.

**Crear (asistido):** `POST /api/fuentes/{id}/accesos/proponer` con `{pregunta, correccion?, anterior?}`:
el modelo recibe el esquema y el diccionario de la fuente y devuelve `{id, descripcion, sql,
parametros}`; el servidor valida (solo lectura, placeholders que coinciden con los parámetros), lo
corre con los valores por defecto (máx. 50 filas) y devuelve propuesta + resultado o el error de la
base. **Nada se guarda** hasta `POST /api/fuentes/{id}/accesos` con la propuesta aprobada.
Editar: `PUT /api/accesos/{id}` (a mano o con una nueva propuesta). Probar con otros valores:
`POST /api/accesos/{id}/probar`. Desactivar/borrar: `PUT` con `activo` / `DELETE`.

**Usar:** herramienta nueva `usar_acceso_directo(nombre, parametros)` en `herramientas.py`. El
prompt lista los accesos activos de las fuentes activas (`- ventas_por_periodo(desde, hasta):
<descripcion>`), con una regla: "si la pregunta encaja con un acceso directo, úsalo antes de escribir
SQL". Si falla (por ejemplo cambió la vista), devuelve el error con la indicación de responder con
`consultar_fuente`, y anota `ultimo_error` (la pantalla lo marca "con error").

**Puente de los lentes (Gemini):** `construirPromptVoz` hoy solo conserva las cabeceras de fuente y
las líneas de tablas. Se agrega: conservar las líneas del bloque de accesos directos (prefijo fijo
"Accesos directos:"), para que la voz también los use.

## 3. Seguridad y errores

- Rutas `/api/fuentes/*/accesos*`, `/api/accesos*` y `.../proponer` exigen admin
  (`acceso.exige_admin`, que ya cubre `/api/fuentes`; se agrega `/api/accesos`).
- `validar_solo_lectura` al guardar y al ejecutar. Una sola sentencia.
- Lo que gasta la IA al proponer queda en el consumo del super admin, como cualquier pregunta.
- La IA no logra una consulta válida: se muestra el error de la base y se puede pedir corrección.

## Pruebas

- Diccionario: guardar/conservar `columnas` y `reglas`, limpiar columnas inexistentes y textos
  largos, que lleguen al prompt; "proponer" con el modelo simulado devuelve borrador sin guardar.
- Accesos: crear, listar, editar, borrar; validar tipos y rangos; rechazar SQL que no sea de solo
  lectura y placeholders que no coinciden; ejecutar con parámetros (motor simulado) y caché de 30 s;
  un fallo anota `ultimo_error` y devuelve la indicación de seguir con `consultar_fuente`; permisos;
  el catálogo aparece en las instrucciones; borrar la fuente borra sus accesos.
- Puente: `construirPromptVoz` conserva el bloque de accesos directos.
- Real con el ERP de JH: proponer el diccionario de las 14 vistas y crear los accesos de ejemplo
  (clientes activos, ventas por período, mejor vendedor por período, productos con menos inventario).
