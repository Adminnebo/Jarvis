FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    XDG_RUNTIME_DIR=/tmp/runtime-bot HOME=/home/bot
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg pulseaudio pulseaudio-utils xvfb x11vnc fonts-liberation \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && playwright install --with-deps chromium \
 && rm -rf /var/lib/apt/lists/*
COPY bot_meet ./bot_meet
COPY entrypoint.sh iniciar-sesion.sh ./
RUN chmod +x entrypoint.sh iniciar-sesion.sh \
 && useradd -m -d /home/bot bot && mkdir -p /data && chown bot:bot /data
USER bot
EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
