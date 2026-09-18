"""Las pistas que acompanan a una consulta fallida, y las reglas del prompt."""

from backend import cerebro, fuentes

ESQUEMA_CRM = {
    "fuente": "Mensajes",
    "tipo": "postgres",
    "tablas": [
        {"tabla": "messages", "columnas": "id bigint, conversation_id bigint, direction text, text text, created_at timestamp"},
        {"tabla": "contacts", "columnas": "id bigint, phone text, name text"},
    ],
}


def _con_fuente(monkeypatch, tipo="postgres"):
    monkeypatch.setattr(fuentes, "obtener", lambda _id: {"id": "crm", "tipo": tipo, "nombre": "Mensajes"})
    monkeypatch.setattr(fuentes, "esquema_de", lambda _id, refrescar=False: ESQUEMA_CRM)


def test_top_en_postgres_pide_limit(monkeypatch):
    _con_fuente(monkeypatch)
    pista = fuentes.pista_de_error(
        "crm", "select top 5 id from calls", Exception('syntax error at or near "5"')
    )
    assert "LIMIT" in pista and "PostgreSQL" in pista


def test_limit_en_sql_server_pide_top(monkeypatch):
    _con_fuente(monkeypatch, tipo="mssql")
    pista = fuentes.pista_de_error("crm", "select id from x limit 5", Exception("Incorrect syntax near '5'"))
    assert "TOP" in pista


def test_columna_inventada_devuelve_las_reales(monkeypatch):
    _con_fuente(monkeypatch)
    sql = "select m.text, c.name from messages m left join contacts c on c.id::text = m.contact_id"
    pista = fuentes.pista_de_error("crm", sql, Exception("column m.contact_id does not exist"))
    assert "Columnas reales de messages: id, conversation_id, direction, text, created_at." in pista
    assert "Columnas reales de contacts: id, phone, name." in pista


def test_group_by_estricto(monkeypatch):
    _con_fuente(monkeypatch)
    pista = fuentes.pista_de_error(
        "crm", "select c.name, count(*) from contacts c",
        Exception('column "c.name" must appear in the GROUP BY clause or be used in an aggregate function'),
    )
    assert "GROUP BY" in pista


def test_tabla_inexistente_lista_las_que_hay(monkeypatch):
    _con_fuente(monkeypatch)
    pista = fuentes.pista_de_error("crm", "select * from mensajes", Exception('relation "mensajes" does not exist'))
    assert "Tablas que existen: messages, contacts." in pista


def test_error_sin_nada_que_decir_no_agrega_pista(monkeypatch):
    _con_fuente(monkeypatch)
    assert fuentes.pista_de_error("crm", "select 1", Exception("timeout")) == ""


def test_consultar_fuente_suma_la_pista_al_error(monkeypatch):
    from backend import herramientas

    _con_fuente(monkeypatch)

    def falla(*_a, **_k):
        raise Exception('syntax error at or near "1"')

    monkeypatch.setattr(fuentes, "consultar", falla)
    salida = herramientas.consultar_fuente("crm", "select top 1 * from calls")
    assert salida.startswith("Error al consultar:")
    assert "Pista: Esta fuente es PostgreSQL" in salida


def test_el_prompt_trae_la_regla_de_identidad():
    from backend import acceso

    texto = cerebro.instrucciones(acceso.por_defecto())
    assert "asistente en tiempo real" in texto
    assert "Nunca digas que eres ChatGPT" in texto
