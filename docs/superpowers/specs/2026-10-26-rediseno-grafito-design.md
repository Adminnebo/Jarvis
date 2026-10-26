# Rediseño visual "Grafito minimal"

Fecha: 2026-10-26. Estado: diseño aprobado por Jorge, pendiente de plan.

## Qué se quiere

Que Jarvis se vea más moderno y profesional sin cambiar cómo se usa: misma estructura y mismo
comportamiento, otro aspecto. Dirección elegida entre tres maquetas (Cristal, Grafito minimal, HUD
holográfico): **Grafito minimal**, sobrio, tipo herramienta de trabajo (Linear, Vercel).

## Alcance

Todo lo visible: pantalla principal, paneles de administración (Fuentes —con diccionario, accesos
directos y consola SQL—, Consumo, Organización, Asistente, Dispositivos, Memoria), modales y pantallas
de login/registro/privacidad (`acceso.py` y `web/privacidad.html`).

Fuera de alcance: cambiar la estructura de la pantalla, la lógica, los textos o el avatar (se mantiene
con su holograma sutil y su tamaño actual).

## Enfoque

Reescribir `web/style.css` sobre tokens (variables CSS) y aplicarlos a cada componente. **No se cambian
los `id` ni las clases que usa el JavaScript**; si un componente necesita una clase nueva solo para
estilo, se agrega sin quitar la vieja. Las páginas de `acceso.py` (estilo propio en `_ESTILO`) pasan a
los mismos tokens. Descartado: Tailwind o rehacer en React (mucho más trabajo y riesgo para un cambio de
aspecto).

## Tokens

```css
--fondo: #0a0a0b;          /* pagina */
--superficie: #111113;     /* paneles, campo de entrada, tarjetas */
--superficie-2: #16161a;   /* hover, filas alternas, campos dentro de paneles */
--borde: #232327;          /* 1 px en todo */
--borde-fuerte: #2e2e34;   /* separadores de seccion, foco sin acento */
--texto: #ececf0;
--tenue: #7d7d86;          /* secundario, etiquetas */
--muy-tenue: #55555c;      /* marcas como "Tú" */
--acento: #4da3ff;         /* lo activo, enlaces, linea de las respuestas, foco */
--acento-suave: rgba(77,163,255,.12);
--ok: #3ddc84;  --peligro: #ff6b6b;  --aviso: #f5b84d;
--radio: 8px;  --radio-chico: 6px;
--fuente: "Inter", system-ui, sans-serif;
--mono: "JetBrains Mono", ui-monospace, monospace;
```

Inter y JetBrains Mono desde Google Fonts. Tamaño base 14 px; títulos de panel 13 px semibold;
etiquetas en mayúsculas de 11 px con `letter-spacing: .12em`. Los nombres de variables que ya existen
(`--fondo`, `--panel`, `--borde`, `--texto`, `--tenue`, `--acento`, `--acento-suave`, `--peligro`,
`--ok`) se conservan (`--panel` pasa a ser alias de `--superficie`) para no romper estilos en línea ni
módulos JS que los usan.

## Componentes

- **Barra superior:** sin caja; línea inferior de 1 px. Punto de estado (verde en línea), nombre del
  asistente en 15 px semibold. Los botones de admin (`.boton-texto` de la barra) son texto gris
  (`--tenue`) que pasa a `--texto` al pasar el mouse; sin borde ni fondo.
- **Campo de entrada** (`.entrada`): una caja `--superficie` con borde 1 px y radio 10 px. Adentro: el
  campo de texto sin borde, "Manos libres" como interruptor discreto, "Voz en vivo" con borde, el
  micrófono como botón claro (`#ededf0`, ícono oscuro) de 30 px. Foco: borde `--acento`.
- **Avatar y orbe:** sin cambios de forma. El texto de estado bajo la escena (`.pie-orbe`) en
  mayúsculas de 11 px `--tenue`.
- **Conversación:** sin burbujas. Mensajes del usuario en `--tenue` con la etiqueta "Tú" en
  `--muy-tenue`; respuestas en `--texto` con borde izquierdo de 2 px `--acento` y 10 px de sangría;
  14 px de separación entre turnos; interlineado 1.55.
- **Botones:** `.boton-texto` = texto con borde 1 px `--borde`, radio 6 px, fondo transparente,
  hover `--superficie-2`; la acción principal de cada panel en claro (`#ededf0` sobre texto oscuro);
  `peligro` en rojo solo al pasar el mouse.
- **Paneles laterales** (`.panel`): fondo `--superficie`, borde izquierdo 1 px, sin sombra pesada;
  `.panel-barra` con título de 13 px y línea inferior; el contenido con 16 px de margen.
- **Tablas** (consola SQL, consumo, accesos): filas separadas por líneas de 1 px, cabecera en
  mayúsculas de 11 px `--tenue`, números alineados a la derecha con cifras tabulares.
- **Formularios:** campos `--fondo` con borde 1 px y radio 6 px; foco con borde `--acento` y anillo
  `--acento-suave`; etiquetas de 12 px `--tenue` arriba del campo.
- **Chips y estados:** texto de 11 px con borde 1 px, sin fondo de color; el color solo en un punto de
  6 px (verde/rojo/ámbar).
- **Login y registro:** tarjeta centrada de 360 px, fondo `--superficie`, borde 1 px, mismo estilo de
  campos y botón principal claro.

## Celular (≤ 720 px)

- Los botones de admin de la barra pasan a un menú "⋯" (un `<details>` en la barra con los mismos
  botones dentro; los `id` no cambian, solo se mueven dentro del menú con CSS/HTML, sin JS nuevo
  salvo cerrarlo al elegir).
- El campo de entrada queda fijo abajo (`position: sticky; bottom: 0`) con fondo `--fondo` y borde
  superior, para escribir con el pulgar.
- Paneles a pantalla completa.

## Verificación

- Capturas de cada pantalla (principal en reposo y con conversación, cada panel, login, celular a
  390 px) con el Electron del monitor de escritorio (`C:\Users\Jorge\monitor-ec2`, como se hizo con
  el panel de JDL), servidas por un Jarvis local con datos de ejemplo. Se revisan antes de publicar.
- Las pruebas existentes (pytest) siguen pasando: no hay cambios de lógica.
- Comprobación de que todos los `id` que usa `web/*.js` siguen existiendo en `index.html`.
