# Acceso a Jarvis desde los paneles, controlado por el super admin

Fecha: 2026-09-08
Estado: aprobado, pendiente de plan de implementación

**Este trabajo toca cuatro repositorios.** El spec vive aquí porque Jarvis es la
pieza central, pero el plan tendrá tareas en:

| Repositorio | Carpeta local | Papel |
|---|---|---|
| `Adminnebo/Jarvis` | `C:\Users\Jorge\jarvis` | Acepta sesiones de Supabase |
| `Adminnebo/whatsapp-dashboard` | `C:\Users\Jorge\dashboard-ws-dinamico` | Inbox — Conversaciones. Dueño del catálogo y del panel de usuarios |
| `Adminnebo/Cotizacionesdashboard` | `C:\Users\Jorge\whatsapp-analytics` | Cotizaciones |
| `Adminnebo/cobranzasdashboard` | `C:\Users\Jorge\cobranzas-dashboard` | Cobranzas |

## Problema

Los tres paneles comparten un directorio de usuarios en Supabase: la tabla
`profiles`, con `role` (`super_admin` / `admin` / `agent`), `platforms` y
`permissions` (text[]), y un catálogo de permisos finos en `permcatalog.js`.

Jarvis vive aparte. Su login es una contraseña por persona en variables de
entorno, y no sabe nada de esos usuarios. Hoy, para que alguien de los paneles
use Jarvis hay que crearle una variable a mano, redesplegar y pasarle la
contraseña por otro canal.

Queremos que el super admin marque una casilla en el panel de usuarios que ya
usa, y que esa persona vea un acceso directo a Jarvis en los paneles y entre de
un clic, sin escribir nada.

## Decisiones

**Entra solo, sin escribir contraseña.** Jarvis confía en la sesión de Supabase
del panel. El permiso del super admin controla el acceso de verdad.

**La verificación va en cada petición, no solo al pintar el botón.** Si solo se
ocultara el botón, cualquiera que escriba la URL de Jarvis entraría igual y el
permiso sería decorativo.

**Las contraseñas por variable se quedan como puerta de respaldo.** Supabase
pasa a ser la entrada normal, pero si Supabase se cae o alguien queda fuera del
directorio, Jarvis sigue siendo accesible. El código ya está hecho y probado; no
cuesta nada conservarlo.

Descartado **Jarvis embebido** en los paneles: arrastra el mismo problema de
sesión y añade los límites del micrófono dentro de un iframe.

## Punto de partida que ya existe

- Jarvis **ya está conectado a la misma base de Supabase**: su catálogo de
  consultas incluye `usuarios_por_rol` y `usuarios_lista`, que leen `profiles`.
  No hay que conectar ninguna base nueva.
- `users.html` dibuja las casillas desde `PERMS.GRUPOS`, así que un grupo nuevo
  en el catálogo aparece solo en el panel del super admin.
- El catálogo de navegador expone `PERMS.aplicar()`, que oculta todo elemento
  con `data-perm` que el usuario no tenga.
- En cobranzas (React) el servidor manda `permissions` al frontend
  (`server/index.js`), y `client/src/App.jsx` los consume.

## Componentes

### 1. El catálogo gana un grupo

En `permcatalog.js`, añadir `'jarvis'` a `PLATAFORMAS` y este grupo a `GRUPOS`:

```js
{
  platform: 'jarvis', label: 'Jarvis — Asistente',
  perms: [
    { key: 'jarvis.usar',  label: 'Usar Jarvis' },
    { key: 'jarvis.admin', label: 'Administrar Jarvis (fuentes, credenciales, consumo)',
      sensible: true }
  ]
}
```

El archivo se replica a mano; el propio archivo avisa de ello. Hay que cambiar
las cinco copias:

```
dashboard-ws-dinamico/auth/permcatalog.js
dashboard-ws-dinamico/public/js/permcatalog.js
whatsapp-analytics/permcatalog.js
whatsapp-analytics/public/js/permcatalog.js
cobranzas-dashboard/server/permcatalog.js
```

**Un detalle que hay que corregir a la vez.** `permisosDe()` termina con
`return ALL_KEYS.slice()` cuando un perfil no tiene ni `permissions` ni
`platforms`: un respaldo para no romper usuarios viejos. Con el grupo nuevo, ese
camino regalaría Jarvis. Hay que excluir las claves `jarvis.*` de ese respaldo
final: **a Jarvis se entra solo si alguien lo concedió a propósito.**

El camino que deriva de `platforms` no necesita cambios: las filas existentes
tienen `platforms` con las tres plataformas viejas, así que `jarvis.*` ya queda
fuera por construcción.

### 2. El acceso directo en los tres paneles

En inbox y cotizaciones —ambos con el catálogo de navegador— basta con un enlace
con `data-perm="jarvis.usar"`; `PERMS.aplicar()` lo oculta solo a quien no lo
tenga.

En cobranzas, que es React, el botón se muestra si `permissions` incluye
`jarvis.usar`, con el mismo patrón que ya usan las demás secciones.

Es comodidad, no control de acceso: el control real está en el punto 4.

### 3. El puente de sesión

Jarvis está en otro dominio, así que la cookie del panel no viaja. El paso es:

1. El botón abre `https://<jarvis>/entrar#t=<access_token de Supabase>`.
2. Esa página lee el fragmento y hace un POST **al mismo origen**, a
   `/acceso/supabase`, con el token en el cuerpo.
3. Jarvis valida el token contra Supabase, lee el perfil, y si tiene
   `jarvis.usar` responde con su cookie de siempre y redirige a `/`.

**Por qué en el fragmento y no en la query:** el fragmento no se manda al
servidor, así que el token no queda en los logs de acceso ni se filtra por la
cabecera `Referer` a terceros.

**Por qué un POST del mismo origen:** la cookie de Jarvis es `SameSite=Lax`, que
no se guardaría en un POST venido de otro sitio.

La página `/entrar` borra el fragmento de la barra de direcciones en cuanto lo
lee, para que no quede en el historial.

### 4. Jarvis verifica en cada petición

Validar el token de Supabase es una llamada a `GET /auth/v1/user` del proyecto,
con el token del usuario como `Authorization` y la clave anónima como `apikey`.
Devuelve el id del usuario. Con ese id, Jarvis lee `profiles` por su conexión
directa a Postgres, que ya tiene.

El rol dentro de Jarvis sale de los permisos, y reusa entero el control que ya
existe:

| Permiso | Rol en Jarvis |
|---|---|
| `jarvis.admin` (o `role` admin/super_admin) | `admin` — fuentes, esquema, consumo |
| solo `jarvis.usar` | `usuario` — conversar y consultar |
| ninguno | no entra |

**Revalidación con caché de 60 segundos.** La cookie de Jarvis dura 30 días. Si
no se revalidara, quitarle el permiso a alguien no tendría efecto hasta que la
cookie caducara. Con el caché, la revocación tarda como mucho un minuto, y no se
paga una consulta a la base en cada petición.

### 5. Identidad y memoria

El id del usuario en Jarvis es `sb-<uuid de Supabase>`, y el nombre sale de
`profiles.full_name`. El prefijo evita chocar con los ids que salen de los
sufijos de las variables de entorno.

Todo lo demás sigue igual que hoy: `hechos-sb-<uuid>.json`,
`conversacion-sb-<uuid>.json`, y la memoria de cada uno es suya.

### 6. Las dos puertas conviven

`acceso.usuario_de_token` sigue resolviendo las cookies de las contraseñas por
variable, sin cambios. La diferencia está al crear la sesión, y en que las
venidas de Supabase se revalidan.

No hace falta guardar el origen en el token: el prefijo `sb-` del id ya lo dice.
Un id que empieza por `sb-` se revalida contra `profiles`; cualquier otro se
resuelve como hasta ahora, contra las variables de entorno.

### 7. Variables en Jarvis

`SUPABASE_ANON_KEY` es nueva y es pública. La URL del proyecto se deriva de
`SUPABASE_PROJECT_REF`, que ya existe.

`SUPABASE_DB_URL` deja de ser opcional para esto. Hoy, sin ella, Jarvis consulta
por MCP, que cuesta más de un segundo por viaje: leer `profiles` así en cada
revalidación pondría ese coste en el camino de cada petición. Si falta, el
puente queda desactivado y se avisa al arrancar, igual que si faltara la clave
anónima.

## Manejo de errores

| Situación | Comportamiento |
|---|---|
| Token de Supabase vencido o inválido | Vuelve al panel a reautenticarse, no a la pantalla de contraseña de Jarvis: quien viene de un panel no tiene contraseña que escribir. |
| Usuario sin `jarvis.usar` | 403 con un mensaje claro pidiendo que se lo solicite a quien administra. No revela si Jarvis existe o no para otros. |
| Supabase no responde al validar | No entra, y lo dice. **Nunca** se cae a modo abierto. |
| Supabase no responde al revalidar | Se conserva el último resultado conocido hasta 5 minutos; pasado eso, fuera. Un corte breve no echa a nadie a mitad de una conversación. |
| Le quitan el permiso mientras usa Jarvis | Queda afuera en cuanto vence el caché, dentro de un minuto. |
| Falta `SUPABASE_ANON_KEY` o `SUPABASE_DB_URL` | El puente queda desactivado y se avisa al arrancar. Las contraseñas por variable siguen funcionando. |
| Perfil sin `full_name` | Se usa la parte del correo anterior a la arroba. Jarvis siempre llama a alguien por algo. |

## Pruebas

**En Jarvis**, sin red, con la validación de Supabase sustituida por una doble:

- Un token válido con `jarvis.usar` crea sesión y el rol es `usuario`.
- Con `jarvis.admin`, el rol es `admin`.
- Con `role` `super_admin` o `admin`, el rol es `admin`.
- Sin ningún permiso de Jarvis, 403 y no se crea cookie.
- Un token inválido no crea sesión.
- Si la validación lanza, no se crea sesión (nunca modo abierto).
- El caché no vuelve a consultar antes de 60 segundos, y sí después.
- Quitado el permiso, la sesión deja de valer pasado el caché.
- Un usuario de Supabase y uno de variable no comparten memoria.
- Sin `SUPABASE_ANON_KEY`, `/acceso/supabase` responde que está desactivado y el
  login por contraseña sigue funcionando.

**En el catálogo** (una vez, en el repo del inbox, replicando después):

- `jarvis.usar` no se concede por el respaldo cuando un perfil no tiene
  `permissions` ni `platforms`.
- Un perfil viejo, con `platforms` de las tres plataformas y `permissions` en
  NULL, no recibe `jarvis.*`.
- `super_admin` y `admin` sí lo reciben.
- Las cinco copias del archivo son idénticas.

**Verificación manual al final:** marcar la casilla a una persona real, entrar
desde los tres paneles, comprobar que Jarvis la saluda por su nombre, que no ve
la conversación de nadie más, y que sin `jarvis.admin` no le aparecen Fuentes ni
Consumo. Después quitarle la casilla y comprobar que en un minuto queda afuera.

## Convenciones

- En Jarvis, Python sin acentos en comentarios y docstrings; la web con acentos.
- En los paneles, seguir el estilo de cada repo.
- Nombres en español.
- Los comentarios explican **por qué**, no qué.

## Fuera de alcance

- **Jarvis embebido** en los paneles. Descartado al elegir el comportamiento.
- **Que el super admin vea o borre la memoria de otros** desde el panel.
- **Unificar las cinco copias de `permcatalog.js`** en un paquete compartido.
  Es una mejora real y el archivo la pide a gritos, pero es un trabajo aparte y
  arriesgarlo aquí retrasaría esto.
- **La persistencia del disco de Jarvis**, que sigue pendiente y ahora afecta
  también a la memoria de la gente de los paneles.
