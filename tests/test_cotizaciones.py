import json

import pytest
from fastapi.testclient import TestClient

# Arriba del todo por lo mismo que en test_permisos.py: main carga el .env real.
from backend import cotizacion_html, cotizaciones, herramientas
from backend.main import app

PRODUCTOS = {
    "9681": {"Codigo": "9681", "Referencia": "#12CR", "Descripcion": "KEYARD ALAMBRE THHN #12 ROJO",
             "Und": "PIES      ", "P1": 14.3, "P2": 14.0, "P3": 13.5, "P4": 13.0, "P5": 12.5,
             "P6": 12.0, "P7": 11.5, "TipoItbis": 18, "Coste": 10.0},
    "3790": {"Codigo": "3790", "Referencia": "QO240", "Descripcion": "BREAKER 2P 40AMP",
             "Und": "UND", "P1": 1614.55, "P2": 1500, "P3": 1400, "P4": 118.0, "P5": 0,
             "P6": 0, "P7": 0, "TipoItbis": 18, "Coste": 1000.0},
    "5555": {"Codigo": "5555", "Referencia": "", "Descripcion": "SIN PRECIO", "Und": "UND",
             "P1": 0, "P2": 0, "P3": 0, "P4": 0, "P5": 0, "P6": 0, "P7": 0, "TipoItbis": 18, "Coste": 0},
}
CLIENTES = [
    {"codigo": 6177, "nombre": "FERRETERIA ELIAM MAX EIRL", "rnc": "131832334", "direccion": "C/ 1",
     "email": "f@x.com", "telefono1": "8095551234", "Celular": "", "NivelPrecio": "P4", "factor": 1.0},
    {"codigo": 4926, "nombre": "FERRETERIA OTRA", "rnc": "", "direccion": "", "email": None,
     "telefono1": "", "Celular": "809", "NivelPrecio": "P2", "factor": 1.1},
]


@pytest.fixture
def catalogo(entorno_limpio, monkeypatch):
    for variable, valor in {
        "JARVIS_FUENTE_CATALOGO": "656ef47a", "JARVIS_BUCKET_COTIZACIONES": "jarvis_cotizaciones",
        "PDFCO_API_KEY": "pdfco", "SUPABASE_SERVICE_ROLE_KEY": "llave",
        "SUPABASE_PROJECT_REF": "abcdefghijklmnopqrst",
    }.items():
        monkeypatch.setenv(variable, valor)
    monkeypatch.delenv("JARVIS_BUCKET_IMAGENES", raising=False)
    monkeypatch.delenv("JARVIS_BUCKET_FICHAS", raising=False)

    consultas = []

    def consultar(sql):
        consultas.append(sql)
        if "List_ProductosIA" in sql:
            return [f for c, f in PRODUCTOS.items() if f"'{c}'" in sql]
        if "codigo = 6177" in sql or "131832334" in sql or "ELIAM" in sql:
            return [CLIENTES[0]]
        if "codigo = 4926" in sql:
            return [CLIENTES[1]]
        if "FERRETERIA" in sql:
            return CLIENTES
        return []

    monkeypatch.setattr(cotizaciones, "_consultar", consultar)
    cotizaciones._borradores.clear()
    return consultas


def _preparar(usuario="admin", **argumentos):
    argumentos.setdefault("productos", json.dumps([{"codigo": "9681", "cantidad": 100}]))
    return herramientas.ejecutar("preparar_cotizacion", json.dumps(argumentos), usuario)


# --- Calculos y borrador ---

def test_los_precios_salen_del_nivel_del_cliente_con_itbis_incluido(catalogo):
    texto = _preparar(cliente="6177", productos=json.dumps([{"codigo": "3790", "cantidad": 2}]))

    borrador = cotizaciones.borrador_de("admin")
    linea = borrador.lineas[0]
    assert linea["precio_unitario"] == 118.0          # P4, no P1
    assert round(linea["precio_bruto"], 2) == 100.0
    assert round(linea["itbis_linea"], 2) == 36.0
    assert borrador.totales == {"subtotal": 200.0, "itbis": 36.0, "total": 236.0}
    assert "aun NO emitido" in texto and "236.00" in texto


def test_el_factor_del_cliente_multiplica_el_precio(catalogo):
    _preparar(cliente="4926", productos=json.dumps([{"codigo": "3790", "cantidad": 1}]))
    assert cotizaciones.borrador_de("admin").lineas[0]["precio_unitario"] == 1650.0   # 1500 * 1.1


def test_de_contado_va_a_p1_sin_buscar_cliente(catalogo):
    _preparar(cliente="Juan Perez", contado="si", ciudad="La Vega",
              productos=json.dumps([{"codigo": "3790", "cantidad": 1}]))
    borrador = cotizaciones.borrador_de("admin")
    assert borrador.lineas[0]["precio_unitario"] == 1614.55
    assert borrador.cliente["nombre"] == "Juan Perez"
    assert borrador.cliente["ciudad"] == "La Vega"
    assert not any("List_ClientesIA" in sql for sql in catalogo)


def test_el_mismo_producto_dos_veces_es_una_linea(catalogo):
    _preparar(cliente="6177", productos=json.dumps([
        {"codigo": "9681", "cantidad": 50}, {"codigo": "9681", "cantidad": 25}]))
    lineas = cotizaciones.borrador_de("admin").lineas
    assert len(lineas) == 1 and lineas[0]["cantidad"] == 75


@pytest.mark.parametrize("argumentos, mensaje", [
    ({"cliente": ""}, "Falta el cliente"),
    ({"cliente": "Nadie Existe"}, "No encontre al cliente"),
    ({"cliente": "FERRETERIA"}, "Hay varios clientes"),
    ({"cliente": "6177", "productos": json.dumps([{"codigo": "0000", "cantidad": 1}])}, "No existen en el catalogo: 0000"),
    ({"cliente": "6177", "productos": json.dumps([{"codigo": "5555", "cantidad": 1}])}, "Sin precio P4"),
    ({"cliente": "6177", "productos": json.dumps([{"codigo": "9681", "cantidad": 0}])}, "Cantidad invalida"),
    ({"cliente": "6177", "productos": json.dumps([{"codigo": "96'81", "cantidad": 1}])}, "Codigo invalido"),
    ({"cliente": "6177", "productos": "no es json"}, "no es JSON"),
])
def test_lo_que_no_cuadra_no_deja_borrador(catalogo, argumentos, mensaje):
    assert mensaje in _preparar(**argumentos)
    assert cotizaciones.borrador_de("admin") is None


def test_el_nombre_del_cliente_no_llega_crudo_al_sql(catalogo):
    _preparar(cliente="ELIAM'; DROP TABLE x --")
    sql = next(s for s in catalogo if "List_ClientesIA" in s)
    assert "'%ELIAM%'" in sql
    assert "DROP" not in sql and ";" not in sql


def test_cada_persona_tiene_su_borrador(catalogo):
    _preparar(usuario="admin", cliente="6177")
    assert cotizaciones.borrador_de("jorge") is None


def test_un_borrador_viejo_ya_no_vale(catalogo, monkeypatch):
    _preparar(cliente="6177")
    cotizaciones._borradores["admin"].creado -= cotizaciones.VIGENCIA_BORRADOR + 1
    assert cotizaciones.borrador_de("admin") is None


# --- Emision ---

@pytest.fixture
def servicios(catalogo, monkeypatch):
    llamadas = {"insertar": [], "actualizar": [], "subir": [], "pdf": []}
    monkeypatch.setattr(cotizaciones, "_insertar", lambda fila: llamadas["insertar"].append(fila) or 7)
    monkeypatch.setattr(cotizaciones, "_actualizar", lambda n, c: llamadas["actualizar"].append((n, c)))
    monkeypatch.setattr(cotizaciones, "_subir", lambda ruta, b: llamadas["subir"].append((ruta, b)))

    def pdf(html, nombre):
        llamadas["pdf"].append((html, nombre))
        return b"%PDF-1.7 prueba"

    monkeypatch.setattr(cotizaciones, "_pdf", pdf)
    monkeypatch.setattr(cotizaciones, "firmar", lambda ruta, s: f"https://firmado/{ruta}?t={s}")
    return llamadas


def test_emitir_numera_genera_el_pdf_y_lo_manda_al_chat(servicios):
    _preparar(cliente="6177", productos=json.dumps([{"codigo": "3790", "cantidad": 2}]))

    texto, adjuntos = herramientas.ejecutar_completo("emitir_cotizacion", "{}", "admin")

    assert "JV-00007" in texto
    assert adjuntos == [{
        "tipo": "cotizacion", "numero": "JV-00007",
        "titulo": "Cotización JV-00007 · FERRETERIA ELIAM MAX EIRL",
        "archivo": "JV-00007.pdf", "url": "https://firmado/JV-00007.pdf?t=86400",
        "enlace": "/api/cotizaciones/JV-00007.pdf", "total": 236.0,
    }]
    fila = servicios["insertar"][0]
    assert fila["estado"] == "generando" and fila["total"] == 236.0
    assert fila["cliente"]["codigo"] == "6177" and fila["productos"][0]["codigo"] == "3790"
    html, _ = servicios["pdf"][0]
    assert "JV-00007" in html and "FERRETERIA ELIAM MAX EIRL" in html and "236.00" in html
    assert servicios["subir"] == [("JV-00007.pdf", b"%PDF-1.7 prueba")]
    assert servicios["actualizar"] == [(7, {"pdf_ruta": "JV-00007.pdf", "estado": "emitida"})]
    # Un segundo "si" no emite otra.
    assert "No hay un borrador" in herramientas.ejecutar("emitir_cotizacion", "{}", "admin")


def test_sin_borrador_no_se_emite_nada(servicios):
    assert "No hay un borrador" in herramientas.ejecutar("emitir_cotizacion", "{}", "admin")
    assert servicios["insertar"] == []


def test_si_falla_el_pdf_queda_marcada_y_el_borrador_vuelve(servicios, monkeypatch):
    _preparar(cliente="6177")

    def falla(html, nombre):
        raise RuntimeError("PDF.co sin creditos")

    monkeypatch.setattr(cotizaciones, "_pdf", falla)
    texto, adjuntos = herramientas.ejecutar_completo("emitir_cotizacion", "{}", "admin")

    assert "PDF.co sin creditos" in texto and adjuntos == []
    assert servicios["actualizar"] == [(7, {"estado": "fallida"})]
    assert cotizaciones.borrador_de("admin") is not None


def test_el_pdf_siempre_dice_camila_y_la_tabla_quien_la_pidio(servicios, monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "x")
    monkeypatch.setenv("JARVIS_PASSWORD_JORGE", "y")
    _preparar(usuario="jorge", cliente="6177")
    herramientas.ejecutar("emitir_cotizacion", "{}", "jorge")
    assert servicios["insertar"][0]["usuario"] == "Jorge"
    html, nombre = servicios["pdf"][0]
    assert 'Usuario: <span class="usuario-value">Camila Reyes</span>' in html
    assert "Jorge" not in html
    assert nombre == "FERRETERIA ELIAM MAX EIRL - JV-00007.pdf"


@pytest.mark.parametrize("cliente, esperado", [
    ("LM AA CONSULTING GROUP LAMA ARMANDO SRL", "LM AA CONSULTING GROUP LAMA ARMANDO SRL - JV-00007.pdf"),
    ('FERRETERIA "EL/SOL": S.R.L.', "FERRETERIA EL SOL S.R.L - JV-00007.pdf"),
    ("", "Cotizacion JV-00007.pdf"),
])
def test_el_nombre_del_archivo_lleva_el_cliente(cliente, esperado):
    assert cotizaciones.nombre_de_archivo(cliente, "JV-00007") == esperado


def test_sin_configurar_no_se_ofrecen(entorno_limpio, monkeypatch):
    monkeypatch.delenv("PDFCO_API_KEY", raising=False)
    nombres = {e["name"] for e in herramientas.esquemas()}
    assert not {"preparar_cotizacion", "emitir_cotizacion"} & nombres


# --- Plantilla ---

def test_la_fecha_sale_como_en_las_de_camila():
    from datetime import datetime

    assert cotizaciones.fecha_de_documento(datetime(2026, 9, 5)) == "05-Sept-2026"
    assert cotizaciones.fecha_de_documento(datetime(2026, 1, 16)) == "16-Jan-2026"


def _linea(i, descripcion="ALAMBRE"):
    return {"codigo": str(i), "referencia": "REF", "descripcion": descripcion, "cantidad": 1,
            "precio_unitario": 118, "itbis_linea": 18, "subtotal_linea": 118}


def test_la_paginacion_es_la_de_n8n():
    # Filas de 76 px: caben 7 en una pagina normal y 4 en la ultima. Lo que
    # sobra de la ultima se pasa entero a una pagina nueva, como en el JS.
    assert [len(b) for b in cotizacion_html.paginar([_linea(i) for i in range(4)])] == [4]
    assert [len(b) for b in cotizacion_html.paginar([_linea(i) for i in range(7)])] == [4, 3]
    assert [len(b) for b in cotizacion_html.paginar([_linea(i) for i in range(12)])] == [7, 4, 1]


def test_la_plantilla_escapa_lo_que_viene_del_catalogo():
    html = cotizacion_html.generar(
        "JV-00001", "16-Sep-2026", {"nombre": "<script>x</script>", "codigo": "1"},
        [_linea(1, 'CABLE 1/2" & <b>')], {"subtotal": 100, "itbis": 18, "total": 118}, "Jorge",
        {"1": "https://img/1.png"},
    )
    assert "<script>x" not in html and "&lt;script&gt;" in html
    assert "1/2&quot; &amp; &lt;b&gt;" in html
    assert 'src="https://img/1.png"' in html
    assert "Page 1 of 1" in html and "Total RD$:</td><td class=\"val\">118.00" in html


# --- Endpoint del PDF ---

def test_el_pdf_solo_se_abre_con_sesion_y_numero_valido(servicios, monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setenv("JARVIS_CLAVE_SECRETA", "clave-de-pruebas-larga")
    cliente = TestClient(app)

    assert cliente.get("/api/cotizaciones/JV-00007.pdf", follow_redirects=False).status_code == 401

    cliente.post("/acceso", data={"clave": "la-del-admin"}, follow_redirects=False)
    respuesta = cliente.get("/api/cotizaciones/JV-00007.pdf", follow_redirects=False)
    assert respuesta.status_code == 302
    assert respuesta.headers["location"] == "https://firmado/JV-00007.pdf?t=300"
    assert cliente.get("/api/cotizaciones/..%2Fotra.pdf", follow_redirects=False).status_code == 404


# --- Cotizar sobre el coste ---

def test_al_coste_se_le_agrega_el_itbis(catalogo):
    # El coste de la base viene sin impuesto y los P con el: sin agregarlo, la
    # cotizacion saldria un 18% por debajo del coste.
    _preparar(cliente="6177", columna_coste="Coste",
              productos=json.dumps([{"codigo": "3790", "cantidad": 1}]))

    linea = cotizaciones.borrador_de("admin").lineas[0]
    assert linea["coste"] == 1000.0
    assert linea["precio_unitario"] == 1180.0
    assert round(linea["precio_bruto"], 2) == 1000.0


def test_el_porcentaje_se_suma_sobre_el_coste(catalogo):
    _preparar(cliente="6177", columna_coste="Coste", recargo="30",
              productos=json.dumps([{"codigo": "3790", "cantidad": 2}]))

    borrador = cotizaciones.borrador_de("admin")
    # 1000 + 30% = 1300, y el ITBIS encima.
    assert borrador.lineas[0]["precio_unitario"] == 1534.0
    assert borrador.totales == {"subtotal": 2600.0, "itbis": 468.0, "total": 3068.0}


def test_el_coste_manda_sobre_el_nivel_y_el_factor_del_cliente(catalogo):
    # El cliente 4926 es P2 con factor 1.1: nada de eso entra en este precio.
    _preparar(cliente="4926", columna_coste="Coste",
              productos=json.dumps([{"codigo": "3790", "cantidad": 1}]))
    assert cotizaciones.borrador_de("admin").lineas[0]["precio_unitario"] == 1180.0


def test_si_el_coste_ya_trae_itbis_no_se_agrega(catalogo, monkeypatch):
    monkeypatch.setenv("JARVIS_COSTE_CON_ITBIS", "true")
    _preparar(cliente="6177", columna_coste="Coste", recargo="30",
              productos=json.dumps([{"codigo": "3790", "cantidad": 1}]))

    linea = cotizaciones.borrador_de("admin").lineas[0]
    assert linea["precio_unitario"] == 1300.0
    assert round(linea["precio_bruto"], 2) == 1101.69


def test_el_borrador_dice_sobre_que_se_calculo(catalogo):
    texto = _preparar(cliente="6177", columna_coste="Coste", recargo="30",
                      productos=json.dumps([{"codigo": "3790", "cantidad": 1}]))

    # Con la cuenta a la vista, un coste que ya trajera ITBIS se nota antes de
    # emitir: el precio saldria mas alto de lo que deberia.
    assert "al coste de 'Coste' mas 30%" in texto
    assert "con ITBIS agregado" in texto
    assert "(coste 1,000.00)" in texto


def test_la_columna_del_coste_no_se_adivina(catalogo):
    texto = _preparar(cliente="6177", columna_coste="CostoPromedio",
                      productos=json.dumps([{"codigo": "3790", "cantidad": 1}]))

    assert "no tiene una columna 'CostoPromedio'" in texto
    assert cotizaciones.borrador_de("admin") is None


def test_un_producto_sin_coste_no_se_cotiza(catalogo):
    texto = _preparar(cliente="6177", columna_coste="Coste",
                      productos=json.dumps([{"codigo": "5555", "cantidad": 1}]))

    assert "Sin coste en 'Coste'" in texto
    assert cotizaciones.borrador_de("admin") is None


@pytest.mark.parametrize("recargo", ["-10", "600", "mucho"])
def test_un_porcentaje_que_no_sirve_no_deja_borrador(catalogo, recargo):
    texto = _preparar(cliente="6177", columna_coste="Coste", recargo=recargo,
                      productos=json.dumps([{"codigo": "3790", "cantidad": 1}]))

    assert "porcentaje sobre el coste" in texto
    assert cotizaciones.borrador_de("admin") is None


def test_sin_columna_de_coste_todo_sigue_como_antes(catalogo):
    _preparar(cliente="6177", productos=json.dumps([{"codigo": "3790", "cantidad": 1}]))
    assert cotizaciones.borrador_de("admin").lineas[0]["precio_unitario"] == 118.0
