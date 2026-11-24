"""Lee capturas/calibracion.jsonl y muestra qué marcas de cada mosaico prenden y apagan.

    python -m bot_meet.herramientas.analizar_calibracion /data/capturas/calibracion.jsonl

La marca que dice "está hablando" es la que aparece en los segundos en que esa
persona habló (los turnos de la reunión de calibración) y en ningún otro. Las que
están siempre (o nunca) no sirven. Por cada candidata se imprime una línea de
tiempo: '#' = presente ese segundo, '.' = ausente.
"""

import json
import sys
from collections import defaultdict


def candidatas(lineas: list[dict], minimo: float = 0.03, maximo: float = 0.9) -> dict[str, list[tuple[str, str]]]:
    """{id de mosaico: [(marca, línea de tiempo)]} de las marcas intermitentes."""
    tiempos = [x["t"] for x in lineas]
    presentes: dict[str, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
    vistos: dict[str, set[int]] = defaultdict(set)
    for x in lineas:
        for m in x["mosaicos"]:
            vistos[m["id"]].add(x["t"])
            for marca in m["marcas"]:
                presentes[m["id"]][marca].add(x["t"])
    salida = {}
    for mosaico, marcas in presentes.items():
        total = len(vistos[mosaico]) or 1
        filas = []
        for marca, ts in marcas.items():
            if minimo <= len(ts) / total <= maximo:
                filas.append((marca, "".join("#" if t in ts else "." for t in tiempos)))
        salida[mosaico] = sorted(filas, key=lambda f: f[1])
    return salida


def textos(lineas: list[dict]) -> dict[str, str]:
    """El texto más común de cada mosaico (ahí suele estar el nombre)."""
    cuenta: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for x in lineas:
        for m in x["mosaicos"]:
            cuenta[m["id"]][m["texto"]] += 1
    return {k: max(v, key=v.get) for k, v in cuenta.items()}


def main():
    ruta = sys.argv[1] if len(sys.argv) > 1 else "/data/capturas/calibracion.jsonl"
    with open(ruta, encoding="utf-8") as f:
        lineas = [json.loads(x) for x in f if x.strip()]
    print(f"{len(lineas)} segundos, de t={lineas[0]['t']} a t={lineas[-1]['t']}\n")
    nombres = textos(lineas)
    for mosaico, filas in candidatas(lineas).items():
        print(f"== {mosaico}  texto: {nombres.get(mosaico, '')!r}")
        for marca, tiempo in filas[:40]:
            print(f"   {tiempo}  {marca}")
        print()


if __name__ == "__main__":
    main()
