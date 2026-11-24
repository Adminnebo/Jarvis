"""Arranca cada sesión a su hora (en un hilo), reintenta subidas y limpia."""
import asyncio
import shutil
import threading
import traceback
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
        # Ids con un hilo vivo. Una cancelada sigue corriendo hasta salir de la
        # llamada: la limpieza no puede tocar su carpeta mientras tanto.
        self._corriendo: set[str] = set()

    def carpeta(self, id_: str) -> Path:
        return self._config.datos / "sesiones" / id_

    # --- arranque ------------------------------------------------------
    def revisar(self, ahora: datetime):
        self._agenda.vencer(ahora)
        for s in self._agenda.por_iniciar(ahora):
            if self._agenda.activas() >= self._config.max_sesiones:
                break
            self._agenda.marcar(s.id, "en_curso")
            self._corriendo.add(s.id)
            self._iniciar_hilo(lambda s=s: self._una(s))

    def _una(self, s: Sesion):
        try:
            resultado = self._correr(s)
            print(f"[lanzador] {s.id}: {resultado}")
        except Exception:  # nunca tumbar el servicio por una reunión
            print(f"[lanzador] {s.id}: error\n{traceback.format_exc()}", flush=True)
        finally:
            if self._agenda.obtener(s.id).estado == "en_curso":
                self._agenda.marcar(s.id, "terminada")
            self._corriendo.discard(s.id)

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
                espera_admision_s=c.espera_admision_s, volcar_dom=c.volcar_dom,
                calibrar_s=c.calibrar_s)
        finally:
            shutil.rmtree(perfil, ignore_errors=True)

    # --- subidas pendientes y limpieza ---------------------------------
    def reintentar_subidas(self):
        from .subidor import Subidor
        for s in self._agenda.todas():
            if s.estado in ("agendada", "en_curso") or s.id in self._corriendo:
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
