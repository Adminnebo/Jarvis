# Bot de Meet, plan 1 de 2: el bot (EC2 `bot-meet`) — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un servicio en el EC2 `bot-meet` que recibe órdenes firmadas, entra a un Google Meet con la cuenta de Nebo, graba solo el audio en pedazos de 5 minutos, anota quién habla y lo sube todo a Jarvis.

**Architecture:** FastAPI chico (`bot_meet/app.py`) con una agenda en un JSON en disco y un lanzador que, a la hora, corre cada sesión en un hilo. Cada sesión abre un Chromium con Playwright (perfil copiado), graba el monitor de PulseAudio con ffmpeg y sube por una cola en disco que sobrevive a cortes. Docker + Caddy (HTTPS, filtro por IP) en el EC2, con despliegue por timer como Jarvis.

**Tech Stack:** Python 3.12, FastAPI 0.115, httpx 0.28, Playwright 1.49 (Chromium, `channel="chromium"`), ffmpeg (libopus), PulseAudio (null sink), Xvfb de respaldo, Docker Compose, Caddy 2.

**Diseño:** `docs/superpowers/specs/2026-11-24-bot-grabacion-meet-design.md`. El plan 2 (Jarvis: aviso, recepción, transcripción, sección Reuniones) va aparte y usa el contrato que se fija aquí.

---

## Contrato con Jarvis (lo usa el plan 2)

**Jarvis → bot** (`https://bot-meet.neboaiconsulting.com`), firmado:

- Cabeceras: `X-Bot-Tiempo: <unix segundos>` y `X-Bot-Firma: <hex>`, donde la firma es
  `HMAC-SHA256(BOT_MEET_SECRETO, f"{tiempo}.{METODO}.{ruta}." + cuerpo)`. `ruta`
  es el path sin dominio (`/v1/sesiones`). La ventana es de ±300 s.
- `POST /v1/sesiones` con el cuerpo `{"id", "meet_url", "inicio", "fin",
  "token_subida", "url_jarvis"}` (fechas ISO con zona). Responde `202
  {"estado":"agendada"}`, `400 {"error":"link_invalido"|"datos_invalidos"}`,
  `401` o `409 {"error":"sin_bot_libre"}`.
- `DELETE /v1/sesiones/{id}`: `200 {"estado":"cancelada"}` o `404`.
- `GET /v1/salud`, sin firma: `{"ok", "activas", "agendadas", "memoria_libre_mb", "carga"}`.

**Bot → Jarvis**, con `Authorization: Bearer <token_subida>`:

- `POST {url_jarvis}/api/reuniones/{id}/eventos` con el JSON `{"tipo": "esperando"|"admitido"|"rechazado"|"fallo"|"terminado", ...}`.
  `fallo` lleva `motivo`; `terminado` lleva `motivo` e `incompleta` (bool).
- `POST {url_jarvis}/api/reuniones/{id}/audio?n=<1..>`: el cuerpo es el `audio/ogg` (Opus) del pedazo n.
- `POST {url_jarvis}/api/reuniones/{id}/hablantes` con el JSON `{"linea": [{"t": <seg desde que entró>, "nombres": [..]}]}`.
- Jarvis responde 2xx si lo recibió. Un `409` (repetido) cuenta como recibido.

---

## Archivos

```
bot-meet/
  requirements.txt            dependencias del bot
  requirements-dev.txt        + pytest
  pytest.ini                  raíz de pruebas del bot
  Dockerfile                  imagen: python slim + ffmpeg + pulseaudio + xvfb + chromium
  entrypoint.sh               levanta PulseAudio (sink "grabacion"), Xvfb si hace falta, uvicorn
  iniciar-sesion.sh           abre el navegador del perfil base para el login de Google (una vez)
  bot_meet/
    __init__.py
    config.py                 variables de entorno -> Config
    firma.py                  firmar / verificar HMAC
    agenda.py                 Sesion + Agenda (JSON en disco, límite de bots, estados)
    reglas.py                 cuándo salir de la reunión (función pura)
    subidor.py                cola en disco hacia Jarvis con reintentos
    grabador.py               ffmpeg en pedazos
    selectores.py             todo lo que depende de la página de Meet (mantenimiento aquí)
    meet.py                   Playwright: entrar, solo audio, chat, leer estado, salir
    sesion.py                 orquesta una reunión de punta a punta
    lanzador.py               arranca sesiones a la hora, reintenta subidas, limpia
    app.py                    FastAPI: /v1/sesiones, /v1/salud
    herramientas/
      __init__.py
      agendar.py              CLI: agenda una sesión firmada (pruebas y uso manual)
      receptor_prueba.py      Jarvis falso que guarda lo que llega (prueba real)
  tests/
    conftest.py
    test_config.py
    test_firma.py
    test_agenda.py
    test_reglas.py
    test_subidor.py
    test_grabador.py
    test_sesion.py
    test_lanzador.py
    test_app.py
    test_meet_simulado.py     Playwright contra la página falsa
    meet_simulado/index.html  página que imita a Meet con los mismos selectores
  servidor/
    LEEME.md                  cómo está montado el EC2 y qué hacer a mano
    docker-compose.yml
    Caddyfile
    desplegar.sh
    bot-meet-despliegue.service
    bot-meet-despliegue.timer
```

Todas las pruebas se corren desde `bot-meet/` con `python -m pytest`. No tocan `tests/` de Jarvis.

---

### Task 1: Esqueleto y configuración

**Files:**
- Create: `bot-meet/requirements.txt`, `bot-meet/requirements-dev.txt`, `bot-meet/pytest.ini`, `bot-meet/bot_meet/__init__.py`, `bot-meet/bot_meet/config.py`, `bot-meet/tests/conftest.py`
- Test: `bot-meet/tests/test_config.py`

- [ ] **Step 1: Crear los archivos base**

`bot-meet/requirements.txt`:
```
fastapi==0.115.6
uvicorn[standard]==0.34.0
httpx==0.28.1
playwright==1.49.1
```

`bot-meet/requirements-dev.txt`:
```
-r requirements.txt
pytest>=8.3
```

`bot-meet/pytest.ini`:
```ini
[pytest]
testpaths = tests
markers =
    navegador: necesita Chromium de Playwright instalado
```

`bot-meet/bot_meet/__init__.py`: vacío.

`bot-meet/tests/conftest.py`:
```python
"""Cada prueba corre sin variables BOT_MEET_ de la máquina."""
import os

import pytest


@pytest.fixture(autouse=True)
def entorno_limpio(monkeypatch):
    for nombre in list(os.environ):
        if nombre.startswith("BOT_MEET_"):
            monkeypatch.delenv(nombre, raising=False)
```

- [ ] **Step 2: Escribir la prueba que falla**

`bot-meet/tests/test_config.py`:
```python
from pathlib import Path

import pytest

from bot_meet.config import leer_config

SECRETO = "s" * 32


def test_valores_por_defecto():
    c = leer_config({"BOT_MEET_SECRETO": SECRETO})
    assert c.secreto == SECRETO
    assert c.datos == Path("/data")
    assert c.max_sesiones == 2
    assert c.pedazo_s == 300
    assert c.headless is True
    assert c.espera_admision_s == 600
    assert c.sel_hablando == '[data-hablando="1"]'
    assert c.volcar_dom is False


def test_lee_las_variables():
    c = leer_config({
        "BOT_MEET_SECRETO": SECRETO, "BOT_MEET_DATOS": "/tmp/x",
        "BOT_MEET_MAX_SESIONES": "1", "BOT_MEET_PEDAZO_S": "60",
        "BOT_MEET_HEADLESS": "0", "BOT_MEET_ESPERA_ADMISION_S": "30",
        "BOT_MEET_SEL_HABLANDO": ".habla", "BOT_MEET_VOLCAR_DOM": "1",
    })
    assert c.datos == Path("/tmp/x")
    assert (c.max_sesiones, c.pedazo_s, c.headless, c.espera_admision_s) == (1, 60, False, 30)
    assert c.sel_hablando == ".habla"
    assert c.volcar_dom is True


@pytest.mark.parametrize("secreto", ["", "corto"])
def test_secreto_obligatorio_y_largo(secreto):
    with pytest.raises(ValueError, match="BOT_MEET_SECRETO"):
        leer_config({"BOT_MEET_SECRETO": secreto})
```

- [ ] **Step 3: Correrla y ver que falla**

Run: `cd bot-meet && python -m pip install -r requirements-dev.txt && python -m pytest tests/test_config.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'bot_meet.config'`

- [ ] **Step 4: Implementar**

`bot-meet/bot_meet/config.py`:
```python
"""Configuración del bot, toda desde variables de entorno."""
import os
from dataclasses import dataclass
from pathlib import Path

# Selector que usa la página de Meet simulada. El de la página real se calibra
# con una reunión de verdad (plan, tarea 14) y va en BOT_MEET_SEL_HABLANDO.
SEL_HABLANDO_SIMULADO = '[data-hablando="1"]'


@dataclass(frozen=True)
class Config:
    secreto: str
    datos: Path
    max_sesiones: int = 2
    pedazo_s: int = 300
    headless: bool = True
    espera_admision_s: int = 600
    sel_hablando: str = SEL_HABLANDO_SIMULADO
    volcar_dom: bool = False


def leer_config(entorno=None) -> Config:
    e = os.environ if entorno is None else entorno
    secreto = e.get("BOT_MEET_SECRETO", "")
    if len(secreto) < 32:
        raise ValueError("BOT_MEET_SECRETO falta o tiene menos de 32 caracteres")
    return Config(
        secreto=secreto,
        datos=Path(e.get("BOT_MEET_DATOS", "/data")),
        max_sesiones=int(e.get("BOT_MEET_MAX_SESIONES", "2")),
        pedazo_s=int(e.get("BOT_MEET_PEDAZO_S", "300")),
        headless=e.get("BOT_MEET_HEADLESS", "1") != "0",
        espera_admision_s=int(e.get("BOT_MEET_ESPERA_ADMISION_S", "600")),
        sel_hablando=e.get("BOT_MEET_SEL_HABLANDO", SEL_HABLANDO_SIMULADO),
        volcar_dom=e.get("BOT_MEET_VOLCAR_DOM", "0") == "1",
    )
```

- [ ] **Step 5: Correr y ver que pasa**

Run: `cd bot-meet && python -m pytest tests/test_config.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add bot-meet/requirements.txt bot-meet/requirements-dev.txt bot-meet/pytest.ini bot-meet/bot_meet/__init__.py bot-meet/bot_meet/config.py bot-meet/tests/conftest.py bot-meet/tests/test_config.py
git commit -m "Start the Meet bot with its configuration"
```

---

### Task 2: Firma de los pedidos

**Files:**
- Create: `bot-meet/bot_meet/firma.py`
- Test: `bot-meet/tests/test_firma.py`

- [ ] **Step 1: Escribir la prueba que falla**

`bot-meet/tests/test_firma.py`:
```python
from bot_meet.firma import firmar, verificar

S = "s" * 32
CUERPO = b'{"id":"r1"}'


def test_firma_valida():
    f = firmar(S, 1000, "post", "/v1/sesiones", CUERPO)
    assert verificar(S, "1000", f, "POST", "/v1/sesiones", CUERPO, ahora=1100)


def test_firma_conocida():
    # Valor fijo: Jarvis (plan 2) tiene que dar exactamente esto.
    assert firmar(S, 1000, "POST", "/v1/sesiones", CUERPO) == (
        "48afd012f6332ff2f2e9e0835636f6a9b6d7f2085a983ab6068614d17d3520b9")


def test_rechaza_cuerpo_cambiado():
    f = firmar(S, 1000, "POST", "/v1/sesiones", CUERPO)
    assert not verificar(S, "1000", f, "POST", "/v1/sesiones", b'{"id":"r2"}', ahora=1000)


def test_rechaza_otra_ruta_o_metodo():
    f = firmar(S, 1000, "POST", "/v1/sesiones", CUERPO)
    assert not verificar(S, "1000", f, "DELETE", "/v1/sesiones", CUERPO, ahora=1000)
    assert not verificar(S, "1000", f, "POST", "/v1/sesiones/x", CUERPO, ahora=1000)


def test_rechaza_fuera_de_ventana():
    f = firmar(S, 1000, "POST", "/v1/sesiones", CUERPO)
    assert not verificar(S, "1000", f, "POST", "/v1/sesiones", CUERPO, ahora=1301)
    assert not verificar(S, "1000", f, "POST", "/v1/sesiones", CUERPO, ahora=699)


def test_rechaza_cabeceras_faltantes_o_raras():
    assert not verificar(S, None, None, "POST", "/v1/sesiones", CUERPO, ahora=1000)
    assert not verificar(S, "abc", "x", "POST", "/v1/sesiones", CUERPO, ahora=1000)
```

- [ ] **Step 2: Correrla y ver que falla**

Run: `cd bot-meet && python -m pytest tests/test_firma.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'bot_meet.firma'`

- [ ] **Step 3: Implementar**

`bot-meet/bot_meet/firma.py`:
```python
"""Firma HMAC de los pedidos de Jarvis al bot.

firma = HMAC-SHA256(secreto, f"{tiempo}.{METODO}.{ruta}." + cuerpo), en hex.
Jarvis usa exactamente la misma cuenta (plan 2).
"""
import hashlib
import hmac
import time

VENTANA_S = 300


def firmar(secreto: str, tiempo: int, metodo: str, ruta: str, cuerpo: bytes) -> str:
    mensaje = f"{tiempo}.{metodo.upper()}.{ruta}.".encode() + cuerpo
    return hmac.new(secreto.encode(), mensaje, hashlib.sha256).hexdigest()


def verificar(secreto, tiempo_txt, firma, metodo, ruta, cuerpo, ahora=None) -> bool:
    try:
        tiempo = int(tiempo_txt)
    except (TypeError, ValueError):
        return False
    ahora = int(time.time()) if ahora is None else ahora
    if abs(ahora - tiempo) > VENTANA_S:
        return False
    esperada = firmar(secreto, tiempo, metodo, ruta, cuerpo)
    return hmac.compare_digest(esperada, firma or "")
```

- [ ] **Step 4: Correr y ver que pasa**

Run: `cd bot-meet && python -m pytest tests/test_firma.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add bot-meet/bot_meet/firma.py bot-meet/tests/test_firma.py
git commit -m "Sign the orders Jarvis sends to the Meet bot"
```

---

### Task 3: Agenda de sesiones

**Files:**
- Create: `bot-meet/bot_meet/agenda.py`
- Test: `bot-meet/tests/test_agenda.py`

- [ ] **Step 1: Escribir la prueba que falla**

`bot-meet/tests/test_agenda.py`:
```python
from datetime import datetime, timedelta, timezone

import pytest

from bot_meet.agenda import Agenda, LinkInvalido, Sesion, SinBotLibre, DatosInvalidos

T0 = datetime(2026, 12, 1, 14, 0, tzinfo=timezone.utc)
URL = "https://meet.google.com/abc-defg-hij"


def sesion(id_="r1", inicio=T0, minutos=60, url=URL):
    return Sesion(id=id_, meet_url=url, inicio=inicio, fin=inicio + timedelta(minutes=minutos),
                  token_subida="tok", url_jarvis="https://asistente.neboaiconsulting.com")


def test_agrega_y_guarda(tmp_path):
    a = Agenda(tmp_path / "agenda.json")
    a.agregar(sesion())
    otra = Agenda(tmp_path / "agenda.json")
    assert otra.obtener("r1").meet_url == URL
    assert otra.obtener("r1").estado == "agendada"


def test_mismo_id_no_duplica(tmp_path):
    a = Agenda(tmp_path / "agenda.json", max_sesiones=1)
    a.agregar(sesion())
    a.agregar(sesion())  # Jarvis reintentó: no cuenta como segunda
    assert len(a.todas()) == 1


@pytest.mark.parametrize("url", [
    "https://meet.google.com/abc-defg-hi",
    "http://meet.google.com/abc-defg-hij",
    "https://evil.com/abc-defg-hij",
    "https://meet.google.com/abc-defg-hij/../x",
])
def test_link_invalido(tmp_path, url):
    with pytest.raises(LinkInvalido):
        Agenda(tmp_path / "a.json").agregar(sesion(url=url))


def test_link_con_parametros_vale(tmp_path):
    Agenda(tmp_path / "a.json").agregar(sesion(url=URL + "?authuser=0"))


def test_fin_antes_de_inicio(tmp_path):
    with pytest.raises(DatosInvalidos):
        Agenda(tmp_path / "a.json").agregar(sesion(minutos=0))


def test_fechas_sin_zona(tmp_path):
    with pytest.raises(DatosInvalidos):
        Agenda(tmp_path / "a.json").agregar(sesion(inicio=T0.replace(tzinfo=None)))


def test_limite_de_bots_a_la_vez(tmp_path):
    a = Agenda(tmp_path / "a.json", max_sesiones=2)
    a.agregar(sesion("r1"))
    a.agregar(sesion("r2", inicio=T0 + timedelta(minutes=30)))
    with pytest.raises(SinBotLibre):
        a.agregar(sesion("r3", inicio=T0 + timedelta(minutes=45)))


def test_sin_cruce_si_alcanza(tmp_path):
    a = Agenda(tmp_path / "a.json", max_sesiones=1)
    a.agregar(sesion("r1"))  # franja 13:59 a 15:15
    a.agregar(sesion("r2", inicio=T0 + timedelta(minutes=80)))  # 15:19, ya no se cruza


def test_canceladas_no_ocupan_lugar(tmp_path):
    a = Agenda(tmp_path / "a.json", max_sesiones=1)
    a.agregar(sesion("r1"))
    assert a.cancelar("r1") is True
    a.agregar(sesion("r2"))
    assert a.cancelar("nada") is False


def test_por_iniciar_y_vencidas(tmp_path):
    a = Agenda(tmp_path / "a.json")
    a.agregar(sesion("r1"))
    assert a.por_iniciar(T0 - timedelta(minutes=2)) == []
    assert [s.id for s in a.por_iniciar(T0 - timedelta(seconds=59))] == ["r1"]
    a.vencer(T0 + timedelta(hours=2))  # pasó la franja (fin + 15 min)
    assert a.obtener("r1").estado == "vencida"
    assert a.por_iniciar(T0 + timedelta(hours=2)) == []


def test_en_curso_se_retoma_al_reiniciar(tmp_path):
    a = Agenda(tmp_path / "a.json")
    a.agregar(sesion("r1"))
    a.marcar("r1", "en_curso")
    assert a.activas() == 1
    otra = Agenda(tmp_path / "a.json")
    assert otra.obtener("r1").estado == "agendada"
```

- [ ] **Step 2: Correrla y ver que falla**

Run: `cd bot-meet && python -m pytest tests/test_agenda.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'bot_meet.agenda'`

- [ ] **Step 3: Implementar**

`bot-meet/bot_meet/agenda.py`:
```python
"""Sesiones agendadas, guardadas en un JSON para sobrevivir reinicios."""
import json
import re
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

PATRON_MEET = re.compile(r"^https://meet\.google\.com/[a-z]{3}-[a-z]{4}-[a-z]{3}(\?[\w=&.-]*)?$")
ANTES = timedelta(minutes=1)
DESPUES = timedelta(minutes=15)
TOPE = timedelta(hours=3)
OCUPAN = ("agendada", "en_curso")


class SinBotLibre(Exception):
    pass


class LinkInvalido(Exception):
    pass


class DatosInvalidos(Exception):
    pass


@dataclass
class Sesion:
    id: str
    meet_url: str
    inicio: datetime
    fin: datetime
    token_subida: str
    url_jarvis: str
    estado: str = "agendada"  # agendada | en_curso | terminada | cancelada | vencida

    def franja(self):
        return self.inicio - ANTES, min(self.fin + DESPUES, self.inicio + TOPE)

    def a_dict(self):
        d = asdict(self)
        d["inicio"], d["fin"] = self.inicio.isoformat(), self.fin.isoformat()
        return d

    @classmethod
    def de_dict(cls, d):
        return cls(**{**d, "inicio": datetime.fromisoformat(d["inicio"]),
                      "fin": datetime.fromisoformat(d["fin"])})


class Agenda:
    def __init__(self, archivo: Path, max_sesiones: int = 2):
        self._archivo = Path(archivo)
        self._max = max_sesiones
        self._lock = threading.RLock()
        self._sesiones: dict[str, Sesion] = {}
        if self._archivo.exists():
            for d in json.loads(self._archivo.read_text(encoding="utf-8")):
                s = Sesion.de_dict(d)
                if s.estado == "en_curso":  # el bot se reinició en medio: se retoma
                    s.estado = "agendada"
                self._sesiones[s.id] = s

    def _guardar(self):
        self._archivo.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._archivo.with_suffix(".tmp")
        tmp.write_text(json.dumps([s.a_dict() for s in self._sesiones.values()]), encoding="utf-8")
        tmp.replace(self._archivo)

    def agregar(self, s: Sesion) -> Sesion:
        if not PATRON_MEET.match(s.meet_url):
            raise LinkInvalido(s.meet_url)
        if s.inicio.tzinfo is None or s.fin.tzinfo is None or s.fin <= s.inicio:
            raise DatosInvalidos("fechas")
        with self._lock:
            if s.id in self._sesiones:
                return self._sesiones[s.id]
            a0, a1 = s.franja()
            cruces = 0
            for otra in self._sesiones.values():
                if otra.estado not in OCUPAN:
                    continue
                b0, b1 = otra.franja()
                if a0 < b1 and b0 < a1:
                    cruces += 1
            if cruces >= self._max:
                raise SinBotLibre(s.id)
            self._sesiones[s.id] = s
            self._guardar()
            return s

    def obtener(self, id_: str):
        return self._sesiones.get(id_)

    def todas(self):
        return list(self._sesiones.values())

    def marcar(self, id_: str, estado: str):
        with self._lock:
            self._sesiones[id_].estado = estado
            self._guardar()

    def cancelar(self, id_: str) -> bool:
        with self._lock:
            s = self._sesiones.get(id_)
            if s is None or s.estado not in OCUPAN:
                return False
            s.estado = "cancelada"
            self._guardar()
            return True

    def por_iniciar(self, ahora: datetime):
        return [s for s in self._sesiones.values()
                if s.estado == "agendada" and s.franja()[0] <= ahora < s.franja()[1]]

    def vencer(self, ahora: datetime):
        with self._lock:
            cambio = False
            for s in self._sesiones.values():
                if s.estado == "agendada" and s.franja()[1] <= ahora:
                    s.estado, cambio = "vencida", True
            if cambio:
                self._guardar()

    def activas(self) -> int:
        return sum(1 for s in self._sesiones.values() if s.estado == "en_curso")
```

- [ ] **Step 4: Correr y ver que pasa**

Run: `cd bot-meet && python -m pytest tests/test_agenda.py -v`
Expected: 14 passed

- [ ] **Step 5: Commit**

```bash
git add bot-meet/bot_meet/agenda.py bot-meet/tests/test_agenda.py
git commit -m "Keep the Meet bot's schedule on disk with a two-bot limit"
```

---

### Task 4: Reglas de salida

**Files:**
- Create: `bot-meet/bot_meet/reglas.py`
- Test: `bot-meet/tests/test_reglas.py`

- [ ] **Step 1: Escribir la prueba que falla**

`bot-meet/tests/test_reglas.py`:
```python
from datetime import datetime, timedelta, timezone

from bot_meet.reglas import motivo_para_salir

E = datetime(2026, 12, 1, 14, 0, tzinfo=timezone.utc)  # entró
FIN = E + timedelta(hours=1)
m = timedelta(minutes=1)


def test_sigue_en_reunion_normal():
    assert motivo_para_salir(E + 30 * m, E, FIN, None, E + 29 * m) is None


def test_sale_si_queda_solo_dos_minutos():
    assert motivo_para_salir(E + 10 * m, E, FIN, E + 9 * m, None) is None
    assert motivo_para_salir(E + 11 * m, E, FIN, E + 9 * m, None) == "solo"


def test_despues_del_fin_espera_15_min_de_silencio():
    assert motivo_para_salir(FIN + 10 * m, E, FIN, None, FIN + 5 * m) is None
    assert motivo_para_salir(FIN + 20 * m, E, FIN, None, FIN + 5 * m) == "silencio"


def test_silencio_desde_antes_del_fin_cuenta_desde_el_fin():
    assert motivo_para_salir(FIN + 14 * m, E, FIN, None, E + 30 * m) is None
    assert motivo_para_salir(FIN + 15 * m, E, FIN, None, E + 30 * m) == "silencio"


def test_sin_voz_detectada_sale_15_min_despues_del_fin():
    assert motivo_para_salir(FIN + 15 * m, E, FIN, None, None) == "silencio"


def test_tope_de_tres_horas():
    assert motivo_para_salir(E + 180 * m, E, E + 240 * m, None, E + 179 * m) == "tope"
```

- [ ] **Step 2: Correrla y ver que falla**

Run: `cd bot-meet && python -m pytest tests/test_reglas.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'bot_meet.reglas'`

- [ ] **Step 3: Implementar**

`bot-meet/bot_meet/reglas.py`:
```python
"""Cuándo sale el bot de la reunión. Función pura, sin reloj propio."""
from datetime import timedelta

SOLO_MAX = timedelta(minutes=2)
SILENCIO_MAX = timedelta(minutes=15)
TOPE = timedelta(hours=3)


def motivo_para_salir(ahora, entrada, fin_evento, solo_desde, ultima_voz):
    """Devuelve "tope", "solo", "silencio" o None (seguir)."""
    if ahora - entrada >= TOPE:
        return "tope"
    if solo_desde is not None and ahora - solo_desde >= SOLO_MAX:
        return "solo"
    if ahora >= fin_evento:
        referencia = max(fin_evento, ultima_voz) if ultima_voz else fin_evento
        if ahora - referencia >= SILENCIO_MAX:
            return "silencio"
    return None
```

- [ ] **Step 4: Correr y ver que pasa**

Run: `cd bot-meet && python -m pytest tests/test_reglas.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add bot-meet/bot_meet/reglas.py bot-meet/tests/test_reglas.py
git commit -m "Decide when the Meet bot leaves a call"
```

---

### Task 5: Subidor con cola en disco

**Files:**
- Create: `bot-meet/bot_meet/subidor.py`
- Test: `bot-meet/tests/test_subidor.py`

- [ ] **Step 1: Escribir la prueba que falla**

`bot-meet/tests/test_subidor.py`:
```python
import json

import httpx

from bot_meet.subidor import Subidor


class Jarvis:
    """Jarvis falso: guarda lo que llega y responde lo que se le pida."""

    def __init__(self):
        self.recibido = []
        self.respuesta = 200

    def __call__(self, req: httpx.Request):
        self.recibido.append((req.method, req.url.path, dict(req.url.params), req.headers.get("authorization"), req.content))
        if self.respuesta == "red":
            raise httpx.ConnectError("caído")
        return httpx.Response(self.respuesta)


def nuevo(tmp_path, jarvis, reloj=lambda: 1000.0):
    cliente = httpx.Client(transport=httpx.MockTransport(jarvis))
    return Subidor(tmp_path / "subidas", "https://j.test/", "r1", "tok", cliente=cliente, reloj=reloj)


def test_envia_en_orden_con_token(tmp_path):
    j = Jarvis()
    s = nuevo(tmp_path, j)
    s.evento("admitido")
    pedazo = tmp_path / "p.ogg"
    pedazo.write_bytes(b"OGG")
    s.audio(1, pedazo)
    s.hablantes([{"t": 3, "nombres": ["Ana"]}])
    assert s.vaciar() == 0
    assert [r[1] for r in j.recibido] == [
        "/api/reuniones/r1/eventos", "/api/reuniones/r1/audio", "/api/reuniones/r1/hablantes"]
    assert j.recibido[0][3] == "Bearer tok"
    assert json.loads(j.recibido[0][4]) == {"tipo": "admitido"}
    assert j.recibido[1][2] == {"n": "1"} and j.recibido[1][4] == b"OGG"
    assert not pedazo.exists()  # se movió a la cola y se borró al confirmarse
    assert list((tmp_path / "subidas").iterdir()) == []


def test_si_jarvis_falla_guarda_y_reintenta_despues(tmp_path):
    j = Jarvis()
    j.respuesta = "red"
    t = [1000.0]
    s = nuevo(tmp_path, j, reloj=lambda: t[0])
    s.evento("admitido")
    s.evento("terminado", motivo="solo", incompleta=False)
    assert s.vaciar() == 2
    j.respuesta = 200
    assert s.vaciar() == 2  # todavía en espera (30 s)
    t[0] += 31
    assert s.vaciar() == 0
    assert [json.loads(r[4])["tipo"] for r in j.recibido if r[4]][-2:] == ["admitido", "terminado"]


def test_la_cola_sobrevive_a_un_reinicio(tmp_path):
    j = Jarvis()
    j.respuesta = 500
    nuevo(tmp_path, j).evento("admitido")
    j.respuesta = 200
    s2 = nuevo(tmp_path, j)
    assert s2.vaciar() == 0
    assert json.loads(j.recibido[-1][4]) == {"tipo": "admitido"}


def test_409_cuenta_como_recibido_y_otros_4xx_se_descartan(tmp_path):
    j = Jarvis()
    j.respuesta = 409
    s = nuevo(tmp_path, j)
    s.evento("admitido")
    assert s.vaciar() == 0
    j.respuesta = 422
    s.evento("admitido")
    assert s.vaciar() == 0  # no se traba la cola por un pedido que nunca va a pasar


def test_descarta_lo_que_tiene_mas_de_24_horas(tmp_path):
    j = Jarvis()
    j.respuesta = 500
    t = [1000.0]
    s = nuevo(tmp_path, j, reloj=lambda: t[0])
    s.evento("admitido")
    t[0] += 24 * 3600 + 1
    assert s.vaciar() == 0
```

- [ ] **Step 2: Correrla y ver que falla**

Run: `cd bot-meet && python -m pytest tests/test_subidor.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'bot_meet.subidor'`

- [ ] **Step 3: Implementar**

`bot-meet/bot_meet/subidor.py`:
```python
"""Cola en disco de lo que va a Jarvis: eventos, pedazos de audio, hablantes.

Cada cosa es un archivo numerado; se envían en orden y se borran solo cuando
Jarvis responde 2xx (o 409, ya lo tenía). Si Jarvis no contesta, se espera
ESPERA_S antes de volver a intentar. Lo que pasa de 24 h se descarta.
"""
import json
import shutil
import time
from pathlib import Path

import httpx

ESPERA_S = 30
VIDA_MAX_S = 24 * 3600


class Subidor:
    def __init__(self, carpeta: Path, url_jarvis: str, id_reunion: str, token: str,
                 cliente: httpx.Client | None = None, reloj=time.time):
        self._dir = Path(carpeta)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._base = f"{url_jarvis.rstrip('/')}/api/reuniones/{id_reunion}"
        self._cabeceras = {"Authorization": f"Bearer {token}"}
        self._cliente = cliente or httpx.Client(timeout=60)
        self._reloj = reloj
        self._proximo_intento = 0.0
        existentes = sorted(self._dir.glob("*.json"))
        self._seq = int(existentes[-1].stem) if existentes else 0

    def _encolar(self, meta: dict, archivo: Path | None = None):
        self._seq += 1
        nombre = f"{self._seq:06d}"
        if archivo is not None:
            shutil.move(str(archivo), self._dir / f"{nombre}.ogg")
            meta["archivo"] = f"{nombre}.ogg"
        meta["creado"] = self._reloj()
        tmp = self._dir / f"{nombre}.tmp"
        tmp.write_text(json.dumps(meta), encoding="utf-8")
        tmp.replace(self._dir / f"{nombre}.json")

    def evento(self, tipo: str, **datos):
        self._encolar({"tipo": "evento", "datos": {"tipo": tipo, **datos}})

    def audio(self, n: int, ruta: Path):
        self._encolar({"tipo": "audio", "n": n}, archivo=Path(ruta))

    def hablantes(self, linea: list):
        self._encolar({"tipo": "hablantes", "datos": {"linea": linea}})

    def _enviar(self, meta: dict) -> httpx.Response:
        if meta["tipo"] == "evento":
            return self._cliente.post(f"{self._base}/eventos", json=meta["datos"], headers=self._cabeceras)
        if meta["tipo"] == "hablantes":
            return self._cliente.post(f"{self._base}/hablantes", json=meta["datos"], headers=self._cabeceras)
        cuerpo = (self._dir / meta["archivo"]).read_bytes()
        return self._cliente.post(f"{self._base}/audio", params={"n": meta["n"]}, content=cuerpo,
                                  headers={**self._cabeceras, "Content-Type": "audio/ogg"})

    def _borrar(self, ruta_json: Path, meta: dict):
        if meta.get("archivo"):
            (self._dir / meta["archivo"]).unlink(missing_ok=True)
        ruta_json.unlink(missing_ok=True)

    def pendientes(self) -> int:
        return len(list(self._dir.glob("*.json")))

    def vaciar(self) -> int:
        """Envía lo que pueda, en orden. Devuelve cuántos quedan pendientes."""
        ahora = self._reloj()
        if ahora < self._proximo_intento:
            return self.pendientes()
        for ruta in sorted(self._dir.glob("*.json")):
            meta = json.loads(ruta.read_text(encoding="utf-8"))
            if ahora - meta["creado"] > VIDA_MAX_S:
                print(f"[subidor] descarto {ruta.name}: más de 24 h sin poder enviarlo")
                self._borrar(ruta, meta)
                continue
            try:
                r = self._enviar(meta)
            except httpx.HTTPError as error:
                print(f"[subidor] Jarvis no responde ({error}); reintento en {ESPERA_S} s")
                self._proximo_intento = ahora + ESPERA_S
                break
            if r.is_success or r.status_code == 409:
                self._borrar(ruta, meta)
            elif 400 <= r.status_code < 500 and r.status_code not in (408, 429):
                print(f"[subidor] Jarvis rechazó {ruta.name} con {r.status_code}; lo descarto")
                self._borrar(ruta, meta)
            else:
                self._proximo_intento = ahora + ESPERA_S
                break
        return self.pendientes()
```

- [ ] **Step 4: Correr y ver que pasa**

Run: `cd bot-meet && python -m pytest tests/test_subidor.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add bot-meet/bot_meet/subidor.py bot-meet/tests/test_subidor.py
git commit -m "Queue everything the Meet bot sends to Jarvis on disk"
```

---

### Task 6: Grabador con ffmpeg

**Files:**
- Create: `bot-meet/bot_meet/grabador.py`
- Test: `bot-meet/tests/test_grabador.py`

- [ ] **Step 1: Escribir la prueba que falla**

`bot-meet/tests/test_grabador.py`:
```python
from bot_meet.grabador import Grabador


class Proceso:
    def __init__(self, args):
        self.args = args
        self.senales = []

    def send_signal(self, s):
        self.senales.append(s)

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.senales.append("kill")


def test_comando_mono_16k_opus_en_pedazos(tmp_path):
    g = Grabador(tmp_path, pedazo_s=300)
    args = g.comando(1)
    assert args[:3] == ["ffmpeg", "-nostdin", "-loglevel"]
    for par in (["-f", "pulse"], ["-i", "grabacion.monitor"], ["-ac", "1"], ["-ar", "16000"],
                ["-c:a", "libopus"], ["-b:a", "24k"], ["-segment_time", "300"],
                ["-segment_start_number", "1"]):
        i = args.index(par[0])
        assert args[i:i + 2] == par
    assert args[-1] == str(tmp_path / "pedazo-%05d.ogg")


def test_pedazos_listos_deja_el_que_se_esta_escribiendo(tmp_path):
    procesos = []
    g = Grabador(tmp_path, popen=lambda a: procesos.append(Proceso(a)) or procesos[-1])
    g.iniciar()
    for n in (1, 2, 3):
        (tmp_path / f"pedazo-{n:05d}.ogg").write_bytes(b"x")
    assert [n for n, _ in g.pedazos_listos()] == [1, 2]
    assert [n for n, _ in g.pedazos_listos(todos=True)] == [1, 2, 3]


def test_al_reiniciar_sigue_la_numeracion(tmp_path):
    procesos = []
    g = Grabador(tmp_path, popen=lambda a: procesos.append(Proceso(a)) or procesos[-1])
    g.iniciar()
    (tmp_path / "pedazo-00001.ogg").write_bytes(b"x")
    (tmp_path / "pedazo-00002.ogg").write_bytes(b"x")
    g.detener()
    assert procesos[0].senales  # SIGINT para que ffmpeg cierre bien el archivo
    for _, ruta in g.pedazos_listos(todos=True):
        ruta.unlink()
    g.iniciar()
    args = procesos[1].args
    assert args[args.index("-segment_start_number") + 1] == "3"
```

- [ ] **Step 2: Correrla y ver que falla**

Run: `cd bot-meet && python -m pytest tests/test_grabador.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'bot_meet.grabador'`

- [ ] **Step 3: Implementar**

`bot-meet/bot_meet/grabador.py`:
```python
"""Graba el monitor de PulseAudio en pedazos Opus mono 16 kHz 24 kbps."""
import signal
import subprocess
from pathlib import Path


class Grabador:
    def __init__(self, carpeta: Path, pedazo_s: int = 300, fuente: str = "grabacion.monitor",
                 popen=None):
        self._dir = Path(carpeta)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._pedazo_s = pedazo_s
        self._fuente = fuente
        self._popen = popen or (lambda args: subprocess.Popen(args))
        self._proc = None
        self._siguiente = 1

    def comando(self, inicio: int) -> list[str]:
        return ["ffmpeg", "-nostdin", "-loglevel", "error",
                "-f", "pulse", "-i", self._fuente,
                "-ac", "1", "-ar", "16000",
                "-c:a", "libopus", "-b:a", "24k", "-application", "voip",
                "-f", "segment", "-segment_time", str(self._pedazo_s),
                "-segment_start_number", str(inicio), "-reset_timestamps", "1",
                str(self._dir / "pedazo-%05d.ogg")]

    def _archivos(self):
        return sorted((int(p.stem.split("-")[1]), p) for p in self._dir.glob("pedazo-*.ogg"))

    def iniciar(self):
        self._proc = self._popen(self.comando(self._siguiente))

    def detener(self):
        if self._proc is None:
            return
        self._proc.send_signal(signal.SIGINT)
        try:
            self._proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._proc.kill()
        self._proc = None
        archivos = self._archivos()
        if archivos:
            self._siguiente = max(self._siguiente, archivos[-1][0] + 1)

    def pedazos_listos(self, todos: bool = False):
        """[(n, ruta)] cerrados. Mientras graba, el último se está escribiendo."""
        archivos = self._archivos()
        if archivos:
            self._siguiente = max(self._siguiente, archivos[-1][0] + 1)
        if self._proc is not None and not todos:
            archivos = archivos[:-1]
        return archivos
```

- [ ] **Step 4: Correr y ver que pasa**

Run: `cd bot-meet && python -m pytest tests/test_grabador.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add bot-meet/bot_meet/grabador.py bot-meet/tests/test_grabador.py
git commit -m "Record the call's audio in five-minute Opus pieces"
```

---

### Task 7: Selectores y control de Meet con Playwright

**Files:**
- Create: `bot-meet/bot_meet/selectores.py`, `bot-meet/bot_meet/meet.py`, `bot-meet/tests/meet_simulado/index.html`
- Test: `bot-meet/tests/test_meet_simulado.py`

- [ ] **Step 1: Instalar Chromium de Playwright en la máquina de desarrollo**

Run: `cd bot-meet && python -m playwright install chromium`
Expected: descarga Chromium y termina sin errores.

- [ ] **Step 2: Crear la página que imita a Meet**

`bot-meet/tests/meet_simulado/index.html`:
```html
<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>Meet simulado</title></head>
<body>
<div id="previa">
  <button aria-label="Desactivar micrófono" onclick="this.dataset.apagado=1">mic</button>
  <button aria-label="Desactivar cámara" onclick="this.dataset.apagado=1">cam</button>
  <button id="unirse" onclick="pedir()">Pedir unirse</button>
</div>
<div id="espera" hidden>Pidiendo unirse...</div>
<div id="rechazo" hidden>Alguien de la llamada rechazó tu solicitud para unirte.</div>
<div id="llamada" hidden>
  <button aria-label="Más opciones" onclick="document.getElementById('menu').hidden=false">...</button>
  <div id="menu" role="menu" hidden>
    <div role="menuitem" onclick="document.getElementById('ajustes').hidden=false">Configuración</div>
  </div>
  <div id="ajustes" role="dialog" hidden>
    <button role="tab">Video</button>
    <label>Resolución de recepción (máxima)
      <select aria-label="Resolución de recepción (máxima)" id="recepcion">
        <option>Alta definición (720p)</option><option>Solo audio</option>
      </select></label>
    <button aria-label="Cerrar" onclick="document.getElementById('ajustes').hidden=true">x</button>
  </div>
  <button aria-label="Chatear con todos" onclick="document.getElementById('chat').hidden=!document.getElementById('chat').hidden">chat</button>
  <div id="chat" hidden>
    <textarea aria-label="Enviar un mensaje" onkeydown="if(event.key==='Enter'){event.preventDefault();enviar(this)}"></textarea>
  </div>
  <ul id="mensajes"></ul>
  <div id="mosaico">
    <div data-participant-id="yo"><span data-self-name="Jarvis · Notas"></span></div>
    <div data-participant-id="p1"><span data-self-name="Ana"></span><i></i></div>
  </div>
  <button aria-label="Abandonar la llamada" onclick="salir()">colgar</button>
</div>
<div id="fuera" hidden>Saliste de la llamada</div>
<script>
const q = new URLSearchParams(location.search);
function pedir() {
  document.getElementById('previa').hidden = true;
  document.getElementById('espera').hidden = false;
  setTimeout(() => {
    document.getElementById('espera').hidden = true;
    document.getElementById(q.get('rechazar') ? 'rechazo' : 'llamada').hidden = false;
  }, Number(q.get('admitir_ms') || 300));
}
function enviar(t) { const li = document.createElement('li'); li.textContent = t.value; document.getElementById('mensajes').append(li); t.value=''; }
function salir() { document.getElementById('llamada').remove(); document.getElementById('fuera').hidden = false; }
window.hablar = (id, si) => { const i = document.querySelector(`[data-participant-id="${id}"] i`); i.toggleAttribute('data-hablando', si); if (si) i.setAttribute('data-hablando', '1'); };
window.quitar = (id) => document.querySelector(`[data-participant-id="${id}"]`).remove();
</script>
</body></html>
```

- [ ] **Step 3: Escribir la prueba que falla**

`bot-meet/tests/test_meet_simulado.py`:
```python
from pathlib import Path

import pytest

pytest.importorskip("playwright")
from bot_meet.meet import MeetPlaywright  # noqa: E402

pytestmark = pytest.mark.navegador
PAGINA = (Path(__file__).parent / "meet_simulado" / "index.html").resolve().as_uri()


@pytest.fixture
def meet(tmp_path):
    m = MeetPlaywright(tmp_path / "perfil", tmp_path / "capturas", headless=True,
                       sel_hablando='[data-hablando="1"]')
    yield m
    m.cerrar()


def test_entra_y_lee_el_estado(meet):
    r = meet.unirse(PAGINA + "?admitir_ms=200", espera_s=10)
    assert r.estado == "admitido"
    e = meet.leer_estado()
    assert e.en_llamada and e.otros == 1 and e.hablando == []
    meet._pagina.evaluate("hablar('p1', true)")
    assert meet.leer_estado().hablando == ["Ana"]
    meet._pagina.evaluate("quitar('p1')")
    assert meet.leer_estado().otros == 0


def test_apaga_micro_y_camara_antes_de_entrar(meet):
    meet.unirse(PAGINA + "?admitir_ms=5000", espera_s=0)
    assert meet._pagina.locator('[aria-label="Desactivar micrófono"]').get_attribute("data-apagado") == "1"
    assert meet._pagina.locator('[aria-label="Desactivar cámara"]').get_attribute("data-apagado") == "1"


def test_rechazado(meet):
    assert meet.unirse(PAGINA + "?rechazar=1&admitir_ms=200", espera_s=10).estado == "rechazado"


def test_nadie_admite_a_tiempo(meet):
    r = meet.unirse(PAGINA + "?admitir_ms=60000", espera_s=2)
    assert (r.estado, r.motivo) == ("rechazado", "sin_respuesta")


def test_solo_audio_y_chat(meet):
    meet.unirse(PAGINA + "?admitir_ms=100", espera_s=10)
    assert meet.solo_audio() is True
    assert meet._pagina.locator("#recepcion").input_value() == "Solo audio"
    assert meet.escribir_chat("Jarvis está grabando") is True
    assert meet._pagina.locator("#mensajes li").inner_text() == "Jarvis está grabando"


def test_salir(meet):
    meet.unirse(PAGINA + "?admitir_ms=100", espera_s=10)
    meet.salir()
    assert meet.leer_estado().en_llamada is False


def test_captura_guarda_imagen(meet, tmp_path):
    meet.unirse(PAGINA + "?admitir_ms=100", espera_s=10)
    ruta = meet.captura("prueba")
    assert ruta.exists() and ruta.suffix == ".png"
```

- [ ] **Step 4: Correrla y ver que falla**

Run: `cd bot-meet && python -m pytest tests/test_meet_simulado.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'bot_meet.meet'`

- [ ] **Step 5: Escribir los selectores**

`bot-meet/bot_meet/selectores.py`:
```python
"""Todo lo que depende de cómo es la página de Meet.

Cuando Google cambie Meet, el mantenimiento es aquí. Chrome se abre en
español (es-419), pero se aceptan también los textos en inglés.
"""
import re

BOTON_UNIRSE = re.compile(r"^(Unirse ahora|Pedir unirse|Solicitar unirse|Join now|Ask to join)$")
APAGAR_MICRO = re.compile(r"Desactivar micrófono|Turn off microphone")
APAGAR_CAMARA = re.compile(r"Desactivar cámara|Turn off camera")
SALIR_LLAMADA = re.compile(r"Abandonar la llamada|Salir de la llamada|Leave call")
TEXTO_RECHAZADO = re.compile(r"rechazó tu solicitud|No puedes unirte|denied your request|You can't join")

MAS_OPCIONES = re.compile(r"Más opciones|More options")
CONFIGURACION = re.compile(r"^(Configuración|Settings)$")
PESTANA_VIDEO = re.compile(r"^(Video|Vídeo)$")
RESOLUCION_RECEPCION = re.compile(r"Resolución de recepción|Receive resolution")
SOLO_AUDIO = "Solo audio"
CERRAR_DIALOGO = re.compile(r"^(Cerrar|Close)$")

BOTON_CHAT = re.compile(r"Chatear con todos|Chat with everyone")
CAJA_CHAT = re.compile(r"Enviar un mensaje|Send a message")

# Cada mosaico de participante lleva data-participant-id; el nombre va en
# data-self-name. "hablando" se reconoce con el selector configurable
# (BOT_MEET_SEL_HABLANDO), que se calibra con una reunión real.
JS_ESTADO = """(selHablando) => {
  const mosaicos = [...document.querySelectorAll('[data-participant-id]')];
  const ids = new Set(mosaicos.map(m => m.getAttribute('data-participant-id')));
  const hablando = [];
  for (const m of mosaicos) {
    const el = m.querySelector('[data-self-name]');
    const nombre = (el ? el.getAttribute('data-self-name') : '').trim();
    if (!nombre) continue;
    let habla = false;
    try { habla = m.matches(selHablando) || !!m.querySelector(selHablando); } catch (e) {}
    if (habla && !hablando.includes(nombre)) hablando.push(nombre);
  }
  return {total: ids.size, hablando};
}"""
```

- [ ] **Step 6: Implementar el control de Meet**

`bot-meet/bot_meet/meet.py`:
```python
"""Chromium manejado por Playwright para entrar a un Meet y seguirlo."""
import time
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import Error as PWError
from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

from . import selectores as S

# Lo mínimo: sin GPU, sin extensiones, sin sincronización, dispositivos falsos
# (no se codifica cámara ni micrófono). El audio de la reunión sale por
# PulseAudio, así que NO va --mute-audio.
ARGUMENTOS = [
    "--disable-gpu", "--disable-extensions", "--disable-sync",
    "--disable-background-networking", "--disable-default-apps",
    "--disable-blink-features=AutomationControlled",
    "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
    "--autoplay-policy=no-user-gesture-required",
    "--window-size=640,360", "--lang=es-419",
]


@dataclass
class ResultadoEntrada:
    estado: str  # admitido | rechazado | fallo
    motivo: str = ""


@dataclass
class EstadoLlamada:
    en_llamada: bool
    otros: int = 0
    hablando: list = field(default_factory=list)


class MeetPlaywright:
    def __init__(self, perfil: Path, capturas: Path, headless: bool = True,
                 sel_hablando: str = '[data-hablando="1"]'):
        self._perfil = Path(perfil)
        self._capturas = Path(capturas)
        self._headless = headless
        self._sel_hablando = sel_hablando
        self._pw = self._contexto = self._pagina = None

    # --- ciclo de vida -------------------------------------------------
    def _abrir(self):
        self._pw = sync_playwright().start()
        self._contexto = self._pw.chromium.launch_persistent_context(
            str(self._perfil), channel="chromium", headless=self._headless,
            args=ARGUMENTOS, ignore_default_args=["--enable-automation"],
            viewport={"width": 640, "height": 360}, locale="es-419",
            permissions=["microphone", "camera"],
        )
        paginas = self._contexto.pages
        self._pagina = paginas[0] if paginas else self._contexto.new_page()

    def cerrar(self):
        try:
            if self._contexto is not None:
                self._contexto.close()
        except PWError:
            pass
        try:
            if self._pw is not None:
                self._pw.stop()
        except Exception:  # Playwright ya muerto: nada que cerrar
            pass
        self._pw = self._contexto = self._pagina = None

    def _viva(self) -> bool:
        return self._pagina is not None and not self._pagina.is_closed()

    def _boton(self, patron):
        return self._pagina.get_by_role("button", name=patron)

    # --- entrar --------------------------------------------------------
    def unirse(self, url: str, espera_s: int) -> ResultadoEntrada:
        if not self._viva():
            self.cerrar()
            self._abrir()
        p = self._pagina
        try:
            p.goto(url, wait_until="domcontentloaded", timeout=60_000)
            if "accounts.google.com" in p.url:
                return ResultadoEntrada("fallo", "sesion_google")
            try:
                self._boton(S.BOTON_UNIRSE).first.wait_for(timeout=45_000)
            except PWTimeout:
                return ResultadoEntrada("fallo", "sin_boton_unirse")
            for patron in (S.APAGAR_MICRO, S.APAGAR_CAMARA):
                boton = self._boton(patron)
                if boton.count():
                    boton.first.click()
            self._boton(S.BOTON_UNIRSE).first.click()
            limite = time.monotonic() + espera_s
            while True:
                if self._boton(S.SALIR_LLAMADA).count():
                    return ResultadoEntrada("admitido")
                if p.get_by_text(S.TEXTO_RECHAZADO).count():
                    return ResultadoEntrada("rechazado", "rechazado")
                if time.monotonic() >= limite:
                    return ResultadoEntrada("rechazado", "sin_respuesta")
                p.wait_for_timeout(1000)
        except PWError as error:
            return ResultadoEntrada("fallo", f"navegador: {error}"[:200])

    # --- ya adentro ----------------------------------------------------
    def solo_audio(self) -> bool:
        """Ajustes > Video > Resolución de recepción: Solo audio. Si falla, sigue."""
        p = self._pagina
        try:
            self._boton(S.MAS_OPCIONES).first.click(timeout=5000)
            p.get_by_role("menuitem", name=S.CONFIGURACION).first.click(timeout=5000)
            p.get_by_role("tab", name=S.PESTANA_VIDEO).first.click(timeout=5000)
            p.get_by_label(S.RESOLUCION_RECEPCION).first.select_option(label=S.SOLO_AUDIO, timeout=5000)
            self._boton(S.CERRAR_DIALOGO).first.click(timeout=5000)
            return True
        except PWError as error:
            print(f"[meet] no pude poner solo audio: {error}")
            p.keyboard.press("Escape")
            return False

    def escribir_chat(self, texto: str) -> bool:
        p = self._pagina
        try:
            self._boton(S.BOTON_CHAT).first.click(timeout=5000)
            caja = p.get_by_label(S.CAJA_CHAT).first
            caja.fill(texto, timeout=5000)
            caja.press("Enter")
            self._boton(S.BOTON_CHAT).first.click(timeout=5000)
            return True
        except PWError as error:
            print(f"[meet] no pude escribir en el chat: {error}")
            return False

    def leer_estado(self) -> EstadoLlamada:
        if not self._viva():
            return EstadoLlamada(False)
        try:
            if not self._boton(S.SALIR_LLAMADA).count():
                return EstadoLlamada(False)
            datos = self._pagina.evaluate(S.JS_ESTADO, self._sel_hablando)
        except PWError:
            return EstadoLlamada(False)
        return EstadoLlamada(True, max(datos["total"] - 1, 0), datos["hablando"])

    def salir(self):
        try:
            if self._viva() and self._boton(S.SALIR_LLAMADA).count():
                self._boton(S.SALIR_LLAMADA).first.click(timeout=5000)
        except PWError:
            pass

    # --- diagnóstico ---------------------------------------------------
    def captura(self, nombre: str) -> Path | None:
        if not self._viva():
            return None
        self._capturas.mkdir(parents=True, exist_ok=True)
        ruta = self._capturas / f"{time.strftime('%Y%m%d-%H%M%S')}-{nombre}.png"
        try:
            self._pagina.screenshot(path=str(ruta))
            return ruta
        except PWError:
            return None

    def volcar(self, nombre: str) -> Path | None:
        """Guarda el HTML de la página (para calibrar selectores)."""
        if not self._viva():
            return None
        self._capturas.mkdir(parents=True, exist_ok=True)
        ruta = self._capturas / f"{time.strftime('%Y%m%d-%H%M%S')}-{nombre}.html"
        ruta.write_text(self._pagina.content(), encoding="utf-8")
        return ruta
```

- [ ] **Step 7: Correr y ver que pasa**

Run: `cd bot-meet && python -m pytest tests/test_meet_simulado.py -v`
Expected: 7 passed. Si sale `Executable doesn't exist`, repetir el Step 1.

- [ ] **Step 8: Commit**

```bash
git add bot-meet/bot_meet/selectores.py bot-meet/bot_meet/meet.py bot-meet/tests/meet_simulado/index.html bot-meet/tests/test_meet_simulado.py
git commit -m "Drive a Meet call with Playwright, tested against a fake Meet page"
```

---

### Task 8: Sesión de punta a punta

**Files:**
- Create: `bot-meet/bot_meet/sesion.py`
- Test: `bot-meet/tests/test_sesion.py`

- [ ] **Step 1: Escribir la prueba que falla**

`bot-meet/tests/test_sesion.py`:
```python
from datetime import datetime, timedelta, timezone

from bot_meet.agenda import Sesion
from bot_meet.meet import EstadoLlamada, ResultadoEntrada
from bot_meet.sesion import AVISO, ejecutar_sesion

T0 = datetime(2026, 12, 1, 14, 0, tzinfo=timezone.utc)


def sesion(minutos=60):
    return Sesion("r1", "https://meet.google.com/abc-defg-hij", T0, T0 + timedelta(minutes=minutos),
                  "tok", "https://j.test")


class Reloj:
    def __init__(self):
        self.t = T0

    def ahora(self):
        return self.t

    def dormir(self, s):
        self.t += timedelta(seconds=s)


class MeetFalso:
    def __init__(self, entradas, estados):
        self.entradas = list(entradas)   # ResultadoEntrada por cada unirse()
        self.estados = estados           # función (segundo) -> EstadoLlamada
        self.chat, self.salio, self.cerrado, self.capturas = [], False, False, []
        self.reloj = None

    def unirse(self, url, espera_s):
        return self.entradas.pop(0)

    def solo_audio(self):
        return True

    def escribir_chat(self, texto):
        self.chat.append(texto)
        return True

    def leer_estado(self):
        return self.estados(int((self.reloj.t - T0).total_seconds()))

    def salir(self):
        self.salio = True

    def captura(self, nombre):
        self.capturas.append(nombre)

    def volcar(self, nombre):
        pass

    def cerrar(self):
        self.cerrado = True


class GrabadorFalso:
    def __init__(self):
        self.inicios, self.detenciones = 0, 0

    def iniciar(self):
        self.inicios += 1

    def detener(self):
        self.detenciones += 1

    def pedazos_listos(self, todos=False):
        return []


class SubidorFalso:
    def __init__(self):
        self.cosas = []

    def evento(self, tipo, **datos):
        self.cosas.append(("evento", tipo, datos))

    def audio(self, n, ruta):
        self.cosas.append(("audio", n))

    def hablantes(self, linea):
        self.cosas.append(("hablantes", linea))

    def vaciar(self):
        return 0

    def tipos(self):
        return [c[1] for c in self.cosas if c[0] == "evento"]


def correr(meet, debe_parar=lambda: False, minutos=60):
    reloj = Reloj()
    meet.reloj = reloj
    g, s = GrabadorFalso(), SubidorFalso()
    r = ejecutar_sesion(sesion(minutos), meet, g, s, debe_parar,
                        ahora=reloj.ahora, dormir=reloj.dormir, espera_admision_s=600)
    return r, g, s


def test_reunion_normal_hasta_quedar_solo():
    # Ana habla del segundo 10 al 20; a los 60 s se va; 2 min después el bot sale.
    def estados(seg):
        if seg >= 60:
            return EstadoLlamada(True, 0, [])
        return EstadoLlamada(True, 1, ["Ana"] if 10 <= seg < 20 else [])
    m = MeetFalso([ResultadoEntrada("admitido")], estados)
    r, g, s = correr(m)
    assert r == "terminada"
    assert s.tipos() == ["esperando", "admitido", "terminado"]
    assert s.cosas[-1] == ("evento", "terminado", {"motivo": "solo", "incompleta": False})
    linea = [c for c in s.cosas if c[0] == "hablantes"][0][1]
    assert linea[0] == {"t": 10, "nombres": ["Ana"]} and len(linea) == 10
    assert m.chat == [AVISO] and m.salio and m.cerrado
    assert g.inicios == 1 and g.detenciones == 1


def test_rechazado():
    m = MeetFalso([ResultadoEntrada("rechazado", "sin_respuesta")], lambda s: EstadoLlamada(False))
    r, g, s = correr(m)
    assert r == "rechazada"
    assert s.cosas[-1] == ("evento", "rechazado", {"motivo": "sin_respuesta"})
    assert g.inicios == 0 and m.cerrado


def test_fallo_al_entrar_guarda_captura():
    m = MeetFalso([ResultadoEntrada("fallo", "sin_boton_unirse")], lambda s: EstadoLlamada(False))
    r, _, s = correr(m)
    assert r == "fallida"
    assert s.cosas[-1] == ("evento", "fallo", {"motivo": "sin_boton_unirse"})
    assert m.capturas == ["fallo-entrar"]


def test_se_cae_y_vuelve_a_entrar_una_vez():
    def estados(seg):
        if 30 <= seg < 31:
            return EstadoLlamada(False)   # Chrome se cayó
        if seg >= 100:
            return EstadoLlamada(True, 0, [])
        return EstadoLlamada(True, 1, [])
    m = MeetFalso([ResultadoEntrada("admitido"), ResultadoEntrada("admitido")], estados)
    r, g, s = correr(m)
    assert r == "terminada" and g.inicios == 2


def test_se_cae_dos_veces_queda_incompleta():
    m = MeetFalso([ResultadoEntrada("admitido"), ResultadoEntrada("fallo", "x")],
                  lambda seg: EstadoLlamada(seg < 30, 1, []))
    r, _, s = correr(m)
    assert r == "incompleta"
    assert s.cosas[-1] == ("evento", "terminado", {"motivo": "caida", "incompleta": True})


def test_cancelada_desde_jarvis():
    m = MeetFalso([ResultadoEntrada("admitido")], lambda seg: EstadoLlamada(True, 1, []))
    llamadas = [0]

    def debe_parar():
        llamadas[0] += 1
        return llamadas[0] > 5
    r, _, s = correr(m, debe_parar)
    assert r == "terminada"
    assert s.cosas[-1][2]["motivo"] == "cancelada"
```

- [ ] **Step 2: Correrla y ver que falla**

Run: `cd bot-meet && python -m pytest tests/test_sesion.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'bot_meet.sesion'`

- [ ] **Step 3: Implementar**

`bot-meet/bot_meet/sesion.py`:
```python
"""Una reunión de punta a punta: entrar, grabar, seguir, salir, subir."""
import time
from datetime import datetime, timezone

from .reglas import motivo_para_salir

AVISO = "Jarvis está grabando esta reunión para tomar notas."
VOLCAR_CADA_S = 10


def _pasar_pedazos(grabador, subidor, todos=False):
    for n, ruta in grabador.pedazos_listos(todos=todos):
        subidor.audio(n, ruta)


def ejecutar_sesion(sesion, meet, grabador, subidor, debe_parar,
                    ahora=lambda: datetime.now(timezone.utc), dormir=time.sleep,
                    espera_admision_s=600, volcar_dom=False) -> str:
    """Devuelve "terminada", "incompleta", "rechazada" o "fallida"."""
    try:
        subidor.evento("esperando")
        subidor.vaciar()
        r = meet.unirse(sesion.meet_url, espera_admision_s)
        if r.estado == "rechazado":
            subidor.evento("rechazado", motivo=r.motivo)
            subidor.vaciar()
            return "rechazada"
        if r.estado != "admitido":
            meet.captura("fallo-entrar")
            subidor.evento("fallo", motivo=r.motivo)
            subidor.vaciar()
            return "fallida"

        subidor.evento("admitido")
        subidor.vaciar()
        meet.solo_audio()
        meet.escribir_chat(AVISO)

        entrada = ahora()
        linea, ultima_voz, solo_desde = [], None, None
        reintento_usado, incompleta, motivo = False, False, None
        ultimo_volcado = 0.0
        grabador.iniciar()
        while True:
            if debe_parar():
                motivo = "cancelada"
                break
            estado = meet.leer_estado()
            t = ahora()
            if not estado.en_llamada:
                grabador.detener()
                _pasar_pedazos(grabador, subidor, todos=True)
                if not reintento_usado:
                    reintento_usado = True
                    if meet.unirse(sesion.meet_url, espera_admision_s).estado == "admitido":
                        grabador.iniciar()
                        dormir(1)
                        continue
                incompleta, motivo = True, "caida"
                break
            if estado.hablando:
                ultima_voz = t
                linea.append({"t": round((t - entrada).total_seconds()), "nombres": estado.hablando})
            solo_desde = (solo_desde or t) if estado.otros == 0 else None
            # Solo para calibrar: guarda el HTML cada 10 s, se detecte voz o no.
            if volcar_dom and time.monotonic() - ultimo_volcado > VOLCAR_CADA_S:
                meet.volcar("llamada")
                ultimo_volcado = time.monotonic()
            _pasar_pedazos(grabador, subidor)
            subidor.vaciar()
            motivo = motivo_para_salir(t, entrada, sesion.fin, solo_desde, ultima_voz)
            if motivo:
                break
            dormir(1)

        meet.salir()
        grabador.detener()
        _pasar_pedazos(grabador, subidor, todos=True)
        subidor.hablantes(linea)
        subidor.evento("terminado", motivo=motivo, incompleta=incompleta)
        subidor.vaciar()
        return "incompleta" if incompleta else "terminada"
    finally:
        meet.cerrar()
```

- [ ] **Step 4: Correr y ver que pasa**

Run: `cd bot-meet && python -m pytest tests/test_sesion.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add bot-meet/bot_meet/sesion.py bot-meet/tests/test_sesion.py
git commit -m "Run one recorded Meet call from joining to the last upload"
```

---

### Task 9: Lanzador

**Files:**
- Create: `bot-meet/bot_meet/lanzador.py`
- Test: `bot-meet/tests/test_lanzador.py`

- [ ] **Step 1: Escribir la prueba que falla**

`bot-meet/tests/test_lanzador.py`:
```python
from datetime import datetime, timedelta, timezone

from bot_meet.agenda import Agenda, Sesion
from bot_meet.config import Config
from bot_meet.lanzador import Lanzador, copiar_perfil

T0 = datetime(2026, 12, 1, 14, 0, tzinfo=timezone.utc)


def sesion(id_, inicio=T0):
    return Sesion(id_, "https://meet.google.com/abc-defg-hij", inicio, inicio + timedelta(hours=1),
                  "tok", "https://j.test")


def preparar(tmp_path, max_sesiones=2):
    config = Config(secreto="s" * 32, datos=tmp_path, max_sesiones=max_sesiones)
    agenda = Agenda(tmp_path / "agenda.json", max_sesiones=max_sesiones)
    corridas = []
    lanz = Lanzador(config, agenda, correr=lambda s: corridas.append(s.id) or "terminada",
                    iniciar_hilo=lambda f: f())
    return agenda, lanz, corridas


def test_arranca_a_la_hora_y_marca_el_final(tmp_path):
    agenda, lanz, corridas = preparar(tmp_path)
    agenda.agregar(sesion("r1"))
    lanz.revisar(T0 - timedelta(minutes=5))
    assert corridas == []
    lanz.revisar(T0)
    assert corridas == ["r1"]
    assert agenda.obtener("r1").estado == "terminada"
    lanz.revisar(T0 + timedelta(seconds=5))
    assert corridas == ["r1"]  # no la vuelve a lanzar


def test_queda_en_curso_mientras_corre(tmp_path):
    agenda, _, _ = preparar(tmp_path, max_sesiones=1)
    lanz = Lanzador(Config(secreto="s" * 32, datos=tmp_path, max_sesiones=1), agenda,
                    correr=lambda s: "terminada", iniciar_hilo=lambda f: None)  # quedan en curso
    agenda.agregar(sesion("r1"))
    lanz.revisar(T0)
    assert agenda.obtener("r1").estado == "en_curso"


def test_vence_las_que_ya_pasaron(tmp_path):
    agenda, lanz, corridas = preparar(tmp_path)
    agenda.agregar(sesion("r1"))
    lanz.revisar(T0 + timedelta(hours=3))
    assert corridas == [] and agenda.obtener("r1").estado == "vencida"


def test_un_error_en_la_sesion_no_tumba_el_lanzador(tmp_path):
    config = Config(secreto="s" * 32, datos=tmp_path)
    agenda = Agenda(tmp_path / "agenda.json")

    def explota(s):
        raise RuntimeError("chrome")
    lanz = Lanzador(config, agenda, correr=explota, iniciar_hilo=lambda f: f())
    agenda.agregar(sesion("r1"))
    lanz.revisar(T0)
    assert agenda.obtener("r1").estado == "terminada"


def test_copiar_perfil_sin_candados_ni_cache(tmp_path):
    base = tmp_path / "perfil"
    (base / "Default" / "Cache").mkdir(parents=True)
    (base / "Default" / "Cookies").write_text("c")
    (base / "SingletonLock").write_text("x")
    destino = copiar_perfil(base, tmp_path / "copia")
    assert (destino / "Default" / "Cookies").read_text() == "c"
    assert not (destino / "SingletonLock").exists()
    assert not (destino / "Default" / "Cache").exists()
```

- [ ] **Step 2: Correrla y ver que falla**

Run: `cd bot-meet && python -m pytest tests/test_lanzador.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'bot_meet.lanzador'`

- [ ] **Step 3: Implementar**

`bot-meet/bot_meet/lanzador.py`:
```python
"""Arranca cada sesión a su hora (en un hilo), reintenta subidas y limpia."""
import asyncio
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path

from .agenda import Agenda, Sesion
from .config import Config

IGNORAR_PERFIL = shutil.ignore_patterns(
    "Singleton*", "Cache", "Code Cache", "GPUCache", "Service Worker", "*.log", "Crashpad")


def copiar_perfil(base: Path, destino: Path) -> Path:
    if destino.exists():
        shutil.rmtree(destino)
    if base.exists():
        shutil.copytree(base, destino, ignore=IGNORAR_PERFIL)
    else:
        destino.mkdir(parents=True)
    return destino


def _hilo(funcion):
    threading.Thread(target=funcion, daemon=True).start()


class Lanzador:
    def __init__(self, config: Config, agenda: Agenda, correr=None, iniciar_hilo=_hilo):
        self._config = config
        self._agenda = agenda
        self._correr = correr or self._correr_de_verdad
        self._iniciar_hilo = iniciar_hilo

    def carpeta(self, id_: str) -> Path:
        return self._config.datos / "sesiones" / id_

    # --- arranque ------------------------------------------------------
    def revisar(self, ahora: datetime):
        self._agenda.vencer(ahora)
        for s in self._agenda.por_iniciar(ahora):
            if self._agenda.activas() >= self._config.max_sesiones:
                break
            self._agenda.marcar(s.id, "en_curso")
            self._iniciar_hilo(lambda s=s: self._una(s))

    def _una(self, s: Sesion):
        try:
            resultado = self._correr(s)
            print(f"[lanzador] {s.id}: {resultado}")
        except Exception as error:  # nunca tumbar el servicio por una reunión
            print(f"[lanzador] {s.id}: error {error!r}")
        finally:
            if self._agenda.obtener(s.id).estado == "en_curso":
                self._agenda.marcar(s.id, "terminada")

    def _correr_de_verdad(self, s: Sesion) -> str:
        from .grabador import Grabador
        from .meet import MeetPlaywright
        from .sesion import ejecutar_sesion
        from .subidor import Subidor

        c = self._config
        dir_ = self.carpeta(s.id)
        perfil = copiar_perfil(c.datos / "perfil", dir_ / "perfil")
        meet = MeetPlaywright(perfil, c.datos / "capturas", headless=c.headless,
                              sel_hablando=c.sel_hablando)
        grabador = Grabador(dir_ / "grabacion", pedazo_s=c.pedazo_s)
        subidor = Subidor(dir_ / "subidas", s.url_jarvis, s.id, s.token_subida)
        try:
            return ejecutar_sesion(
                s, meet, grabador, subidor,
                debe_parar=lambda: self._agenda.obtener(s.id).estado == "cancelada",
                espera_admision_s=c.espera_admision_s, volcar_dom=c.volcar_dom)
        finally:
            shutil.rmtree(perfil, ignore_errors=True)

    # --- subidas pendientes y limpieza ---------------------------------
    def reintentar_subidas(self):
        from .subidor import Subidor
        for s in self._agenda.todas():
            if s.estado in ("agendada", "en_curso"):
                continue
            dir_ = self.carpeta(s.id)
            if not dir_.exists():
                continue
            subidas = dir_ / "subidas"
            quedan = 0
            if subidas.exists():
                quedan = Subidor(subidas, s.url_jarvis, s.id, s.token_subida).vaciar()
            if quedan == 0:
                shutil.rmtree(dir_, ignore_errors=True)

    async def correr_siempre(self):
        vueltas = 0
        while True:
            try:
                self.revisar(datetime.now(timezone.utc))
                if vueltas % 12 == 0:  # cada minuto
                    await asyncio.to_thread(self.reintentar_subidas)
            except Exception as error:
                print(f"[lanzador] vuelta fallida: {error!r}")
            vueltas += 1
            await asyncio.sleep(5)
```

- [ ] **Step 4: Correr y ver que pasa**

Run: `cd bot-meet && python -m pytest tests/test_lanzador.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add bot-meet/bot_meet/lanzador.py bot-meet/tests/test_lanzador.py
git commit -m "Launch each scheduled Meet session on time and retry its uploads"
```

---

### Task 10: API del bot

**Files:**
- Create: `bot-meet/bot_meet/app.py`
- Test: `bot-meet/tests/test_app.py`

- [ ] **Step 1: Escribir la prueba que falla**

`bot-meet/tests/test_app.py`:
```python
import json
import time

from fastapi.testclient import TestClient

from bot_meet.agenda import Agenda
from bot_meet.app import crear_app
from bot_meet.config import Config
from bot_meet.firma import firmar

S = "s" * 32
CUERPO = {"id": "r1", "meet_url": "https://meet.google.com/abc-defg-hij",
          "inicio": "2026-12-01T14:00:00+00:00", "fin": "2026-12-01T15:00:00+00:00",
          "token_subida": "tok", "url_jarvis": "https://asistente.neboaiconsulting.com"}


def cliente(tmp_path, max_sesiones=2):
    config = Config(secreto=S, datos=tmp_path, max_sesiones=max_sesiones)
    agenda = Agenda(tmp_path / "agenda.json", max_sesiones=max_sesiones)
    return TestClient(crear_app(config, agenda, lanzador=None)), agenda


def firmado(metodo, ruta, cuerpo=b""):
    t = int(time.time())
    return {"X-Bot-Tiempo": str(t), "X-Bot-Firma": firmar(S, t, metodo, ruta, cuerpo)}


def post(c, cuerpo):
    datos = json.dumps(cuerpo).encode()
    return c.post("/v1/sesiones", content=datos,
                  headers={**firmado("POST", "/v1/sesiones", datos), "Content-Type": "application/json"})


def test_agenda_una_sesion(tmp_path):
    c, agenda = cliente(tmp_path)
    r = post(c, CUERPO)
    assert r.status_code == 202 and r.json() == {"estado": "agendada"}
    assert agenda.obtener("r1").token_subida == "tok"


def test_sin_firma_401(tmp_path):
    c, _ = cliente(tmp_path)
    assert c.post("/v1/sesiones", json=CUERPO).status_code == 401


def test_link_invalido_400(tmp_path):
    c, _ = cliente(tmp_path)
    r = post(c, {**CUERPO, "meet_url": "https://zoom.us/j/1"})
    assert r.status_code == 400 and r.json() == {"error": "link_invalido"}


def test_datos_invalidos_400(tmp_path):
    c, _ = cliente(tmp_path)
    assert post(c, {"id": "r1"}).json() == {"error": "datos_invalidos"}
    assert post(c, {**CUERPO, "url_jarvis": "ftp://x"}).json() == {"error": "datos_invalidos"}


def test_sin_bot_libre_409(tmp_path):
    c, _ = cliente(tmp_path, max_sesiones=1)
    post(c, CUERPO)
    r = post(c, {**CUERPO, "id": "r2"})
    assert r.status_code == 409 and r.json() == {"error": "sin_bot_libre"}


def test_cancelar(tmp_path):
    c, agenda = cliente(tmp_path)
    post(c, CUERPO)
    r = c.delete("/v1/sesiones/r1", headers=firmado("DELETE", "/v1/sesiones/r1"))
    assert r.status_code == 200 and agenda.obtener("r1").estado == "cancelada"
    assert c.delete("/v1/sesiones/r9", headers=firmado("DELETE", "/v1/sesiones/r9")).status_code == 404


def test_salud_sin_firma(tmp_path):
    c, _ = cliente(tmp_path)
    post(c, CUERPO)
    d = c.get("/v1/salud").json()
    assert d["ok"] is True and d["agendadas"] == 1 and d["activas"] == 0
    assert "memoria_libre_mb" in d and "carga" in d
```

- [ ] **Step 2: Correrla y ver que falla**

Run: `cd bot-meet && python -m pytest tests/test_app.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'bot_meet.app'`

- [ ] **Step 3: Implementar**

`bot-meet/bot_meet/app.py`:
```python
"""API del bot: Jarvis agenda y cancela; el monitor mira la salud."""
import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .agenda import Agenda, DatosInvalidos, LinkInvalido, Sesion, SinBotLibre
from .config import Config, leer_config
from .firma import verificar

CAMPOS = ("id", "meet_url", "inicio", "fin", "token_subida", "url_jarvis")


def _memoria_libre_mb():
    try:
        with open("/proc/meminfo") as f:
            for linea in f:
                if linea.startswith("MemAvailable:"):
                    return int(linea.split()[1]) // 1024
    except OSError:
        pass
    return None


def _carga():
    try:
        return os.getloadavg()[0]
    except (OSError, AttributeError):
        return None


def crear_app(config: Config, agenda: Agenda, lanzador=None) -> FastAPI:
    @asynccontextmanager
    async def vida(app):
        tarea = asyncio.create_task(lanzador.correr_siempre()) if lanzador else None
        yield
        if tarea:
            tarea.cancel()

    app = FastAPI(lifespan=vida, docs_url=None, redoc_url=None, openapi_url=None)

    async def firmado(peticion: Request) -> bytes | None:
        cuerpo = await peticion.body()
        ok = verificar(config.secreto, peticion.headers.get("X-Bot-Tiempo"),
                       peticion.headers.get("X-Bot-Firma"), peticion.method,
                       peticion.url.path, cuerpo)
        return cuerpo if ok else None

    @app.post("/v1/sesiones")
    async def agendar(peticion: Request):
        cuerpo = await firmado(peticion)
        if cuerpo is None:
            return JSONResponse({"error": "firma"}, status_code=401)
        try:
            d = json.loads(cuerpo)
            if not all(isinstance(d.get(k), str) and d.get(k) for k in CAMPOS):
                raise DatosInvalidos("campos")
            if not (d["url_jarvis"].startswith("https://") or d["url_jarvis"].startswith("http://127.0.0.1")):
                raise DatosInvalidos("url_jarvis")
            s = Sesion(id=d["id"], meet_url=d["meet_url"],
                       inicio=datetime.fromisoformat(d["inicio"]), fin=datetime.fromisoformat(d["fin"]),
                       token_subida=d["token_subida"], url_jarvis=d["url_jarvis"])
            agenda.agregar(s)
        except LinkInvalido:
            return JSONResponse({"error": "link_invalido"}, status_code=400)
        except SinBotLibre:
            return JSONResponse({"error": "sin_bot_libre"}, status_code=409)
        except (DatosInvalidos, ValueError, TypeError, AttributeError):
            return JSONResponse({"error": "datos_invalidos"}, status_code=400)
        return JSONResponse({"estado": "agendada"}, status_code=202)

    @app.delete("/v1/sesiones/{id_}")
    async def cancelar(id_: str, peticion: Request):
        if await firmado(peticion) is None:
            return JSONResponse({"error": "firma"}, status_code=401)
        if not agenda.cancelar(id_):
            return JSONResponse({"error": "no_existe"}, status_code=404)
        return {"estado": "cancelada"}

    @app.get("/v1/salud")
    async def salud():
        todas = agenda.todas()
        return {"ok": True, "activas": agenda.activas(),
                "agendadas": sum(1 for s in todas if s.estado == "agendada"),
                "memoria_libre_mb": _memoria_libre_mb(), "carga": _carga()}

    return app


def crear_app_desde_entorno() -> FastAPI:
    from .lanzador import Lanzador
    config = leer_config()
    agenda = Agenda(config.datos / "agenda.json", max_sesiones=config.max_sesiones)
    return crear_app(config, agenda, Lanzador(config, agenda))
```

- [ ] **Step 4: Correr y ver que pasa**

Run: `cd bot-meet && python -m pytest tests/test_app.py -v`
Expected: 7 passed

- [ ] **Step 5: Correr todas las pruebas del bot**

Run: `cd bot-meet && python -m pytest -v`
Expected: todo pasa (las de `navegador` también, si Chromium está instalado).

- [ ] **Step 6: Commit**

```bash
git add bot-meet/bot_meet/app.py bot-meet/tests/test_app.py
git commit -m "Expose the Meet bot's signed schedule API and its health"
```

---

### Task 11: Herramientas para la prueba real

**Files:**
- Create: `bot-meet/bot_meet/herramientas/__init__.py`, `bot-meet/bot_meet/herramientas/agendar.py`, `bot-meet/bot_meet/herramientas/receptor_prueba.py`

Estas dos no llevan prueba propia: se usan en la tarea 14 contra el bot real y reutilizan `firmar`, que ya está probada.

- [ ] **Step 1: Escribir el agendador de línea de comandos**

`bot-meet/bot_meet/herramientas/__init__.py`: vacío.

`bot-meet/bot_meet/herramientas/agendar.py`:
```python
"""Agenda una sesión firmada en el bot local.

    python -m bot_meet.herramientas.agendar https://meet.google.com/abc-defg-hij \
        --minutos 30 --jarvis http://127.0.0.1:9000
"""
import argparse
import json
import os
import secrets
import time
from datetime import datetime, timedelta, timezone

import httpx

from ..firma import firmar


def main():
    p = argparse.ArgumentParser()
    p.add_argument("meet_url")
    p.add_argument("--minutos", type=int, default=30)
    p.add_argument("--jarvis", default="http://127.0.0.1:9000")
    p.add_argument("--bot", default="http://127.0.0.1:8000")
    a = p.parse_args()
    ahora = datetime.now(timezone.utc)
    cuerpo = json.dumps({
        "id": f"prueba-{int(time.time())}", "meet_url": a.meet_url,
        "inicio": ahora.isoformat(), "fin": (ahora + timedelta(minutes=a.minutos)).isoformat(),
        "token_subida": secrets.token_urlsafe(24), "url_jarvis": a.jarvis,
    }).encode()
    t = int(time.time())
    firma = firmar(os.environ["BOT_MEET_SECRETO"], t, "POST", "/v1/sesiones", cuerpo)
    r = httpx.post(f"{a.bot}/v1/sesiones", content=cuerpo, headers={
        "X-Bot-Tiempo": str(t), "X-Bot-Firma": firma, "Content-Type": "application/json"})
    print(r.status_code, r.text, json.loads(cuerpo)["id"])


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Escribir el Jarvis falso**

`bot-meet/bot_meet/herramientas/receptor_prueba.py`:
```python
"""Jarvis falso para la prueba real: guarda en /data/prueba/<id>/ lo que llega.

    python -m bot_meet.herramientas.receptor_prueba    # escucha en 127.0.0.1:9000
"""
import json
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request

DESTINO = Path("/data/prueba")
app = FastAPI()


@app.post("/api/reuniones/{id_}/eventos")
async def eventos(id_: str, peticion: Request):
    d = DESTINO / id_
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "eventos.jsonl", "a", encoding="utf-8") as f:
        f.write((await peticion.body()).decode() + "\n")
    print("evento", id_, (await peticion.body()).decode())
    return {"ok": True}


@app.post("/api/reuniones/{id_}/audio")
async def audio(id_: str, n: int, peticion: Request):
    d = DESTINO / id_
    d.mkdir(parents=True, exist_ok=True)
    (d / f"pedazo-{n:05d}.ogg").write_bytes(await peticion.body())
    print("audio", id_, n)
    return {"ok": True}


@app.post("/api/reuniones/{id_}/hablantes")
async def hablantes(id_: str, peticion: Request):
    d = DESTINO / id_
    d.mkdir(parents=True, exist_ok=True)
    (d / "hablantes.json").write_text(json.dumps(await peticion.json(), ensure_ascii=False), encoding="utf-8")
    return {"ok": True}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=9000)
```

- [ ] **Step 3: Revisar que importan**

Run: `cd bot-meet && python -c "import bot_meet.herramientas.agendar, bot_meet.herramientas.receptor_prueba; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add bot-meet/bot_meet/herramientas
git commit -m "Add a signed scheduling CLI and a fake Jarvis for the live test"
```

---

### Task 12: Imagen Docker

**Files:**
- Create: `bot-meet/Dockerfile`, `bot-meet/entrypoint.sh`, `bot-meet/iniciar-sesion.sh`, `bot-meet/.dockerignore`

- [ ] **Step 1: Escribir el Dockerfile**

`bot-meet/Dockerfile`:
```dockerfile
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    XDG_RUNTIME_DIR=/tmp/runtime-bot HOME=/home/bot
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg pulseaudio pulseaudio-utils xvfb x11vnc fonts-liberation \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && playwright install --with-deps chromium \
 && rm -rf /var/lib/apt/lists/*
COPY bot_meet ./bot_meet
COPY entrypoint.sh iniciar-sesion.sh ./
RUN chmod +x entrypoint.sh iniciar-sesion.sh \
 && useradd -m -d /home/bot bot && mkdir -p /data && chown bot:bot /data
USER bot
EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
```

`playwright install chromium` trae Chromium completo, que es el que usa `channel="chromium"` (headless nuevo, con salida de audio a PulseAudio).

- [ ] **Step 2: Escribir el arranque**

`bot-meet/entrypoint.sh`:
```sh
#!/bin/sh
# PulseAudio con una salida falsa "grabacion": Chrome suena ahí y ffmpeg graba
# su monitor. Xvfb solo si se pidió Chrome con pantalla (BOT_MEET_HEADLESS=0).
set -e
mkdir -p "$XDG_RUNTIME_DIR" && chmod 700 "$XDG_RUNTIME_DIR"
pulseaudio -D --exit-idle-time=-1 --disallow-exit --log-target=stderr
for _ in 1 2 3 4 5 6 7 8 9 10; do pactl info >/dev/null 2>&1 && break; sleep 0.5; done
pactl load-module module-null-sink sink_name=grabacion sink_properties=device.description=grabacion >/dev/null
pactl set-default-sink grabacion
if [ "${BOT_MEET_HEADLESS:-1}" = "0" ]; then
  Xvfb :99 -screen 0 640x360x16 -nolisten tcp &
  export DISPLAY=:99
fi
exec uvicorn bot_meet.app:crear_app_desde_entorno --factory --host 0.0.0.0 --port 8000 --no-access-log
```

- [ ] **Step 3: Escribir el login de Google**

`bot-meet/iniciar-sesion.sh`:
```sh
#!/bin/sh
# Abre Chromium con el perfil base (/data/perfil) para iniciar sesión en Google
# UNA vez. Se ve desde la PC de Jorge por un túnel SSH:
#   modo devtools (por defecto): chrome://inspect -> localhost:9222
#   modo vnc: un visor VNC a localhost:5900
# Se corre con red del host (ver servidor/LEEME.md).
set -e
MODO="${1:-devtools}"
CHROME=$(python -c "from playwright.sync_api import sync_playwright as s; p=s().start(); print(p.chromium.executable_path); p.stop()")
Xvfb :98 -screen 0 1280x800x16 -nolisten tcp &
export DISPLAY=:98
sleep 1
if [ "$MODO" = "vnc" ]; then
  x11vnc -display :98 -localhost -rfbport 5900 -nopw -forever -quiet &
fi
exec "$CHROME" --user-data-dir=/data/perfil --no-first-run --lang=es-419 \
  --remote-debugging-port=9222 --remote-debugging-address=127.0.0.1 \
  --disable-blink-features=AutomationControlled \
  https://accounts.google.com/
```

`bot-meet/.dockerignore`:
```
tests
servidor
__pycache__
*.pyc
```

- [ ] **Step 4: Commit**

```bash
git add bot-meet/Dockerfile bot-meet/entrypoint.sh bot-meet/iniciar-sesion.sh bot-meet/.dockerignore
git commit -m "Package the Meet bot with Chromium, PulseAudio and ffmpeg"
```

(La imagen se construye en el EC2 en la tarea 13: en esta PC no hay Docker.)

---

### Task 13: Servidor: Compose, Caddy, despliegue

**Files:**
- Create: `bot-meet/servidor/docker-compose.yml`, `bot-meet/servidor/Caddyfile`, `bot-meet/servidor/desplegar.sh`, `bot-meet/servidor/bot-meet-despliegue.service`, `bot-meet/servidor/bot-meet-despliegue.timer`, `bot-meet/servidor/LEEME.md`

- [ ] **Step 1: Escribir Compose y Caddy**

`bot-meet/servidor/docker-compose.yml`:
```yaml
# Bot de Meet en su EC2 (18.227.166.134, t3.small, us-east-2). Ver LEEME.md.
name: bot-meet

x-base: &base
  restart: unless-stopped
  logging: { driver: json-file, options: { max-size: 10m, max-file: "3" } }

services:
  bot:
    <<: *base
    build: ./repo/bot-meet
    image: bot-meet-bot:latest
    env_file: bot.env
    volumes: [datos:/data]
    shm_size: 256m          # Chrome usa /dev/shm; el de Docker (64 MB) se queda corto
    mem_limit: 1600m        # deja aire a Caddy y al sistema en 2 GB + swap
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/v1/salud', timeout=4)"]
      interval: 30s
      timeout: 5s
      retries: 3

  caddy:
    <<: *base
    image: caddy:2-alpine
    ports: ["80:80", "443:443"]
    volumes: [./Caddyfile:/etc/caddy/Caddyfile:ro, caddy:/data]
    mem_limit: 64m

volumes:
  datos:
  caddy:
```

`bot-meet/servidor/Caddyfile`:
```
# Solo Jarvis (54.174.88.26) habla con el bot; el monitor (nebocore) mira la salud.
bot-meet.neboaiconsulting.com {
	@monitor {
		remote_ip 3.132.126.1
		path /v1/salud
	}
	handle @monitor {
		reverse_proxy bot:8000
	}
	@jarvis remote_ip 54.174.88.26
	handle @jarvis {
		reverse_proxy bot:8000
	}
	handle {
		respond 403
	}
}
```

- [ ] **Step 2: Escribir el despliegue**

`bot-meet/servidor/desplegar.sh`:
```bash
#!/usr/bin/env bash
# Despliega el bot desde GitHub: si cambió bot-meet/ en la rama, reconstruye.
#   desplegar.sh          -> solo si hay cambios en bot-meet/
#   desplegar.sh forzar   -> reconstruye igual
# Lo corre cada minuto bot-meet-despliegue.timer. Registro: /var/log/bot-meet-despliegue.log
# No reinicia el bot si hay una reunión grabándose: espera a la próxima vuelta.
set -euo pipefail
cd /opt/bot-meet
exec 9>/run/bot-meet-despliegue.lock
flock -n 9 || exit 0
RAMA="$(cat rama 2>/dev/null || echo main)"
log() { echo "$(date -u +%FT%TZ) $*" >> /var/log/bot-meet-despliegue.log; }

git -C repo fetch -q --depth 1 origin "$RAMA" || { log "no se pudo leer GitHub"; exit 0; }
antes=$(git -C repo rev-parse HEAD)
nuevo=$(git -C repo rev-parse FETCH_HEAD)
if [ "${1:-}" != "forzar" ]; then
  [ "$antes" = "$nuevo" ] && exit 0
  if git -C repo diff --quiet "$antes" "$nuevo" -- bot-meet 2>/dev/null; then
    git -C repo reset -q --hard FETCH_HEAD
    exit 0
  fi
  # El puerto 8000 no está publicado en el host: se pregunta desde adentro.
  activas=$(docker compose exec -T bot python -c "import json,urllib.request; print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/v1/salud', timeout=4))['activas'])" 2>/dev/null || echo 0)
  if [ "$activas" != "0" ]; then
    log "hay $activas reunión(es) grabándose; despliego después"
    exit 0
  fi
fi
git -C repo reset -q --hard FETCH_HEAD
cp repo/bot-meet/servidor/docker-compose.yml repo/bot-meet/servidor/Caddyfile .
log "bot: ${antes:0:7} -> ${nuevo:0:7}"
docker image inspect bot-meet-bot:latest >/dev/null 2>&1 && docker tag bot-meet-bot:latest bot-meet-bot:anterior
if ! docker compose build bot >> /var/log/bot-meet-despliegue.log 2>&1; then
  log "FALLÓ la construcción; sigue lo anterior"; exit 1
fi
docker compose up -d >> /var/log/bot-meet-despliegue.log 2>&1
for _ in $(seq 24); do
  sleep 5
  estado=$(docker inspect -f '{{.State.Health.Status}}' "$(docker compose ps -q bot)" 2>/dev/null || true)
  [ "$estado" = "healthy" ] && break
done
if [ "$estado" != "healthy" ]; then
  log "el bot no quedó sano ($estado): vuelvo a la imagen anterior"
  docker tag bot-meet-bot:anterior bot-meet-bot:latest
  docker compose up -d --no-build bot >> /var/log/bot-meet-despliegue.log 2>&1
  exit 1
fi
docker image prune -f >/dev/null 2>&1 || true
docker builder prune -f --keep-storage 500MB >/dev/null 2>&1 || true
log "listo"
```

`bot-meet/servidor/bot-meet-despliegue.service`:
```ini
[Unit]
Description=Desplegar el bot de Meet si cambió en GitHub

[Service]
Type=oneshot
ExecStart=/opt/bot-meet/desplegar.sh
```

`bot-meet/servidor/bot-meet-despliegue.timer`:
```ini
[Unit]
Description=Mirar GitHub cada minuto y desplegar el bot de Meet

[Timer]
OnBootSec=2min
OnUnitActiveSec=1min

[Install]
WantedBy=timers.target
```

- [ ] **Step 3: Escribir el LEEME**

`bot-meet/servidor/LEEME.md`:
````markdown
# Servidor del bot de Meet (EC2 18.227.166.134, `ssh bot-meet`)

t3.small (2 GB + 2 GB de swap), us-east-2, Ubuntu 24.04. Copia versionada de
lo que vive en `/opt/bot-meet`. El secreto (`bot.env`) NO está aquí.

| Ruta | Qué es |
|---|---|
| `/opt/bot-meet/repo` | clon de Adminnebo/Jarvis (llave de despliegue de solo lectura) |
| `/opt/bot-meet/rama` | rama que se despliega (`main`; durante la prueba, la rama de trabajo) |
| `/opt/bot-meet/bot.env` | `BOT_MEET_SECRETO=...` (el mismo que tiene Jarvis), `BOT_MEET_SEL_HABLANDO=...` |
| volumen `bot-meet_datos` | `/data`: agenda, perfil de Google, sesiones, capturas |

**Desplegar = push a la rama.** El timer mira cada minuto; si hay una
reunión grabándose, espera. Registro: `sudo tail -f /var/log/bot-meet-despliegue.log`.

## Iniciar sesión con la cuenta de Google del bot (una vez, o si se cierra)

En el servidor, con el bot apagado para que no use el perfil:

    cd /opt/bot-meet && sudo docker compose stop bot
    sudo docker run --rm -it --network host -v bot-meet_datos:/data \
      --entrypoint ./iniciar-sesion.sh bot-meet-bot:latest

En la PC: `ssh -L 9222:127.0.0.1:9222 bot-meet`, abrir Chrome en
`chrome://inspect`, «Configure…» → `localhost:9222`, «inspect» en la pestaña
de Google y entrar con la cuenta. Si Google dice que el navegador no es seguro,
usar VNC: correr el script con `vnc` al final, túnel `-L 5900:127.0.0.1:5900`
y un visor VNC a `localhost:5900`. Al terminar: Ctrl+C y `sudo docker compose up -d bot`.

## Ver qué pasó

    sudo docker compose logs --tail 200 bot
    sudo docker compose exec bot ls /data/capturas      # capturas de fallos
    sudo docker compose exec -T bot python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/v1/salud').read().decode())"
````

- [ ] **Step 4: Commit y push de la rama**

```bash
git add bot-meet/servidor
git commit -m "Deploy the Meet bot behind Caddy on its own EC2"
git push -u origin feat/bot-grabacion-meet
```
(Si el push pide credenciales, usar la de `username=jorgedsz`, ver la memoria de GitHub.)

- [ ] **Step 5: Pedirle a Jorge las dos cosas de AWS y DNS**

Jorge tiene que:
1. Crear el registro DNS `A bot-meet.neboaiconsulting.com → 18.227.166.134`.
2. Abrir en el grupo de seguridad del EC2 los puertos **80 y 443 para todos** (Let's Encrypt valida desde IPs variables; Caddy filtra por IP y el bot pide firma), y dejar el 22 solo desde su IP.

Esperar confirmación antes del Step 7.

- [ ] **Step 6: Llave de despliegue y montaje en el servidor**

```bash
ssh bot-meet 'ssh-keygen -t ed25519 -N "" -f ~/.ssh/github_jarvis -C bot-meet-despliegue && cat ~/.ssh/github_jarvis.pub'
```
Agregar esa llave pública como deploy key de solo lectura:
```bash
gh repo deploy-key add - --repo Adminnebo/Jarvis --title "bot-meet EC2 (solo lectura)" <<< "<la llave de arriba>"
```
Luego, en el servidor:
```bash
ssh bot-meet 'set -e
printf "Host github.com\n  IdentityFile ~/.ssh/github_jarvis\n  IdentitiesOnly yes\n" >> ~/.ssh/config
ssh-keyscan github.com >> ~/.ssh/known_hosts 2>/dev/null
sudo mkdir -p /opt/bot-meet && sudo chown ubuntu:ubuntu /opt/bot-meet
cd /opt/bot-meet
git clone -q --depth 1 -b feat/bot-grabacion-meet git@github.com:Adminnebo/Jarvis.git repo
echo feat/bot-grabacion-meet > rama
cp repo/bot-meet/servidor/desplegar.sh repo/bot-meet/servidor/docker-compose.yml repo/bot-meet/servidor/Caddyfile .
chmod +x desplegar.sh
umask 077; echo "BOT_MEET_SECRETO=$(openssl rand -hex 32)" > bot.env
sudo cp repo/bot-meet/servidor/bot-meet-despliegue.service repo/bot-meet/servidor/bot-meet-despliegue.timer /etc/systemd/system/
sudo systemctl daemon-reload'
```
El despliegue corre como root (systemd), y root necesita la misma llave de GitHub:
```bash
ssh bot-meet 'sudo mkdir -p /root/.ssh && sudo cp ~/.ssh/github_jarvis /root/.ssh/ && sudo cp ~/.ssh/known_hosts /root/.ssh/ && printf "Host github.com\n  IdentityFile /root/.ssh/github_jarvis\n  IdentitiesOnly yes\n" | sudo tee -a /root/.ssh/config >/dev/null'
```

- [ ] **Step 7: Primer despliegue**

```bash
ssh bot-meet 'cd /opt/bot-meet && sudo ./desplegar.sh forzar; sudo tail -5 /var/log/bot-meet-despliegue.log; sudo systemctl enable --now bot-meet-despliegue.timer'
```
Expected: la última línea del registro es `listo`.

- [ ] **Step 8: Revisar que responde y que filtra**

```bash
ssh bot-meet 'cd /opt/bot-meet && sudo docker compose exec -T bot python -c "import urllib.request; print(urllib.request.urlopen(\"http://127.0.0.1:8000/v1/salud\").read().decode())"'
curl -s -o /dev/null -w "%{http_code}\n" https://bot-meet.neboaiconsulting.com/v1/salud
```
Expected: desde el servidor, `{"ok":true,...}`; desde la PC de Jorge, `403` (no es Jarvis) y un certificado válido (sin error de TLS).

- [ ] **Step 9: Medir el consumo en reposo**

```bash
ssh bot-meet 'sudo docker stats --no-stream; free -m'
```
Expected: el contenedor `bot` debajo de ~80 MB sin reuniones (no hay ningún Chrome abierto).

---

### Task 14: Login de Google, prueba real y calibración

Esta tarea necesita a Jorge en vivo.

- [ ] **Step 1: Login de la cuenta del bot**

Seguir «Iniciar sesión con la cuenta de Google del bot» en `bot-meet/servidor/LEEME.md`. Jorge inicia sesión con la cuenta de Nebo. Al terminar, arrancar el bot otra vez (`sudo docker compose up -d bot`).

- [ ] **Step 2: Activar el volcado de HTML y levantar el Jarvis falso**

Con el volcado activado, el bot guarda el HTML de la llamada cada 10 s en `/data/capturas/*-llamada.html`, sirve para calibrar. El Jarvis falso corre dentro del mismo contenedor:
```bash
ssh bot-meet 'cd /opt/bot-meet && echo BOT_MEET_VOLCAR_DOM=1 | sudo tee -a bot.env && sudo docker compose up -d bot && sleep 5 && sudo docker compose exec -d bot python -m bot_meet.herramientas.receptor_prueba'
```

- [ ] **Step 3: Revisar que el Jarvis falso responde**

```bash
ssh bot-meet 'cd /opt/bot-meet && sudo docker compose exec -T bot python -c "import urllib.request as u; r=u.Request(\"http://127.0.0.1:9000/api/reuniones/x/eventos\", data=b\"{}\", method=\"POST\"); print(u.urlopen(r).read())"'
```
Expected: `b'{"ok":true}'`

- [ ] **Step 4: Jorge crea un Meet y el bot entra**

Jorge crea un Meet desde su cuenta y pasa el link. Luego:
```bash
ssh bot-meet 'cd /opt/bot-meet && sudo docker compose exec bot sh -c "python -m bot_meet.herramientas.agendar https://meet.google.com/<código> --minutos 15"'
```
Expected: `202 {"estado":"agendada"} prueba-<n>`. En menos de 10 s el bot pide entrar. Jorge lo admite y ve en el chat «Jarvis está grabando esta reunión para tomar notas». Dos personas hablan unos 10 minutos y después salen las dos.

- [ ] **Step 5: Medir mientras graba**

Durante la reunión:
```bash
ssh bot-meet 'sudo docker stats --no-stream; uptime'
```
Anotar la RAM y la CPU del contenedor. Si pasa de ~900 MB, 2 bots no caben en el t3.small: o se baja `BOT_MEET_MAX_SESIONES=1` o se sube a t3.medium. Decidirlo con Jorge.

- [ ] **Step 6: Revisar lo que llegó**

```bash
ssh bot-meet 'cd /opt/bot-meet && sudo docker compose exec bot sh -c "ls -la /data/prueba/*/ && cat /data/prueba/*/eventos.jsonl && head -c 600 /data/prueba/*/hablantes.json"'
```
Expected:
- eventos `esperando`, `admitido` y `terminado` con `"motivo": "solo"`,
- `pedazo-00001.ogg` … (unos 11 MB por hora, ~2 MB por cada 10 minutos),
- `hablantes.json`.

Bajar un pedazo y escucharlo:
```bash
ssh bot-meet 'cd /opt/bot-meet && sudo docker compose cp bot:/data/prueba/. /tmp/prueba' && scp -r bot-meet:/tmp/prueba ./prueba-bot
```
El audio tiene que oírse claro, con las voces de los dos.

- [ ] **Step 7: Calibrar quién habla**

Si `hablantes.json` trae `"linea": []`, el selector simulado no sirve en la página real. Bajar los HTML de `/data/capturas/*-llamada.html` (`sudo docker compose cp bot:/data/capturas /tmp/capturas` y `scp -r bot-meet:/tmp/capturas .`) y comparar uno tomado mientras hablaba una persona con otro en silencio. Lo que hay que buscar es qué atributo o clase cambia en el mosaico `[data-participant-id]` de quien habla. Con ese selector:
```bash
ssh bot-meet 'cd /opt/bot-meet && sudo sed -i "/BOT_MEET_VOLCAR_DOM/d" bot.env && echo "BOT_MEET_SEL_HABLANDO=<selector>" | sudo tee -a bot.env && sudo docker compose up -d bot'
```
Repetir el Step 4 (5 minutos alcanzan) hasta que `hablantes.json` traiga los nombres. Si `data-self-name` tampoco existe en la página real, ajustar `JS_ESTADO` en `bot_meet/selectores.py`, con la página simulada cambiada igual, y pasar otra vez `tests/test_meet_simulado.py`.

- [ ] **Step 8: Revisar «solo audio»**

En los registros (`sudo docker compose logs bot | grep "solo audio"`) no tiene que aparecer «no pude poner solo audio». Si aparece, revisar la captura y ajustar `MAS_OPCIONES`, `CONFIGURACION`, `PESTANA_VIDEO` y `RESOLUCION_RECEPCION` en `selectores.py`.

- [ ] **Step 9: Commit de la calibración**

```bash
git add bot-meet/bot_meet/selectores.py bot-meet/tests/meet_simulado/index.html bot-meet/servidor/LEEME.md
git commit -m "Calibrate the Meet bot's selectors against a live call"
git push
```
Anotar en `servidor/LEEME.md` el `BOT_MEET_SEL_HABLANDO` que quedó y la RAM y CPU que se midieron.

---

## Después de este plan

Plan 2: `docs/superpowers/plans/2026-11-24-bot-meet-2-jarvis.md`, la parte de Jarvis: el interruptor «Grabar siempre», el botón en el aviso previo, la orden firmada al bot, la recepción de `/api/reuniones/*`, la transcripción con nombres, el resumen, la sección Reuniones, `buscar_reuniones`, el WhatsApp y la retención. Cuando esté listo, `BOT_MEET_SECRETO` se copia de `/opt/bot-meet/bot.env` a `jarvis.env`, se quita el receptor de prueba y `rama` vuelve a `main` después del merge.
