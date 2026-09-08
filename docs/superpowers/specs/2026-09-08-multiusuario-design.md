# Varias personas usando Jarvis

Fecha: 2026-09-08
Estado: aprobado, pendiente de plan de implementación

## Problema

Jarvis tiene una sola contraseña compartida. `acceso.py` no tiene concepto de
usuario: guarda `JARVIS_PASSWORD`, firma una cookie con esa misma contraseña, y
quien la sepa entra.

Si hoy le damos la contraseña a otra persona, comparte todo:

- **La conversación.** `conversacion.json` es un archivo único y `/api/estado`
  devuelve el historial. Abriría Jarvis y vería el chat ajeno.
- **La memoria.** `hechos.json` también es único, y
  `memoria.resumen_para_prompt()` inyecta todos los hechos en el prompt
  (`cerebro.py:155`). Jarvis le contaría cosas del otro.
- **El nombre.** `JARVIS_USUARIO` es una variable global (`cerebro.py:55`), así
  que llamaría a todos igual.
- **La configuración.** Podría agregar y borrar fuentes, ver credenciales
  enmascaradas, correr SQL a mano y mirar el gasto.

Queremos que entren varias personas, que lo personal sea privado y que lo del
negocio siga siendo común.

## Decisión

**Una variable de entorno por persona.**

```
JARVIS_PASSWORD=...          # el admin. Ya existe.
JARVIS_PASSWORD_JORGE=...    # una persona mas
JARVIS_PASSWORD_ANA=...      # otra
```

El id sale del sufijo en minúsculas (`jorge`), y el nombre para el prompt del
sufijo capitalizado (`Jorge`). El nombre del admin sigue saliendo de
`JARVIS_USUARIO`, como hoy. Agregar a alguien es agregar una variable.

**La pantalla de login no cambia.** Como cada contraseña es distinta, la que se
escribe ya dice quién es: se compara contra todas y la que coincide determina la
identidad. Sin campo de usuario.

Descartado un catálogo de usuarios en JSON con contraseñas hasheadas y una
herramienta para generar los hashes: más de la mitad del trabajo para un
beneficio que aquí no se cobra. Las contraseñas quedan en claro en las variables
del proveedor, junto a la clave de OpenAI y las credenciales de las bases, que
valen mucho más. Una filtración de las variables entrega cosas peores que estas
contraseñas, así que hashearlas protegería poco.

Descartado también un panel de administración: obliga a tener almacenamiento
persistente, que hoy no existe (todo va a disco y el disco del hosting se borra
en cada despliegue).

## Componentes

### 1. `acceso.py` — quién es quién

Funciones nuevas:

| Función | Qué hace |
|---|---|
| `usuarios()` | Lee el entorno y devuelve la lista de personas: `{id, nombre, rol}` más su contraseña. El admin primero. |
| `quien_entra(intento)` | Compara la contraseña contra todas en tiempo constante y devuelve el usuario, o `None`. |
| `usuario_de_token(valor)` | Valida la firma y devuelve el usuario del token, o `None`. |
| `es_admin(usuario)` | Rol `admin` solo para el dueño de `JARVIS_PASSWORD`. |

**El token cambia de forma.** Hoy es `caduca.firma`, firmado con la contraseña
misma. Pasa a ser `usuario.caduca.firma`, firmado con una clave del servidor.

Es obligatorio: sin el id dentro del token, Jarvis sabe que entraste pero no
quién sos, y la memoria separada no puede funcionar.

La clave de firma se deriva de `JARVIS_CLAVE_SECRETA` con HMAC sobre la etiqueta
`sesiones`, para no reutilizar tal cual la clave que cifra las credenciales. Si
esa variable no está, se deriva de las contraseñas configuradas: estable entre
despliegues mientras no cambien. Cambiar `JARVIS_CLAVE_SECRETA` cierra la sesión
de todos, y esa es justamente la forma de echar a alguien de inmediato.

La comparación de contraseñas sigue con `hmac.compare_digest`, como hoy, y se
recorren **todas** las contraseñas sin cortar en la primera coincidencia, para
que el tiempo de respuesta no revele cuántos usuarios hay.

### 2. `memoria.py` — un archivo por persona

`hechos.json` y `conversacion.json` pasan a ser `hechos-<id>.json` y
`conversacion-<id>.json`. Todas las funciones públicas reciben el id del usuario
como primer parámetro.

Las fuentes, el esquema, las leyendas de tablas y el consumo **no** se tocan:
son de la empresa y siguen siendo comunes.

### 3. El usuario viaja explícito, no por variable de contexto

`cerebro.instrucciones(extra)` y `cerebro.responder(mensajes, extra)` reciben el
usuario. `herramientas.ejecutar(nombre, argumentos)` también, porque `recordar` y
`buscar_memoria` escriben en la memoria de alguien.

**Por qué explícito y no una variable de contexto global.** `/api/chat` devuelve
un `StreamingResponse` cuyo generador corre después de que el middleware
terminó; ahí una variable de contexto puede perderse o quedar la de otra
petición. El fallo sería escribir los recuerdos de una persona en el archivo de
otra: intermitente, silencioso y muy difícil de ver. Son unos ocho puntos de
llamada; vale la pena el ruido.

El middleware deja el usuario en `peticion.state.usuario`, y cada ruta que lo
necesita añade un parámetro `Request` y lo lee de ahí, de forma síncrona, antes
de que empiece a correr cualquier generador.

### 4. `main.py` — permisos en el servidor

El middleware `guardia` ya valida la cookie. Se le añaden dos pasos: resolver el
usuario y, si la ruta es de administración y el usuario no es admin, devolver
403.

Solo para admin:

- `/api/fuentes` y todo lo que cuelga: `tipos`, `salud`, `probar`,
  `{id}/esquema`, `{id}/tablas`, `{id}/consultar`, y el `DELETE`.
- `/api/esquema/refrescar`
- `GET /api/consumo` y `DELETE /api/consumo`

Abierto a todos: el chat, la voz, la memoria propia, la conversación propia, y
`POST /api/consumo/voz` — este último lo escribe el navegador durante la sesión
de voz, así que bloquearlo rompería el registro de gasto de cualquiera que no
sea admin.

El bloqueo va en el servidor. Esconder el botón en la web es cosmética, no
seguridad.

Rutas que pasan a ser por usuario: `/api/estado` (el historial), `/api/chat`,
`/api/conversacion/agregar`, `/api/conversacion/reiniciar`, `/api/memoria`,
`/api/memoria/{id_hecho}`, `/api/herramienta` y `/api/voz/sesion` (que arma las
instrucciones con el nombre y la memoria de quien habla).

### 5. La web

`/api/estado` devuelve además `usuario` y `rol`. Con eso la interfaz oculta lo
que no corresponde: el botón de fuentes y el de consumo para quien no es admin.
Es comodidad, no control de acceso.

## Compatibilidad

**Sin variables `JARVIS_PASSWORD_*`, no cambia nada visible.** Hay un solo
usuario, el admin, con su contraseña de siempre. El despliegue actual y el uso
en local siguen igual.

En local sin `JARVIS_PASSWORD` tampoco cambia nada: no hay login, y todo se
atribuye al usuario por defecto.

## Migración

Al arrancar, si existen `hechos.json` y `conversacion.json` sueltos y todavía no
existe el archivo con el id del admin, se le adjudican. Nadie pierde su memoria.
Idempotente: al segundo arranque no hace nada.

Los archivos viejos no se borran; quedan como respaldo frío.

## Manejo de errores

| Situación | Comportamiento |
|---|---|
| Dos personas con la misma contraseña | Al arrancar se avisa por consola y gana el primero. No se puede distinguir quién entra, y callarlo mezclaría las memorias. |
| Variable con sufijo vacío o raro (`JARVIS_PASSWORD_`) | Se ignora, con aviso por consola. |
| Contraseña vacía en una variable | Se ignora. Una contraseña vacía dejaría entrar a cualquiera. |
| Token de un usuario que ya no existe | Se trata como no autorizado: vuelve al login. Es lo que pasa al quitarle a alguien su variable. |
| Token con firma inválida o vencido | No autorizado, igual que hoy. |
| Usuario normal pidiendo una ruta de admin | 403 con mensaje claro, no 404 ni 401. |

## Pruebas

`acceso.py` es lógica pura sobre el entorno: se prueba sin red ni servidor.

- **Lectura del entorno**: con solo `JARVIS_PASSWORD` hay un usuario admin; con
  dos variables más hay tres usuarios y solo uno es admin; los sufijos vacíos y
  las contraseñas vacías se descartan.
- **Identidad por contraseña**: la de Jorge devuelve a Jorge, la del admin
  devuelve al admin, una incorrecta devuelve `None`.
- **Token**: uno firmado se valida y devuelve el usuario correcto; uno
  manipulado se rechaza; uno vencido se rechaza; uno de un usuario que ya no
  está en el entorno se rechaza.
- **Aislamiento**: los hechos guardados con el id de Jorge no aparecen al leer
  los de Lucas, ni en `resumen_para_prompt`.
- **Migración**: con archivos viejos sueltos, el admin los hereda; al correr
  otra vez no se duplican ni se pisan.
- **Permisos**: un usuario normal recibe 403 en `/api/fuentes` y en
  `GET /api/consumo`; el admin recibe 200; ambos reciben 200 en
  `POST /api/consumo/voz`.

Verificación manual al final: entrar con las dos contraseñas en dos navegadores
distintos, comprobar que cada uno ve su propia conversación, que Jarvis llama a
cada uno por su nombre, y que el que no es admin no tiene botón de fuentes ni
puede llegar a `/api/fuentes` a mano.

## Convenciones del proyecto

- Python sin acentos en comentarios, docstrings y nombres; la web con acentos.
- Nombres en español, como el resto del proyecto.
- Los comentarios explican **por qué**, no qué.

## Fuera de alcance

Decidido explícitamente, no por olvido:

- **Contraseñas hasheadas y panel de administración.** Razonado arriba.
- **Gasto por persona.** `consumo.py` existe y sería agregarle el id, pero no se
  pidió. Queda anotado como trabajo aparte.
- **Persistencia del disco.** Sigue pendiente del spec anterior y ahora afecta
  también a la memoria de cada usuario: sin volumen montado, un redespliegue se
  la lleva. Es un problema propio, no de esta funcionalidad.
- **Roles más finos que admin/usuario.** Dos alcanzan para lo que se pidió.
- **Que un usuario vea o administre la memoria de otro.**
