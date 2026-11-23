# Jarvis dentro de cada panel de JH

Fecha: 2026-11-23 · Ramas: `feat/jarvis-en-paneles` (Jarvis) y `feat/jarvis` (jh-panel-completo)

## Objetivo

Jarvis disponible en Conversaciones, Cotizaciones, Cobranzas, Marketing y
Reactivación (portaljh.neboaiconsulting.com) como un orbe flotante, sabiendo
qué tiene abierto la persona y pudiendo consultar los datos del panel **con
los mismos permisos que la persona tiene en él**.

## Decisiones

| Tema | Decisión |
|---|---|
| Qué sabe | Lo que está en pantalla (cada panel lo informa) + consultas de solo lectura al panel + lo que Jarvis ya tenía (SQL de JH) |
| Permisos | Jarvis llama a rutas nuevas `/api/jarvis/*` de cada panel con el token de Supabase de quien pregunta; esas rutas usan el mismo control de plataforma y permiso que la pantalla. Los paneles no filtran por vendedor y Jarvis tampoco |
| Quién lo ve | Quien tenga `jarvis.usar`/`jarvis.admin` o sea admin/super_admin (las reglas que Jarvis ya aplica a los paneles). Sin permiso el widget no aparece |
| Widget | `jarvis-widget.js` servido por Jarvis (ruta libre), en shadow DOM, `JarvisWidget.init({panel, getToken, getContexto})`; reemplaza el botón "Jarvis" que abría otra pestaña |
| Sesión | Jarvis acepta `Authorization: Bearer <token de Supabase>` (además de los tokens de dispositivo) en cada pedido; sin cookies. CORS solo para `JARVIS_ORIGENES_PANELES` (por defecto `https://portaljh.neboaiconsulting.com`) |
| Destino de las consultas | Jarvis arma la URL con su propio mapa panel → prefijo sobre `JARVIS_PORTAL_JH`; nunca usa una URL que mande el navegador |
| Herramienta | `consultar_panel(consulta, parametros)`; el catálogo de consultas del panel activo va en la instrucción del turno |
| Micrófono | Los paneles pasan a `Permissions-Policy: microphone=(self)` para poder dictar |
| Límite de pedidos | En los paneles que limitan por IP, los pedidos con token se cuentan por usuario (las consultas de Jarvis salen todas del mismo servidor) |

## Consultas por panel

| Panel | Consulta | Ruta |
|---|---|---|
| Conversaciones | `conversaciones` (q, sin_responder, limite) · `conversacion` (id) · `contacto` (id) | `/api/jarvis/conversaciones`, `/api/jarvis/conversaciones/{id}`, `/api/jarvis/contacto/{id}` |
| Cotizaciones | `cotizaciones` (dias, q) · `cotizacion` (numero) · `embudo` · `seguimiento` · `llamadas` (dias) | `/cotizaciones/api/jarvis/...` |
| Cobranzas | `cartera` (limite, q) · `cliente` (codigo) · `promesas` | `/cobranzas/api/jarvis/...` |
| Marketing | `creaciones` (dias, q) · `publicaciones` | `/marketing/api/jarvis/...` |
| Reactivación | `resumen` · `clientes` (estado, clasificacion, q) · `cliente` (codigo) | `/reactivacion/api/jarvis/...` |

Ninguna tiene efectos (p. ej. leer una conversación no la marca leída).

## Pruebas

Jarvis: token de Supabase en el encabezado, CORS, widget libre, contexto del
panel en la instrucción, la herramienta (URL armada por Jarvis, permisos 403,
sin panel activo). Paneles: cada ruta `/api/jarvis/*` exige sesión, plataforma
y permiso, y no modifica nada.
