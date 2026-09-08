import json

from backend import herramientas, memoria


def test_el_parametro_usuario_no_aparece_en_el_esquema():
    esquema = next(
        e for e in herramientas.esquemas() if e["name"] == "recordar"
    )
    propiedades = esquema["parameters"]["properties"]
    assert "usuario" not in propiedades
    assert "usuario" not in esquema["parameters"]["required"]
    assert "contenido" in propiedades


def test_recordar_escribe_en_la_memoria_de_quien_habla():
    herramientas.ejecutar(
        "recordar", json.dumps({"contenido": "Le gusta el te"}), "jorge"
    )
    assert memoria.todos_los_hechos("jorge") != []
    assert memoria.todos_los_hechos("lucas") == []


def test_buscar_memoria_solo_ve_lo_propio():
    memoria.recordar("lucas", "El coche es azul", "general")
    de_lucas = herramientas.ejecutar("buscar_memoria", json.dumps({"consulta": "coche"}), "lucas")
    de_jorge = herramientas.ejecutar("buscar_memoria", json.dumps({"consulta": "coche"}), "jorge")
    assert "azul" in de_lucas
    assert "azul" not in de_jorge


def test_una_herramienta_sin_usuario_sigue_funcionando():
    resultado = herramientas.ejecutar("hora_actual", "{}", "jorge")
    assert "de" in resultado
