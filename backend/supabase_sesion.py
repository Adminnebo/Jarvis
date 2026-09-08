"""El puente con los paneles.

Los tres paneles comparten un directorio de usuarios en Supabase. Aqui se
valida el token de sesion de una persona, se lee su perfil y se decide si
puede usar Jarvis y con que rol.

Este modulo no sabe de HTTP ni de cookies: solo traduce un token en un
usuario. Lo de arriba lo hace acceso.py.
"""

import os
import re
import threading
import time

import httpx

# Los ids de quienes vienen de los paneles llevan este prefijo, para no chocar
# con los que salen de los sufijos de las variables de entorno.
PREFIJO = "sb-"

# Cuanto vale un perfil ya leido. La cookie de Jarvis dura 30 dias; sin
# revalidar, quitarle el permiso a alguien no surtiria efecto hasta entonces.
VIGENCIA = 60

# Si la base no responde, cuanto se conserva el ultimo perfil conocido. Un
# corte breve no debe echar a nadie a mitad de una conversacion.
GRACIA = 300

UUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def configurado() -> bool:
    """Si falta algo, el puente queda apagado y solo entran las contrasenas.

    SUPABASE_DB_URL cuenta: sin conexion directa, leer el perfil iria por MCP
    y pondria mas de un segundo en el camino de cada peticion.
    """
    return all(
        os.getenv(variable, "").strip()
        for variable in ("SUPABASE_ANON_KEY", "SUPABASE_PROJECT_REF", "SUPABASE_DB_URL")
    )


def url_proyecto() -> str:
    referencia = os.getenv("SUPABASE_PROJECT_REF", "").strip()
    return f"https://{referencia}.supabase.co"


def id_de_token(token: str) -> str | None:
    """Valida el token contra Supabase y devuelve el uuid de quien lo trajo.

    Se le pregunta a Supabase en vez de verificar la firma aqui: asi no hace
    falta guardar el secreto de firma del proyecto, y un token revocado deja
    de valer de inmediato.
    """
    if not token or not configurado():
        return None

    respuesta = httpx.get(
        f"{url_proyecto()}/auth/v1/user",
        headers={
            "Authorization": f"Bearer {token}",
            "apikey": os.getenv("SUPABASE_ANON_KEY", "").strip(),
        },
        timeout=10,
    )
    if respuesta.status_code != 200:
        return None
    return respuesta.json().get("id")


def perfil(uuid: str) -> dict | None:
    """El perfil de esa persona en la tabla que comparten los paneles."""
    if not UUID.match(uuid or ""):
        # El uuid se interpola en el SQL. Viene de Supabase, pero comprobarlo
        # aqui es lo que garantiza que nunca entre otra cosa.
        raise ValueError("El identificador no es un uuid.")

    from . import esquema

    filas = esquema.consultar_directo(
        "select id, email, full_name, role, permissions, platforms "
        f"from profiles where id = '{uuid}' limit 1;"
    )
    return filas[0] if filas else None


# --------------------------------------------------------------------------
# Cache de perfiles
# --------------------------------------------------------------------------

_cache: dict[str, tuple[float, dict | None]] = {}
_candado = threading.Lock()


def perfil_cacheado(uuid: str) -> dict | None:
    """El perfil, releido como mucho una vez por minuto.

    Devuelve el ultimo conocido si la base no responde, hasta GRACIA segundos.
    Pasado eso propaga el error: preferimos dejar a alguien fuera antes que
    mantener viva una sesion que ya no podemos comprobar.
    """
    ahora = time.monotonic()

    with _candado:
        guardado = _cache.get(uuid)
    if guardado and ahora - guardado[0] < VIGENCIA:
        return guardado[1]

    try:
        fresco = perfil(uuid)
    except Exception:  # noqa: BLE001 - la base puede no responder
        if guardado and ahora - guardado[0] < GRACIA:
            return guardado[1]
        raise

    with _candado:
        _cache[uuid] = (ahora, fresco)
    return fresco


def limpiar_cache() -> None:
    with _candado:
        _cache.clear()
