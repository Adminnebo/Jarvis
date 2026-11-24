"""Agenda una sesión firmada en el bot local.

    python -m bot_meet.herramientas.agendar https://meet.google.com/abc-defg-hij \
        --minutos 30 --jarvis http://127.0.0.1:9000
"""
import argparse
import json
import os
import secrets
import time
from datetime import datetime, timedelta, timezone

import httpx

from ..firma import firmar


def main():
    p = argparse.ArgumentParser()
    p.add_argument("meet_url")
    p.add_argument("--minutos", type=int, default=30)
    p.add_argument("--jarvis", default="http://127.0.0.1:9000")
    p.add_argument("--bot", default="http://127.0.0.1:8000")
    a = p.parse_args()
    ahora = datetime.now(timezone.utc)
    cuerpo = json.dumps({
        "id": f"prueba-{int(time.time())}", "meet_url": a.meet_url,
        "inicio": ahora.isoformat(), "fin": (ahora + timedelta(minutes=a.minutos)).isoformat(),
        "token_subida": secrets.token_urlsafe(24), "url_jarvis": a.jarvis,
    }).encode()
    t = int(time.time())
    firma = firmar(os.environ["BOT_MEET_SECRETO"], t, "POST", "/v1/sesiones", cuerpo)
    r = httpx.post(f"{a.bot}/v1/sesiones", content=cuerpo, headers={
        "X-Bot-Tiempo": str(t), "X-Bot-Firma": firma, "Content-Type": "application/json"})
    print(r.status_code, r.text, json.loads(cuerpo)["id"])


if __name__ == "__main__":
    main()
