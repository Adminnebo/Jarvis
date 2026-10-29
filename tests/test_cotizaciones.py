import json

import pytest
from fastapi.testclient import TestClient

# Arriba del todo por lo mismo que en test_permisos.py: main carga el .env real.
from backend import cotizacion_html, cotizaciones, herramientas, mesa
from backend.main import app

PRODUCTOS = {
    "9681": {"Codigo": "9681", "Referencia": "#12CR", "Descripcion": "KEYARD ALAMBRE THHN #12 ROJO",
             "Und": "PIES      ", "P1": 14.3, "P2": 14.0, "P3": 13.5, "P4": 13.0, "P5": 12.5,
             "P6": 12.0, "P7": 11.5, "TipoItbis": 18, "costo": 10.0},
    "3790": {"Codigo": "3790", "Referencia": "QO240", "Descripcion": "BREAKER 2P 40AMP",
             "Und": "UND", "P1": 1614.55, "P2": 1500, "P3": 1400, "P4": 118.0, "P5": 0,
             "P6": 0, "P7": 0, "TipoItbis": 18, "costo": 100.0},
    "5555": {"Codigo": "5555", "Referencia": "", "Descripcion": "SIN PRECIO", "Und": "UND",
             "P1": 0, "P2": 0, "P3": 0, "P4": 0, "P5": 0, "P6": 0, "P7": 0, "TipoItbis": 18, "costo": 0},
}
CLIENTES = [
    {"codigo": 6177, "nombre": "FERRETERIA ELIAM MAX EIRL", "rnc": "131832334", "direccion": "C/ 1",
     "email": "f@x.com", "telefono1": "8095551234", "Celular": "", "NivelPrecio": "P4", "factor": 1.0},
    {"codigo": 4926, "nombre": "FERRETERIA OTRA", "rnc": "", "direccion": "", "email": None,
     "telefono1": "", "Celular": "809", "NivelPrecio": "P2", "factor": 1.1},
    {"codigo": 7000, "nombre": "FERRETERIA SOLO JV", "rnc": "", "direccion": "", "email": None,
     "telefono1": "", "Celular": "", "NivelPrecio": "P1", "factor": 1.0},
]
# Cotizacion real de JH (vistas iCotizacionesWebIA / dCotizacionesWebIA).
HEADER_JH = {
    "nfactura": 3807, "cliente": 6177, "clientenombre": "FERRETERIA ELIAM MAX EIRL",
    "RNC": "131832334", "Telefono": "8095551234", "Direccion": "C/ 1", "Correo": "f@x.com",
    "Ciudad": "", "Sector": "", "Contacto": "", "fecha": "2026-10-28T10:00:00",
    "total": 28582.40, "confirmada": 1, "pago": 0,
}
DETALLE_JH = [
    {"codigo": "9681", "cantidad": 100.0, "precio": 13.0, "porItbis": 18,
     "Descripcion": "KEYARD ALAMBRE THHN #12 ROJO", "Und": "PIES"},
    {"codigo": "3790", "cantidad": 2.0, "precio": 150.0, "porItbis": 18,
     "Descripcion": "BREAKER 2P 40AMP", "Und": "UND"},
]

# Costo de la ultima compra hasta el dia de la 3807: el breaker costaba menos.
COMPRAS_JH = {"3790": 80.0}
# Lo cotizado antes en JH (lo mas reciente primero). El keyard se suele dar
# entre 13.60 y 14.00; al cliente 6177 se le dio a 13.80. El breaker, una vez.
COTIZADO_ANTES = [
    {"codigo": "9681", "precio": 13.5, "nfactura": 3700, "fecha": "2026-10-20T10:00:00",
     "cliente": "OTRA", "cliente_codigo": 4926},
    {"codigo": "9681", "precio": 13.8, "nfactura": 3650, "fecha": "2026-10-10T10:00:00",
     "cliente": "FERRETERIA ELIAM MAX EIRL", "cliente_codigo": 6177},
    {"codigo": "9681", "precio": 14.2, "nfactura": 3600, "fecha": "2026-09-01T10:00:00",
     "cliente": "OTRA", "cliente_codigo": 4926},
    {"codigo": "9681", "precio": 14.0, "nfactura": 3500, "fecha": "2026-08-01T10:00:00",
     "cliente": "OTRA", "cliente_codigo": 4926},
    {"codigo": "9681", "precio": 13.6, "nfactura": 3400, "fecha": "2026-07-01T10:00:00",
     "cliente": "OTRA", "cliente_codigo": 4926},
    {"codigo": "3790", "precio": 140.0, "nfactura": 3300, "fecha": "2026-06-01T10:00:00",
     "cliente": "OTRA", "cliente_codigo": 4926},
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

    def consultar(sql, limite=60):
        consultas.append(sql)
        if "List_ComprasIA" in sql:                # ultima compra hasta el dia de la cotizacion
            return [{"Codigo": c, "Costo": v} for c, v in COMPRAS_JH.items()
                    if f"'{c}'" in sql and "'2026-10-28'" in sql]
        if "DATEADD(day, -180" in sql:            # a cuanto se ha cotizado (referencias)
            return [r for r in COTIZADO_ANTES if f"'{r['codigo']}'" in sql]
        if "List_ProductosIA" in sql:
            return [f for c, f in PRODUCTOS.items() if f"'{c}'" in sql]
        if "iCotizacionesWebIA" in sql:            # cabecera de JH
            if "nfactura = 3807" in sql or "cliente = 6177" in sql:
                return [HEADER_JH]
            if "WHERE" not in sql:                 # la ultima en general de JH
                return [HEADER_JH]
            return []
        if "dCotizacionesWebIA" in sql:            # lineas de JH
            return DETALLE_JH if "nfactura = 3807" in sql else []
        if "codigo = 6177" in sql or "131832334" in sql or "ELIAM" in sql:
            return [CLIENTES[0]]
        if "codigo = 4926" in sql:
            return [CLIENTES[1]]
        if "codigo = 7000" in sql:
            return [CLIENTES[2]]
        if "FERRETERIA" in sql:
            return CLIENTES
        return []

    monkeypatch.setattr(cotizaciones, "_consultar", consultar)
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


def test_un_borrador_sin_usar_dos_horas_ya_no_vale(catalogo):
    _preparar(cliente="6177")
    mesa.envejecer("admin", mesa.VIGENCIA - 60)
    assert cotizaciones.borrador_de("admin") is not None
    mesa.envejecer("admin", 120)
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
    assert "No hay ninguna cotizacion sin emitir" in herramientas.ejecutar("emitir_cotizacion", "{}", "admin")


def test_sin_borrador_no_se_emite_nada(servicios):
    assert "No hay ninguna cotizacion sin emitir" in herramientas.ejecutar("emitir_cotizacion", "{}", "admin")
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
    monkeypatch.delenv("JARVIS_PDF_KEY", raising=False)
    monkeypatch.delenv("PDFCO_API_KEY", raising=False)
    nombres = {e["name"] for e in herramientas.esquemas()}
    assert not {"preparar_cotizacion", "emitir_cotizacion", "buscar_cotizacion",
                "crear_variantes", "ajustar_precios", "analizar_cotizacion"} & nombres


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


# --- Cotizar al costo ---

def test_el_costo_ya_trae_el_itbis_y_no_se_le_agrega(catalogo):
    # Es una columna de precio mas, como los P1..P7: el bruto se despeja.
    _preparar(cliente="6177", al_costo="si",
              productos=json.dumps([{"codigo": "3790", "cantidad": 1}]))

    linea = cotizaciones.borrador_de("admin").lineas[0]
    assert linea["coste"] == 100.0
    assert linea["precio_unitario"] == 100.0
    assert round(linea["precio_bruto"], 2) == 84.75


def test_el_margen_al_costo_es_sobre_el_costo(catalogo):
    _preparar(cliente="6177", al_costo="si", margen="30",
              productos=json.dumps([{"codigo": "3790", "cantidad": 2}]))

    borrador = cotizaciones.borrador_de("admin")
    # Igual que las variantes: 100 con 30% sale a 130, no a 142.86.
    assert borrador.lineas[0]["precio_unitario"] == 130.0
    assert borrador.lineas[0]["ajuste"] == "costo + 30%"
    assert borrador.totales["total"] == 260.0


def test_el_costo_manda_sobre_el_nivel_y_el_factor_del_cliente(catalogo):
    # El cliente 4926 es P2 con factor 1.1: nada de eso entra en este precio.
    _preparar(cliente="4926", al_costo="si",
              productos=json.dumps([{"codigo": "3790", "cantidad": 1}]))
    assert cotizaciones.borrador_de("admin").lineas[0]["precio_unitario"] == 100.0


def test_el_borrador_dice_sobre_que_se_calculo(catalogo):
    texto = _preparar(cliente="6177", al_costo="si", margen="30",
                      productos=json.dumps([{"codigo": "3790", "cantidad": 1}]))

    assert "al costo + 30% sobre el costo" in texto
    assert "ITBIS incluido" in texto
    assert "(costo 100.00)" in texto


def test_un_producto_sin_costo_no_se_cotiza(catalogo):
    texto = _preparar(cliente="6177", al_costo="si",
                      productos=json.dumps([{"codigo": "5555", "cantidad": 1}]))

    assert "Sin costo en el catalogo" in texto
    assert cotizaciones.borrador_de("admin") is None


@pytest.mark.parametrize("margen", ["-10", "5000", "mucho"])
def test_un_margen_que_no_sirve_no_deja_borrador(catalogo, margen):
    texto = _preparar(cliente="6177", al_costo="si", margen=margen,
                      productos=json.dumps([{"codigo": "3790", "cantidad": 1}]))

    assert "margen" in texto
    assert cotizaciones.borrador_de("admin") is None


def test_un_margen_de_mas_de_100_si_vale(catalogo):
    # Sobre el costo, 150% es posible: 100 sale a 250.
    _preparar(cliente="6177", al_costo="si", margen="150",
              productos=json.dumps([{"codigo": "3790", "cantidad": 1}]))
    assert cotizaciones.borrador_de("admin").lineas[0]["precio_unitario"] == 250.0


def test_sin_al_costo_todo_sigue_como_antes(catalogo):
    _preparar(cliente="6177", margen="30",
              productos=json.dumps([{"codigo": "3790", "cantidad": 1}]))
    assert cotizaciones.borrador_de("admin").lineas[0]["precio_unitario"] == 118.0


# --------------------------------------------------------------------------
# Un RNC dictado en voz llega con una cifra mal
# --------------------------------------------------------------------------

def test_un_rnc_con_una_cifra_de_mas_no_se_busca_como_nombre(catalogo):
    # Doce cifras: antes no parecia un RNC y se buscaba como nombre, sin exito.
    assert cotizaciones.cifras_de_rnc("402-21599556-0") == "402215995560"
    assert cotizaciones.cifras_de_rnc("FERRETERIA ELIAM") is None
    assert cotizaciones.cifras_de_rnc("6177") is None        # eso es un codigo


def test_a_una_cifra_cubre_los_errores_de_dictado():
    variantes = cotizaciones.a_una_cifra_de("1318323334")       # sobra un 3
    assert "131832334" in variantes
    assert "131832334" in cotizaciones.a_una_cifra_de("131832834")   # una cambiada
    assert "131832334" in cotizaciones.a_una_cifra_de("13183234")    # falta una
    assert "131832334" in cotizaciones.a_una_cifra_de("131823334")   # dos al reves
    assert all(len(v) in (9, 10, 11) and v.isdigit() for v in variantes)


def test_un_rnc_mal_oido_ofrece_al_cliente_que_esta_a_una_cifra(catalogo):
    respuesta = _preparar(cliente="1318323334")

    assert "No hay ningun cliente con el RNC 1 3 1 8 3 2 3 3 3 4" in respuesta
    assert "FERRETERIA ELIAM MAX EIRL (RNC 1 3 1 8 3 2 3 3 4, codigo 6177)" in respuesta
    assert "cifra por cifra" in respuesta
    assert "No cotices hasta que lo confirme" in respuesta
    assert cotizaciones.borrador_de("admin") is None


def test_un_rnc_que_no_se_parece_a_ninguno_manda_a_repetirlo(catalogo):
    respuesta = _preparar(cliente="999-99999-9")

    assert "No hay ningun cliente con el RNC 9 9 9 9 9 9 9 9 9" in respuesta
    assert "pregunta si lo entendiste bien, o si va de contado" in respuesta


def test_el_rnc_exacto_sigue_entrando_directo(catalogo):
    assert "FERRETERIA ELIAM MAX EIRL" in _preparar(cliente="1-31-83233-4")


# --- Recotizar desde una cotizacion existente ---

def test_calcular_linea_nivel_elegido_sin_factor_con_utilidad(catalogo):
    fila = PRODUCTOS["9681"]
    # P7 pelado, sin factor: 11.5 tal cual
    linea = cotizaciones.calcular_linea(fila, 100, "P7", 1.0)
    assert linea["precio_unitario"] == 11.5
    # P5 (12.5) con 6% de utilidad: 12.5 / (1 - 0.06) = 13.2978 -> 13.30
    con_util = cotizaciones.calcular_linea(fila, 100, "P5", 1.0, utilidad_nivel=6)
    assert con_util["precio_unitario"] == 13.30


def test_leer_utilidad_valida_el_rango():
    assert cotizaciones._leer_utilidad("6") == 6.0
    assert cotizaciones._leer_utilidad("") == 0.0
    with pytest.raises(cotizaciones.ErrorCotizacion):
        cotizaciones._leer_utilidad("99")      # > MAX_UTILIDAD
    with pytest.raises(cotizaciones.ErrorCotizacion):
        cotizaciones._leer_utilidad("abc")


def test_encontrada_se_guarda_y_vence(emitidas):
    _buscar("la 3807")
    assert cotizaciones.encontrada_de("admin").numero == "3807"
    mesa.envejecer("admin", mesa.VIGENCIA + 1)
    assert cotizaciones.encontrada_de("admin") is None


FILA_EMITIDA = {
    "numero": 12, "creada_at": "2026-10-20T14:00:00+00:00", "total": 1150.0,
    "cliente": {"codigo": "6177", "nombre": "FERRETERIA ELIAM MAX EIRL",
                "rnc": "131832334", "nivel": "P4", "factor": 1.0},
    "productos": [{"codigo": "9681", "descripcion": "KEYARD ALAMBRE THHN #12 ROJO",
                   "unidad": "PIES", "cantidad": 100, "precio_unitario": 13.0}],
}
# Una JV de un cliente que NO tiene nada en JH (cliente 7000), para el camino
# en que la busqueda por cliente devuelve solo la de Jarvis.
FILA_JV_SOLO = {
    "numero": 11, "creada_at": "2026-10-19T09:00:00+00:00", "total": 1150.0,
    "cliente": {"codigo": "7000", "nombre": "FERRETERIA SOLO JV", "rnc": "",
                "nivel": "P1", "factor": 1.0},
    "productos": [{"codigo": "9681", "descripcion": "KEYARD ALAMBRE THHN #12 ROJO",
                   "unidad": "PIES", "cantidad": 100, "precio_unitario": 13.0}],
}


@pytest.fixture
def emitidas(catalogo, monkeypatch):

    def filas(params):
        if "numero" in params:
            return [FILA_EMITIDA] if params["numero"] == "eq.12" else []
        if params.get("cliente->>codigo") == "eq.6177":
            return [FILA_EMITIDA]
        if params.get("cliente->>codigo") == "eq.7000":
            return [FILA_JV_SOLO]
        if set(params) <= {"estado", "order", "limit", "select"}:   # la ultima JV en general
            return [FILA_EMITIDA]
        if "cliente->>nombre" in params:
            return [FILA_EMITIDA] if "ELIAM" in params["cliente->>nombre"].upper() else []
        return []

    monkeypatch.setattr(cotizaciones, "_filas_emitidas", filas)


def _buscar(consulta, usuario="admin"):
    return herramientas.ejecutar("buscar_cotizacion", json.dumps({"consulta": consulta}), usuario)


def test_busca_por_codigo_solo_jv_la_guarda(emitidas):
    # 7000 solo tiene JV: la trae directo y la guarda.
    texto = _buscar("7000")
    assert "JV-00011" in texto and "KEYARD" in texto
    enc = cotizaciones.encontrada_de("admin")
    assert enc.numero == "JV-00011" and enc.fuente == "jv"


def test_busca_por_numero_jv_la_guarda(emitidas):
    assert "JV-00012" in _buscar("la JV-12")
    enc = cotizaciones.encontrada_de("admin")
    assert enc.numero == "JV-00012" and enc.fuente == "jv"


def test_busca_por_rnc_resuelve_el_cliente(emitidas):
    # RNC -> cliente 6177, que tiene en ambas fuentes: pide elegir.
    texto = _buscar("131832334")
    assert "3807" in texto and "JV-00012" in texto


def test_varios_clientes_pide_elegir(emitidas):
    texto = _buscar("FERRETERIA")
    assert "varios clientes" in texto.lower()
    assert cotizaciones.encontrada_de("admin") is None


def test_sin_cotizaciones_lo_dice(emitidas):
    assert "No encontr" in _buscar("4926")   # cliente existe pero sin cotizaciones


def _recotizar(nivel, utilidad="", usuario="admin"):
    # Lo que antes era recotizar ahora es una variante "a nivel".
    variante = {"base": "nivel", "nivel": nivel, "utilidad": utilidad}
    return herramientas.ejecutar(
        "crear_variantes", json.dumps({"variantes": json.dumps([variante])}), usuario
    )


def test_recotizar_usa_el_nivel_sin_factor(emitidas):
    _buscar("7000")
    texto = _recotizar("7")
    borrador = cotizaciones.borrador_de("admin")
    assert borrador.lineas[0]["precio_unitario"] == 11.5     # P7 crudo, sin factor
    assert borrador.totales["total"] == 1150.0
    assert "sin emitir" in texto and "'P7'" in texto


def test_recotizar_con_utilidad(emitidas):
    _buscar("7000")
    _recotizar("5", "6")
    borrador = cotizaciones.borrador_de("admin")
    assert borrador.lineas[0]["precio_unitario"] == 13.30    # P5=12.5 / 0.94


def test_recotizar_sin_encontrada_lo_dice(emitidas):
    assert "usca" in _recotizar("7")


def test_recotizar_nivel_invalido(emitidas):
    _buscar("7000")
    assert "P1 a P7" in _recotizar("banana")


def test_recotizar_nomenclatura_jh(emitidas):
    # "55" = nivel P5 con 5% de utilidad: 12.5 / 0.95 = 13.16
    _buscar("7000")
    _recotizar("55")
    assert cotizaciones.borrador_de("admin").lineas[0]["precio_unitario"] == 13.16
    # "550" = nivel P5 con 50% de utilidad: 12.5 / 0.5 = 25.0
    _buscar("7000")
    _recotizar("550")
    assert cotizaciones.borrador_de("admin").lineas[0]["precio_unitario"] == 25.0
    # "47" = nivel P4 con 7%: 13.0 / 0.93 = 13.98
    _buscar("7000")
    _recotizar("47")
    assert cotizaciones.borrador_de("admin").lineas[0]["precio_unitario"] == 13.98


def test_recotizar_nomenclatura_nivel_fuera_de_rango(emitidas):
    _buscar("7000")
    assert "1 a 7" in _recotizar("80")       # 8 no es un nivel


@pytest.fixture
def servicios_y_emitidas(servicios, emitidas):
    return servicios


def test_recotizar_y_emitir_saca_una_jv_nueva(servicios_y_emitidas):
    _buscar("7000")
    _recotizar("7")
    texto, adjuntos = herramientas.ejecutar_completo("emitir_cotizacion", "{}", "admin")
    assert "JV-00007" in texto                      # _insertar mock devuelve 7
    fila = servicios_y_emitidas["insertar"][0]
    assert fila["cliente"]["codigo"] == "7000"
    assert fila["productos"][0]["codigo"] == "9681"
    assert fila["productos"][0]["precio_unitario"] == 11.5   # el nivel P7 recotizado
    assert fila["total"] == 1150.0
    assert adjuntos[0]["numero"] == "JV-00007"


# --- Cotizaciones reales de JH ---

def test_busca_cotizacion_jh_por_numero(emitidas):
    texto = _buscar("la 3807")
    assert "3807" in texto and "FERRETERIA ELIAM MAX EIRL" in texto
    encontrada = cotizaciones.encontrada_de("admin")
    assert encontrada.fuente == "jh"
    assert encontrada.productos[0]["codigo"] == "9681"


def test_busca_por_cliente_con_ambas_pregunta(emitidas):
    # 6177 tiene JV (FILA_EMITIDA) y JH (HEADER_JH): debe pedir elegir.
    texto = _buscar("6177")
    assert "3807" in texto and "JV-00012" in texto
    assert cotizaciones.encontrada_de("admin") is None


def test_busca_ultima_en_general(emitidas):
    # "en general" = la real de JH (3807), aunque haya una JV; se menciona la JV.
    texto = _buscar("la última cotización en general")
    assert "3807" in texto and "JH" in texto and "JV-00012" in texto
    enc = cotizaciones.encontrada_de("admin")
    assert enc.fuente == "jh" and enc.numero == "3807"


def test_archivo_para_envio_de_jh_genera_el_pdf(servicios_y_emitidas):
    # Mandar la 3807 de JH: genera el PDF tal cual (precios reales) y lo sube.
    datos = cotizaciones.archivo_para_envio("3807")
    assert datos == {"referencia": "3807", "titulo": "FERRETERIA ELIAM MAX EIRL",
                     "ruta": "jh-3807.pdf"}
    assert servicios_y_emitidas["subir"][0][0] == "jh-3807.pdf"
    html, _ = servicios_y_emitidas["pdf"][0]
    assert "3807" in html and "FERRETERIA ELIAM MAX EIRL" in html


def test_recotizar_desde_jh_emite_jv(servicios_y_emitidas):
    _buscar("la 3807")                       # cotizacion de JH
    _recotizar("2")                          # el breaker no tiene P5..P7
    texto, adjuntos = herramientas.ejecutar_completo("emitir_cotizacion", "{}", "admin")
    assert "JV-00007" in texto               # la nueva es JV, no toca la 3807
    fila = servicios_y_emitidas["insertar"][0]
    assert fila["cliente"]["nombre"] == "FERRETERIA ELIAM MAX EIRL"
    assert fila["productos"][0]["codigo"] == "9681"
    assert fila["productos"][0]["precio_unitario"] == 14.0   # P2 del keyard


# --- Mesa: variantes, ajustes y margenes (todo sobre el costo) ---
# La 3807 de JH: 100 KEYARD a 13 (costo 10, 30%) y 2 BREAKER a 150 (costo 100,
# 50%). General: costo 1200, venta 1600 -> 33.3%.

def _herr(nombre, usuario="admin", **argumentos):
    return herramientas.ejecutar(nombre, json.dumps(argumentos), usuario)


def _variantes(*pedidos):
    return _herr("crear_variantes", variantes=json.dumps(list(pedidos)))


def test_jalar_una_cotizacion_dice_sus_margenes(emitidas):
    texto = _buscar("jálame la cotización 3807 y dime qué tiene")
    assert "Cotizacion 3807" in texto
    assert "1. 100 PIES de KEYARD ALAMBRE THHN #12 ROJO" in texto and "margen 30.0%" in texto
    assert "2. 2 UND de BREAKER 2P 40AMP" in texto and "margen 50.0%" in texto
    assert "Margen general: 33.3% sobre el costo" in texto


def test_el_pedido_del_audio_dos_variantes_y_la_original_sigue(servicios_y_emitidas):
    _buscar("3807")
    texto = _variantes({"base": "costo"}, {"base": "costo", "margen": 50})
    assert "'a costo'" in texto and "'costo + 50%'" in texto
    assert "margen general 0.0%" in texto and "margen general 50.0%" in texto
    assert servicios_y_emitidas["insertar"] == []           # nada emitido sin el si

    texto, adjuntos = herramientas.ejecutar_completo(
        "emitir_cotizacion", json.dumps({"cuales": "todas"}), "admin")
    assert len(adjuntos) == 2 and all("variante" not in a for a in adjuntos)
    a_costo, con_50 = servicios_y_emitidas["insertar"]
    assert [l["precio_unitario"] for l in a_costo["productos"]] == [10.0, 100.0]
    assert [l["precio_unitario"] for l in con_50["productos"]] == [15.0, 150.0]   # 100 -> 150
    linea = con_50["productos"][0]
    assert linea["costo"] == 10.0 and linea["margen"] == pytest.approx(50)
    assert "niveles" not in linea
    assert con_50["cliente"]["cotizacion_origen"] == "3807"
    assert cotizaciones.borrador_de("admin") is None
    for html, _ in servicios_y_emitidas["pdf"]:
        assert "costo" not in html.lower()                  # el PDF no muestra costos

    # "Y el producto X en la 3807, cual es mi margen overall?"
    texto = _herr("analizar_cotizacion", cotizacion="la 3807", producto="keyard")
    assert "margen 30.0%" in texto and "Margen general: 33.3%" in texto


def test_ajustar_la_original_ajusta_una_copia_y_avisa_sin_bloquear(emitidas):
    _buscar("3807")
    texto = _herr("ajustar_precios", piso="25", cambios=json.dumps([
        {"linea": "1", "precio": 9}, {"linea": "breaker", "margen": 20}]))
    assert "'ajustada'" in texto
    assert "RD$ 13.00 -> RD$ 9.00" in texto and "A PERDIDA" in texto
    assert "RD$ 150.00 -> RD$ 120.00" in texto
    # Venta 900 + 240 contra costo 1200.
    assert "33.3% -> -5.0%" in texto and "ROMPE EL PISO de 25%" in texto
    # Con el breaker a 120 (gana 40), el keyard tiene que ganar 260 en 100: 12.60.
    assert "lo mas bajo seria RD$ 12.60" in texto
    assert cotizaciones.encontrada_de("admin").productos[0]["precio_unitario"] == 13.0
    borrador = cotizaciones.borrador_de("admin")
    assert borrador.nombre == "ajustada" and borrador.lineas[0]["precio_unitario"] == 9.0


def test_volver_al_precio_original(emitidas):
    _buscar("3807")
    _herr("ajustar_precios", cambios=json.dumps([{"linea": "1", "precio": 9}]))
    texto = _herr("ajustar_precios", cambios=json.dumps([{"linea": "1", "original": "si"}]))
    assert "RD$ 9.00 -> RD$ 13.00" in texto


def test_hasta_donde_puedo_bajar_sin_romper_el_piso(emitidas):
    _buscar("3807")
    texto = _herr("analizar_cotizacion", producto="1", piso="25")
    # Hace falta ganar 300; el breaker gana 100 -> 100(p - 10) >= 200.
    assert "lo mas bajo que se puede dejar es RD$ 12.00" in texto


def test_se_nombra_la_variante_por_lo_que_la_distingue(emitidas):
    _buscar("3807")
    _variantes({"base": "costo"}, {"base": "costo", "margen": 50})
    assert "'costo + 50%'" in _herr("analizar_cotizacion", cotizacion="la del 50")
    assert "'a costo'" in _herr("analizar_cotizacion", cotizacion="la de costo")
    assert "(original)" in _herr("analizar_cotizacion", cotizacion="la original")
    _variantes({"base": "nivel", "nivel": "150"})       # P1 + 50%
    assert "Pregunta cual" in _herr("analizar_cotizacion", cotizacion="la del 50")
    assert "No hay una cotizacion" in _herr("analizar_cotizacion", cotizacion="la del 80")


def test_comparar_todas(emitidas):
    _buscar("3807")
    _variantes({"base": "costo"}, {"base": "costo", "margen": 50})
    texto = _herr("analizar_cotizacion", cotizacion="todas")
    assert "original 3807" in texto and "a costo" in texto and "costo + 50%" in texto


def test_producto_que_no_esta_en_la_cotizacion(emitidas):
    _buscar("3807")
    assert "No hay un producto" in _herr("analizar_cotizacion", producto="tubo pvc")


def test_buscar_otra_reemplaza_la_mesa_y_avisa(emitidas):
    _buscar("3807")
    _variantes({"base": "costo"})
    texto = _buscar("JV-12")
    assert "Se descartaron" in texto and "a costo" in texto
    assert cotizaciones.borrador_de("admin") is None
    assert cotizaciones.encontrada_de("admin").numero == "JV-00012"


def test_una_cotizacion_que_no_existe_lo_dice(emitidas):
    assert "No existe la cotizacion 1000" in _buscar("la 1000")
    # La 7000 no es cotizacion, pero 7000 si es un cliente: trae la suya y avisa.
    texto = _buscar("la 7000")
    assert "La cotizacion 7000 no existe en JH" in texto and "JV-00011" in texto
    # Si pidieron el cliente, el aviso sobra.
    assert "no existe" not in _buscar("la del cliente 7000")


# --- Margen de cuando se cotizo contra el de hoy ---
# En la 3807 (28-oct) el breaker costaba 80 (ultima compra), hoy 100. El keyard
# no tiene compra anterior: va con el de hoy. Entonces: costo 1000 + 160 = 1160
# contra venta 1600 -> 37.9%. Hoy: 33.3%.

def test_una_vieja_da_el_margen_de_entonces_y_el_de_hoy(emitidas, catalogo):
    texto = _buscar("3807")
    assert "CUANDO SE COTIZO dejaba 37.9% sobre el costo" in texto
    assert "si se repite igual HOY deja 33.3%" in texto
    assert "1 producto(s) sin costo de esa fecha van con el de hoy" in texto
    assert "(al cotizar: costo 80.00, margen 87.5%)" in texto
    # Solo una consulta de compras, con los que no tienen costo guardado.
    compras = [s for s in catalogo if "List_ComprasIA" in s]
    assert len(compras) == 1 and "'2026-10-28'" in compras[0]


def test_analizar_la_original_da_los_dos(emitidas):
    _buscar("3807")
    texto = _herr("analizar_cotizacion", cotizacion="la 3807", producto="breaker")
    assert "Margen general: 33.3%" in texto and "CUANDO SE COTIZO dejaba 37.9%" in texto
    assert "Cuando se cotizo: costo 80.00, margen 87.5%" in texto
    assert "CUANDO SE COTIZO dejaba 37.9%" in _herr("analizar_cotizacion", cotizacion="todas")


def test_las_variantes_van_con_el_costo_de_hoy(emitidas):
    _buscar("3807")
    _variantes({"base": "costo", "margen": 50})
    assert all("costo_cotizado" not in l for l in cotizaciones.borrador_de("admin").lineas)
    texto = _herr("analizar_cotizacion", cotizacion="la del 50")
    assert "CUANDO SE COTIZO" not in texto and "al cotizar" not in texto


def test_una_jv_usa_el_costo_que_guardo(emitidas, monkeypatch):
    fila = {**FILA_EMITIDA, "productos": [{**FILA_EMITIDA["productos"][0], "costo": 8.0}]}
    monkeypatch.setattr(cotizaciones, "_filas_emitidas", lambda params: [fila])
    texto = _buscar("JV-12")
    # Venta 1300 contra costo guardado 800 -> 62.5%; hoy 1000 -> 30%.
    assert "CUANDO SE COTIZO dejaba 62.5%" in texto and "HOY deja 30.0%" in texto


def test_si_el_costo_no_cambio_lo_dice_en_una(emitidas):
    texto = _buscar("JV-12")      # sin costo guardado ni compras: solo el de hoy
    assert "solo se puede decir el margen con el costo de hoy" in texto
    assert "CUANDO SE COTIZO" not in texto


# --- La mesa en pantalla ---

@pytest.fixture
def web(emitidas, monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setenv("JARVIS_CLAVE_SECRETA", "clave-de-pruebas-larga")
    cliente = TestClient(app)
    assert cliente.get("/api/mesa").status_code == 401
    cliente.post("/acceso", data={"clave": "la-del-admin"}, follow_redirects=False)
    return cliente


def test_la_tabla_trae_la_original_y_las_variantes(web):
    assert web.get("/api/mesa").json()["cotizaciones"] == []
    _buscar("3807")
    _variantes({"base": "costo", "margen": 50})
    vista = web.get("/api/mesa").json()
    original, variante = vista["cotizaciones"]
    assert original["id"] == "original" and original["original"]
    assert round(original["margen"], 1) == 33.3 and round(original["margen_cotizado"], 1) == 37.9
    breaker = original["lineas"][1]
    assert breaker["costo"] == 100.0 and breaker["costo_cotizado"] == 80.0
    assert round(breaker["margen_cotizado"], 1) == 87.5
    assert variante["id"] == "costo + 50%" and variante["margen_cotizado"] is None
    assert vista["activa"] == "costo + 50%"


def test_un_precio_cambiado_a_mano(web):
    _buscar("3807")
    web.post("/api/mesa/elegir", json={"piso": "25"})
    respuesta = web.post("/api/mesa/precio", json={"cotizacion": "original", "linea": 1, "precio": "9"})
    datos = respuesta.json()
    # La original no se toca: se cambia una copia, que queda activa.
    assert "'ajustada'" in datos["nota"] and "ROMPE EL PISO" in datos["nota"]
    assert datos["nota"].startswith("Cambio hecho a mano") and "Di el producto" not in datos["nota"]
    assert datos["corto"] == ("Cambie a mano en la tabla «ajustada»: producto 1 (KEYARD ALAMBRE "
                              "THHN #12 ROJO) de RD$ 13.00 a RD$ 9.00. Margen general 33.3% -> 0.0%.")
    vista = datos["vista"]
    assert vista["activa"] == "ajustada"
    ajustada = vista["cotizaciones"][1]
    assert ajustada["lineas"][0]["precio"] == 9.0 and ajustada["rompe_piso"]
    assert vista["cotizaciones"][0]["lineas"][0]["precio"] == 13.0
    assert web.post("/api/mesa/precio", json={"cotizacion": "original", "linea": 9,
                                               "precio": "1"}).status_code == 400


def test_la_pestana_elegida_es_con_la_que_se_trabaja(web):
    _buscar("3807")
    _variantes({"base": "costo"}, {"base": "costo", "margen": 50})
    assert web.post("/api/mesa/elegir", json={"cotizacion": "a costo"}).json()["activa"] == "a costo"
    assert cotizaciones.borrador_de("admin").nombre == "a costo"


def test_las_herramientas_de_la_mesa_avisan_a_la_web(web):
    respuesta = web.post("/api/herramienta", json={"nombre": "buscar_cotizacion",
                                                   "argumentos": json.dumps({"consulta": "3807"})})
    assert respuesta.json()["mesa"] is True
    respuesta = web.post("/api/herramienta", json={"nombre": "recordar", "argumentos": "{}"})
    assert respuesta.json()["mesa"] is False


# --- A cuanto se ha cotizado ---

def test_al_traerla_dice_lo_que_se_le_dio_antes_al_cliente(emitidas, catalogo):
    texto = _buscar("3807")
    # 13.00 esta bajo lo que se suele cotizar (13.60-14.00), pero el 6177 es P4 y
    # 13.00 es su precio de lista: no es una alarma.
    assert "producto 1 a 13.00: a este cliente se le dio a 13.80 el 10-Oct-2026 (la 3650)" in texto
    assert "POR DEBAJO" not in texto
    assert "producto 2" not in texto.split("CONTRA LO COTIZADO ANTES")[1]
    (sql,) = [s for s in catalogo if "DATEADD(day, -180" in s]
    assert "d.nfactura <> 3807" in sql            # la misma no es referencia de si misma


def test_la_tabla_trae_la_referencia(web):
    _buscar("3807")
    keyard, breaker = web.get("/api/mesa").json()["cotizaciones"][0]["lineas"]
    ref = keyard["referencia"]
    assert not ref["bajo"] and ref["p25"] == 13.6 and ref["p75"] == 14.0
    assert ref["al_cliente"]["precio"] == 13.8
    assert breaker["referencia"]["p25"] is None and not breaker["referencia"]["bajo"]


def test_ajustar_avisa_solo_de_lo_que_cambio(emitidas):
    _buscar("3807")
    texto = _herr("ajustar_precios", cambios=json.dumps([{"linea": "2", "precio": 120}]))
    assert "CONTRA LO COTIZADO ANTES" not in texto       # el 2 no tiene "normal" (1 vez)
    texto = _herr("ajustar_precios", cambios=json.dumps([{"linea": "1", "precio": 12}]))
    assert ("producto 1 a 12.00: POR DEBAJO DE LO NORMAL (se suele cotizar entre 13.60 y 14.00; "
            "su precio de lista P4 es 13.00)") in texto
    texto = _herr("ajustar_precios", cambios=json.dumps([{"linea": "1", "precio": 13.8}]))
    assert "CONTRA LO COTIZADO ANTES" not in texto       # normal y lo mismo que al cliente


def test_analizar_un_producto_da_su_referencia(emitidas):
    _buscar("3807")
    texto = _herr("analizar_cotizacion", producto="keyard")
    assert "Contra lo cotizado antes: se suele cotizar entre 13.60 y 14.00 (mediana 13.80" in texto
    assert "POR DEBAJO" not in texto and "mas bajo" not in texto      # es su lista P4
    _herr("ajustar_precios", cambios=json.dumps([{"linea": "1", "precio": 12}]))
    assert "ESTA POR DEBAJO DE LO NORMAL" in _herr("analizar_cotizacion", producto="keyard")


def test_precios_dados(catalogo):
    texto = herramientas.ejecutar("precios_dados", json.dumps(
        {"producto": "9681", "cliente": "6177"}), "admin")
    assert "se suele cotizar entre 13.60 y 14.00" in texto
    assert "a este cliente, la ultima vez a 13.80 (10-Oct-2026, la 3650)" in texto
    assert "La mas reciente: 13.50 a OTRA" in texto
    assert "Precios de lista hoy: P1 14.30" in texto
    texto = herramientas.ejecutar("precios_dados", json.dumps({"producto": "3790"}), "admin")
    assert "se cotizo 1 vez, a: 140.00" in texto


def test_si_la_referencia_falla_la_cotizacion_sigue(emitidas, monkeypatch):
    from backend import historial

    def falla(*_):
        raise RuntimeError("base caida")
    monkeypatch.setattr(historial, "referencias", falla)
    texto = _buscar("3807")
    assert "Cotizacion 3807" in texto and "CONTRA LO COTIZADO" not in texto
