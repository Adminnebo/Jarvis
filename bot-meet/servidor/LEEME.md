# Servidor del bot de Meet (EC2 18.227.166.134, `ssh bot-meet`)

t3.small (2 GB + 2 GB de swap), us-east-2, Ubuntu 24.04. Copia versionada de
lo que vive en `/opt/bot-meet`. El secreto (`bot.env`) NO está aquí.

| Ruta | Qué es |
|---|---|
| `/opt/bot-meet/repo` | clon de Adminnebo/Jarvis (llave de despliegue de solo lectura) |
| `/opt/bot-meet/rama` | rama que se despliega (`main`; durante la prueba, la rama de trabajo) |
| `/opt/bot-meet/bot.env` | `BOT_MEET_SECRETO=...` (el mismo que tiene Jarvis), `BOT_MEET_SEL_HABLANDO=...` |
| volumen `bot-meet_datos` | `/data`: agenda, perfil de Google, sesiones, capturas |

**Desplegar = push a la rama.** El timer mira cada minuto; si hay una
reunión grabándose, espera. Registro: `sudo tail -f /var/log/bot-meet-despliegue.log`.

## Iniciar sesión con la cuenta de Google del bot (una vez, o si se cierra)

En el servidor, con el bot apagado para que no use el perfil:

    cd /opt/bot-meet && sudo docker compose stop bot
    sudo docker run --rm -it --network host -v bot-meet_datos:/data \
      --entrypoint ./iniciar-sesion.sh bot-meet-bot:latest

En la PC: `ssh -L 9222:127.0.0.1:9222 bot-meet`, abrir Chrome en
`chrome://inspect`, «Configure…» → `localhost:9222`, «inspect» en la pestaña
de Google y entrar con la cuenta. Si Google dice que el navegador no es seguro,
usar VNC: correr el script con `vnc` al final, túnel `-L 5900:127.0.0.1:5900`
y un visor VNC a `localhost:5900`. Al terminar: Ctrl+C y `sudo docker compose up -d bot`.

## Ver qué pasó

    sudo docker compose logs --tail 200 bot
    sudo docker compose exec bot ls /data/capturas      # capturas de fallos
    sudo docker compose exec -T bot python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/v1/salud').read().decode())"
