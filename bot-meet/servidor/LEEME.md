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

El despliegue corre como root sobre un clon de `ubuntu`: hace falta
`git config --system --add safe.directory /opt/bot-meet/repo` (ya puesto), si
no el registro dice «no se pudo leer GitHub».

## Medido en la primera prueba real (2026-11-24)

- Reposo: 42 MB, sin Chrome abierto.
- Grabando un Meet de 3 personas con «Solo audio»: ~500 MB de RAM y 35-40 % de
  un núcleo (con el volcado de HTML cada 10 s encendido). Dos bots caben en RAM;
  en CPU, el t3.small rinde 40 % de un núcleo sostenido entre sus dos vCPU, así
  que con dos bots a la vez gasta créditos de CPU.
- Audio: Opus mono 16 kHz, ~2,2 MB por cada 5 min (unos 27 MB por hora), voces a -24 dB de media.
- Quién habla (calibrado el 2026-11-25 con `BOT_MEET_CALIBRAR_S` y
  `analizar_calibracion`): el nombre sale de «Más opciones para X» en el texto del
  mosaico, la presentación y el propio bot («Fondos y efectos») no cuentan, y
  «hablando» es la clase `.gjg47c` → `BOT_MEET_SEL_HABLANDO=.gjg47c` en `bot.env`.
  Si Google cambia la página y los nombres vuelven a salir como «Participante»,
  repetir la calibración: `BOT_MEET_CALIBRAR_S=240`, una reunión por turnos y
  `python -m bot_meet.herramientas.analizar_calibracion`.

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
