# WhatsApp: conexión asistida por un worker con la sesión de Facebook de Nebo

Fecha: 2026-11-19 · Rama: `feat/whatsapp-conexion-asistida` (sale de `main`)
Antes: `docs/superpowers/specs/2026-11-09-integraciones-whatsapp-design.md`.

## Problema

La coexistencia de WhatsApp (Zernio → Embedded Signup de Meta) obliga a quien
conecta a entrar con una cuenta de Facebook dueña del negocio. Meta lo exige
para cualquier proveedor; no hay forma de saltarlo por API. Las personas que
usan Jarvis no tienen (ni deberían necesitar) una cuenta de Facebook de negocio.

## Objetivo

Que la persona solo **escriba su número y escanee un QR**. Todo lo demás lo
hace un worker en el servidor con un navegador que ya tiene iniciada la sesión
de una **cuenta de Facebook dedicada de Nebo**, administradora del portafolio
de Nebo.

## Decisiones

| Tema | Decisión | Por qué |
|---|---|---|
| Cuenta de Facebook | Una dedicada solo a esto, admin del portafolio de Nebo pero **no** la única | Si Meta la restringe, el portafolio y los números siguen a salvo |
| Inicio de sesión | Una vez, a mano, **desde el mismo servidor**, por una pantalla remota; el worker reusa ese perfil del navegador | Una sesión que cambia de IP o se reinicia con contraseña dispara verificaciones |
| Dónde corre | Contenedor `navegador` (Playwright + Chromium) en el compose de Jarvis, sin puerto público; perfil en un volumen propio | Misma IP siempre; la sesión sobrevive a los despliegues |
| Memoria | El EC2 pasa de t3.micro a **t3.small (2 GB)**; Chromium solo vive mientras hay trabajo | Hoy quedan ~410 MB libres; Chromium con Facebook pide 300–400 MB |
| Concurrencia | Un trabajo a la vez; el siguiente recibe "hay otra conexión en curso" | Son pocas conexiones; un solo perfil de navegador no admite dos manos |
| Algo raro en pantalla | El robot se detiene sin cerrar nada, avisa al super admin, que termina a mano y le devuelve el control | Facebook a veces pide captcha o "¿eres tú?", y Meta cambia sus pantallas |

Riesgo aceptado por Jorge: las condiciones de Meta no permiten usar Facebook de
forma automatizada; la cuenta dedicada puede ser restringida. Se mitiga con la
sesión reusada, la misma IP, un trabajo a la vez y la cuenta separada de la
principal.

## Arquitectura

```
EC2 de Jarvis (t3.small)
  jarvis (FastAPI)
    backend/conexion_whatsapp.py   orquesta: pide el trabajo, guarda su estado,
                                   avisa al super admin, sirve el QR
    rutas /api/integraciones/whatsapp/conexion*, /api/navegador/*
  navegador (contenedor nuevo, red interna de compose, sin puertos publicados)
    navegador/servidor.py          API HTTP interna (token compartido)
    navegador/robot.py             los pasos sobre Zernio/Meta
    volumen navegador_perfil       el perfil de Chromium (sesion de Facebook)
  web/integraciones.js             tarjeta WhatsApp: numero → progreso → QR
  web/navegador.js                 pantalla "Sesion de Facebook" (super admin)
```

Jarvis y el navegador hablan por `http://navegador:8000` con
`NAVEGADOR_TOKEN` (cabecera `Authorization: Bearer`), generado al desplegar y
presente en `jarvis.env` y en el entorno del contenedor nuevo.

## El contenedor `navegador`

Imagen basada en `mcr.microsoft.com/playwright/python` (versión fija), con
FastAPI y uvicorn. Límite de memoria 900 MB en compose. Chromium se lanza con
`launch_persistent_context(user_data_dir="/perfil", headless=True)`, viewport
1280×800, idioma `es-ES`, zona `America/Santo_Domingo`, y **se cierra** cuando
no hay trabajo ni pantalla remota abierta durante 2 min.

API interna (todo con el token):

| Ruta | Qué hace |
|---|---|
| `GET /estado` | `{ocupado, trabajo: {id, fase, detalle, qr?}, navegador_abierto}` |
| `POST /trabajos` `{id, url, telefono}` | Empieza una conexión. 409 si ya hay una |
| `POST /trabajos/{id}/cancelar` | La corta y cierra las páginas del trabajo |
| `POST /trabajos/{id}/seguir` | Le devuelve el control al robot después de una intervención |
| `GET /pantalla` | JPEG de la página activa (abre Chromium si está cerrado) |
| `POST /accion` `{tipo: click|escribir|tecla|ir, x, y, texto, tecla, url}` | Mano remota del super admin |

Fases de un trabajo: `preparando` → `qr` → `terminando` → `listo`, o
`necesita_ayuda` / `error` / `cancelado`. `qr` lleva la imagen del código
(captura recortada del elemento, PNG en base64), que se refresca en cada
consulta.

## El robot (`navegador/robot.py`)

Pasos, cada uno con su espera máxima (por defecto 45 s) y buscando por texto
visible en español **o** inglés, nunca por clases CSS:

1. Abrir la `authUrl` de Zernio (hosted signup). Si Zernio abre una ventana de
   Meta, seguir en esa ventana.
2. Si Meta muestra "Iniciar sesión" / "Log in": **no** escribir contraseña →
   `necesita_ayuda` ("La sesión de Facebook se cerró").
3. Pantallas de consentimiento ("Continuar como …", "Comenzar", "Get started",
   "Siguiente", "Next"): pulsar el botón.
4. Elegir el portafolio cuyo nombre contiene `NAVEGADOR_PORTAFOLIO` (por
   defecto "Nebo").
5. Elegir "Conectar tu cuenta existente de WhatsApp Business" / "Connect your
   existing WhatsApp Business app".
6. Escribir el teléfono (país + número) y seguir.
7. Al ver "Comparte tus contactos y chats" / el QR: fase `qr`; esperar hasta
   10 min a que desaparezca el QR o aparezca la confirmación.
8. Pulsar los "Siguiente/Finalizar/Listo" que queden; fase `terminando`.
9. Listo cuando la página navega a `…/integraciones/whatsapp/callback` de
   Jarvis (la vuelta firmada que ya existe) y responde; fase `listo`.

Cualquier pantalla que no encaje con el paso esperado, un captcha, o "Confirma
tu identidad" → `necesita_ayuda` con una captura. Tope total del trabajo:
15 min.

Los pasos viven en una tabla de datos (texto a buscar → acción), para ajustarlos
sin tocar la lógica cuando Meta cambie algo.

## Lado de Jarvis (`backend/conexion_whatsapp.py`)

- `iniciar(usuario, telefono)`: normaliza el número
  (`whatsapp.normalizar_numero`), prepara el perfil de Zernio y la `authUrl`
  (lo mismo que hoy hace `/integraciones/whatsapp/conectar`), crea el trabajo
  en el navegador. Si está ocupado: "Hay otra conexión en curso, intenta en unos
  minutos".
- `estado(usuario)`: consulta el navegador y devuelve fase, detalle y QR, solo
  si el trabajo es de esa persona (Jarvis guarda en memoria qué trabajo es de
  quién).
- Al entrar en `necesita_ayuda`: aviso de sistema a los super admin
  ("Una conexión de WhatsApp necesita ayuda") con enlace a la pantalla remota.
  Una vez por trabajo.
- `cancelar(usuario)`.

Rutas:

| Ruta | Quién |
|---|---|
| `POST /api/integraciones/whatsapp/conexion` `{telefono}` | quien conecta |
| `GET /api/integraciones/whatsapp/conexion` | quien conecta (sondeo cada 2 s) |
| `DELETE /api/integraciones/whatsapp/conexion` | quien conecta |
| `GET /api/navegador/pantalla`, `POST /api/navegador/accion`, `GET /api/navegador/estado`, `POST /api/navegador/seguir` | solo super admin (`acceso.exige_admin`) |

La ruta vieja `/integraciones/whatsapp/conectar` (redirige a Meta) queda para el
super admin como plan B.

## Interfaz

**Tarjeta WhatsApp** (sin conectar): campo "Tu número de WhatsApp Business" +
**Conectar**. Después:

- "Preparando la conexión…" con spinner.
- Fase `qr`: el QR grande + "Abre **WhatsApp Business** en tu teléfono, toca el
  mensaje de Meta que te acaba de llegar y escanea este código." + nota
  "Si no te llegó, en WhatsApp Business ve a Ajustes → Herramientas para la
  empresa → … y busca la opción de conectar con Facebook."
- `terminando`: "Casi listo…".
- `listo`: recarga la tarjeta ("Conectado como …").
- `necesita_ayuda`: "Estamos terminando tu conexión; te avisamos cuando esté."
- `error`: el motivo + **Reintentar**. Botón **Cancelar** mientras dure.

**Pantalla "Sesión de Facebook"** (super admin, botón en el panel de
Integraciones): imagen del navegador refrescada cada segundo, clic sobre la
imagen = clic en el navegador (coordenadas escaladas), una caja de texto para
escribir, teclas Enter/Tab/Escape, una barra de dirección, el estado del
trabajo y **Que siga el robot**.

## Seguridad

- El contenedor no publica puertos; sin el token no responde.
- La sesión de Facebook solo sale del contenedor como imágenes, y solo hacia
  super admin. Quien conecta ve únicamente el recorte del QR.
- La mano remota solo la tiene el super admin (`exige_admin`), no quien conecta.
- El trabajo valida que `url` sea de `zernio.com` y el robot no navega fuera de
  `zernio.com`, `facebook.com`, `whatsapp.com`, `fbcdn.net` y el dominio de
  Jarvis.

## Pruebas

- `conexion_whatsapp.py` y las rutas: con un navegador falso (httpx
  MockTransport): ocupado, de quién es el trabajo, QR solo al dueño, aviso a
  super admin una vez, permisos de la mano remota.
- `navegador/robot.py`: la tabla de pasos contra páginas HTML locales que imitan
  cada pantalla (incluida una de login y una desconocida → `necesita_ayuda`),
  con Playwright de verdad, en un archivo de pruebas aparte que se salta si
  Playwright no está instalado.
- Prueba real con Jorge: primer inicio de sesión por la pantalla remota y la
  primera conexión de un número.

## Despliegue

1. Cambiar el EC2 a t3.small (parar, cambiar tipo, arrancar: ~2–3 min sin Jarvis).
2. Generar `NAVEGADOR_TOKEN`; agregar el servicio `navegador` y el volumen al
   `docker-compose.yml` de `/opt/jarvis` y al script de despliegue (que hoy solo
   reconstruye `jarvis`).
3. OK de Jorge → push a `main`.
4. Jorge inicia sesión con la cuenta dedicada por la pantalla remota.
5. Prueba con un número real.

## Fuera de alcance

Resolver captchas o verificaciones solo; varias conexiones a la vez; usar otra
cuenta de Facebook por cliente.
