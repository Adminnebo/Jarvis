"""Las conexiones reutilizadas no se comparten entre hilos.

FreeTDS (pymssql) aborta el proceso si una conexion se cierra mientras otro
hilo la esta usando. Paso en produccion: dos herramientas a la vez, una fallaba
y cerraba la conexion compartida, y Jarvis se reiniciaba.
"""

import json
import random
import threading
import time

import pytest

from backend import fuentes, herramientas


class Conexion:
    abiertas = 0
    violaciones: list[str] = []
    candado = threading.Lock()

    def __init__(self):
        with Conexion.candado:
            Conexion.abiertas += 1
        self.en_uso = 0
        self.cerrada = False

    def usar(self, falla: bool):
        with Conexion.candado:
            if self.cerrada:
                Conexion.violaciones.append("uso de una conexion cerrada")
            if self.en_uso:
                Conexion.violaciones.append("dos hilos en la misma conexion")
            self.en_uso += 1
        time.sleep(random.uniform(0.001, 0.005))
        with Conexion.candado:
            self.en_uso -= 1
        if falla:
            raise RuntimeError("se cayo la conexion")
        return [{"ok": 1}]

    def close(self):
        with Conexion.candado:
            if self.en_uso:
                Conexion.violaciones.append("cerrada mientras otro hilo la usaba")
            self.cerrada = True


@pytest.fixture(autouse=True)
def pool_limpio():
    fuentes._libres.clear()
    fuentes._generacion.clear()
    Conexion.abiertas = 0
    Conexion.violaciones = []
    yield
    fuentes._libres.clear()


def _consulta(falla=False):
    return fuentes._con_reintento("f1", Conexion, lambda c: c.usar(falla))


def test_muchos_hilos_a_la_vez_nunca_comparten_ni_cierran_una_conexion_en_uso():
    errores = []

    def trabajo(i):
        for _ in range(30):
            try:
                # Una de cada cinco falla, como una conexion caida o un SQL malo.
                _consulta(falla=random.random() < 0.2)
            except RuntimeError:
                errores.append(i)
            if random.random() < 0.1:
                fuentes.soltar_conexion("f1")   # como mantener_vivas tras un fallo

    hilos = [threading.Thread(target=trabajo, args=(i,)) for i in range(8)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join()

    assert Conexion.violaciones == []
    assert len(fuentes._libres.get("f1", [])) <= fuentes.MAX_LIBRES


def test_una_consulta_seguida_reusa_la_misma_conexion():
    _consulta()
    _consulta()
    assert Conexion.abiertas == 1


def test_si_la_conexion_guardada_murio_se_reabre_y_reintenta():
    _consulta()
    llamadas = []

    def ejecutar(conexion):
        llamadas.append(conexion)
        if len(llamadas) == 1:
            raise RuntimeError("conexion muerta")
        return "bien"

    assert fuentes._con_reintento("f1", Conexion, ejecutar) == "bien"
    assert llamadas[0].cerrada and not llamadas[1].cerrada
    assert Conexion.abiertas == 2


def test_la_conexion_tomada_antes_de_editar_la_fuente_no_vuelve_al_pool():
    def ejecutar(conexion):
        fuentes.soltar_conexion("f1")   # editan la fuente mientras consulta
        return "bien"

    fuentes._con_reintento("f1", Conexion, ejecutar)
    assert fuentes._libres.get("f1", []) == []


def test_argumentos_cortados_piden_repetir_la_llamada():
    texto = herramientas.ejecutar(
        "consultar_fuente", '{"fuente": "656ef47a", "sql": "select top 5 * fro', "admin"
    )
    assert "llegaron cortados" in texto and "Vuelve a llamar" in texto
    assert json.loads(json.dumps(texto))
