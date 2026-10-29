# Servidor de Jarvis (EC2 54.174.88.26, `ssh jarvis`)

Copia versionada de lo que vive en `/opt/jarvis` del servidor. Los secretos
(`jarvis.env`, `reloj.env`, `android.env`) NO estan aqui: solo en el servidor.

## Como se despliega

Cada minuto `jarvis-despliegue.timer` corre `/opt/jarvis/desplegar.sh`, que mira
la rama principal de los tres repos (clones en `/opt/jarvis/repos/`):

| servicio        | repo                    | rama   |
|-----------------|-------------------------|--------|
| `jarvis`        | Adminnebo/Jarvis        | main   |
| `puente-android`| Adminnebo/jarvis-lentes (`puente/`) | main |
| `puente-reloj`  | Adminnebo/jarvis-reloj (`puente/`)  | master |

Si una rama cambio, reconstruye solo ese servicio con los contenedores viejos
encendidos y lo reemplaza. Si Jarvis no queda sano en 2 minutos, vuelve solo a la
imagen anterior (`jarvis-jarvis:anterior`). Registro: `/var/log/jarvis-despliegue.log`.

**Hacer push a `main` = desplegar a produccion.** No se suben archivos a mano.

## A mano

    ssh jarvis
    sudo /opt/jarvis/desplegar.sh            # desplegar ya, sin esperar el minuto
    sudo /opt/jarvis/desplegar.sh forzar     # reconstruir todo
    sudo tail -f /var/log/jarvis-despliegue.log
    curl https://asistente.neboaiconsulting.com/api/version   # que commit corre

Volver a la version anterior de un servicio (ej. jarvis):

    cd /opt/jarvis
    sudo docker tag jarvis-jarvis:anterior jarvis-jarvis:latest
    sudo docker compose up -d --no-build jarvis

Ojo: el timer lo vuelve a desplegar en el siguiente cambio de `main`; para
quedarse en la anterior hay que revertir el commit en GitHub.

## Si cambias algo de esta carpeta

El servidor no la lee sola: copiala a `/opt/jarvis/` (y los `.service`/`.timer`
a `/etc/systemd/system/` + `systemctl daemon-reload`).

Acceso de lectura a GitHub: llaves de despliegue `/root/.ssh/deploy_<repo>` (alias
`gh-<repo>` en `/root/.ssh/config`), una por repo, solo lectura.
