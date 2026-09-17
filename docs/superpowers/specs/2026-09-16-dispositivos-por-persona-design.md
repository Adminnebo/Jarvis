# Dispositivos por persona, y costos separados

Fecha: 2026-09-16
Estado: **reemplazado** por
[cuentas y dispositivos](2026-09-16-cuentas-y-dispositivos-design.md). La
decisión abierta al final de este documento (APK por persona vs. reloj que
pregunta y guarda) se resolvió a favor de la segunda opción, implementada
como vinculación por código. Se deja el documento como registro de las
alternativas consideradas.

Extiende [multiusuario](2026-09-08-multiusuario-design.md), que ya resolvió el
acceso desde el navegador. Aquí se cierra lo que quedó fuera: los dispositivos
—relojes y lentes— y la atribución del gasto.

Va en dos fases. La **fase 1** da identidad a cada dispositivo; la **fase 2**
separa los costos. La 2 depende de la 1: sin saber quién habla no hay a quién
cobrarle.

---

# Fase 1 — Cada dispositivo sabe quién lo lleva

## Problema

El multiusuario de Jorge funciona por el navegador: cada persona tiene su
`JARVIS_PASSWORD_<NOMBRE>`, el token lleva su id, y su memoria vive en
`hechos-<id>.json`.

Los dispositivos no pasan por ahí. El reloj habla con el puente, y el puente
entra a Jarvis con **una sola contraseña**:

```js
// puente/src/jarvis.js
constructor({ base, password, ... })   // JARVIS_PASSWORD, la del admin
```

Consecuencias, todas del mismo origen:

- **Todos los relojes son la misma persona.** Comparten conversación y memoria.
  Si dos hablan a la vez se pisan: el historial se intercala y cada uno ve lo
  que preguntó el otro.
- **Jarvis llama a todos igual**, con el nombre del admin.
- **Los dispositivos entran como admin.** El token del reloj solo sabe
  preguntar, pero la sesión que el puente abre contra Jarvis es la del dueño de
  `JARVIS_PASSWORD`, que sí puede todo.

## Decisión

**Un token de reloj por persona, que el puente traduce a su contraseña.**

```
TOKEN_RELOJ_LUCAS=a1b2...      ->  JARVIS_PASSWORD_LUCAS
TOKEN_RELOJ_JORGE=c3d4...      ->  JARVIS_PASSWORD_JORGE
TOKEN_RELOJ=...                ->  JARVIS_PASSWORD        (el de hoy, sigue valiendo)
```

Sigue la misma forma que eligió Jorge: **una variable de entorno por persona**,
sin catálogo ni panel de administración. Agregar a alguien es agregar dos
variables y compilar su APK.

El puente mantiene **una sesión de Jarvis por persona**, no una global. Hoy
`Jarvis` es una instancia con una cookie; pasa a ser un mapa de id a sesión.

**El APK lleva el token de su dueño.** `JARVIS_TOKEN` ya se inyecta desde
`local.properties` al compilar, así que no hace falta código nuevo en el reloj:
es el mismo APK compilado con otro valor.

### Por qué no otras opciones

**Un token compartido y que el reloj diga quién es.** Cualquiera con el token
podría decir que es otro: el reloj no tiene forma de probarlo. El token *es* la
credencial, así que tiene que ser distinto por persona.

**Pedir usuario y contraseña en el reloj.** Escribir en una pantalla de pulgada
y media es malo, y no aporta: el reloj es personal, ya identifica a su dueño.

**Un panel para dar de alta.** Necesita almacenamiento persistente, que hoy no
existe. Jorge ya descartó esto por lo mismo.

## Componentes

### `puente/src/config.js`

Lee el entorno y arma el mapa de personas.

| | |
|---|---|
| `personas()` | Devuelve id, token y contraseña a partir de `TOKEN_RELOJ_*` y su `JARVIS_PASSWORD_*` |
| Validación al arrancar | Un `TOKEN_RELOJ_X` sin su `JARVIS_PASSWORD_X` es un error de configuración: hay que decirlo al arrancar, no en la primera pregunta |

### `puente/src/index.js`

`tokenValido()` deja de devolver un booleano y pasa a devolver **quién es**.
Todas las rutas —`/preguntar`, `/preguntar/stream`, `/hablar`, `/voz/sdp`,
`/voz/config`, `/voz/herramienta`— usan esa identidad para elegir la sesión.

La comparación recorre **todos** los tokens sin cortar en el primero que
coincide, igual que hace `acceso.quien_entra`, para no filtrar cuántas personas
hay por el tiempo de respuesta.

El límite de peticiones pasa a ser **por persona**: hoy `MAX_POR_MINUTO` es
global y un dispositivo puede dejar sin servicio a los demás.

### `puente/src/jarvis.js`

De una instancia con una cookie a un registro de sesiones. Cada persona tiene la
suya, se renueva sola al caducar, y el fallo de una no afecta a las otras.

### El reloj

Sin cambios de código. Cada persona recibe su APK, compilado con su token.

## Pruebas de la fase 1

- **Dos personas no se pisan**: dos tokens distintos preguntando a la vez
  producen dos sesiones y dos conversaciones separadas.
- **Token desconocido**: 401, sin revelar si existe.
- **Token sin contraseña asociada**: el puente no arranca y dice cuál falta.
- **Límite por persona**: agotar el de uno no afecta al otro.
- **Compatibilidad**: un `TOKEN_RELOJ` sin sufijo sigue funcionando, así que los
  relojes ya instalados no se rompen al desplegar.

---

# Fase 2 — Costos separados

## Problema

`consumo.registrar()` guarda modo, modelo, tokens y costo. **No guarda quién.**
El tablero agrupa por modelo y por modo, y responde "cuánto gasté", nunca
"cuánto gastó cada quien".

Con varias personas y varios dispositivos esa pregunta pasa a ser la importante:
sin ella no se puede repartir el costo, ni detectar que un dispositivo se quedó
hablando solo, ni poner un tope por persona.

## Decisión

**Una columna más, no una tabla más.**

`registrar()` recibe el id del usuario y lo guarda en el registro. El archivo
`consumo.jsonl` no cambia de forma —es JSON por línea, tolera campos nuevos— y
los registros viejos simplemente no lo traen.

```json
{"cuando": "...", "usuario": "lucas", "dispositivo": "reloj",
 "modo": "voz", "modelo": "gpt-realtime-2.1", "tokens": 3000, "costo": 0.072}
```

Se agregan **dos** campos, no uno:

- `usuario`: a quién cobrarle.
- `dispositivo`: navegador, reloj o lentes. La misma persona desde dos aparatos
  gasta distinto, y saberlo es la mitad del valor de medirlo.

Los registros sin `usuario` se agrupan como *(anteriores)*, visible en el
tablero. No se inventa un dueño para datos que no lo tienen.

### Qué gana el tablero

Un filtro más —persona— y dos agrupaciones nuevas: **por persona** y **por
dispositivo**. Las columnas que ya existen se calculan igual dentro de cada
grupo.

La cifra que hoy corona el tablero es el costo por minuto hablando. Con esto
pasa a poder leerse por persona, que es lo accionable.

### Topes por persona

Fuera del alcance de esta fase, pero el diseño lo deja servido: con el gasto por
persona registrado, un tope es comparar contra un `JARVIS_TOPE_<NOMBRE>` antes
de responder. Se menciona para no cerrar la puerta.

## Lo que esta fase NO resuelve

**No separa el gasto en la factura de OpenAI.** Todo sigue saliendo de la misma
clave y la misma cuenta. Esto atribuye el costo, no lo divide en origen.

Separarlo de verdad exigiría una clave de OpenAI por persona, con su propio
proyecto y su propia facturación. Es posible —OpenAI permite varios proyectos
bajo una organización— pero multiplica la configuración y no aporta nada hasta
que alguien tenga que **pagar por separado**, no solo saber cuánto gastó.

La recomendación es medir primero con esta fase y decidir después, con datos.

## Pruebas de la fase 2

- **Atribución**: una consulta desde el navegador de A y otra desde el reloj de
  B producen dos registros con distinto usuario y distinto dispositivo.
- **Aritmética por grupo**: el costo por persona suma exactamente el total.
- **Registros viejos**: los que no traen usuario no rompen el tablero y salen
  agrupados aparte.
- **Filtros**: filtrar por persona deja solo sus registros.

---

## Orden sugerido

1. Fase 1 en el puente, con sus pruebas. Es lo que desbloquea repartir relojes.
2. Recompilar un APK por persona.
3. Fase 2, que ya puede etiquetar cada gasto con su dueño.

La fase 1 sirve por sí sola: sin ella, repartir relojes hoy significa que todos
comparten memoria y se pisan.

---

## Decisión abierta

**Un APK por persona.** El token va compilado dentro del APK, así que cada
persona necesita el suyo. Quien reparta los relojes tiene que no equivocarse:
instalar el APK de Lucas en el reloj de Jorge hace que Jorge hable como Lucas
—su memoria, su conversación, su gasto.

La alternativa es que el reloj pregunte quién lo lleva la primera vez y guarde
la elección. Evita el riesgo de repartir el APK equivocado, pero es más código
y peor primera experiencia en una pantalla de pulgada y media.

Se propone la primera. Falta confirmarlo antes de implementar.

---

## Estado al 2026-09-16

Nada de esto está implementado todavía. Lo que sí está verificado:

- `acceso.py` ya distingue personas y el token lleva el id (Jorge, 08/09).
- `memoria.py` ya guarda un archivo por persona.
- `consumo.registrar()` **no** recibe ni guarda el usuario: revisado en
  `backend/consumo.py:188`.
- `puente/src/jarvis.js` abre la sesión con una sola contraseña, pasada al
  constructor: revisado en el repo Jarvis-Reloj.
