import json

import pytest

from backend import fuentes


@pytest.fixture
def motor(monkeypatch):
    """Un motor de mentira que anota lo que recibe."""
    vistos = []

    def falso(config, sql, limite, id_fuente=None, parametros=None):
        vistos.append({"sql": sql, "parametros": parametros, "limite": limite})
        return [{"n": 1}]

    monkeypatch.setitem(fuentes.MOTORES, "mssql", falso)
    monkeypatch.setattr(fuentes, "obtener", lambda _id: {
        "id": "erp", "nombre": "ERP", "tipo": "mssql", "activa": True, "solo_lectura": True, "config": {}})
    return vistos


def test_consultar_pasa_los_parametros_al_motor(motor):
    fuentes.consultar("erp", "select count(*) n from v where f >= %(desde)s", 10, parametros={"desde": "2026-10-26"})
    assert motor[0]["parametros"] == {"desde": "2026-10-26"}


def test_sin_parametros_sigue_como_antes(motor):
    fuentes.consultar("erp", "select 1", 10)
    assert motor[0]["parametros"] is None


from backend import accesos  # noqa: E402

VENTAS = {
    "id": "ventas_por_periodo",
    "pregunta": "¿Cuántas ventas se hicieron hoy?",
    "descripcion": "Cantidad y monto de ventas entre dos fechas.",
    "sql": "select count(*) as ventas from List_OrdenVentasIA where Fecha >= %(desde)s and Fecha < %(hasta)s",
    "parametros": {
        "desde": {"tipo": "fecha", "descripcion": "Desde (incluida)", "por_defecto": "2026-10-26"},
        "hasta": {"tipo": "fecha", "descripcion": "Hasta (excluida)", "por_defecto": "2026-10-27"},
    },
}


def test_guardar_y_listar(motor):
    accesos.guardar("erp", VENTAS)
    [a] = accesos.listar("erp")
    assert a["id"] == "ventas_por_periodo" and a["parametros"]["desde"]["tipo"] == "fecha"
    assert a["activo"] is True and a["ultimo_error"] is None


def test_el_sql_tiene_que_ser_de_solo_lectura(motor):
    with pytest.raises(accesos.ErrorDeAcceso, match="solo lectura"):
        accesos.guardar("erp", {**VENTAS, "sql": "delete from List_ClientesIA"})


def test_los_placeholders_tienen_que_coincidir(motor):
    with pytest.raises(accesos.ErrorDeAcceso, match="hasta"):
        accesos.guardar("erp", {**VENTAS, "sql": "select 1 where f >= %(desde)s"})


def test_el_nombre_es_corto_y_sin_espacios(motor):
    with pytest.raises(accesos.ErrorDeAcceso):
        accesos.guardar("erp", {**VENTAS, "id": "ventas de hoy!"})


def test_tipos_de_variable(motor):
    p = {"tipo": "entero", "descripcion": "Cuantos", "por_defecto": 5, "minimo": 1, "maximo": 50}
    assert accesos.valor(p, "7") == 7
    with pytest.raises(accesos.ErrorDeAcceso):
        accesos.valor(p, 500)
    assert accesos.valor({"tipo": "fecha"}, "2026-10-26") == "2026-10-26"
    with pytest.raises(accesos.ErrorDeAcceso):
        accesos.valor({"tipo": "fecha"}, "26/10/2026")
    with pytest.raises(accesos.ErrorDeAcceso):
        accesos.valor({"tipo": "texto"}, "x" * 101)


def test_borrar_y_desactivar(motor):
    accesos.guardar("erp", VENTAS)
    accesos.activar("ventas_por_periodo", False)
    assert accesos.listar("erp")[0]["activo"] is False
    assert accesos.borrar("ventas_por_periodo") is True
    assert accesos.listar("erp") == []


def test_borrar_la_fuente_borra_sus_accesos(motor):
    accesos.guardar("erp", VENTAS)
    accesos.borrar_de_fuente("erp")
    assert accesos.listar("erp") == []


def test_ejecutar_usa_los_parametros_y_los_por_defecto(motor):
    accesos.guardar("erp", VENTAS)
    r = accesos.ejecutar("ventas_por_periodo", {"desde": "2026-10-01"})
    assert r["filas"] == [{"n": 1}]
    assert motor[0]["parametros"] == {"desde": "2026-10-01", "hasta": "2026-10-27"}


def test_el_resultado_se_cachea_30_segundos(motor):
    accesos.guardar("erp", VENTAS)
    accesos.ejecutar("ventas_por_periodo", {})
    accesos.ejecutar("ventas_por_periodo", {})
    assert len(motor) == 1


def test_un_fallo_queda_anotado_y_dice_como_seguir(motor, monkeypatch):
    accesos.guardar("erp", VENTAS)

    def rompe(*a, **k):
        raise RuntimeError("Invalid object name 'List_OrdenVentasIA'")
    monkeypatch.setitem(fuentes.MOTORES, "mssql", rompe)
    r = accesos.ejecutar("ventas_por_periodo", {})
    assert "consultar_fuente" in r["error"]
    assert "Invalid object name" in accesos.obtener("ventas_por_periodo")["ultimo_error"]


def test_uno_desactivado_o_inexistente_no_se_ejecuta(motor):
    accesos.guardar("erp", VENTAS)
    accesos.activar("ventas_por_periodo", False)
    assert "error" in accesos.ejecutar("ventas_por_periodo", {})
    assert "error" in accesos.ejecutar("no_existe", {})


def test_catalogo_para_el_prompt(motor, monkeypatch):
    monkeypatch.setattr(fuentes, "activas", lambda: [{"id": "erp", "nombre": "ERP"}])
    accesos.guardar("erp", VENTAS)
    texto = accesos.catalogo_para_prompt()
    assert texto.startswith("- acceso ventas_por_periodo(desde, hasta) [fuente erp]:")


def test_borrar_la_fuente_borra_sus_accesos_desde_fuentes(motor, monkeypatch):
    accesos.guardar("erp", VENTAS)
    monkeypatch.setattr(fuentes, "_leer", lambda: [{"id": "erp"}])
    monkeypatch.setattr(fuentes, "_escribir", lambda lista: None)
    fuentes.borrar("erp")
    assert accesos.listar("erp") == []


def test_la_herramienta_usa_el_acceso(motor):
    from backend import herramientas

    accesos.guardar("erp", VENTAS)
    texto = herramientas.usar_acceso_directo("ventas_por_periodo", '{"desde": "2026-10-20"}')
    assert json.loads(texto) == [{"n": 1}]
    assert "JSON" in herramientas.usar_acceso_directo("ventas_por_periodo", "{no es json")


def test_las_instrucciones_listan_los_accesos(motor, monkeypatch):
    from backend import acceso, cerebro

    monkeypatch.setattr(fuentes, "activas", lambda: [{"id": "erp", "nombre": "ERP"}])
    monkeypatch.setattr(fuentes, "resumen_para_prompt", lambda: "- id \"erp\": ERP")
    accesos.guardar("erp", VENTAS)
    texto = cerebro.instrucciones(acceso.Usuario("u", "Ana", "usuario"))
    assert "- acceso ventas_por_periodo(desde, hasta)" in texto
    assert "usar_acceso_directo" in texto


def test_rutas_de_accesos_solo_admin(motor, monkeypatch):
    from fastapi.testclient import TestClient

    from backend import cuentas
    from backend.main import app

    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setenv("JARVIS_CLAVE_SECRETA", "clave-de-pruebas-larga")
    admin = TestClient(app)
    admin.post("/acceso", data={"clave": "la-del-admin"}, follow_redirects=False)
    r = admin.post("/api/fuentes/erp/accesos", json=VENTAS)
    assert r.status_code == 200 and r.json()["id"] == "ventas_por_periodo"
    assert [a["id"] for a in admin.get("/api/fuentes/erp/accesos").json()["accesos"]] == ["ventas_por_periodo"]
    assert admin.post("/api/accesos/ventas_por_periodo/probar", json={"parametros": {}}).json()["filas"] == [{"n": 1}]
    assert admin.put("/api/accesos/ventas_por_periodo", json={"activo": False}).status_code == 200
    assert admin.post("/api/fuentes/erp/accesos", json={**VENTAS, "sql": "drop table x"}).status_code == 400

    cuentas.crear_organizacion("JH", "Ana", "ana@jh.com", "una-clave-larga")
    ana = TestClient(app)
    ana.post("/acceso/cuenta", data={"email": "ana@jh.com", "password": "una-clave-larga"}, follow_redirects=False)
    assert ana.get("/api/fuentes/erp/accesos").status_code == 403
    assert ana.delete("/api/accesos/ventas_por_periodo").status_code == 403
    assert admin.delete("/api/accesos/ventas_por_periodo").json() == {"ok": True}
