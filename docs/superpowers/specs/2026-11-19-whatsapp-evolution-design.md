# WhatsApp por Evolution API: vincular con QR o código

Fecha: 2026-11-19 · Rama: `feat/whatsapp-conexion-asistida`
Reemplaza, por ahora, a `2026-11-19-whatsapp-conexion-asistida-design.md` (el
worker con Facebook queda sin construir) y cambia el proveedor de
`2026-11-09-integraciones-whatsapp-design.md`.

## Por qué

La coexistencia por Zernio/Meta obliga a entrar con Facebook. Con Evolution
(Baileys) la persona vincula Jarvis como un dispositivo más de su WhatsApp,
igual que WhatsApp Web: escanea un QR y listo. Sirve con WhatsApp normal y
Business. Riesgo aceptado: no es la vía oficial de Meta.

## Decisiones

| Tema | Decisión |
|---|---|
| Servidor | El Evolution v2.3.7 de server2 (`EVOLUTION_URL`/`EVOLUTION_API_KEY`, la clave global que Jarvis ya usa para mandar cotizaciones) |
| Instancia | Una por persona, `jarvis-<usuario>`, creada por Jarvis al pulsar Conectar |
| Configuración al crearla | Webhook a Jarvis (mensajes nuevos, cambios de conexión, QR), `groupsIgnore`, **no** marcar leídos, no "en línea", sin historial completo, sin rechazar llamadas |
| Vincular | QR que se refresca; o **código de 8 letras** con el número (para quien abre Jarvis en el mismo teléfono) |
| Webhook | `POST /integraciones/whatsapp/evolution?clave=<secreto de esa instancia>`; el secreto identifica a la persona y se compara también el nombre de la instancia |
| Proveedor por persona | Quien tiene instancia de Evolution usa Evolution; si no, lo de Zernio (sigue en el código; su ruta de conectar queda como plan B) |
| Desconectar | `logout` + `delete` de la instancia en Evolution |
| Caída | `connection.update` con `close` por cierre de sesión (401/403) → desconectado + aviso de sistema; un `close` normal es reconexión y se ignora |

Lo demás no cambia: pendientes por chat, IA con las reglas de Avisos, campanita,
avisos por el WhatsApp de Jarvis (instancia `nebo-wa (Respaldo)`), y las
herramientas `buscar_chats`, `leer_chat`, `responder_chat`,
`confirmar_respuesta_chat`.

## Piezas

- `backend/evolution_wa.py`: cliente de Evolution para las instancias de las
  personas (crear, conectar/QR/código, estado, datos, borrar, chats, mensajes,
  enviar) y lectura de mensajes de Baileys (texto, adjuntos, teléfono con
  `@lid`/`remoteJidAlt`).
- Tabla `evolution_instancias (usuario_id, instancia, clave, numero, actualizado)`.
- `integraciones.py`: guardar/leer/borrar la instancia de cada persona.
- `whatsapp_chats.py`: `recibir_evolution(evento, clave)`; buscar/leer/preparar/
  confirmar/barrer eligen el proveedor de la persona; el QR y el código.
- Rutas: `POST/GET /api/integraciones/whatsapp/vincular` (crear y sondear: QR,
  código, estado), `DELETE /api/integraciones/whatsapp` también borra en
  Evolution, y el webhook.
- Interfaz: tarjeta WhatsApp → Conectar → QR que se renueva cada pocos segundos,
  "Usar código en vez de QR" (pide el número), y al vincular "Conectado como …".

## Pruebas

Cliente y webhook con httpx MockTransport y eventos de ejemplo con la forma
real de Evolution v2 (`messages.upsert`, `connection.update`, `qrcode.updated`);
rutas con TestClient. Prueba real con Jorge: vincular por QR, por código,
mensaje importante/trivial/contestado, leer y responder por voz, desvincular
desde el teléfono.
