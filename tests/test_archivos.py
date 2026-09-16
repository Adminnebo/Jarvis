import json

import pytest
from fastapi.testclient import TestClient

# Arriba del todo por lo mismo que en test_permisos.py: main carga el .env real.
from backend import archivos, cerebro, herramientas
from backend.main import app

BASE = "https://abcdefghijklmnopqrst.supabase.co/storage/v1"


@pytest.fixture
def configurado(entorno_limpio, monkeypatch):
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "llave-de-pruebas")
    monkeypatch.setenv("SUPABASE_PROJECT_REF", "abcdefghijklmnopqrst")
    monkeypatch.setenv("JARVIS_BUCKET_IMAGENES", "Lucas_imagenes")
    monkeypatch.setenv("JARVIS_BUCKET_FICHAS", "Lucas_fichas_tecnicas")
    # Nada de red en las pruebas: si algo quisiera listar, falla a la vista.
    monkeypatch.setattr(archivos, "refrescar", lambda: pytest.fail("no debia listar"))
    monkeypatch.setattr(archivos, "refrescar_en_segundo_plano", lambda: None)
    archivos.usar_indices(
        {
            "imagen": archivos.armar_indice(["305400.png", "0774 - copia.png", "ZN25100.png"]),
            "ficha": archivos.armar_indice(["305400.pdf", "30024 .pdf"]),
        },
        {"imagen": True, "ficha": True},
    )


@pytest.mark.parametrize("nombre, codigo", [
    ("305400.png", "305400"),
    ("0774 - copia.png", "0774"),
    ("1 copia - copia - copia.png", "1"),
    ("11815 (2).png", "11815"),
    ("302209 - Copy.png", "302209"),
    ("30024 .pdf", "30024"),
    ("10294p.png", "10294P"),
    (" 305400 ", "305400"),
    ("carpeta/305400.pdf", "305400"),
])
def test_los_nombres_de_archivo_se_vuelven_codigos(nombre, codigo):
    assert archivos.normalizar(nombre) == codigo


def test_el_original_gana_a_sus_copias():
    indice = archivos.armar_indice(["11815 (2).png", "11815.png", "11815 - copia.png"])
    assert indice == {"11815": "11815.png"}


def test_una_copia_sola_tambien_sirve():
    assert archivos.armar_indice(["0774 - copia.png"]) == {"0774": "0774 - copia.png"}


def test_sin_llave_o_sin_buckets_no_esta_configurado(entorno_limpio, monkeypatch):
    monkeypatch.setenv("SUPABASE_PROJECT_REF", "abcdefghijklmnopqrst")
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.setenv("JARVIS_BUCKET_IMAGENES", "Lucas_imagenes")
    assert not archivos.configurado()

    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "llave")
    monkeypatch.delenv("JARVIS_BUCKET_IMAGENES")
    monkeypatch.delenv("JARVIS_BUCKET_FICHAS", raising=False)
    assert not archivos.configurado()


def test_sin_configurar_la_herramienta_no_se_ofrece(entorno_limpio, monkeypatch):
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    nombres = [e["name"] for e in herramientas.esquemas()]
    assert "mandar_archivos_producto" not in nombres
    assert "recordar" in nombres


def test_configurada_se_ofrece_y_no_pide_usuario(configurado):
    esquema = next(e for e in herramientas.esquemas() if e["name"] == "mandar_archivos_producto")
    assert esquema["parameters"]["required"] == ["codigos"]


def test_manda_lo_que_hay_y_dice_lo_que_no(configurado):
    texto, adjuntos = herramientas.ejecutar_completo(
        "mandar_archivos_producto",
        json.dumps({"codigos": "305400, zn25100", "nombres": "Modulo porta contador | Tornillo"}),
        "admin",
    )

    assert [(a["tipo"], a["codigo"]) for a in adjuntos] == [
        ("imagen", "305400"), ("ficha", "305400"), ("imagen", "ZN25100"),
    ]
    assert adjuntos[0]["url"] == f"{BASE}/object/public/Lucas_imagenes/305400.png"
    assert adjuntos[0]["titulo"] == "Modulo porta contador"
    assert "No existe ficha tecnica de Tornillo" in texto
    assert "no ofrezcas el archivo de otro producto" in texto
    # Las URLs van a la pantalla, nunca al texto que lee el modelo.
    assert "http" not in texto


def test_solo_manda_el_tipo_que_pidieron(configurado):
    _, adjuntos = herramientas.ejecutar_completo(
        "mandar_archivos_producto", json.dumps({"codigos": "305400", "tipo": "ficha"}), "admin"
    )
    assert [a["tipo"] for a in adjuntos] == ["ficha"]


def test_un_producto_sin_archivos_no_manda_nada(configurado):
    texto, adjuntos = herramientas.ejecutar_completo(
        "mandar_archivos_producto", json.dumps({"codigos": "999999"}), "admin"
    )
    assert adjuntos == []
    assert "No existe imagen de 999999, ficha tecnica de 999999" in texto


def test_los_nombres_con_espacios_van_codificados(configurado):
    _, adjuntos = herramientas.ejecutar_completo(
        "mandar_archivos_producto", json.dumps({"codigos": "0774", "tipo": "imagen"}), "admin"
    )
    assert adjuntos[0]["url"].endswith("/Lucas_imagenes/0774%20-%20copia.png")


@pytest.mark.parametrize("argumentos, error", [
    ({"codigos": ""}, "falta el Codigo"),
    ({"codigos": "1,2,3,4,5,6"}, "como mucho 5"),
    ({"codigos": "305400", "tipo": "video"}, "'tipo' tiene que ser"),
])
def test_pedidos_mal_formados_no_mandan_nada(configurado, argumentos, error):
    texto, adjuntos = herramientas.ejecutar_completo(
        "mandar_archivos_producto", json.dumps(argumentos), "admin"
    )
    assert error in texto
    assert adjuntos == []


def test_un_bucket_privado_usa_enlace_firmado(configurado, monkeypatch):
    archivos.usar_indices({"ficha": {"305400": "305400.pdf"}}, {"ficha": False})
    pedidas = []

    class Respuesta:
        def raise_for_status(self):
            return self

        def json(self):
            return {"signedURL": "/object/sign/Lucas_fichas_tecnicas/305400.pdf?token=abc"}

    class Cliente:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json):
            pedidas.append((url, json))
            return Respuesta()

    monkeypatch.setattr(archivos, "_cliente", Cliente)
    encontrados, _ = archivos.buscar(["305400"], ["ficha"])

    assert encontrados[0]["url"] == f"{BASE}/object/sign/Lucas_fichas_tecnicas/305400.pdf?token=abc"
    assert pedidas == [(f"{BASE}/object/sign/Lucas_fichas_tecnicas/305400.pdf", {"expiresIn": 3600})]


def test_el_endpoint_de_herramientas_devuelve_los_adjuntos(configurado, monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setenv("JARVIS_CLAVE_SECRETA", "clave-de-pruebas-larga")
    cliente = TestClient(app)
    assert cliente.post("/acceso", data={"clave": "la-del-admin"}, follow_redirects=False).status_code == 303

    respuesta = cliente.post("/api/herramienta", json={
        "nombre": "mandar_archivos_producto",
        "argumentos": json.dumps({"codigos": "305400", "tipo": "imagen"}),
    }).json()

    assert "Enviado al chat" in respuesta["resultado"]
    assert respuesta["adjuntos"][0]["url"].endswith("/305400.png")

    otra = cliente.post("/api/herramienta", json={"nombre": "hora_actual"}).json()
    assert otra["adjuntos"] == []


def test_los_adjuntos_de_voz_quedan_en_el_historial(configurado, monkeypatch):
    monkeypatch.setenv("JARVIS_PASSWORD", "la-del-admin")
    monkeypatch.setenv("JARVIS_CLAVE_SECRETA", "clave-de-pruebas-larga")
    cliente = TestClient(app)
    cliente.post("/acceso", data={"clave": "la-del-admin"}, follow_redirects=False)

    adjunto = {"tipo": "imagen", "codigo": "305400", "titulo": "Modulo", "url": "https://x/305400.png"}
    cliente.post("/api/conversacion/agregar", json={
        "role": "assistant", "content": "[Enviado al chat: imagen de Modulo]", "adjuntos": [adjunto],
    })

    historial = cliente.get("/api/estado").json()["historial"]
    assert historial[-1]["adjuntos"] == [adjunto]


def test_el_modo_texto_emite_los_adjuntos_y_los_guarda(configurado, monkeypatch):
    """Una ronda con la llamada a la herramienta y otra con la respuesta."""

    class Evento:
        def __init__(self, **campos):
            self.__dict__.update(campos)

    class Llamada:
        type = "function_call"
        name = "mandar_archivos_producto"
        arguments = json.dumps({"codigos": "305400", "tipo": "ficha"})
        call_id = "c1"

        def model_dump(self):
            return {"type": self.type, "name": self.name, "arguments": self.arguments,
                    "call_id": self.call_id}

    rondas = [
        [Evento(type="response.completed", response=Evento(output=[Llamada()], usage=None))],
        [Evento(type="response.output_text.delta", delta="Ahi va la ficha."),
         Evento(type="response.completed", response=Evento(output=[], usage=None))],
    ]

    class Api:
        class responses:
            @staticmethod
            def create(**_):
                return iter(rondas.pop(0))

    monkeypatch.setattr(cerebro, "cliente", lambda: Api)
    monkeypatch.setattr(cerebro.conectores, "activos", lambda: [])
    from backend import acceso, memoria

    usuario = acceso.Usuario("admin", "Admin", "admin")
    eventos = list(cerebro.responder([{"role": "user", "content": "la ficha del 305400"}], usuario))

    adjuntos = [e["dato"] for e in eventos if e["tipo"] == "adjuntos"]
    assert adjuntos and adjuntos[0][0]["tipo"] == "ficha"
    guardado = memoria.cargar_conversacion("admin")[-1]
    assert guardado["content"] == "Ahi va la ficha."
    assert guardado["adjuntos"][0]["codigo"] == "305400"
