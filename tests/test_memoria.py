import json

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


def _escribir_archivos_viejos(carpeta):
    (carpeta / "hechos.json").write_text(
        json.dumps([{"id": "aaa11111", "contenido": "Un recuerdo viejo",
                     "categoria": "general", "creado": "2026-01-01T00:00:00"}]),
        encoding="utf-8",
    )
    (carpeta / "conversacion.json").write_text(
        json.dumps([{"role": "user", "content": "hola de antes"}]),
        encoding="utf-8",
    )


def test_el_admin_hereda_los_archivos_sueltos(entorno_limpio):
    _escribir_archivos_viejos(entorno_limpio)

    memoria.migrar_archivos_sueltos("admin")

    assert memoria.todos_los_hechos("admin")[0]["contenido"] == "Un recuerdo viejo"
    assert memoria.cargar_conversacion("admin")[0]["content"] == "hola de antes"
    # Los viejos quedan como respaldo frio.
    assert (entorno_limpio / "hechos.json").exists()


def test_migrar_dos_veces_no_pisa_lo_nuevo(entorno_limpio):
    _escribir_archivos_viejos(entorno_limpio)
    memoria.migrar_archivos_sueltos("admin")

    memoria.recordar("admin", "Un recuerdo nuevo", "general")
    memoria.migrar_archivos_sueltos("admin")

    contenidos = [h["contenido"] for h in memoria.todos_los_hechos("admin")]
    assert "Un recuerdo nuevo" in contenidos
    assert len(contenidos) == 2


def test_sin_archivos_viejos_no_hace_nada():
    memoria.migrar_archivos_sueltos("admin")
    assert memoria.todos_los_hechos("admin") == []
