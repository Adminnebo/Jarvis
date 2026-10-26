from backend import rutas

SEÑALES = ("JARVIS_HOSPEDADO", "RAILWAY_ENVIRONMENT", "RAILWAY_PROJECT_ID", "RAILWAY_SERVICE_ID",
           "RENDER", "FLY_APP_NAME", "DYNO", "KUBERNETES_SERVICE_HOST", "WEBSITE_INSTANCE_ID",
           "GOOGLE_CLOUD_PROJECT")


def _limpio(monkeypatch):
    for nombre in SEÑALES:
        monkeypatch.delenv(nombre, raising=False)


def test_sin_senales_es_la_maquina_de_casa(monkeypatch):
    _limpio(monkeypatch)
    assert rutas.hospedado() is False


def test_en_un_ec2_propio_se_marca_a_mano(monkeypatch):
    _limpio(monkeypatch)
    monkeypatch.setenv("JARVIS_HOSPEDADO", "1")
    assert rutas.hospedado() is True


def test_railway_sigue_contando(monkeypatch):
    _limpio(monkeypatch)
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    assert rutas.hospedado() is True
