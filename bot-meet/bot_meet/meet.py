"""Chromium manejado por Playwright para entrar a un Meet y seguirlo."""
import json
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
    # 1024 px: más angosto, Meet esconde el botón del chat en "Más opciones".
    "--window-size=1024,600", "--lang=es-419",
]
# Playwright pone --mute-audio por defecto: con eso ffmpeg graba silencio
# (probado en el EC2: -91 dB con él, -4.6 dB sin él).
QUITAR_POR_DEFECTO = ["--enable-automation", "--mute-audio"]


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
            args=ARGUMENTOS, ignore_default_args=QUITAR_POR_DEFECTO,
            viewport={"width": 1024, "height": 600}, locale="es-419",
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

    def _en_llamada(self) -> bool:
        """El botón de colgar está en la página y visible. Se busca en el DOM y no
        por rol: un cartel encima saca la llamada del árbol de accesibilidad."""
        salir = self._pagina.locator(S.CSS_EN_LLAMADA)
        return bool(salir.count()) and salir.first.is_visible()

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
                if self._en_llamada():
                    self._cerrar_dialogos()   # el cartel de bienvenida tapa la llamada
                    return ResultadoEntrada("admitido")
                rechazo = p.get_by_text(S.TEXTO_RECHAZADO)
                if rechazo.count() and rechazo.first.is_visible():  # get_by_text cuenta lo oculto
                    return ResultadoEntrada("rechazado", "rechazado")
                if time.monotonic() >= limite:
                    self.captura("sin-admision")
                    return ResultadoEntrada("rechazado", "sin_respuesta")
                p.wait_for_timeout(1000)
        except PWError as error:
            return ResultadoEntrada("fallo", f"navegador: {error}"[:200])

    # --- ya adentro ----------------------------------------------------
    def silenciar(self) -> int:
        """Apaga micrófono y cámara si quedaron prendidos (al entrar directo, sin sala
        de espera, Meet los dejaba encendidos). Devuelve cuántos apagó."""
        apagados = 0
        try:
            # Se vuelve a buscar después de cada clic: el botón apagado deja de
            # calzar con el selector y la lista se corre.
            for _ in range(4):
                visibles = [b for b in self._pagina.locator(S.CSS_PRENDIDOS).all() if b.is_visible()]
                if not visibles:
                    break
                visibles[0].click(timeout=3000)
                apagados += 1
        except PWError as error:
            print(f"[meet] no pude apagar micrófono/cámara: {str(error).splitlines()[0]}")
        return apagados

    def solo_audio(self) -> bool:
        """Ajustes > Video > Resolución de recepción: Solo audio. Si falla, sigue."""
        p = self._pagina
        try:
            self._boton(S.MAS_OPCIONES).first.click(timeout=5000)
            p.get_by_role("menuitem", name=S.CONFIGURACION).first.click(timeout=5000)
            p.get_by_role("tab", name=S.PESTANA_VIDEO).first.click(timeout=5000)
            lista = p.get_by_label(S.RESOLUCION_RECEPCION).first
            # En el Meet real es un menú propio (role=combobox), no un <select>.
            if lista.evaluate("e => e.tagName") == "SELECT":
                lista.select_option(label=S.SOLO_AUDIO, timeout=5000)
            else:
                lista.click(timeout=5000)
                p.get_by_role("option", name=S.SOLO_AUDIO).first.click(timeout=5000)
            self._boton(S.CERRAR_DIALOGO).first.click(timeout=5000)
            return True
        except PWError as error:
            print(f"[meet] no pude poner solo audio: {str(error).splitlines()[0]}")
            self.captura("solo-audio")
            self._cerrar_dialogos()
            return False

    def _cerrar_dialogos(self):
        """Escape un par de veces: un menú o diálogo abierto tapa la llamada."""
        try:
            for _ in range(2):
                self._pagina.keyboard.press("Escape")
                self._pagina.wait_for_timeout(300)
        except PWError:
            pass

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
            print(f"[meet] no pude escribir en el chat: {str(error).splitlines()[0]}")
            self.captura("chat")
            self._cerrar_dialogos()
            return False

    def leer_estado(self) -> EstadoLlamada:
        if not self._viva():
            return EstadoLlamada(False)
        try:
            datos = self._pagina.evaluate(S.JS_ESTADO, self._sel_hablando)
            # Dentro si está el botón de colgar o si hay mosaicos de personas: con alguien
            # presentando el botón desaparecía y el bot se daba por caído (2026-11-25).
            dentro = bool(self._pagina.locator(S.CSS_EN_LLAMADA).count()) or datos["personas"] > 0
        except PWError:
            return EstadoLlamada(False)
        if not dentro:
            return EstadoLlamada(False)
        return EstadoLlamada(True, datos["otros"], datos["hablando"])

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

    def anotar_calibracion(self, t: int) -> None:
        """Una línea de capturas/calibracion.jsonl con la foto de los mosaicos en el segundo t."""
        if not self._viva():
            return
        try:
            mosaicos = self._pagina.evaluate(S.JS_FOTO)
        except PWError:
            return
        self._capturas.mkdir(parents=True, exist_ok=True)
        with open(self._capturas / "calibracion.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": t, "mosaicos": mosaicos}, ensure_ascii=False) + "\n")

    def volcar(self, nombre: str) -> Path | None:
        """Guarda el HTML de la página (para calibrar selectores)."""
        if not self._viva():
            return None
        self._capturas.mkdir(parents=True, exist_ok=True)
        ruta = self._capturas / f"{time.strftime('%Y%m%d-%H%M%S')}-{nombre}.html"
        ruta.write_text(self._pagina.content(), encoding="utf-8")
        return ruta
