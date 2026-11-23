"""Ningun id que busca el JS de la web puede desaparecer de su HTML (rediseno sin romper nada)."""

import re
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
# Cada pagina con su JS. Lo que no esta aqui es de la pantalla de Jarvis (index.html).
PAGINAS = {"estructura.js": "estructura.html"}
# Sin pagina propia: el widget de los paneles busca dentro de su shadow root, no ids.
SIN_PAGINA = {"jarvis-widget.js"}


def test_todos_los_ids_que_usa_el_js_existen():
    faltan = []
    for js in WEB.glob("*.js"):
        if js.name in SIN_PAGINA:
            continue
        html = (WEB / PAGINAS.get(js.name, "index.html")).read_text(encoding="utf-8")
        existentes = set(re.findall(r'id="([^"]+)"', html))
        texto = js.read_text(encoding="utf-8")
        usados = set(re.findall(r'\$\$?\("([\w-]+)"\)', texto)) | set(re.findall(r'getElementById\("([\w-]+)"\)', texto))
        faltan += [f"{js.name}: {i}" for i in sorted(usados - existentes)]
    assert not faltan, f"El JS busca ids que no estan en su HTML: {faltan}"
