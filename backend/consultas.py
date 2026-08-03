"""Base de conocimiento: consultas SQL ya escritas para las tablas reales.

Existe por velocidad. Sin esto el modelo tiene que inventar el SQL en cada
pregunta: son segundos de generacion y un riesgo de equivocarse con nombres de
columnas. Aqui elige una consulta por nombre y le pasa parametros.

Para agregar una consulta basta con anadir una entrada a CATALOGO. El texto de
`descripcion` es lo unico que ve el modelo, asi que tiene que decir con
precision que responde.
"""

import json
import re
import threading
import time
from dataclasses import dataclass, field
from decimal import Decimal

from . import esquema

VIGENCIA_CACHE = 30  # segundos


@dataclass
class Parametro:
    tipo: str                  # "entero" | "texto" | "fecha"
    descripcion: str
    por_defecto: object = None
    minimo: int = 1
    maximo: int = 500


@dataclass
class Consulta:
    descripcion: str
    sql: str
    parametros: dict[str, Parametro] = field(default_factory=dict)
    # Cuanto vale la pena cachear el resultado. Los datos que cambian cada
    # pocos segundos van bajo; los snapshots diarios, alto.
    vigencia: int = VIGENCIA_CACHE


# --------------------------------------------------------------------------
# El catalogo
# --------------------------------------------------------------------------

LIMITE = Parametro("entero", "Cuantos resultados devolver", 5, 1, 100)
DIAS = Parametro("entero", "Cuantos dias hacia atras mirar", 7, 1, 365)

CATALOGO: dict[str, Consulta] = {

    # ---------------- Cartera y deuda ----------------

    "cartera_resumen": Consulta(
        "Estado actual de toda la cartera de cobranzas: deuda total, deuda "
        "vencida, credito ofrecido y numero de clientes. Es la foto mas "
        "reciente. Usala para 'cuanto se debe en total' o 'como va la cartera'.",
        """
        select fecha, slot, deuda_total, deuda_vencida, credito_ofrecido,
               total_clientes,
               round(deuda_vencida / nullif(deuda_total, 0) * 100, 1) as pct_vencida
        from deuda_historico
        order by fecha desc, slot desc
        limit 1;
        """,
        vigencia=300,
    ),

    "cartera_tendencia": Consulta(
        "Evolucion de la deuda total y vencida dia a dia. Para 'como ha "
        "cambiado la deuda', 'subio o bajo', tendencias de la cartera.",
        """
        select fecha,
               max(deuda_total) as deuda_total,
               max(deuda_vencida) as deuda_vencida,
               max(total_clientes) as total_clientes
        from deuda_historico
        where fecha >= current_date - {dias}
        group by fecha
        order by fecha desc;
        """,
        {"dias": DIAS},
        vigencia=300,
    ),

    "cartera_variacion": Consulta(
        "Cuanto subio o bajo la deuda entre la primera y la ultima medicion "
        "del periodo. Responde 'cuanto cambio la deuda esta semana'.",
        """
        with extremos as (
            select
                (array_agg(deuda_total order by fecha, slot))[1] as deuda_inicial,
                (array_agg(deuda_total order by fecha desc, slot desc))[1] as deuda_final,
                (array_agg(deuda_vencida order by fecha, slot))[1] as vencida_inicial,
                (array_agg(deuda_vencida order by fecha desc, slot desc))[1] as vencida_final,
                min(fecha) as desde, max(fecha) as hasta
            from deuda_historico
            where fecha >= current_date - {dias}
        )
        select desde, hasta, deuda_inicial, deuda_final,
               deuda_final - deuda_inicial as cambio_deuda,
               vencida_inicial, vencida_final,
               vencida_final - vencida_inicial as cambio_vencida
        from extremos;
        """,
        {"dias": DIAS},
        vigencia=300,
    ),

    "top_deudores": Consulta(
        "Los clientes que mas dinero deben, con su deuda total, vencida y "
        "telefono. Para 'quien debe mas', 'los mayores deudores'.",
        """
        select nombre, empresa, phone, deuda_total, deuda_vencida,
               credito_ofrecido, estado
        from llamada_cola
        where deuda_total is not null
        order by deuda_total desc
        limit {limite};
        """,
        {"limite": LIMITE},
        vigencia=120,
    ),

    "deudores_vencidos": Consulta(
        "Clientes ordenados por deuda VENCIDA, que es la que ya paso su fecha "
        "de pago. Mas urgente que la deuda total.",
        """
        select nombre, empresa, phone, deuda_vencida, deuda_total,
               round(deuda_vencida / nullif(deuda_total, 0) * 100, 1) as pct_vencido
        from llamada_cola
        where deuda_vencida > 0
        order by deuda_vencida desc
        limit {limite};
        """,
        {"limite": LIMITE},
        vigencia=120,
    ),

    "deuda_por_agente": Consulta(
        "Cuanta deuda tiene asignada cada agente y cuantos clientes lleva.",
        """
        select coalesce(agente, 'sin asignar') as agente,
               count(*) as clientes,
               sum(deuda_total) as deuda_total,
               sum(deuda_vencida) as deuda_vencida
        from llamada_cola
        group by agente
        order by deuda_total desc nulls last;
        """,
        vigencia=120,
    ),

    "buscar_deudor": Consulta(
        "Busca un cliente por nombre, empresa o telefono y devuelve su deuda "
        "y estado. Usala cuando pregunten por alguien concreto.",
        """
        select nombre, empresa, phone, deuda_total, deuda_vencida,
               credito_ofrecido, estado, agente, created_at
        from llamada_cola
        where nombre ilike '%{texto}%'
           or empresa ilike '%{texto}%'
           or phone like '%{texto}%'
        order by deuda_total desc nulls last
        limit 10;
        """,
        {"texto": Parametro("texto", "Nombre, empresa o telefono a buscar")},
    ),

    # ---------------- Llamadas ----------------

    "cola_resumen": Consulta(
        "Cuantas llamadas hay en cada estado de la cola y cuanta deuda "
        "representan. Para 'cuantas llamadas hay pendientes'.",
        """
        select estado, count(*) as llamadas,
               sum(deuda_total) as deuda_asociada
        from llamada_cola
        group by estado
        order by llamadas desc;
        """,
    ),

    "llamadas_recientes": Consulta(
        "Las ultimas llamadas de cobranza realizadas, con su resultado, la "
        "intencion de pago detectada y la fecha que prometio el cliente.",
        """
        select created_at, phone, name, intencion_pago, fecha_pago, notas
        from "Cobranzas_call_logs"
        order by created_at desc
        limit {limite};
        """,
        {"limite": LIMITE},
    ),

    "intencion_pago_resumen": Consulta(
        "Como se reparten las llamadas segun la intencion de pago detectada "
        "(pago_inmediato, fecha_especifica, evasivo, no_contesta, etc.). "
        "Para medir efectividad de la cobranza.",
        """
        select coalesce(intencion_pago, 'sin clasificar') as intencion,
               count(*) as llamadas,
               round(100.0 * count(*) / sum(count(*)) over (), 1) as porcentaje
        from "Cobranzas_call_logs"
        group by intencion_pago
        order by llamadas desc;
        """,
        vigencia=120,
    ),

    "llamadas_por_dia": Consulta(
        "Volumen de llamadas de cobranza por dia, con cuantas fueron "
        "contactos efectivos. Para 'cuantas llamamos hoy' o tendencia.",
        """
        select date(created_at) as dia,
               count(*) as llamadas,
               count(*) filter (where intencion_pago is not null
                                  and intencion_pago <> 'no_contesta') as contactos,
               count(*) filter (where intencion_pago in
                     ('pago_inmediato', 'fecha_especifica', 'proximo_corte')) as compromisos
        from "Cobranzas_call_logs"
        where created_at >= current_date - {dias}
        group by dia
        order by dia desc;
        """,
        {"dias": DIAS},
    ),

    "compromisos_de_pago": Consulta(
        "Llamadas donde el cliente se comprometio a pagar, con la fecha que "
        "dijo. Son las de mayor valor para seguimiento.",
        """
        select created_at, phone, name, intencion_pago, fecha_pago, notas
        from "Cobranzas_call_logs"
        where intencion_pago in ('pago_inmediato', 'fecha_especifica',
                                 'proximo_corte', 'promesa_vaga')
        order by created_at desc
        limit {limite};
        """,
        {"limite": LIMITE},
    ),

    "disparos_resumen": Consulta(
        "Estado de los disparos de llamadas automaticas y cuando fue el ultimo.",
        """
        select estado, count(*) as disparos,
               min(created_at) as primero, max(created_at) as ultimo
        from llamada_disparo
        group by estado
        order by disparos desc;
        """,
    ),

    "agenda_llamadas": Consulta(
        "La configuracion del marcador automatico: si esta activo, en que "
        "horarios llama, que agente usa y cuando encolo por ultima vez.",
        """
        select enabled, weekdays_only, auto_enqueue, agent_name,
               blocks, last_enqueue_date, updated_at, updated_by
        from call_schedule
        limit 1;
        """,
        vigencia=120,
    ),

    # ---------------- Promesas de pago ----------------

    "promesas_pendientes": Consulta(
        "Promesas de pago registradas que todavia no vencen, con el monto y "
        "la fecha comprometida.",
        """
        select nombre, phone, fecha_prometida, monto_al_prometer, estado,
               fecha_llamada, texto_original
        from promesa_pago
        where fecha_prometida >= current_date
        order by fecha_prometida
        limit {limite};
        """,
        {"limite": LIMITE},
    ),

    "promesas_vencidas": Consulta(
        "Promesas de pago cuya fecha ya paso. Son las que hay que perseguir.",
        """
        select nombre, phone, fecha_prometida, monto_al_prometer, estado,
               current_date - fecha_prometida as dias_de_retraso
        from promesa_pago
        where fecha_prometida < current_date
        order by fecha_prometida
        limit {limite};
        """,
        {"limite": LIMITE},
    ),

    # ---------------- WhatsApp ----------------

    "whatsapp_resumen": Consulta(
        "Panorama de la mensajeria de WhatsApp: mensajes enviados y recibidos "
        "por tipo, contactos distintos y periodo cubierto.",
        """
        select direction as direccion, type as tipo, count(*) as mensajes,
               count(distinct wa_id) as contactos,
               max(sent_at) as ultimo
        from whatsapp_reply_record
        group by direction, type
        order by mensajes desc;
        """,
        vigencia=60,
    ),

    "whatsapp_actividad": Consulta(
        "Mensajes de WhatsApp por dia, separando entrantes y salientes. "
        "Para ver el ritmo de conversacion.",
        """
        select date(sent_at) as dia,
               count(*) filter (where direction = 'in') as recibidos,
               count(*) filter (where direction = 'out') as enviados,
               count(distinct wa_id) as contactos
        from whatsapp_reply_record
        where sent_at >= current_date - {dias}
        group by dia
        order by dia desc;
        """,
        {"dias": DIAS},
        vigencia=60,
    ),

    "whatsapp_top_contactos": Consulta(
        "Los contactos de WhatsApp con mas mensajes intercambiados, con "
        "nombre si esta mapeado.",
        """
        select w.wa_id, g.contact_name as nombre,
               count(*) as mensajes,
               count(*) filter (where w.direction = 'in') as recibidos,
               max(w.sent_at) as ultimo_mensaje
        from whatsapp_reply_record w
        left join ghl_contact_map g on g.wa_id = w.wa_id
        group by w.wa_id, g.contact_name
        order by mensajes desc
        limit {limite};
        """,
        {"limite": LIMITE},
        vigencia=60,
    ),

    "whatsapp_sin_responder": Consulta(
        "Contactos cuyo ultimo mensaje fue entrante: escribieron y nadie "
        "contesto todavia.",
        """
        with ultimo as (
            select distinct on (wa_id) wa_id, direction, sent_at, message_body
            from whatsapp_reply_record
            order by wa_id, sent_at desc
        )
        select u.wa_id, g.contact_name as nombre, u.sent_at as ultimo_mensaje,
               left(u.message_body, 120) as texto
        from ultimo u
        left join ghl_contact_map g on g.wa_id = u.wa_id
        where u.direction = 'in'
        order by u.sent_at desc
        limit {limite};
        """,
        {"limite": LIMITE},
        vigencia=60,
    ),

    # ---------------- Clientes y configuracion ----------------

    "clientes_config_resumen": Consulta(
        "Cuantos clientes tienen la cobranza automatica activada o desactivada "
        "y cuantos estan marcados como IVR (contestadora).",
        """
        select
            count(*) as total,
            count(*) filter (where enabled) as activos,
            count(*) filter (where not enabled) as inactivos,
            count(*) filter (where ivr) as detectados_ivr
        from cliente_config;
        """,
        vigencia=120,
    ),

    "clientes_ivr": Consulta(
        "Telefonos detectados como contestadora automatica (IVR), con el "
        "detalle de la deteccion. Llamarlos es perder tiempo.",
        """
        select phone, ivr_tipo, ivr_detalle, ivr_at, enabled
        from cliente_config
        where ivr
        order by ivr_at desc nulls last
        limit {limite};
        """,
        {"limite": LIMITE},
        vigencia=120,
    ),

    # ---------------- Operacion e infraestructura ----------------

    "proveedores_saldo": Consulta(
        "Saldo actual de cada proveedor de API (OpenAI, Anthropic, Twilio, "
        "Deepseek...), su gasto diario y su limite de presupuesto. Para "
        "'cuanto me queda de credito' o 'cuanto estoy gastando'.",
        """
        select provider as proveedor, label as nombre, enabled as activo,
               cached_balance as saldo, budget_limit as limite,
               cached_daily_cost as gasto_diario,
               cached_total_cost as gasto_total,
               cached_at as actualizado, last_error as ultimo_error
        from provider_accounts
        order by cached_balance asc nulls last;
        """,
        vigencia=60,
    ),

    "proveedores_saldo_bajo": Consulta(
        "Proveedores cuyo saldo esta por debajo del 20 por ciento de su "
        "limite. Es la alerta de recarga.",
        """
        select provider as proveedor, label as nombre, cached_balance as saldo,
               budget_limit as limite,
               round(cached_balance / nullif(budget_limit, 0) * 100, 1) as pct_restante,
               cached_daily_cost as gasto_diario
        from provider_accounts
        where enabled
          and cached_balance is not null
          and budget_limit is not null
          and cached_balance < budget_limit * 0.20
        order by pct_restante;
        """,
        vigencia=60,
    ),

    "servicios_estado": Consulta(
        "Estado de los servicios monitoreados: si respondieron bien, su "
        "latencia y cuando se revisaron. Para 'esta todo funcionando'.",
        """
        select name as servicio, enabled as activo, last_ok as ok,
               last_status as codigo, last_latency_ms as latencia_ms,
               last_checked_at as revisado, last_error as error
        from service_checks
        order by last_ok nulls first, name;
        """,
        vigencia=30,
    ),

    "usuarios_por_rol": Consulta(
        "Cuantos usuarios hay de cada rol en la plataforma.",
        """
        select role as rol, count(*) as usuarios
        from profiles
        group by role
        order by usuarios desc;
        """,
        vigencia=300,
    ),

    "usuarios_lista": Consulta(
        "Lista de usuarios de la plataforma con su rol y correo.",
        """
        select full_name as nombre, email, role as rol, created_at
        from profiles
        order by created_at desc
        limit {limite};
        """,
        {"limite": LIMITE},
        vigencia=300,
    ),

    "n8n_fallos": Consulta(
        "Ejecuciones de n8n que fallaron, con el flujo y cuando. Para "
        "'que se rompio' o 'hay errores en los automatismos'.",
        """
        select workflow_name as flujo, status as estado, started_at as inicio,
               stopped_at as fin, execution_id
        from n8n_execution_archive
        where status is distinct from 'success'
          and started_at >= current_date - {dias}
        order by started_at desc
        limit {limite};
        """,
        {"dias": DIAS, "limite": LIMITE},
    ),

    "n8n_resumen": Consulta(
        "Cuantas ejecuciones de n8n hubo por flujo y cuantas fallaron.",
        """
        select workflow_name as flujo,
               count(*) as ejecuciones,
               count(*) filter (where status = 'success') as exitosas,
               count(*) filter (where status is distinct from 'success') as fallidas,
               max(started_at) as ultima
        from n8n_execution_archive
        where started_at >= current_date - {dias}
        group by workflow_name
        order by ejecuciones desc;
        """,
        {"dias": DIAS},
    ),

    "cotizaciones_faltantes": Consulta(
        "Numeros de cotizacion que faltan y siguen sin resolver.",
        """
        select numero, notificado_at, resuelto, resuelto_at
        from cotizaciones_faltantes
        where not resuelto
        order by numero
        limit {limite};
        """,
        {"limite": LIMITE},
    ),

    "ultima_cotizacion": Consulta(
        "El ultimo numero de cotizacion emitido.",
        """
        select numero, encabezado, created_at
        from nro_cotizacion
        order by created_at desc
        limit 1;
        """,
    ),

    "creditos_plataforma": Consulta(
        "Creditos y configuracion de recarga automatica de los clientes de "
        "la plataforma.",
        """
        select name as cliente, credits as creditos, has_card as tiene_tarjeta,
               auto_recharge_enabled as recarga_auto,
               auto_recharge_threshold as umbral,
               calls_paused as llamadas_pausadas,
               messages_paused as mensajes_pausados, updated_at
        from clients
        where not archived
        order by credits asc
        limit {limite};
        """,
        {"limite": LIMITE},
        vigencia=60,
    ),
}


# --------------------------------------------------------------------------
# Validacion y ejecucion
# --------------------------------------------------------------------------

class ParametroInvalido(ValueError):
    pass


def validar(consulta: Consulta, recibidos: dict) -> dict:
    """Convierte y acota los parametros. Nada llega crudo al SQL."""
    limpios = {}

    for nombre, spec in consulta.parametros.items():
        valor = recibidos.get(nombre, spec.por_defecto)

        if valor is None:
            raise ParametroInvalido(f"Falta el parametro '{nombre}'.")

        if spec.tipo == "entero":
            try:
                numero = int(valor)
            except (TypeError, ValueError):
                raise ParametroInvalido(f"'{nombre}' debe ser un numero.") from None
            limpios[nombre] = max(spec.minimo, min(spec.maximo, numero))

        elif spec.tipo == "texto":
            texto = str(valor).strip()
            if not texto:
                raise ParametroInvalido(f"'{nombre}' no puede estar vacio.")
            # Solo lo que puede aparecer en un nombre o telefono. Cierra la
            # puerta a comillas y punto y coma sin depender de escapes.
            limpio = re.sub(r"[^\w\sáéíóúüñÁÉÍÓÚÜÑ.@+-]", "", texto)[:80]
            if not limpio:
                raise ParametroInvalido(f"'{nombre}' no tiene caracteres validos.")
            limpios[nombre] = limpio

        elif spec.tipo == "fecha":
            texto = str(valor).strip()
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", texto):
                raise ParametroInvalido(f"'{nombre}' debe tener formato AAAA-MM-DD.")
            limpios[nombre] = texto

    return limpios


# --------------------------------------------------------------------------
# Cache de resultados
# --------------------------------------------------------------------------

_cache: dict[str, tuple[float, list[dict]]] = {}
_candado = threading.Lock()


def ejecutar(nombre: str, parametros: dict | None = None) -> dict:
    """Corre una consulta del catalogo y devuelve sus filas."""
    consulta = CATALOGO.get(nombre)
    if consulta is None:
        cercanas = sugerir(nombre)
        pista = f" Quiza quisiste: {', '.join(cercanas)}." if cercanas else ""
        return {"error": f"No existe la consulta '{nombre}'.{pista}"}

    try:
        limpios = validar(consulta, parametros or {})
    except ParametroInvalido as error:
        return {"error": str(error)}

    clave = f"{nombre}:{json.dumps(limpios, sort_keys=True)}"
    ahora = time.monotonic()

    with _candado:
        guardado = _cache.get(clave)
        if guardado and ahora - guardado[0] < consulta.vigencia:
            return {"consulta": nombre, "filas": guardado[1], "de_cache": True}

    sql = consulta.sql.format(**limpios) if limpios else consulta.sql

    try:
        filas = esquema.consultar(sql)
    except Exception as error:  # noqa: BLE001 - se lo explicamos al modelo
        return {"error": f"Fallo la consulta '{nombre}': {str(error)[:200]}"}

    filas = [normalizar(fila) for fila in filas]

    with _candado:
        _cache[clave] = (ahora, filas)

    return {"consulta": nombre, "filas": filas, "de_cache": False}


def normalizar(fila: dict) -> dict:
    """Deja la fila serializable a JSON y sin decimales absurdos."""
    limpia = {}
    for clave, valor in fila.items():
        if isinstance(valor, Decimal):
            limpia[clave] = round(float(valor), 2)
        elif isinstance(valor, float):
            limpia[clave] = round(valor, 2)
        elif isinstance(valor, (dict, list)) or valor is None or isinstance(valor, (int, str, bool)):
            limpia[clave] = valor
        else:
            limpia[clave] = str(valor)
    return limpia


def sugerir(nombre: str) -> list[str]:
    """Nombres parecidos, para que el modelo se corrija sin otro viaje."""
    partes = [p for p in re.split(r"[_\s]+", nombre.lower()) if len(p) > 2]
    return [
        clave for clave in CATALOGO
        if any(parte in clave for parte in partes)
    ][:3]


def limpiar_cache() -> None:
    with _candado:
        _cache.clear()


# --------------------------------------------------------------------------
# Presentacion para el modelo
# --------------------------------------------------------------------------

def catalogo_para_prompt() -> str:
    """El indice que ve el modelo. Sin esto tendria que preguntar que hay."""
    lineas = []
    for nombre, consulta in CATALOGO.items():
        firma = nombre
        if consulta.parametros:
            argumentos = ", ".join(
                f"{p}={spec.por_defecto}" if spec.por_defecto is not None else p
                for p, spec in consulta.parametros.items()
            )
            firma = f"{nombre}({argumentos})"
        descripcion = " ".join(consulta.descripcion.split())
        lineas.append(f"- {firma}: {descripcion}")
    return "\n".join(lineas)


def info() -> dict:
    return {
        "consultas": len(CATALOGO),
        "nombres": sorted(CATALOGO),
    }
