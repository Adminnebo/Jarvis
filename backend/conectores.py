"""Servidores MCP remotos que Jarvis puede usar.

Estos no se ejecutan aqui: se los declaramos a OpenAI y sus servidores hablan
directamente con el MCP. Por eso no hace falta instalar nada localmente, pero
tambien por eso el token viaja a OpenAI en cada peticion.
"""

import os

URL_SUPABASE = "https://mcp.supabase.com/mcp"


def supabase() -> dict | None:
    """Descriptor del MCP de Supabase, o None si no esta configurado."""
    token = os.getenv("SUPABASE_ACCESS_TOKEN", "").strip()
    if not token or token.startswith("sbp-pon-tu"):
        return None

    parametros = []

    referencia = os.getenv("SUPABASE_PROJECT_REF", "").strip()
    if referencia:
        # Acotar a un proyecto tambien apaga las herramientas de cuenta
        # (crear/pausar proyectos), que no queremos al alcance de la voz.
        parametros.append(f"project_ref={referencia}")

    if solo_lectura():
        parametros.append("read_only=true")

    url = URL_SUPABASE + ("?" + "&".join(parametros) if parametros else "")

    return {
        "type": "mcp",
        "server_label": "supabase",
        "server_url": url,
        "authorization": token,
        "require_approval": "never",
        # Acotar la lista mantiene el catalogo pequeno y evita que el modelo
        # se vaya por herramientas lentas o irrelevantes en medio de una
        # conversacion hablada.
        "allowed_tools": [
            "execute_sql",
            "list_tables",
            "get_advisors",
            "get_logs",
        ],
    }


def solo_lectura() -> bool:
    return os.getenv("SUPABASE_SOLO_LECTURA", "true").strip().lower() != "false"


def activos() -> list[dict]:
    return [conector for conector in (supabase(),) if conector is not None]


def resumen() -> dict:
    """Para que la interfaz pueda mostrar que hay conectado."""
    return {
        "supabase": supabase() is not None,
        "supabase_solo_lectura": solo_lectura(),
        "supabase_proyecto": os.getenv("SUPABASE_PROJECT_REF", "").strip(),
    }
