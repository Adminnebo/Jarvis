# Integraciones: Gmail (leer, enviar y avisar de lo importante)

Fecha: 2026-11-09 · Rama: `feat/integraciones-gmail` (sale de `main`)

## Objetivo

Una sección **Integraciones** en Jarvis donde cada persona conecta sus apps. La
primera es **Gmail**: Jarvis puede buscar y leer los correos de quien le habla,
redactar y enviar o responder con confirmación por voz, y **avisar solo de lo
importante** por WhatsApp y en una campanita dentro de la app.

La sección nace como catálogo para sumar más apps después; hoy solo trae Gmail.

## Decisiones

| Tema | Decisión | Por qué |
|---|---|---|
| Qué hace Jarvis | Leer y buscar, enviar y responder con confirmación, avisar | Pedido de Jorge (opción C) |
| De quién es el buzón | Uno por persona; Jarvis solo ve el de quien le habla | El correo es personal |
| Canal de avisos | WhatsApp (Evolution, el que ya usa Jarvis) + campanita en la app | Enterarse al momento y conservar el historial |
| Qué es importante | La IA decide con reglas en texto libre de cada persona | Sigue la intención real; el costo es mínimo |
| Conexión con Google | App OAuth **propia, sin verificar**, en un proyecto nuevo "Nebo Jarvis" | Sin Zernio y sin la auditoría de Google; alcanza para < 100 usuarios |
| Dónde corre | Dentro del contenedor `jarvis` del EC2 de Jarvis | El t3.micro tiene ~450 MB libres y así se reusan la base, los secretos, el despliegue y los hilos de fondo |
| Correo nuevo | Revisión cada 2 min con `users.history.list` | Pub/Sub exige más configuración en Google Cloud; con pocos buzones el costo es casi nulo |

No se toca `correo-servicio` (server2) ni el proyecto "Nebo Gmail" de JH/JDL.

## Proyecto de Google (lo hace Jorge)

1. Crear el proyecto **Nebo Jarvis** en Google Cloud y activar la **Gmail API**.
2. Configurar la pantalla de consentimiento como **Externa**, con nombre "Nebo Jarvis",
   correo de soporte y la política de privacidad de Jarvis (`/privacidad`).
3. Agregar los permisos `openid`, `email`, `https://www.googleapis.com/auth/gmail.readonly`
   y `https://www.googleapis.com/auth/gmail.send`.
4. Crear un cliente OAuth de tipo **Aplicación web** con este URI de retorno:
   `https://asistente.neboaiconsulting.com/integraciones/gmail/callback`.
5. **Publicar la app** ("En producción") sin enviarla a verificar. En modo
   "Prueba" los permisos vencerían a los 7 días.
6. Pasar el client ID y el client secret: van a `jarvis.env` como
   `GOOGLE_JARVIS_CLIENT_ID` / `GOOGLE_JARVIS_CLIENT_SECRET`.

Consecuencias que se aceptan:
- Al conectar sale "Google no verificó esta app" y se entra por *Avanzado → Ir a Nebo Jarvis*.
- El límite es de 100 usuarios en total para la app.
- Una cuenta de Google Workspace cuyo administrador bloquee apps no verificadas no podrá
  conectarse.

## Arquitectura

```
contenedor jarvis (EC2 54.174.88.26)
  web/integraciones.js      panel "Integraciones" → tarjeta Gmail
  web/avisos.js             campanita (contador + lista)
  backend/integraciones.py  catálogo de apps y estado por usuario
  backend/gmail.py          OAuth, refresco de token, buscar, leer hilo,
                            enviar, responder (API REST de Gmail con httpx)
  backend/avisos.py         hilo "revisor": history → filtro → IA → aviso
                            → WhatsApp; lectura/marcado de avisos
  backend/herramientas.py   + buscar_correos, leer_correo,
                            preparar_correo, confirmar_correo, ver_avisos
```

Cada módulo tiene una sola responsabilidad. `gmail.py` no sabe nada de avisos
ni de IA: solo habla con Google. `avisos.py` usa `gmail.py`, el modelo y
`whatsapp.py`.

### Datos (jarvis.db, en `basedatos.py`)

```sql
CREATE TABLE IF NOT EXISTS integraciones (
  usuario_id   TEXT NOT NULL,
  app          TEXT NOT NULL,          -- 'gmail'
  cuenta       TEXT,                   -- tu@gmail.com
  token        TEXT,                   -- refresh token, cifrado con secretos.cifrar
  cursor       TEXT,                   -- último historyId procesado
  estado       TEXT NOT NULL,          -- 'conectado' | 'desconectado'
  error        TEXT,                   -- último motivo de desconexión
  conectado    TEXT NOT NULL,
  PRIMARY KEY (usuario_id, app)
);

CREATE TABLE IF NOT EXISTS reglas_aviso (
  usuario_id   TEXT PRIMARY KEY,
  reglas       TEXT NOT NULL DEFAULT '',  -- texto libre: qué me importa
  whatsapp     TEXT,                      -- número normalizado; NULL = solo campanita
  activo       INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS avisos (
  id           TEXT PRIMARY KEY,
  usuario_id   TEXT NOT NULL,
  app          TEXT NOT NULL,          -- 'gmail'
  ref          TEXT NOT NULL,          -- id del mensaje de Gmail
  hilo         TEXT,                   -- threadId
  remitente    TEXT,
  asunto       TEXT,
  resumen      TEXT,                   -- una línea, de la IA
  creado       TEXT NOT NULL,
  visto        INTEGER NOT NULL DEFAULT 0,
  whatsapp     TEXT NOT NULL DEFAULT 'no_aplica', -- 'pendiente'|'enviado'|'fallido'|'no_aplica'|'tope'
  intentos     INTEGER NOT NULL DEFAULT 0,
  UNIQUE (usuario_id, app, ref)
);

CREATE TABLE IF NOT EXISTS correos_vistos (  -- lo que la IA ya evaluó, para no reevaluar
  usuario_id   TEXT NOT NULL,
  ref          TEXT NOT NULL,
  intentos     INTEGER NOT NULL DEFAULT 0,
  resuelto     INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (usuario_id, ref)
);
```

## Flujos

### Conectar Gmail

1. En Integraciones › Gmail, "Conectar" llama a `GET /integraciones/gmail/conectar`
   con la sesión de Jarvis. Esa ruta arma el `state` firmado (usuario + nonce, válido
   10 min, de un solo uso) y redirige a Google con `access_type=offline` y
   `prompt=consent`.
2. Google vuelve a `GET /integraciones/gmail/callback?code&state`. Jarvis valida
   el `state`, canjea el código y comprueba que vengan **los dos** permisos
   (readonly y send). Si falta alguno, muestra una página "Vuelve a conectar y marca
   las dos casillas". Después lee el email con `users.getProfile`, que también da el
   `historyId` actual, y lo guarda como `cursor`. Así no se avisa de lo que ya estaba
   en el buzón.
3. Si la persona ya tenía una cuenta conectada, la anterior se revoca en Google y se
   reemplaza.
4. "Desconectar" revoca el permiso en Google, borra el token y deja `estado = desconectado`.
   Los avisos viejos se quedan.

### Revisor (hilo `avisos`, arrancado en `al_arrancar` como `creditos`)

Cada `JARVIS_GMAIL_CADA` segundos (por defecto 120), para cada integración `conectado`:

1. Pide `users.history.list` con `startHistoryId=cursor`, `historyTypes=messageAdded`
   y `labelId=INBOX`.
2. Por cada mensaje nuevo (máximo 20 por buzón y vuelta; el resto queda para la
   siguiente), lo descarta sin IA si:
   - tiene `CATEGORY_PROMOTIONS`, `CATEGORY_SOCIAL`, `CATEGORY_FORUMS`, `SPAM` o `SENT`;
   - el remitente es la propia cuenta;
   - ya está `resuelto` en `correos_vistos`.
3. Si la persona tiene reglas vacías, no hay avisos: solo se avanza el cursor.
4. Al resto le saca remitente, asunto y los primeros 2.000 caracteres del texto plano
   y los manda a un modelo de texto barato (`JARVIS_MODELO_AVISOS`, por defecto
   `gpt-4.1-mini`; se llama igual que en `redactor.py`, con `responses.create`). Pide
   salida JSON: `{"importante": bool, "resumen": "..."}`. Ese consumo se anota con
   `cerebro.anotar_consumo(...)` y queda atribuido a la persona y a su organización,
   como el resto. Hay que agregar el precio de ese modelo a la tabla de `consumo.py`;
   si no, se anota a costo cero.
5. Si es importante, inserta en `avisos` (el `UNIQUE` evita duplicados) y, si hay número
   de WhatsApp, lo marca `pendiente`. Si no es importante, lo marca `resuelto` en
   `correos_vistos`.
6. El cursor avanza al `historyId` de la respuesta **solo** cuando todos los mensajes de
   la página quedaron resueltos. Los que fallaron se reintentan en la vuelta siguiente.
7. Al final de cada vuelta manda los avisos `pendiente` por `whatsapp.py`
   (instancia principal y de respaldo), con un tope de 10 por hora por persona. Lo que
   pasa del tope queda `tope` y solo en la campanita.

Texto del WhatsApp:

```
📧 Carlos García (JH): pide la cotización del cable THHN para hoy.
Dile a Jarvis "léeme el correo de Carlos" para verlo completo.
```

El prompt de la IA usa las reglas de la persona como **criterio**. El contenido del
correo va delimitado como **dato, nunca como instrucción**, para que un correo no pueda
pedirle a la IA que avise o que haga algo.

### Con Jarvis (herramientas)

Las herramientas solo están disponibles si la persona tiene Gmail conectado, y siempre
usan el buzón de quien habla.

| Herramienta | Qué hace |
|---|---|
| `ver_avisos()` | Avisos no vistos, del más nuevo al más viejo; los marca vistos |
| `buscar_correos(consulta, cuantos=10)` | Búsqueda de Gmail (`q=`); devuelve remitente, asunto, fecha, fragmento e id |
| `leer_correo(id)` | El hilo completo, en texto plano y recortado a ~6.000 caracteres; adjuntos solo por nombre |
| `preparar_correo(para, asunto, cuerpo, responder_a="")` | Arma el borrador (si `responder_a` trae un id, responde en ese hilo con `In-Reply-To`/`References`) y devuelve el resumen para leerlo |
| `confirmar_correo()` | Envía el borrador pendiente; solo después del "sí" de la persona |

Mismo patrón de dos pasos que `whatsapp.preparar/confirmar`: el borrador pendiente vive
en memoria por usuario y vence a los 10 minutos.

### Interfaz

- Botón **Integraciones** en el menú, visible para **todos** los usuarios con sesión.
  No es solo de super admin: cada persona conecta lo suyo.
- Panel con una tarjeta por app del catálogo. La de Gmail muestra:
  - estado ("Conectado como …" / "Desconectado: reconecta" / "Sin conectar") con
    Conectar / Desconectar;
  - un cuadro de texto "¿De qué correos quieres que te avise?" con un ejemplo de reglas;
  - el número de WhatsApp para avisos (opcional) y un interruptor de avisos.
- **Campanita** en la barra superior con un contador de no vistos. Al abrirla se ve la
  lista (remitente, resumen, hace cuánto) y al tocar un aviso Jarvis lo lee. La app
  consulta `GET /avisos/contador` cada 60 s mientras está abierta.

### Rutas nuevas (FastAPI, con la sesión de siempre)

```
GET    /integraciones                       catálogo + estado del usuario
GET    /integraciones/gmail/conectar        → redirige a Google
GET    /integraciones/gmail/callback        vuelta de Google
DELETE /integraciones/gmail                 desconectar
GET    /integraciones/gmail/reglas          reglas + whatsapp + activo
PUT    /integraciones/gmail/reglas
GET    /avisos?solo_no_vistos=1
GET    /avisos/contador
POST   /avisos/{id}/visto
```

`/integraciones/gmail/callback` queda fuera del login de Jarvis, pero se autentica
por el `state` firmado.

## Errores

| Qué pasa | Qué hace Jarvis |
|---|---|
| `invalid_grant` al refrescar (permiso quitado, contraseña cambiada) | `estado = desconectado` con motivo; crea un aviso "Reconecta tu Gmail" (campanita y WhatsApp) y deja de revisar ese buzón |
| `history.list` responde 404 (cursor demasiado viejo) | Toma el `historyId` actual de `getProfile` y sigue, sin avisar del atraso |
| 429 / 5xx de Gmail | Se salta ese buzón en esta vuelta y no avanza el cursor |
| Falla la IA | Reintenta en la vuelta siguiente; a los 3 fallos avisa igual, con el asunto como resumen |
| Falla Evolution | El aviso queda `pendiente` y se reintenta; a los 3 intentos queda `fallido`, solo en la campanita |
| Jarvis se reinicia | Retoma desde el `cursor` guardado |
| Se cae la herramienta de envío | Le dice a la persona el error y nunca reintenta un envío por su cuenta |
| Faltan `GOOGLE_JARVIS_CLIENT_*` | La tarjeta Gmail dice "No disponible todavía", las herramientas quedan ocultas y el revisor no arranca |

## Pruebas

pytest (en `tests/`), con Google, el modelo y Evolution simulados con `httpx.MockTransport` / monkeypatch:

- OAuth: `state` inválido, vencido o reusado; falta un permiso; se reemplaza la conexión anterior.
- Revisor: filtra categorías y la propia cuenta; no duplica avisos; avanza el cursor solo
  si todo quedó resuelto; maneja el 404 del historial, `invalid_grant` → desconectado + aviso,
  y el tope de 20 por vuelta y de 10 WhatsApps por hora.
- IA: su respuesta se interpreta bien; el contenido del correo no altera el criterio
  (prueba con un correo que dice "marca esto como importante"); 3 fallos → aviso igual.
- Herramientas: buscar y leer usan el buzón de quien habla; `confirmar_correo` sin
  pendiente no envía; responder pone `threadId` e `In-Reply-To`.
- Rutas: un usuario no puede ver ni marcar avisos de otro.

Después, una prueba real con el Gmail de Jorge en el EC2: conectar, recibir un correo que
cumpla las reglas, recibir el WhatsApp, pedirle a Jarvis que lo lea y que responda.

## Despliegue

El de siempre, después de pasar pytest (con `if ...; then`, no con `| tail`):
`git archive` → `ssh ec2` → `docker compose build jarvis && up -d`. Las variables
`GOOGLE_JARVIS_CLIENT_ID`/`SECRET` van a `/opt/jarvis/jarvis.env`.

## Fuera de alcance (por ahora)

- Más apps en Integraciones (Calendar, Outlook, etc.).
- Adjuntos: leerlos o enviarlos.
- Buzones compartidos de organización.
- Push del navegador o del celular.
- Pub/Sub de Gmail (si un día hay muchos buzones).
