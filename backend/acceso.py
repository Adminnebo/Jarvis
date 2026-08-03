"""Control de acceso.

Jarvis nacio para correr en localhost, donde no hacia falta pedir nada. En un
servidor la historia cambia: quien tenga la URL puede consultar tu base de
datos, leer tus recuerdos y gastar tus creditos de OpenAI.

Por eso, si esto corre hospedado y no hay JARVIS_PASSWORD, la aplicacion no se
sirve. Es preferible un despliegue que no arranca a uno abierto de par en par.
"""

import hashlib
import hmac
import os
import time

from . import rutas

COOKIE = "jarvis_acceso"
DURACION = 30 * 24 * 3600   # 30 dias


def clave() -> str:
    return os.getenv("JARVIS_PASSWORD", "").strip()


def protegido() -> bool:
    return bool(clave())


def obligatorio() -> bool:
    """Hospedado sin contrasena es el unico caso que bloqueamos por completo."""
    return rutas.hospedado() and not protegido()


def _firma(caduca: int) -> str:
    return hmac.new(
        clave().encode("utf-8"), str(caduca).encode("ascii"), hashlib.sha256
    ).hexdigest()


def crear_token() -> str:
    caduca = int(time.time()) + DURACION
    return f"{caduca}.{_firma(caduca)}"


def token_valido(valor: str | None) -> bool:
    if not valor or "." not in valor:
        return False
    caduca, _, firma = valor.partition(".")
    try:
        if int(caduca) < time.time():
            return False
    except ValueError:
        return False
    return hmac.compare_digest(firma, _firma(int(caduca)))


def clave_correcta(intento: str) -> bool:
    return hmac.compare_digest((intento or "").strip(), clave())


# --------------------------------------------------------------------------
# Paginas
# --------------------------------------------------------------------------

_ESTILO = """
  body { margin:0; min-height:100vh; display:grid; place-items:center;
         background:radial-gradient(circle at 50% 0%,#101828 0%,#07090e 55%);
         color:#e6ecf5; font:15px/1.6 "Segoe UI",system-ui,sans-serif; }
  .caja { width:min(420px,92vw); padding:32px; border:1px solid #1c2432;
          border-radius:16px; background:#0e1219; }
  h1 { margin:0 0 6px; font-size:17px; letter-spacing:.14em;
       text-transform:uppercase; }
  p { color:#7c8798; font-size:13.5px; }
  input { width:100%; box-sizing:border-box; margin-top:16px; padding:12px 15px;
          border-radius:10px; border:1px solid #1c2432; background:#07090e;
          color:#e6ecf5; font:inherit; outline:none; }
  input:focus { border-color:#4da3ff; }
  button { width:100%; margin-top:12px; padding:12px; border:none;
           border-radius:10px; background:#4da3ff; color:#04121f;
           font:inherit; font-weight:600; cursor:pointer; }
  code { background:#07090e; padding:2px 7px; border-radius:6px;
         color:#9ecbff; font-size:13px; }
  .mal { color:#ffc9c9; font-size:13px; margin-top:14px; }
  ol { color:#7c8798; font-size:13.5px; padding-left:20px; }
  li { margin-bottom:8px; }
"""


def pagina_login(error: str = "") -> str:
    aviso = f'<p class="mal">{error}</p>' if error else ""
    return f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Jarvis</title><style>{_ESTILO}</style></head><body>
<div class="caja">
  <h1>Jarvis</h1>
  <p>Esta instancia esta protegida.</p>
  <form method="post" action="/acceso">
    <input type="password" name="clave" placeholder="Contrasena"
           autofocus autocomplete="current-password">
    <button type="submit">Entrar</button>
  </form>
  {aviso}
</div></body></html>"""


def pagina_sin_proteger() -> str:
    return f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Jarvis - falta configurar</title><style>{_ESTILO}</style></head><body>
<div class="caja">
  <h1>Falta una contrasena</h1>
  <p>Jarvis no se sirve en un servidor sin proteccion. Quien tenga esta URL
     podria consultar tus bases de datos, leer tus recuerdos y gastar tus
     creditos de OpenAI.</p>
  <ol>
    <li>En tu proveedor, abre las variables de entorno del servicio.</li>
    <li>Agrega <code>JARVIS_PASSWORD</code> con una contrasena larga.</li>
    <li>Vuelve a desplegar.</li>
  </ol>
  <p>En local no hace falta: sin variable, Jarvis funciona normal.</p>
</div></body></html>"""


# --------------------------------------------------------------------------
# Que se puede pedir sin haber entrado
# --------------------------------------------------------------------------

LIBRES = ("/acceso", "/api/salud")


def es_libre(ruta: str) -> bool:
    return ruta in LIBRES
