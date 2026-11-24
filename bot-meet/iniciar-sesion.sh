#!/bin/sh
# Abre Chromium con el perfil base (/data/perfil) para iniciar sesión en Google
# UNA vez. Se ve desde la PC de Jorge por un túnel SSH:
#   modo devtools (por defecto): chrome://inspect -> localhost:9222
#   modo vnc: un visor VNC a localhost:5900
# Se corre con red del host (ver servidor/LEEME.md).
set -e
MODO="${1:-devtools}"
CHROME=$(python -c "from playwright.sync_api import sync_playwright as s; p=s().start(); print(p.chromium.executable_path); p.stop()")
Xvfb :98 -screen 0 1280x800x16 -nolisten tcp &
export DISPLAY=:98
sleep 1
if [ "$MODO" = "vnc" ]; then
  x11vnc -display :98 -localhost -rfbport 5900 -nopw -forever -quiet &
fi
# --no-sandbox: dentro de Docker no hay sandbox de Chrome (Playwright lo pone
# solo al lanzar el bot; aquí se lanza a mano).
exec "$CHROME" --user-data-dir=/data/perfil --no-first-run --lang=es-419 --no-sandbox \
  --remote-debugging-port=9222 --remote-debugging-address=127.0.0.1 \
  --disable-blink-features=AutomationControlled \
  https://accounts.google.com/
