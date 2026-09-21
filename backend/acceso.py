"""Control de acceso.

Jarvis nacio para correr en localhost, donde no hacia falta pedir nada. En un
servidor la historia cambia: quien tenga la URL puede consultar tu base de
datos, leer tus recuerdos y gastar tus creditos de OpenAI.

Por eso, si esto corre hospedado y no hay JARVIS_PASSWORD, la aplicacion no se
sirve. Es preferible un despliegue que no arranca a uno abierto de par en par.
"""

import hashlib
import hmac
import html
import os
import time
from dataclasses import dataclass

from . import rutas

COOKIE = "jarvis_acceso"
DURACION = 30 * 24 * 3600   # 30 dias


PREFIJO = "JARVIS_PASSWORD_"


@dataclass(frozen=True)
class Usuario:
    id: str
    nombre: str
    rol: str        # "admin" | "usuario"
    # Solo lo llevan las cuentas de organizacion (cuentas.py). None para las
    # de JARVIS_PASSWORD_<NOMBRE> y las de los paneles de Supabase.
    organizacion_id: str | None = None


def _catalogo() -> list[tuple[Usuario, str]]:
    """Cada persona con su contrasena, leidas del entorno.

    El admin es quien tiene JARVIS_PASSWORD; su nombre sigue saliendo de
    JARVIS_USUARIO, como cuando habia un solo usuario. Los demas salen del
    sufijo de la variable: JARVIS_PASSWORD_JORGE es jorge, y se llama Jorge.
    """
    entradas: list[tuple[Usuario, str]] = []

    nombre_admin = os.getenv("JARVIS_USUARIO", "").strip() or "Admin"
    principal = os.getenv("JARVIS_PASSWORD", "").strip()
    entradas.append((Usuario("admin", nombre_admin, "admin"), principal))

    for variable, valor in sorted(os.environ.items()):
        if not variable.startswith(PREFIJO):
            continue

        sufijo = variable[len(PREFIJO):].strip()
        contrasena = (valor or "").strip()

        # Una contrasena vacia dejaria entrar a cualquiera, y un sufijo vacio
        # no da un id con el que separar la memoria. El aviso no va aqui: esto
        # corre en cada peticion y llenaria el log. Lo hace avisar_de_*().
        if not sufijo or not contrasena:
            continue

        entradas.append(
            (Usuario(sufijo.lower(), sufijo.capitalize(), "usuario"), contrasena)
        )

    return entradas


def usuarios() -> list[Usuario]:
    return [usuario for usuario, _ in _catalogo()]


def clave() -> str:
    return os.getenv("JARVIS_PASSWORD", "").strip()


def protegido() -> bool:
    return bool(clave())


def obligatorio() -> bool:
    """Hospedado sin contrasena es el unico caso que bloqueamos por completo."""
    return rutas.hospedado() and not protegido()


def clave_de_sesion() -> bytes:
    """La clave con la que se firman las cookies.

    Antes se firmaba con la contrasena misma, pero con varias personas el token
    tiene que decir quien es y la firma no puede depender de una sola clave.

    Se deriva de JARVIS_CLAVE_SECRETA en vez de usarla tal cual, para no
    reutilizar la clave que cifra las credenciales. Sin esa variable se deriva
    de las contrasenas configuradas: estable entre despliegues mientras no
    cambien. Cambiar JARVIS_CLAVE_SECRETA cierra la sesion de todos, y esa es
    la forma de echar a alguien de inmediato.
    """
    secreta = os.getenv("JARVIS_CLAVE_SECRETA", "").strip()
    if not secreta:
        secreta = "|".join(sorted(c for _, c in _catalogo() if c))
    return hmac.new(secreta.encode("utf-8"), b"sesiones", hashlib.sha256).digest()


def _firma(id_usuario: str, caduca: int) -> str:
    cuerpo = f"{id_usuario}.{caduca}".encode("utf-8")
    return hmac.new(clave_de_sesion(), cuerpo, hashlib.sha256).hexdigest()


def crear_token(usuario: Usuario) -> str:
    caduca = int(time.time()) + DURACION
    return f"{usuario.id}.{caduca}.{_firma(usuario.id, caduca)}"


def usuario_de_token(valor: str | None) -> Usuario | None:
    """El usuario que hay dentro de un token valido, o None."""
    if not valor:
        return None

    partes = valor.split(".", 2)
    if len(partes) != 3:
        return None

    id_usuario, caduca_texto, firma = partes

    try:
        caduca = int(caduca_texto)
    except ValueError:
        return None

    if caduca < time.time():
        return None

    if not hmac.compare_digest(firma, _firma(id_usuario, caduca)):
        return None

    from . import supabase_sesion

    if id_usuario.startswith(supabase_sesion.PREFIJO):
        # Quien viene de un panel no vive en el catalogo de variables: su
        # nombre y su permiso los confirma supabase_sesion.revalidar() contra
        # profiles, en el middleware. Aqui solo consta que la firma es buena.
        #
        # El rol es "sin-confirmar" a proposito, y no "usuario": asi, si algun
        # dia alguien llama a esta funcion sin revalidar despues, lo que
        # reciba no le sirve para pasar por ningun control.
        return Usuario(id_usuario, id_usuario, "sin-confirmar")

    from . import cuentas

    if id_usuario.startswith(cuentas.PREFIJO):
        # Vive en jarvis.db, no en el entorno: si borraron la cuenta, esto
        # devuelve None y el token deja de valer, igual que con una variable.
        return cuentas.usuario_de_id(id_usuario[len(cuentas.PREFIJO):])

    # Que la firma sea buena no basta: si le quitaron su variable, ese token
    # ya no vale.
    return usuario_de_id(id_usuario)


def usuario_de_id(id_usuario: str) -> Usuario | None:
    """Busca en el catalogo de variables de entorno. No sirve para 'sb-' ni 'u-'."""
    return next((u for u in usuarios() if u.id == id_usuario), None)


def quien_entra(intento: str) -> Usuario | None:
    """Devuelve la persona cuya contrasena es la escrita, o None.

    Recorre todas las contrasenas sin cortar en la primera coincidencia: si
    saliera antes, el tiempo de respuesta revelaria cuantos usuarios hay y en
    que orden estan.
    """
    escrita = (intento or "").strip()
    encontrado: Usuario | None = None

    for usuario, contrasena in _catalogo():
        if not contrasena:
            continue
        if hmac.compare_digest(escrita, contrasena) and encontrado is None:
            encontrado = usuario

    return encontrado


def por_defecto() -> Usuario:
    """Quien es el usuario cuando no hay login: en local, y solo ahi."""
    return _catalogo()[0][0]


def _variables_ignoradas() -> list[str]:
    """Variables con el prefijo que no llegan a ser un usuario."""
    return [
        variable
        for variable, valor in sorted(os.environ.items())
        if variable.startswith(PREFIJO)
        and (not variable[len(PREFIJO):].strip() or not (valor or "").strip())
    ]


def avisar_de_contrasenas_repetidas() -> None:
    """Revisa la configuracion de usuarios y avisa de lo que quedo mal.

    Se llama una sola vez, al arrancar. Dos personas con la misma contrasena
    son indistinguibles al entrar, y callarlo mezclaria sus memorias sin que
    nadie se entere; gana el primero del catalogo. Una variable ignorada suele
    ser un despiste que deja a alguien afuera sin explicacion.
    """
    for variable in _variables_ignoradas():
        print(f"  AVISO: se ignora {variable}: sufijo o contrasena vacios.")

    vistas: dict[str, str] = {}
    repetidas: list[str] = []

    for usuario, contrasena in _catalogo():
        if not contrasena:
            continue
        if contrasena in vistas:
            repetidas.append(f"{usuario.id} y {vistas[contrasena]}")
        else:
            vistas[contrasena] = usuario.id

    for par in repetidas:
        print(
            f"  AVISO: {par} se repiten la contrasena. No se pueden distinguir "
            "al entrar y comparten memoria. Ponles contrasenas distintas."
        )


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
  .bien { color:#9be9a8; font-size:13px; margin-top:14px; }
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
  <p style="margin-top:18px;">
    <a href="/acceso/cuenta">Entrar con tu correo</a>
  </p>
</div></body></html>"""


def pagina_registro(error: str = "", hecho: str = "") -> str:
    """Alta de organizaciones. Solo la ve quien administra Jarvis.

    Los dos mensajes se escapan: `hecho` lleva el nombre de la organizacion
    tal como se escribio, y esto se arma con un f-string.
    """
    aviso = (
        f'<p class="mal">{html.escape(error)}</p>' if error
        else f'<p class="bien">{html.escape(hecho)}</p>' if hecho
        else ""
    )
    return f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Jarvis - Nueva organizacion</title><style>{_ESTILO}</style></head><body>
<div class="caja">
  <h1>Nueva organizacion</h1>
  <p>Con la primera persona que la administra. Esa persona entra despues con
     su correo y puede sumar al resto de su gente.</p>
  <form method="post" action="/registro">
    <input type="text" name="organizacion" placeholder="Nombre de la organizacion"
           autofocus required>
    <input type="text" name="nombre" placeholder="Nombre de quien la administra" required>
    <input type="email" name="email" placeholder="Su correo" required
           autocomplete="off">
    <input type="password" name="password" placeholder="Su contrasena (minimo 8 caracteres)"
           required autocomplete="new-password">
    <button type="submit">Crear</button>
  </form>
  {aviso}
  <p style="margin-top:18px;"><a href="/">Volver a Jarvis</a></p>
</div></body></html>"""


def pagina_entrar_cuenta(error: str = "") -> str:
    aviso = f'<p class="mal">{error}</p>' if error else ""
    return f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Jarvis - Entrar</title><style>{_ESTILO}</style></head><body>
<div class="caja">
  <h1>Entrar</h1>
  <form method="post" action="/acceso/cuenta">
    <input type="email" name="email" placeholder="Correo" required
           autofocus autocomplete="email">
    <input type="password" name="password" placeholder="Contrasena" required
           autocomplete="current-password">
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


def pagina_de_entrada() -> str:
    """Recibe el token del panel y lo convierte en una sesion de Jarvis.

    El token llega en el fragmento de la URL, no en la query: el fragmento no
    se manda al servidor, asi que no queda en los logs de acceso ni se filtra
    por la cabecera Referer. Se borra de la barra en cuanto se lee, para que
    tampoco quede en el historial.

    El POST es al mismo origen porque la cookie es SameSite=Lax y no se
    guardaria en un POST venido de otro sitio.
    """
    guion = """
(async () => {
  const mensaje = document.getElementById('mensaje');
  const token = new URLSearchParams(location.hash.slice(1)).get('t');
  history.replaceState(null, '', location.pathname);

  if (!token) {
    mensaje.textContent = 'Falta el token. Vuelve a entrar desde el panel.';
    return;
  }

  try {
    const r = await fetch('/acceso/supabase', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: token }),
    });
    if (r.ok) { location.replace('/'); return; }
    const datos = await r.json().catch(() => ({}));
    mensaje.textContent = datos.error || 'No se pudo entrar.';
  } catch (e) {
    mensaje.textContent = 'No se pudo contactar con Jarvis.';
  }
})();
"""
    return f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Jarvis</title><style>{_ESTILO}</style></head><body>
<div class="caja">
  <h1>Jarvis</h1>
  <p id="mensaje">Entrando...</p>
</div>
<script>{guion}</script>
</body></html>"""


# --------------------------------------------------------------------------
# Que se puede pedir sin haber entrado
# --------------------------------------------------------------------------

LIBRES = (
    "/acceso", "/api/salud", "/api/version", "/entrar", "/acceso/supabase",
    "/acceso/cuenta", "/api/dispositivos/vincular",
)


def es_libre(ruta: str) -> bool:
    return ruta in LIBRES


def exige_admin(ruta: str, metodo: str) -> bool:
    """Que solo puede hacer quien administra Jarvis.

    Se decide aqui y lo aplica el middleware. Esconder el boton en la web es
    comodidad, no control de acceso.
    """
    if ruta.startswith("/api/fuentes"):
        return True
    if ruta == "/api/esquema/refrescar":
        return True
    # Solo el tablero de gasto. /api/consumo/voz no entra: lo escribe el
    # navegador de cualquiera durante la sesion de voz.
    if ruta == "/api/consumo" and metodo in ("GET", "DELETE"):
        return True
    # Lo que consumio cada organizacion es del negocio, no de cada cliente.
    if ruta.startswith("/api/organizaciones"):
        return True
    # Crear organizaciones. Estuvo abierto a cualquiera, y como las fuentes de
    # datos son comunes, cualquiera que tuviera la URL podia registrarse y
    # consultarlas.
    if ruta == "/registro":
        return True
    return False
