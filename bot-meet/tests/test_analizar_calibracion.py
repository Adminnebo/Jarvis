from bot_meet.herramientas.analizar_calibracion import candidatas, textos


def foto(t, ana_habla):
    return {"t": t, "mosaicos": [
        {"id": "p1", "texto": "Ana", "marcas": ["c:fijo", "a:data-self-name=Ana"] + (["c:habla"] if ana_habla else [])},
        {"id": "yo", "texto": "Jarvis", "marcas": ["c:fijo"]},
    ]}


def test_encuentra_la_marca_que_prende_al_hablar():
    lineas = [foto(t, 3 <= t < 6) for t in range(10)]
    c = candidatas(lineas)
    assert c["p1"] == [("c:habla", "...###....")]   # las fijas no salen
    assert c["yo"] == []
    assert textos(lineas) == {"p1": "Ana", "yo": "Jarvis"}
