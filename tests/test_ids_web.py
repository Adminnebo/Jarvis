"""Ningun id que busca el JS de la web puede desaparecer del HTML (rediseno sin romper nada)."""

import re
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"


def test_todos_los_ids_que_usa_el_js_existen():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    existentes = set(re.findall(r'id="([^"]+)"', html))
    usados = set()
    for js in WEB.glob("*.js"):
        texto = js.read_text(encoding="utf-8")
        usados |= set(re.findall(r'\$\$?\("([\w-]+)"\)', texto))
        usados |= set(re.findall(r'getElementById\("([\w-]+)"\)', texto))
    faltan = sorted(usados - existentes)
    assert not faltan, f"El JS busca ids que no estan en index.html: {faltan}"
