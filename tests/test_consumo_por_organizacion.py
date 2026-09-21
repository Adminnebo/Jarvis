"""Cuanto lleva consumido cada organizacion, y de donde sale ese numero."""

import pytest

from backend import consumo, cuentas

# Un millon de tokens de entrada de gpt-5.6-terra son 2 dolares.
UN_MILLON = {"input_tokens": 1_000_000}


@pytest.fixture
def organizacion():
    return cuentas.crear_organizacion("Acme", "Lucas", "lucas@acme.com", "una-clave-larga")


def test_una_organizacion_nueva_no_consumio_nada(organizacion):
    assert cuentas.consumido(organizacion.organizacion_id) == {
        "consultas": 0, "tokens": 0, "costo": 0.0, "cobrado": 0.0,
        "margen": 0.0, "markup": 1.0,
    }


def test_lo_consumido_se_suma(organizacion):
    usuario = cuentas.entrar("lucas@acme.com", "una-clave-larga")
    consumo.registrar("texto", "gpt-5.6-terra", UN_MILLON, usuario=usuario)
    consumo.registrar("texto", "gpt-5.6-terra", UN_MILLON, usuario=usuario)

    resultado = cuentas.consumido(organizacion.organizacion_id)
    assert resultado["consultas"] == 2
    assert resultado["costo"] == 4.0
    assert resultado["tokens"] == 2_000_000


def test_el_margen_separa_lo_que_cuesta_de_lo_que_se_cobra(organizacion, monkeypatch):
    monkeypatch.setenv("JARVIS_MARGEN", "30")

    usuario = cuentas.entrar("lucas@acme.com", "una-clave-larga")
    consumo.registrar("texto", "gpt-5.6-terra", UN_MILLON, usuario=usuario)

    resultado = cuentas.consumido(organizacion.organizacion_id)
    assert resultado["costo"] == 2.0      # lo que cuesta en OpenAI
    assert resultado["cobrado"] == 2.6    # 2 dolares mas un 30%
    assert resultado["margen"] == 30.0


def test_sin_variable_se_cobra_al_costo(organizacion):
    assert cuentas.margen(organizacion.organizacion_id) == 0.0
    assert cuentas.markup(organizacion.organizacion_id) == 1.0


def test_el_margen_de_una_organizacion_pisa_al_general(organizacion, monkeypatch):
    otra = cuentas.crear_organizacion("Otra", "Ana", "ana@otra.com", "otra-clave-larga")
    monkeypatch.setenv("JARVIS_MARGEN", "30")
    monkeypatch.setenv(f"JARVIS_MARGEN_{organizacion.organizacion_id}", "50")

    assert cuentas.margen(organizacion.organizacion_id) == 50.0
    assert cuentas.margen(otra.organizacion_id) == 30.0


def test_el_id_del_margen_propio_se_acepta_en_mayusculas(organizacion, monkeypatch):
    # En Railway se escriben las variables en mayusculas por costumbre.
    monkeypatch.setenv(f"JARVIS_MARGEN_{organizacion.organizacion_id.upper()}", "50")
    assert cuentas.margen(organizacion.organizacion_id) == 50.0


@pytest.mark.parametrize("escrito, esperado", [
    ("30", 30.0), ("30%", 30.0), (" 30 ", 30.0), ("12,5", 12.5), ("12.5", 12.5),
    ("0", 0.0),
])
def test_el_porcentaje_se_escribe_como_sea_natural(organizacion, monkeypatch, escrito, esperado):
    monkeypatch.setenv("JARVIS_MARGEN", escrito)
    assert cuentas.margen(organizacion.organizacion_id) == esperado


@pytest.mark.parametrize("escrito", ["treinta", "-10", "", "30 por ciento"])
def test_un_margen_invalido_se_cobra_al_costo(organizacion, monkeypatch, escrito):
    monkeypatch.setenv("JARVIS_MARGEN", escrito)
    assert cuentas.margen(organizacion.organizacion_id) == 0.0


def test_un_margen_propio_invalido_cae_al_general(organizacion, monkeypatch):
    monkeypatch.setenv("JARVIS_MARGEN", "30")
    monkeypatch.setenv(f"JARVIS_MARGEN_{organizacion.organizacion_id}", "mucho")
    assert cuentas.margen(organizacion.organizacion_id) == 30.0


def test_quien_no_tiene_organizacion_no_paga_margen(monkeypatch):
    monkeypatch.setenv("JARVIS_MARGEN", "30")
    assert cuentas.margen(None) == 0.0


def test_avisa_al_arrancar_si_un_margen_esta_mal(organizacion, monkeypatch, capsys):
    monkeypatch.setenv("JARVIS_MARGEN", "treinta")
    monkeypatch.setenv("JARVIS_MARGEN_noexiste", "50")
    monkeypatch.setenv(f"JARVIS_MARGEN_{organizacion.organizacion_id}", "40")

    cuentas.avisar_de_margenes_invalidos()

    # En minusculas: Windows pasa los nombres de variable a mayusculas y Linux
    # no, y el aviso tiene que salir en los dos.
    salida = capsys.readouterr().out.lower()
    assert "jarvis_margen='treinta'" in salida
    assert "jarvis_margen_noexiste no corresponde" in salida
    # El que esta bien no se menciona.
    assert organizacion.organizacion_id not in salida


def test_con_todo_bien_no_avisa_nada(organizacion, monkeypatch, capsys):
    monkeypatch.setenv("JARVIS_MARGEN", "30")
    cuentas.avisar_de_margenes_invalidos()
    assert capsys.readouterr().out == ""


def test_el_consumo_de_una_organizacion_no_le_pega_a_otra(organizacion):
    otra = cuentas.crear_organizacion("Otra", "Ana", "ana@otra.com", "otra-clave-larga")

    usuario = cuentas.entrar("lucas@acme.com", "una-clave-larga")
    consumo.registrar("texto", "gpt-5.6-terra", UN_MILLON, usuario=usuario)

    assert cuentas.consumido(organizacion.organizacion_id)["costo"] == 2.0
    assert cuentas.consumido(otra.organizacion_id)["costo"] == 0.0


def test_las_sesiones_de_voz_no_cuentan_como_consultas(organizacion):
    usuario = cuentas.entrar("lucas@acme.com", "una-clave-larga")
    consumo.registrar_sesion("gpt-realtime-2.1", 60.0, usuario=usuario)

    # La sesion solo aporta tiempo; su costo ya esta en las respuestas.
    assert cuentas.consumido(organizacion.organizacion_id)["consultas"] == 0


def test_sin_organizacion_no_hay_nada_que_medir():
    assert cuentas.consumido(None)["cobrado"] == 0.0


def test_listar_organizaciones_trae_lo_consumido(organizacion):
    usuario = cuentas.entrar("lucas@acme.com", "una-clave-larga")
    consumo.registrar("texto", "gpt-5.6-terra", UN_MILLON, usuario=usuario)

    lista = cuentas.organizaciones()
    assert len(lista) == 1
    assert lista[0]["nombre"] == "Acme"
    assert lista[0]["cobrado"] == 2.0


# --------------------------------------------------------------------------
# El consumo ahora vive en la base de datos
# --------------------------------------------------------------------------

def test_lo_registrado_se_lee_de_vuelta():
    registro = consumo.registrar("texto", "gpt-5.6-terra", {"input_tokens": 100})
    guardados = consumo.todos()

    assert len(guardados) == 1
    assert guardados[0]["modelo"] == "gpt-5.6-terra"
    assert guardados[0]["costo"] == registro["costo"]


def test_borrar_deja_la_tabla_vacia():
    consumo.registrar("texto", "gpt-5.6-terra", {"input_tokens": 100})
    consumo.borrar()
    assert consumo.todos() == []


def test_migrar_el_jsonl_viejo_sube_los_registros(entorno_limpio):
    import json

    viejo = consumo.archivo()
    viejo.write_text(
        json.dumps({"cuando": "2026-09-01T10:00:00", "modo": "texto",
                    "modelo": "gpt-5.6-terra", "tokens": 10, "costo": 0.5,
                    "entrada_texto": 10}) + "\n"
        # Una linea rota no puede impedir arrancar.
        + "esto no es json\n",
        encoding="utf-8",
    )

    consumo.migrar_jsonl()

    guardados = consumo.todos()
    assert len(guardados) == 1
    assert guardados[0]["costo"] == 0.5
    # Las casillas que no existian entran en cero, no en NULL.
    assert guardados[0]["entrada_audio"] == 0
    # El archivo viejo no se borra: se renombra.
    assert not viejo.exists()
    assert viejo.with_suffix(".jsonl.migrado").exists()


def test_migrar_es_idempotente(entorno_limpio):
    import json

    consumo.archivo().write_text(
        json.dumps({"cuando": "2026-09-01T10:00:00", "modo": "texto",
                    "modelo": "gpt-5.6-terra", "tokens": 10, "costo": 0.5}) + "\n",
        encoding="utf-8",
    )
    consumo.migrar_jsonl()
    consumo.migrar_jsonl()

    assert len(consumo.todos()) == 1


# --------------------------------------------------------------------------
# El nombre de cada persona en el desglose por organizacion
# --------------------------------------------------------------------------

def test_el_nombre_sale_de_donde_vive_cada_cuenta(organizacion, monkeypatch):
    from backend import supabase_sesion

    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setenv("JARVIS_PASSWORD_JORGE", "la-de-jorge")
    uuid = "11111111-2222-3333-4444-555555555555"
    monkeypatch.setattr(supabase_sesion, "nombres_de_perfiles",
                        lambda uuids: {uuid: "Ana Perez"} if uuid in uuids else {})

    nombres = cuentas.nombres_de_usuarios([
        organizacion.id,        # cuenta de organizacion: tabla usuarios
        f"sb-{uuid}",           # panel: perfil de Supabase
        "jorge",                # contrasena por variable
        "sb-no-existe",
        None,
    ])

    assert nombres[organizacion.id] == "Lucas"
    assert nombres[f"sb-{uuid}"] == "Ana Perez"
    assert nombres["jorge"] == "Jorge"
    # Lo que no se encuentra se muestra por su id, en vez de desaparecer.
    assert nombres["sb-no-existe"] == "sb-no-existe"
    assert nombres[None] == "(sin registrar)"


def test_si_supabase_no_responde_el_desglose_sale_igual(organizacion, monkeypatch):
    from backend import supabase_sesion

    def revienta(uuids):
        raise RuntimeError("sin red")

    monkeypatch.setattr(supabase_sesion, "nombres_de_perfiles", revienta)
    uuid = "11111111-2222-3333-4444-555555555555"

    # El tablero no puede caerse porque Supabase tarde: sale con los ids.
    assert cuentas.nombres_de_usuarios([f"sb-{uuid}"]) == {f"sb-{uuid}": f"sb-{uuid}"}


def test_los_perfiles_se_piden_de_una_sola_vez(monkeypatch):
    from backend import supabase_sesion

    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon")
    monkeypatch.setenv("SUPABASE_PROJECT_REF", "abcdefghijklmnopqrst")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service")
    llamadas = []

    class Respuesta:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return [
                {"id": "11111111-2222-3333-4444-555555555555", "full_name": "Ana Perez", "email": "a@x.com"},
                {"id": "66666666-7777-8888-9999-000000000000", "full_name": "", "email": "beto@x.com"},
            ]

    monkeypatch.setattr(supabase_sesion.httpx, "get",
                        lambda url, **o: llamadas.append(o["params"]) or Respuesta())

    nombres = supabase_sesion.nombres_de_perfiles([
        "11111111-2222-3333-4444-555555555555",
        "66666666-7777-8888-9999-000000000000",
        "'); drop table profiles; --",      # no es un uuid: no entra al filtro
    ])

    assert len(llamadas) == 1
    assert "drop" not in llamadas[0]["id"]
    # Mismo criterio que al entrar: sin nombre, la parte del correo.
    assert nombres == {
        "11111111-2222-3333-4444-555555555555": "Ana Perez",
        "66666666-7777-8888-9999-000000000000": "beto",
    }
