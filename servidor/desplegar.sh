#!/usr/bin/env bash
# Despliega Jarvis y sus puentes desde GitHub (como hacia Railway).
#
#   desplegar.sh           -> si main cambio en algun repo, reconstruye solo ese servicio
#   desplegar.sh forzar    -> reconstruye todo aunque no haya cambios
#
# Lo corre cada minuto el timer jarvis-despliegue.timer. Registro en
# /var/log/jarvis-despliegue.log. Si Jarvis no queda sano en 2 minutos, vuelve a
# la imagen anterior sola.
set -euo pipefail
cd /opt/jarvis
exec 9>/run/jarvis-despliegue.lock
flock -n 9 || exit 0

log() { echo "$(date -u +%FT%TZ) $*" >> /var/log/jarvis-despliegue.log; }

# servicio | carpeta del repo | rama
REPOS=(
  "jarvis|repos/Jarvis|main"
  "puente-android|repos/jarvis-lentes|main"
  "puente-reloj|repos/jarvis-reloj|master"
)

cambiados=()
for fila in "${REPOS[@]}"; do
  IFS='|' read -r servicio carpeta rama <<< "$fila"
  if ! git -C "$carpeta" fetch -q --depth 1 origin "$rama" 2>>/var/log/jarvis-despliegue.log; then
    log "$servicio: no se pudo leer GitHub, sigue lo que hay"
    continue
  fi
  antes=$(git -C "$carpeta" rev-parse HEAD)
  nuevo=$(git -C "$carpeta" rev-parse FETCH_HEAD)
  if [ "$antes" != "$nuevo" ] || [ "${1:-}" = "forzar" ]; then
    git -C "$carpeta" reset -q --hard FETCH_HEAD
    log "$servicio: ${antes:0:7} -> ${nuevo:0:7}"
    cambiados+=("$servicio")
  fi
done
[ ${#cambiados[@]} -eq 0 ] && exit 0

# La version que muestra Jarvis (backend/version.py lee esta variable).
echo "JARVIS_COMMIT=$(git -C repos/Jarvis rev-parse HEAD)" > .env

# Guardar la imagen actual para poder volver.
for s in "${cambiados[@]}"; do
  docker image inspect "jarvis-$s:latest" >/dev/null 2>&1 && docker tag "jarvis-$s:latest" "jarvis-$s:anterior"
done

# Construir con los contenedores viejos encendidos; si falla, no se toca nada.
if ! docker compose build "${cambiados[@]}" >> /var/log/jarvis-despliegue.log 2>&1; then
  log "FALLO la construccion de ${cambiados[*]}; sigue corriendo lo anterior"
  exit 1
fi
docker compose up -d "${cambiados[@]}" >> /var/log/jarvis-despliegue.log 2>&1

if [[ " ${cambiados[*]} " == *" jarvis "* ]]; then
  for _ in $(seq 24); do
    sleep 5
    estado=$(docker inspect -f '{{.State.Health.Status}}' "$(docker compose ps -q jarvis)" 2>/dev/null || true)
    [ "$estado" = "healthy" ] && break
  done
  if [ "$estado" != "healthy" ]; then
    log "Jarvis no quedo sano ($estado): vuelvo a la imagen anterior"
    docker tag jarvis-jarvis:anterior jarvis-jarvis:latest
    docker compose up -d --no-build jarvis >> /var/log/jarvis-despliegue.log 2>&1
    exit 1
  fi
fi

# El disco es chico (6.7 GB): la cache de construccion se come lo que sobre.
docker image prune -f >/dev/null 2>&1 || true
docker builder prune -f --keep-storage 300MB >/dev/null 2>&1 || true
log "listo: ${cambiados[*]}"
