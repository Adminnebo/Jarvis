"""Diccionario por tabla: leyenda, significado de columnas y reglas."""

import pytest

from backend import fuentes

ESQUEMA = {"fuente": "ERP", "tipo": "mssql", "tablas": [
    {"tabla": "List_ClientesIA", "columnas": "Codigo varchar, Nombre varchar, Estado char"},
]}


@pytest.fixture
def fuente(monkeypatch):
    guardadas = [{"id": "erp", "nombre": "ERP", "tipo": "mssql", "activa": True, "config": {}, "tablas": {}}]
    monkeypatch.setattr(fuentes, "_leer", lambda: guardadas)
    monkeypatch.setattr(fuentes, "_escribir", lambda lista: guardadas.__setitem__(slice(None), lista))
    monkeypatch.setattr(fuentes, "esquema_de", lambda _id, refrescar=False: ESQUEMA)
    monkeypatch.setattr(fuentes, "contar_filas", lambda *_: None)
    return guardadas


def test_se_guardan_columnas_y_reglas(fuente):
    fuentes.guardar_config_tablas("erp", {"List_ClientesIA": {
        "activa": True, "leyenda": " clientes ",
        "columnas": {"Estado": " 'A' = activo ", "Inventada": "no existe", "Nombre": ""},
        "reglas": " Activo es Estado = 'A'. ",
    }})
    cfg = fuente[0]["tablas"]["List_ClientesIA"]
    assert cfg == {"activa": True, "leyenda": "clientes",
                   "columnas": {"Estado": "'A' = activo"}, "reglas": "Activo es Estado = 'A'."}


def test_los_textos_largos_se_recortan(fuente):
    fuentes.guardar_config_tablas("erp", {"List_ClientesIA": {
        "columnas": {"Estado": "x" * 500}, "reglas": "y" * 5000}})
    cfg = fuente[0]["tablas"]["List_ClientesIA"]
    assert len(cfg["columnas"]["Estado"]) == 200 and len(cfg["reglas"]) == 1000


def test_el_panel_recibe_el_diccionario(fuente):
    fuentes.guardar_config_tablas("erp", {"List_ClientesIA": {
        "leyenda": "clientes", "columnas": {"Estado": "'A' = activo"}, "reglas": "r"}})
    tabla = fuentes.esquema_con_estado("erp")["tablas"][0]
    assert tabla["columnas_significado"] == {"Estado": "'A' = activo"}
    assert tabla["reglas"] == "r"


def test_el_prompt_lleva_columnas_y_reglas(fuente, monkeypatch):
    monkeypatch.setattr(fuentes, "activas", lambda: fuente)
    fuentes.guardar_config_tablas("erp", {"List_ClientesIA": {
        "leyenda": "clientes", "columnas": {"Estado": "'A' = activo"}, "reglas": "Activo es Estado = 'A'."}})
    texto = fuentes.resumen_para_prompt()
    assert "List_ClientesIA (clientes)" in texto
    assert "Estado: 'A' = activo" in texto
    assert "Reglas: Activo es Estado = 'A'." in texto
