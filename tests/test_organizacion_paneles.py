"""Quien entra desde los paneles de Supabase queda en una organizacion."""

import pytest

from backend import consumo, cuentas, supabase_sesion

PERFIL = {
    "id": "11111111-2222-3333-4444-555555555555",
    "email": "ana@jh.com",
    "full_name": "Ana Perez",
    "role": "agent",
    "permissions": ["jarvis.usar"],
    "platforms": None,
}


@pytest.fixture
def jh(monkeypatch):
    monkeypatch.setenv("JARVIS_ORGANIZACION_PANELES", "JH Electroalambres")
    cuentas.asegurar_organizacion_de_paneles()


def test_sin_variable_los_de_los_paneles_no_tienen_organizacion():
    # Como hasta ahora: son de la casa.
    assert supabase_sesion.usuario_de_perfil(PERFIL).organizacion_id is None


def test_con_variable_entran_a_la_organizacion(jh):
    usuario = supabase_sesion.usuario_de_perfil(PERFIL)
    assert usuario.organizacion_id == cuentas.ID_PANELES
    assert cuentas.nombre_organizacion(usuario.organizacion_id) == "JH Electroalambres"


def test_el_rol_no_cambia_por_estar_en_la_organizacion(jh):
    admin = supabase_sesion.usuario_de_perfil({**PERFIL, "permissions": ["jarvis.admin"]})
    assert admin.rol == "admin"
    assert admin.organizacion_id == cuentas.ID_PANELES


def test_sin_permiso_de_jarvis_sigue_sin_entrar(jh):
    assert supabase_sesion.usuario_de_perfil({**PERFIL, "permissions": ["inbox.send"]}) is None


def test_la_revalidacion_conserva_la_organizacion(jh, monkeypatch):
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-de-prueba")
    monkeypatch.setenv("SUPABASE_PROJECT_REF", "abcdefghijklmnopqrst")
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://x:y@z:5432/postgres")
    monkeypatch.setattr(supabase_sesion, "perfil_cacheado", lambda uuid: PERFIL)

    previo = supabase_sesion.usuario_de_perfil(PERFIL)
    assert supabase_sesion.revalidar(previo).organizacion_id == cuentas.ID_PANELES


def test_crearla_dos_veces_no_la_duplica(jh):
    cuentas.asegurar_organizacion_de_paneles()
    nombres = [o["nombre"] for o in cuentas.organizaciones()]
    assert nombres == ["JH Electroalambres"]


def test_cambiar_el_nombre_no_cambia_el_id(jh, monkeypatch):
    # El id fijo es lo que permite renombrarla sin partir su historial.
    monkeypatch.setenv("JARVIS_ORGANIZACION_PANELES", "JH Electroalambres SRL")
    cuentas.asegurar_organizacion_de_paneles()

    assert cuentas.nombre_organizacion(cuentas.ID_PANELES) == "JH Electroalambres SRL"
    assert len(cuentas.organizaciones()) == 1


def test_sin_variable_no_se_crea_nada():
    cuentas.asegurar_organizacion_de_paneles()
    assert cuentas.organizaciones() == []


def test_registrarse_con_el_mismo_nombre_no_se_queda_con_ella(jh):
    # /registro genera ids al azar: nunca puede tomar el de los paneles.
    intruso = cuentas.crear_organizacion(
        "JH Electroalambres", "Otro", "otro@x.com", "una-clave-larga",
    )
    assert intruso.organizacion_id != cuentas.ID_PANELES
    assert supabase_sesion.usuario_de_perfil(PERFIL).organizacion_id == cuentas.ID_PANELES


def test_su_consumo_se_le_cobra_con_margen(jh, monkeypatch):
    monkeypatch.setenv("JARVIS_MARGEN", "30")
    usuario = supabase_sesion.usuario_de_perfil(PERFIL)

    consumo.registrar("texto", "gpt-5.6-terra", {"input_tokens": 1_000_000}, usuario=usuario)

    resultado = cuentas.consumido(cuentas.ID_PANELES)
    assert resultado["costo"] == 2.0
    assert resultado["cobrado"] == 2.6


def test_su_margen_propio_se_pone_con_el_id_fijo(jh, monkeypatch):
    monkeypatch.setenv("JARVIS_MARGEN", "30")
    monkeypatch.setenv("JARVIS_MARGEN_PANELES", "50")
    assert cuentas.margen(cuentas.ID_PANELES) == 50.0


def test_de_punta_a_punta_entrando_por_el_panel(jh, monkeypatch):
    """El login del panel, el middleware y el estado, con Supabase simulado."""
    from fastapi.testclient import TestClient

    from backend.main import app

    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setenv("JARVIS_CLAVE_SECRETA", "clave-de-pruebas-larga")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-de-prueba")
    monkeypatch.setenv("SUPABASE_PROJECT_REF", "abcdefghijklmnopqrst")
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://x:y@z:5432/postgres")
    # Solo se simula Supabase; lo demas es el camino real.
    monkeypatch.setattr(supabase_sesion, "id_de_token", lambda token: PERFIL["id"])
    monkeypatch.setattr(supabase_sesion, "perfil_cacheado", lambda uuid: PERFIL)

    cliente = TestClient(app)
    assert cliente.post("/acceso/supabase", json={"token": "de-ana"}).status_code == 200

    estado = cliente.get("/api/estado").json()
    assert estado["usuario"] == "Ana Perez"
    assert estado["organizacion"] == "JH Electroalambres"
    # Su organizacion la administra Supabase, no el panel de Jarvis.
    assert estado["es_admin_org"] is False
