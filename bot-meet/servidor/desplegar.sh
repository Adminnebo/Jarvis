#!/usr/bin/env bash
# Despliega el bot desde GitHub: si cambió bot-meet/ en la rama, reconstruye.
#   desplegar.sh          -> solo si hay cambios en bot-meet/
#   desplegar.sh forzar   -> reconstruye igual
# Lo corre cada minuto bot-meet-despliegue.timer. Registro: /var/log/bot-meet-despliegue.log
# No reinicia el bot si hay una reunión grabándose: espera a la próxima vuelta.
set -euo pipefail
cd /opt/bot-meet
exec 9>/run/bot-meet-despliegue.lock
flock -n 9 || exit 0
RAMA="$(cat rama 2>/dev/null || echo main)"
log() { echo "$(date -u +%FT%TZ) $*" >> /var/log/bot-meet-despliegue.log; }

git -C repo fetch -q --depth 1 origin "$RAMA" || { log "no se pudo leer GitHub"; exit 0; }
antes=$(git -C repo rev-parse HEAD)
nuevo=$(git -C repo rev-parse FETCH_HEAD)
if [ "${1:-}" != "forzar" ]; then
  [ "$antes" = "$nuevo" ] && exit 0
  if git -C repo diff --quiet "$antes" "$nuevo" -- bot-meet 2>/dev/null; then
    git -C repo reset -q --hard FETCH_HEAD
    exit 0
  fi
  # El puerto 8000 no está publicado en el host: se pregunta desde adentro.
  activas=$(docker compose exec -T bot python -c "import json,urllib.request; print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/v1/salud', timeout=4))['activas'])" 2>/dev/null || echo 0)
  if [ "$activas" != "0" ]; then
    log "hay $activas reunión(es) grabándose; despliego después"
    exit 0
  fi
fi
git -C repo reset -q --hard FETCH_HEAD
cp repo/bot-meet/servidor/docker-compose.yml repo/bot-meet/servidor/Caddyfile .
log "bot: ${antes:0:7} -> ${nuevo:0:7}"
docker image inspect bot-meet-bot:latest >/dev/null 2>&1 && docker tag bot-meet-bot:latest bot-meet-bot:anterior
if ! docker compose build bot >> /var/log/bot-meet-despliegue.log 2>&1; then
  log "FALLÓ la construcción; sigue lo anterior"; exit 1
fi
docker compose up -d >> /var/log/bot-meet-despliegue.log 2>&1
estado=""
for _ in $(seq 24); do
  sleep 5
  estado=$(docker inspect -f '{{.State.Health.Status}}' "$(docker compose ps -q bot)" 2>/dev/null || true)
  [ "$estado" = "healthy" ] && break
done
if [ "$estado" != "healthy" ]; then
  log "el bot no quedó sano ($estado): vuelvo a la imagen anterior"
  if docker image inspect bot-meet-bot:anterior >/dev/null 2>&1; then
    docker tag bot-meet-bot:anterior bot-meet-bot:latest
    docker compose up -d --no-build bot >> /var/log/bot-meet-despliegue.log 2>&1
  fi
  exit 1
fi
docker image prune -f >/dev/null 2>&1 || true
docker builder prune -f --keep-storage 500MB >/dev/null 2>&1 || true
log "listo"
