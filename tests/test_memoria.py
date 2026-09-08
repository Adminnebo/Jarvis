from backend import memoria


def test_los_hechos_de_cada_uno_no_se_mezclan():
    memoria.recordar("lucas", "Le gusta el cafe cargado", "preferencias")
    memoria.recordar("jorge", "Vive en Monterrey", "personal")

    de_lucas = [h["contenido"] for h in memoria.todos_los_hechos("lucas")]
    de_jorge = [h["contenido"] for h in memoria.todos_los_hechos("jorge")]

    assert de_lucas == ["Le gusta el cafe cargado"]
    assert de_jorge == ["Vive en Monterrey"]


def test_el_resumen_del_prompt_solo_trae_lo_propio():
    memoria.recordar("lucas", "Le gusta el cafe cargado", "preferencias")
    memoria.recordar("jorge", "Vive en Monterrey", "personal")

    assert "cafe" in memoria.resumen_para_prompt("lucas")
    assert "Monterrey" not in memoria.resumen_para_prompt("lucas")


def test_buscar_no_cruza_usuarios():
    memoria.recordar("lucas", "El proyecto Jarvis usa Supabase", "proyectos")
    assert memoria.buscar("lucas", "Jarvis") != []
    assert memoria.buscar("jorge", "Jarvis") == []


def test_olvidar_solo_alcanza_lo_propio():
    hecho = memoria.recordar("lucas", "Un dato cualquiera", "general")
    assert memoria.olvidar("jorge", hecho["id"]) is False
    assert memoria.olvidar("lucas", hecho["id"]) is True


def test_la_conversacion_es_de_cada_uno():
    memoria.guardar_conversacion("lucas", [{"role": "user", "content": "hola"}])
    assert memoria.cargar_conversacion("lucas") != []
    assert memoria.cargar_conversacion("jorge") == []

    memoria.borrar_conversacion("lucas")
    assert memoria.cargar_conversacion("lucas") == []
