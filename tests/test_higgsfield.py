import httpx
import pytest

from backend import higgsfield


@pytest.fixture
def con_clave(monkeypatch):
    monkeypatch.setenv("HIGGSFIELD_API_KEY_ID", "id1")
    monkeypatch.setenv("HIGGSFIELD_API_KEY_SECRET", "sec1")


class _R:
    def __init__(self, estado, cuerpo=None, contenido=b""):
        self.status_code = estado
        self._cuerpo = cuerpo or {}
        self.content = contenido
        self.text = str(cuerpo)

    def json(self):
        return self._cuerpo


def test_sin_clave_no_esta_configurado(monkeypatch):
    monkeypatch.delenv("HIGGSFIELD_API_KEY_ID", raising=False)
    assert higgsfield.configurado() is False


def test_crear_video_sube_la_foto_y_pide_el_modelo(con_clave, monkeypatch):
    pedidos = []

    def post(url, json=None, headers=None, timeout=None):
        pedidos.append(("POST", url, json, headers))
        if url.endswith("/files/generate-upload-url"):
            return _R(200, {"upload_url": "https://s3/subir", "public_url": "https://cdn/foto.jpg",
                            "upload_headers": {"Content-Type": "image/jpeg", "x-amz-tagging": "t"}})
        return _R(200, {"request_id": "req-1", "status": "queued"})

    def put(url, content=None, headers=None, timeout=None):
        pedidos.append(("PUT", url, None, headers))
        return _R(200)

    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(httpx, "put", put)

    url = higgsfield.subir_imagen(b"jpg", "image/jpeg")
    request_id = higgsfield.crear_video(url, "breathing calmly")

    assert url == "https://cdn/foto.jpg"
    assert request_id == "req-1"
    assert pedidos[0][3]["Authorization"] == "Key id1:sec1"
    # La subida a S3 lleva SUS cabeceras y nunca la clave de Higgsfield.
    assert pedidos[1][0] == "PUT" and "Authorization" not in pedidos[1][3]
    assert pedidos[2][1] == "https://api.higgsfield.ai/kling-video/v2.5-turbo/pro/image-to-video"
    assert pedidos[2][2]["image_url"] == "https://cdn/foto.jpg"
    assert pedidos[2][2]["duration"] == 5


def test_el_modelo_se_cambia_con_una_variable(con_clave, monkeypatch):
    monkeypatch.setenv("JARVIS_AVATAR_MODELO", "minimax/hailuo-2.3/standard/image-to-video")
    vistos = []
    monkeypatch.setattr(httpx, "post", lambda url, **k: vistos.append((url, k["json"])) or _R(200, {"request_id": "r"}))
    higgsfield.crear_video("https://cdn/f.jpg", "p")
    assert vistos[0][0].endswith("/minimax/hailuo-2.3/standard/image-to-video")
    assert vistos[0][1]["duration"] == 6


def test_estado_terminado_trae_la_url_del_video(con_clave, monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda url, **k: _R(200, {
        "status": "completed", "request_id": "req-1", "video": {"url": "https://cdn/v.mp4"}}))
    assert higgsfield.estado("req-1") == {"estado": "listo", "url": "https://cdn/v.mp4", "error": None}


@pytest.mark.parametrize("crudo,esperado", [
    ("queued", "generando"), ("in_progress", "generando"),
    ("failed", "error"), ("nsfw", "error"), ("canceled", "error"),
])
def test_estados_de_higgsfield(con_clave, monkeypatch, crudo, esperado):
    monkeypatch.setattr(httpx, "get", lambda url, **k: _R(200, {"status": crudo, "request_id": "r", "error": "x"}))
    assert higgsfield.estado("r")["estado"] == esperado


def test_un_rechazo_de_la_api_es_un_error_legible(con_clave, monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda url, **k: _R(402, {"detail": "Not enough credits"}))
    with pytest.raises(higgsfield.ErrorDeHiggsfield, match="Not enough credits"):
        higgsfield.crear_video("https://cdn/f.jpg", "p")
