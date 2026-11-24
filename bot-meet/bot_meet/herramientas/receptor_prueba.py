"""Jarvis falso para la prueba real: guarda en /data/prueba/<id>/ lo que llega.

    python -m bot_meet.herramientas.receptor_prueba    # escucha en 127.0.0.1:9000
"""
import json
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request

DESTINO = Path("/data/prueba")
app = FastAPI()


@app.post("/api/reuniones/{id_}/eventos")
async def eventos(id_: str, peticion: Request):
    d = DESTINO / id_
    d.mkdir(parents=True, exist_ok=True)
    texto = (await peticion.body()).decode()
    with open(d / "eventos.jsonl", "a", encoding="utf-8") as f:
        f.write(texto + "\n")
    print("evento", id_, texto)
    return {"ok": True}


@app.post("/api/reuniones/{id_}/audio")
async def audio(id_: str, n: int, peticion: Request):
    d = DESTINO / id_
    d.mkdir(parents=True, exist_ok=True)
    (d / f"pedazo-{n:05d}.ogg").write_bytes(await peticion.body())
    print("audio", id_, n)
    return {"ok": True}


@app.post("/api/reuniones/{id_}/hablantes")
async def hablantes(id_: str, peticion: Request):
    d = DESTINO / id_
    d.mkdir(parents=True, exist_ok=True)
    (d / "hablantes.json").write_text(json.dumps(await peticion.json(), ensure_ascii=False), encoding="utf-8")
    return {"ok": True}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=9000)
