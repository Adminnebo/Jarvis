"""Buscar como suena: en voz, 'trooper' es TRUPER y 'cascos' es CASCO."""

import pytest

from backend import fuentes

DESCRIPCIONES = [
    "TRUPER CASCO PROTECTOR BLANCO", "TRUPER CASCO PROTECTOR AMARILLO",
    "MAKITA TALADRO 1/2", "STANLEY MARTILLO UÑA", "SG TIANDY CAMARA IP BULLET 4MP",
    "TECLADO USB", "KEYARD ALAMBRE THHN #12 ROJO", "BOSCH BROCA 6.0MM",
]


@pytest.fixture
def vocabulario():
    return fuentes.armar_vocabulario(DESCRIPCIONES)


@pytest.mark.parametrize("dicho, escrito", [
    ("trooper", "truper"), ("maquita", "makita"), ("estanli", "stanley"),
    ("tiandi", "tiandy"), ("cascos", "casco"), ("amarilla", "amarillo"),
    ("taladros", "taladro"), ("bosh", "bosch"),
])
def test_lo_mal_oido_encuentra_su_palabra(vocabulario, dicho, escrito):
    assert fuentes.parecidas_de_oido(dicho, vocabulario) == [escrito]


@pytest.mark.parametrize("termino", [
    "casco",        # ya esta: se busca como siempre
    "alam",         # un trozo de una palabra que esta tambien vale
    "inversor",     # no esta ni se parece a nada: no se inventa
    "6.0mm", "12",  # las medidas no se corrigen de oido
    "usb",          # demasiado corta para adivinar
])
def test_lo_que_no_hay_que_tocar_no_se_toca(vocabulario, termino):
    assert fuentes.parecidas_de_oido(termino, vocabulario) == []


def test_una_palabra_corta_no_salta_a_otra_distinta(vocabulario):
    # Con seis letras solo se perdona una: 'teclas' queda a dos de TECLADO y
    # 'rosca' a dos de BROCA, y ninguna de las dos es la otra.
    assert fuentes.parecidas_de_oido("teclas", vocabulario) == []
    assert fuentes.parecidas_de_oido("rosca", vocabulario) == []


def test_suena_igual_gana_a_casi_igual():
    vocabulario = fuentes.armar_vocabulario(["TRUPER PALA", "TRUPEX GUANTE", "TRUPEX LENTE"])
    assert fuentes.parecidas_de_oido("trooper", vocabulario) == ["truper"]


@pytest.fixture
def catalogo(monkeypatch):
    consultas = []

    def motor(config, sql, limite, id_fuente=None):
        consultas.append(sql)
        if sql.startswith("select Descripcion from"):
            return [{"Descripcion": d} for d in DESCRIPCIONES]
        return []

    monkeypatch.setattr(fuentes, "obtener", lambda id_fuente: {"tipo": "mssql", "config": {}})
    monkeypatch.setattr(fuentes, "columnas_de_texto",
                        lambda id_fuente, tabla: ("Productos", ["Codigo", "Descripcion"]))
    monkeypatch.setattr(fuentes, "contar_filas", lambda id_fuente, tabla: 8)
    monkeypatch.setitem(fuentes.MOTORES, "mssql", motor)
    fuentes._vocabularios.clear()
    fuentes._vocabularios_en_curso.clear()
    return consultas


def test_la_busqueda_agrega_la_forma_escrita_sin_quitar_la_dicha(catalogo):
    fuentes.vocabulario_de("f1", "Productos", ["Codigo", "Descripcion"], esperar=True)
    fuentes.buscar_en_tabla("f1", "Productos", "cascos trooper")

    sql = catalogo[-1]
    assert "Descripcion like '%trooper%' or Descripcion like '%truper%'" in sql
    assert "Descripcion like '%cascos%' or Descripcion like '%casco%'" in sql


def test_la_primera_busqueda_no_espera_al_vocabulario(catalogo):
    # Sin vocabulario cargado busca como siempre; no bloquea a quien pregunta.
    fuentes._vocabularios[("f1", "Productos")] = None
    fuentes._vocabularios_en_curso.add(("f1", "Productos"))   # como si se estuviera leyendo
    fuentes.buscar_en_tabla("f1", "Productos", "trooper")

    assert "truper" not in catalogo[-1]
    assert "Descripcion like '%trooper%'" in catalogo[-1]


def test_si_el_catalogo_no_se_puede_leer_se_busca_como_siempre(catalogo, monkeypatch, capsys):
    def motor_roto(config, sql, limite, id_fuente=None):
        if sql.startswith("select Descripcion from"):
            raise RuntimeError("sin conexion")
        catalogo.append(sql)
        return []

    monkeypatch.setitem(fuentes.MOTORES, "mssql", motor_roto)
    fuentes.vocabulario_de("f1", "Productos", ["Codigo", "Descripcion"], esperar=True)
    fuentes.buscar_en_tabla("f1", "Productos", "trooper")

    assert "no pude leer el vocabulario" in capsys.readouterr().out
    assert "truper" not in catalogo[-1]


def test_sin_saber_el_tamano_de_la_tabla_no_se_lee_entera(catalogo, monkeypatch):
    monkeypatch.setattr(fuentes, "contar_filas", lambda id_fuente, tabla: None)
    fuentes.buscar_en_tabla("f1", "Productos", "trooper")

    assert not any(sql.startswith("select Descripcion from") for sql in catalogo)
    assert ("f1", "Productos") not in fuentes._vocabularios_en_curso


def test_una_fuente_por_mcp_no_se_lee_entera(catalogo, monkeypatch, capsys):
    monkeypatch.setattr(fuentes, "obtener",
                        lambda id_fuente: {"tipo": "supabase", "config": {"access_token": "x"}})
    fuentes.vocabulario_de("f1", "Productos", ["Codigo", "Descripcion"], esperar=True)

    assert not any(sql.startswith("select Descripcion from") for sql in catalogo)
    assert fuentes.parecidas_de_oido("trooper", fuentes._vocabularios[("f1", "Productos")]) == []
