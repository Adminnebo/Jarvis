# Cuentas de organización y vinculación de reloj por código

Fecha: 2026-09-16
Estado: implementado

Reemplaza [dispositivos por persona](2026-09-16-dispositivos-por-persona-design.md).
Ese spec proponía un token estático compilado por APK y dejaba como "decisión
abierta" la alternativa de que el reloj pregunte y guarde un código. Se optó
por esa alternativa, y de paso se sumó lo que el spec anterior no resolvía:
una base de datos propia de organizaciones y usuarios, para poder atribuirle
el gasto a quien corresponde.

## Problema

Jarvis identificaba personas de dos formas, ninguna con base de datos propia:
`JARVIS_PASSWORD_<NOMBRE>` por variable de entorno, y sesiones de Supabase de
los paneles. Los dispositivos (reloj) no tenían identidad: el puente entraba
con la contraseña del admin, así que todos los relojes eran la misma persona.

Además no existía el concepto de organización, así que no había forma de
saber "a quién cobrarle" el consumo.

## Decisión

**Una base de datos SQLite propia** (`data/jarvis.db`, sin dependencias
nuevas) con `organizaciones` → `usuarios`, y un flujo de alta/login por
correo y contraseña (`POST /registro`, `POST /acceso/cuenta`) que converge en
la misma cookie de sesión que ya usaban los otros dos caminos de acceso
(`backend/acceso.py`). El rol de una cuenta de organización es siempre
`"usuario"`: nunca administra Fuentes/Consumo/Esquema, eso sigue siendo del
dueño de `JARVIS_PASSWORD`. Administrar la propia organización (agregar
gente) es un permiso aparte, `es_admin_org`.

**Vinculación de reloj por código**, no por token compilado: cualquier
persona ya logueada en Jarvis —por cualquiera de los tres caminos— genera un
código de 6 caracteres desde `POST /api/dispositivos/codigo`, vence en 10
minutos y es de un solo uso. El reloj lo canjea sin sesión
(`POST /api/dispositivos/vincular`, en `acceso.LIBRES`) por un token propio,
que manda como `Authorization: Bearer <token>` en cada pedido. El middleware
(`backend/main.py:guardia`) resuelve ese header antes que la cookie y marca
`peticion.state.dispositivo = "reloj"`.

**Atribución de gasto**: `consumo.registrar()` ahora guarda `usuario_id`,
`organizacion_id` y `dispositivo` en cada registro. El tablero de consumo
agrupa por organización además de por modelo/modo; los registros de antes de
esto se agrupan como "(sin organización)".

## Medir el consumo (segunda parte, 2026-09-17)

El consumo se mudó de `data/consumo.jsonl` a la tabla `consumo` de la misma
base: de esto sale la factura, y un archivo plano en un disco efímero no es
base para cobrar. `consumo.migrar_jsonl()` sube el archivo viejo al arrancar,
una sola vez, y lo renombra en vez de borrarlo.

`cuentas.consumido(organizacion_id)` suma lo que lleva gastado cada una, y el
margen separa lo que cuesta de lo que se cobra. El tablero muestra ambas
cifras; `/api/organizaciones` las lista todas y es solo para quien administra
Jarvis.

**El margen es un porcentaje por variable de entorno** (2026-09-21):
`JARVIS_MARGEN` para todas y `JARVIS_MARGEN_<id>` para una en particular. Al
principio era una columna `markup` en la tabla `organizaciones`, pero sin
interfaz solo se podía cambiar con SQL a mano; pasó a variable de entorno
porque es como se configura todo lo demás en Jarvis. La columna ya no se lee
(en las bases viejas queda, inerte). Un valor inválido se avisa al arrancar.

`/api/organizacion`, la vista del cliente, devuelve solo lo que paga: costo
real y margen quedan afuera, porque con esos dos se calcula cuánto se le gana.

**Sin corte por consumo, por ahora.** Se evaluó un crédito prepago que
devolviera 402 en las rutas que llaman al modelo y se descartó: primero hay
que ver cuánto consume cada quien, y recién con esos números decidir si hace
falta un tope. Medir no obliga a cortar; cortar sin datos sí obliga a
adivinar el tope.

**Lo que no resuelve**: el consumo de voz sigue siendo auto-reportado por el
cliente (`POST /api/consumo/voz`), así que sirve para medir pero no es una
base confiable para facturar. Cerrarlo pide reconciliar contra la API de uso
de OpenAI, o cobrar por minuto de sesión, que sí lo mide el servidor.

## Componentes

| Módulo | Qué hace |
|---|---|
| `backend/basedatos.py` | Conexión SQLite compartida; crea el esquema en cada apertura (`CREATE TABLE IF NOT EXISTS`), así no depende de que el evento de arranque haya corrido. |
| `backend/cuentas.py` | Organizaciones y usuarios: alta, login, hash de contraseña (PBKDF2-HMAC-SHA256, sin dependencias nuevas), miembros. |
| `backend/dispositivos.py` | Códigos de vinculación y tokens de dispositivo; resuelve el dueño de un token sea cual sea el origen de su cuenta. |

`acceso.Usuario` ganó un campo `organizacion_id: str | None = None`, con
default para no romper las construcciones existentes.

## Qué no cambia

`fuentes.py`, `esquema.py`, `archivos.py`, `herramientas.py` y
`supabase_sesion.py` siguen igual: son datos comunes o un camino de login
aparte que no necesitaba tocarse.

## Pruebas

`tests/test_cuentas.py`, `tests/test_dispositivos.py`, y los casos nuevos en
`tests/test_permisos.py` (`/registro`, `/acceso/cuenta`,
`/api/dispositivos/*`, `/api/organizacion/*`, el header `Authorization:
Bearer`) y `tests/test_consumo.py` (atribución por organización). Verificado
también a mano contra el servidor real: alta de organización, generación y
canje de código, uso del token como reloj, y que un código usado o vencido no
vuelve a servir.
