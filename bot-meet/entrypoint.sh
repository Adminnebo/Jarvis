#!/bin/sh
# PulseAudio con una salida falsa "grabacion": Chrome suena ahí y ffmpeg graba
# su monitor. Xvfb solo si se pidió Chrome con pantalla (BOT_MEET_HEADLESS=0).
set -e
mkdir -p "$XDG_RUNTIME_DIR" && chmod 700 "$XDG_RUNTIME_DIR"
pulseaudio -D --exit-idle-time=-1 --disallow-exit --log-target=stderr
for _ in 1 2 3 4 5 6 7 8 9 10; do pactl info >/dev/null 2>&1 && break; sleep 0.5; done
pactl load-module module-null-sink sink_name=grabacion sink_properties=device.description=grabacion >/dev/null
pactl set-default-sink grabacion
if [ "${BOT_MEET_HEADLESS:-1}" = "0" ]; then
  Xvfb :99 -screen 0 640x360x16 -nolisten tcp &
  export DISPLAY=:99
fi
exec uvicorn bot_meet.app:crear_app_desde_entorno --factory --host 0.0.0.0 --port 8000 --no-access-log
