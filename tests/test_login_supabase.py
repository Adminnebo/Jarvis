"""Entrar a Jarvis con el correo y la contrasena de los paneles (Supabase)."""

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import acceso, supabase_sesion
from backend.main import app

UUID = "11111111-2222-3333-4444-555555555555"


@pytest.fixture
def configurado(monkeypatch):
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-de-prueba")
    monkeypatch.setenv("SUPABASE_PROJECT_REF", "abcdefghijklmnopqrst")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-de-prueba")
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setenv("JARVIS_CLAVE_SECRETA", "clave-de-pruebas-larga")
    supabase_sesion.limpiar_cache()


class _Respuesta:
    def __init__(self, estado, cuerpo):
        self.status_code = estado
        self._cuerpo = cuerpo

    def json(self):
        return self._cuerpo


def _supabase(monkeypatch, *, password_buena="la-del-panel", perfil=None, pedidos=None):
    """Supabase de mentira: la API de contrasena, la de usuario y profiles."""
    def post(url, params=None, json=None, headers=None, timeout=None):
        if pedidos is not None:
            pedidos.append((url, params, json))
        if json and json.get("password") == password_buena:
            return _Respuesta(200, {"access_token": "token-de-panel"})
        return _Respuesta(400, {"error": "invalid_grant"})

    def get(url, params=None, headers=None, timeout=None):
        if url.endswith("/auth/v1/user"):
            ok = headers.get("Authorization") == "Bearer token-de-panel"
            return _Respuesta(200 if ok else 401, {"id": UUID} if ok else {})
        filas = [perfil] if perfil else []
        respuesta = _Respuesta(200, filas)
        respuesta.raise_for_status = lambda: None
        return respuesta

    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(httpx, "get", get)


def _perfil(**cambios):
    datos = {"id": UUID, "email": "jmorel@jhelectroalambres.com", "full_name": "J. Morel",
             "role": "agent", "permissions": ["jarvis.usar"], "platforms": []}
    datos.update(cambios)
    return datos


def test_con_las_credenciales_del_panel_y_permiso_entra(configurado, monkeypatch):
    pedidos = []
    _supabase(monkeypatch, perfil=_perfil(), pedidos=pedidos)
    cliente = TestClient(app)

    r = cliente.post("/acceso/cuenta", data={"email": "jmorel@jhelectroalambres.com",
                                              "password": "la-del-panel"}, follow_redirects=False)

    assert r.status_code == 303
    assert acceso.COOKIE in r.cookies
    assert pedidos[0][0] == "https://abcdefghijklmnopqrst.supabase.co/auth/v1/token"
    assert pedidos[0][1] == {"grant_type": "password"}


def test_credenciales_buenas_pero_sin_permiso_de_jarvis(configurado, monkeypatch):
    _supabase(monkeypatch, perfil=_perfil(permissions=["conversaciones.ver"]))
    r = TestClient(app).post("/acceso/cuenta", data={"email": "a@b.com", "password": "la-del-panel"},
                             follow_redirects=False)
    assert r.status_code == 403
    assert "No tienes acceso a Jarvis" in r.text
    assert acceso.COOKIE not in r.cookies


def test_contrasena_mala_no_entra(configurado, monkeypatch):
    _supabase(monkeypatch, perfil=_perfil())
    r = TestClient(app).post("/acceso/cuenta", data={"email": "a@b.com", "password": "otra"},
                             follow_redirects=False)
    assert r.status_code == 401
    assert "Correo o contrasena incorrectos" in r.text


def test_si_supabase_no_responde_no_entra(configurado, monkeypatch):
    def caido(*args, **kwargs):
        raise httpx.ConnectError("sin red")
    monkeypatch.setattr(httpx, "post", caido)
    assert supabase_sesion.token_con_password("a@b.com", "x") is None
    r = TestClient(app).post("/acceso/cuenta", data={"email": "a@b.com", "password": "x"},
                             follow_redirects=False)
    assert r.status_code == 401


def test_sin_supabase_configurado_no_se_le_pregunta(monkeypatch):
    def no_deberia(*args, **kwargs):
        raise AssertionError("no tenia que llamar a Supabase")
    monkeypatch.setattr(httpx, "post", no_deberia)
    assert supabase_sesion.token_con_password("a@b.com", "x") is None
    r = TestClient(app).post("/acceso/cuenta", data={"email": "a@b.com", "password": "x"},
                             follow_redirects=False)
    assert r.status_code == 401


def test_la_pagina_de_login_ofrece_el_correo_de_los_paneles():
    assert "el mismo de los paneles" in TestClient(app).get("/acceso").text
