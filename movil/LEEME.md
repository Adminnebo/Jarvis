# Jarvis para Android

App de Capacitor que abre el Jarvis de siempre (`server.url` =
`https://asistente.neboaiconsulting.com`, la sesión es la misma cookie) y suma
una sola cosa nativa: **grabar reuniones presenciales con la pantalla apagada**.

- `android/app/src/main/java/com/neboai/jarvis/GrabadoraServicio.java`: servicio
  en primer plano (tipo `microphone`, notificación «Jarvis está grabando» con
  «Terminar»). Graba OGG/Opus mono 16 kHz en pedazos de 5 min y los sube él mismo
  a `/api/reuniones/{id}/audio` con el token de la reunión; si no hay red, quedan
  en `files/cola/` y se reintentan.
- `GrabadoraPlugin.java`: el puente `GrabadoraPresencial` (`iniciar`, `terminar`,
  `estado`) que usa `web/apps/grabadora.js` cuando corre dentro de la app.
- Como la interfaz viene del servidor, los cambios de pantalla no piden otro APK;
  solo los cambios en esta carpeta.

**Compilar:** GitHub Actions (`.github/workflows/apk.yml`) en cada push a `main`
que toque `movil/`, en los PR y a mano; el APK queda en el run → Artifacts →
`jarvis-apk`. Es de depuración, sin tienda: instalarlo permitiendo «orígenes
desconocidos». Local: `npm ci && npx cap sync android && cd android && ./gradlew assembleDebug`
(JDK 21 + Android SDK). Android 10 o más nuevo.

Conectar Gmail/Outlook (Integraciones) conviene hacerlo desde el navegador: Google
no deja iniciar sesión dentro de una WebView.
