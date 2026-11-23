# Apps dentro de Jarvis — 2: Correo (Gmail)

Fecha: 2026-11-23 · Rama: `feat/apps-correo` (sale de `main`)
Antes: `2026-11-20-apps-whatsapp-design.md` (la primera app y su forma de trabajar).

## Objetivo

La bandeja de Gmail de cada persona **dentro de Jarvis**, lo más parecida a Gmail
(computadora) y a la app de Gmail (celular): carpetas y etiquetas, pestañas de
Recibidos, leer hilos con su formato, acciones, redactar con adjuntos, buscar y
ver lo nuevo sin recargar.

## Decisiones

| Tema | Decisión |
|---|---|
| Permiso | Se agrega `https://www.googleapis.com/auth/gmail.modify` a la app de Google. Cada persona reconecta una vez; hasta entonces la bandeja es de solo lectura + responder, con una franja para reconectar |
| Datos | Jarvis hace de intermediario con la API de Gmail; el token nunca sale del servidor |
| Dónde | `/apps/correo` (`web/apps-correo.html`, `web/apps/correo.js`, `web/apps/correo.css`). La barra de Jarvis de las apps pasa a tener pestañas **WhatsApp \| Correo** (también en `/apps/whatsapp`) |
| HTML de los correos | En un `<iframe sandbox>` sin `allow-scripts` ni `allow-same-origin` (con `allow-popups` para los enlaces), con `<base target="_blank">` y una CSP que bloquea imágenes remotas hasta "Mostrar imágenes". Las imágenes `cid:` las incrusta el servidor como `data:` |
| Tiempo real | Mientras la vista está abierta, cada 25 s `GET /cambios?desde=<historyId>` (Gmail no avisa a terceros sin Pub/Sub) |
| Borrar | Mueve a la Papelera (`trash`); el borrado definitivo no se ofrece |
| Estilo | El de Gmail en modo oscuro (sin logos ni marca de Google) |

## Primera versión

- Menú: Recibidos, Destacados, Enviados, Borradores, Todos, Spam, Papelera y las
  etiquetas de la persona, con contador de no leídos.
- Recibidos con pestañas Principal / Promociones / Social.
- Lista: remitente (o "Para: …" en Enviados), asunto, fragmento, fecha, clip,
  negrita si no leído, estrella, casillas para elegir varios. 50 por página, con
  "más antiguos".
- Hilo: mensajes anteriores plegados (se abren al tocar), cuerpo HTML aislado,
  adjuntos para ver o descargar.
- Acciones (uno o varios): archivar, eliminar, leído/no leído, destacar, mover a
  etiqueta. Cambio inmediato en pantalla, vuelta atrás si Gmail falla, "Deshacer".
- Redactar (ventana flotante; pantalla completa en celular): Para/CC/CCO,
  asunto, editor con negrita, cursiva, listas y enlaces; adjuntos ≤ 25 MB;
  borrador guardado solo en Gmail; responder, responder a todos y reenviar
  (mismo hilo, con la cita del original).
- Buscar con la sintaxis de Gmail.
- Celular: lista a pantalla completa, menú con ☰, botón flotante "Redactar",
  "atrás" del teléfono vuelve a la lista.

Fuera (segunda versión): Outlook en la misma vista, programar envío, filtros,
firma, posponer, varias cuentas.

## Servidor

### `backend/gmail.py` (se amplía)

- `MODIFICAR` en `PERMISOS`; `permisos(refresh)` devuelve los permisos que dio
  la persona (el `scope` que devuelve Google al refrescar el token, en caché).
- Lectura: `etiquetas(token)` (con contadores), `hilos(token, etiqueta, consulta,
  pagina)` (ids + `nextPageToken`) y `hilo_completo(token, id)`, `adjunto(token,
  mensaje, id)`, `cambios(token, desde)` (historial con mensajes agregados,
  borrados y cambios de etiquetas).
- Escritura: `modificar_hilos(token, ids, agregar, quitar)`,
  `papelera(token, ids)`, `crear_borrador` / `actualizar_borrador` /
  `borrar_borrador` / `enviar_borrador`, y `enviar_mime(token, crudo, hilo)`.

### `backend/apps_correo.py` (nuevo)

- `resumen_de_hilo(hilo)` para la lista: remitentes, asunto, fragmento, fecha,
  no leído, destacado, adjuntos, cantidad de mensajes.
- `mensaje_para_ver(mensaje)`: cabeceras, HTML (o el texto convertido a HTML),
  adjuntos, e imágenes `cid:` incrustadas.
- `armar_mime(...)`: correo multipart (texto + HTML + adjuntos), con
  `In-Reply-To` / `References` al responder.
- Los hilos de la lista se piden en paralelo (hasta 10 a la vez).

### Rutas (`backend/rutas_apps_correo.py`, con sesión)

| Ruta | Qué |
|---|---|
| `GET /apps/correo` | la página |
| `GET /api/apps/correo/estado` | conectado, cuenta, si puede modificar |
| `GET /api/apps/correo/etiquetas` | menú con contadores |
| `GET /api/apps/correo/hilos?etiqueta=&q=&pagina=` | lista |
| `GET /api/apps/correo/hilos/{id}` | hilo completo |
| `GET /api/apps/correo/adjunto/{mensaje}/{adjunto}?nombre=&tipo=` | archivo |
| `POST /api/apps/correo/acciones` | `{ids, accion: archivar/eliminar/leido/no_leido/destacar/quitar_estrella/mover/quitar_etiqueta, etiqueta}` |
| `PUT /api/apps/correo/borrador` | crear o actualizar (multipart con adjuntos) |
| `DELETE /api/apps/correo/borrador/{id}` | descartar |
| `POST /api/apps/correo/enviar` | enviar (multipart) |
| `GET /api/apps/correo/cambios?desde=` | lo que cambió desde un historyId |

Sin Gmail conectado → 409 `{conectar: true}` (la vista muestra "Conectar Gmail").
Sin `gmail.modify` → las acciones de escritura devuelven 403 `{reconectar: true}`.

## Pruebas

`gmail.py` y `apps_correo.py` con MockTransport (rutas, cuerpos, MIME armado,
HTML con `cid:`, permisos), rutas con TestClient (409, 403, acciones,
borradores, adjuntos), interfaz con capturas en 1366 y 400 px con un Gmail
falso. Prueba real con la cuenta de Jorge después de agregar el permiso.
