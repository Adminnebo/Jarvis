"""Borradores con IA para el super admin: diccionario de una tabla y accesos directos.

Nada de aca guarda: devuelve propuestas que la persona revisa y aprueba en la
interfaz. Usa el mismo modelo de Jarvis; el gasto queda en el consumo de quien pide.
"""

import json
import os

from . import accesos, cerebro, fuentes

DIALECTO = {"mssql": "SQL Server (TOP N, nunca LIMIT)", "postgres": "PostgreSQL (LIMIT N, nunca TOP)"}


def _cliente():
    return cerebro.cliente()


def _modelo() -> str:
    return os.getenv("OPENAI_MODEL", "gpt-5.6-terra")


def _pedir(instrucciones: str, entrada: str, usuario=None) -> dict:
    respuesta = _cliente().responses.create(
        model=_modelo(), instructions=instrucciones,
        # La API exige la palabra JSON en el mensaje para usar json_object.
        input=entrada + "\n\nResponde solo con el objeto JSON pedido.",
        text={"format": {"type": "json_object"}},
    )
    cerebro.anotar_consumo(_modelo(), getattr(respuesta, "usage", None), usuario)
    return json.loads(respuesta.output_text or "{}")


def _tabla(id_fuente: str, tabla: str) -> dict:
    for entrada in fuentes.esquema_de(id_fuente)["tablas"]:
        if entrada["tabla"] == tabla:
            return entrada
    raise ValueError(f"No existe la tabla '{tabla}' en esa fuente.")


def _muestra(id_fuente: str, tabla: str) -> list[dict]:
    fuente = fuentes.obtener(id_fuente)
    sql = (f"select top 5 * from {tabla}" if fuente["tipo"] == "mssql" else f"select * from {tabla} limit 5")
    try:
        return fuentes.consultar(id_fuente, sql, 5)
    except Exception:  # noqa: BLE001 - sin muestra el borrador sale igual, solo menos preciso
        return []


def proponer_diccionario(id_fuente: str, tabla: str, usuario=None) -> dict:
    entrada = _tabla(id_fuente, tabla)
    filas = _muestra(id_fuente, tabla)
    datos = _pedir(
        "Documentas tablas de una base de datos de empresa para un asistente que responde preguntas "
        "de negocio. Devuelve JSON con: leyenda (una frase corta: que contiene la tabla), columnas "
        "(objeto columna -> significado, solo las columnas que no se entienden por el nombre o cuyos "
        "valores son codigos, p. ej. Estado: 'A' = activo) y reglas (texto: como se cuentan o filtran "
        "cosas habituales, p. ej. 'un cliente activo es Estado = A'). En espanol. No inventes: si no "
        "se deduce de las columnas y las filas de ejemplo, no lo pongas.",
        f"Tabla: {tabla}\nColumnas: {entrada['columnas']}\n"
        f"Filas de ejemplo:\n{json.dumps(filas, ensure_ascii=False, default=str)[:4000]}",
        usuario,
    )
    columnas = datos.get("columnas") if isinstance(datos.get("columnas"), dict) else {}
    return {"leyenda": str(datos.get("leyenda") or "").strip(),
            "columnas": {str(k): str(v).strip() for k, v in columnas.items() if str(v).strip()},
            "reglas": str(datos.get("reglas") or "").strip()}


def proponer_acceso(id_fuente: str, pregunta: str, correccion: str = "", anterior: dict | None = None,
                    usuario=None) -> dict:
    """{'propuesta': {...}, 'resultado': filas|None, 'error': texto|None}"""
    fuente = fuentes.obtener(id_fuente)
    if fuente is None:
        raise ValueError(f"No existe la fuente '{id_fuente}'.")
    contexto = fuentes.resumen_de(id_fuente)
    pedido = f"Pregunta: {pregunta}\n\nEsquema y diccionario de la fuente:\n{contexto}"
    if anterior:
        pedido += f"\n\nPropuesta anterior:\n{json.dumps(anterior, ensure_ascii=False)}"
    if correccion:
        pedido += f"\n\nCorreccion pedida: {correccion}"
    propuesta = _pedir(
        "Conviertes una pregunta de negocio en una consulta SQL reutilizable de solo lectura para "
        f"{DIALECTO.get(fuente['tipo'], fuente['tipo'])}. Devuelve JSON con: id (nombre corto en "
        "minusculas con guiones bajos que describa la pregunta general, p. ej. ventas_por_periodo), "
        "descripcion (que responde, en una o dos frases: la lee un asistente para elegirla), sql (usa "
        "variables %(nombre)s para fechas, cantidades y textos que cambian; para periodos usa desde "
        "incluida y hasta excluida) y parametros (objeto nombre -> {tipo: fecha|entero|texto, "
        "descripcion, por_defecto}; las fechas por defecto son las de hoy, AAAA-MM-DD). Usa solo "
        "tablas y columnas del esquema y respeta el diccionario y sus reglas.",
        pedido, usuario,
    )
    propuesta["pregunta"] = pregunta
    try:
        limpio = accesos.validar(propuesta)
        valores = {n: accesos.valor(s, s.get("por_defecto")) for n, s in limpio["parametros"].items()}
        filas = fuentes.consultar(id_fuente, limpio["sql"], 50, parametros=valores or None)
        return {"propuesta": limpio, "resultado": filas, "error": None}
    except accesos.ErrorDeAcceso as error:
        return {"propuesta": propuesta, "resultado": None, "error": str(error)}
    except Exception as error:  # noqa: BLE001 - el error de la base se muestra para corregir
        return {"propuesta": propuesta, "resultado": None, "error": fuentes.explicar(error)}
