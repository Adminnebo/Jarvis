"""Todo lo que depende de cómo es la página de Meet.

Cuando Google cambie Meet, el mantenimiento es aquí. Chrome se abre en
español (es-419), pero se aceptan también los textos en inglés.
"""
import re

BOTON_UNIRSE = re.compile(r"^(Unirse ahora|Pedir unirse|Solicitar unirse|Join now|Ask to join)$")
APAGAR_MICRO = re.compile(r"Desactivar micrófono|Turn off microphone")
APAGAR_CAMARA = re.compile(r"Desactivar cámara|Turn off camera")
SALIR_LLAMADA = re.compile(r"Abandonar la llamada|Salir de la llamada|Leave call")
# Para saber si sigue en la llamada se busca en el DOM, no por rol: con un
# diálogo abierto Meet saca los botones del árbol de accesibilidad y por rol
# parecería que el bot ya no está (pasó en la primera prueba real).
CSS_EN_LLAMADA = ('[aria-label="Abandonar la llamada"], [aria-label="Salir de la llamada"], '
                  '[aria-label="Leave call"]')
TEXTO_RECHAZADO = re.compile(r"rechazó tu solicitud|No puedes unirte|denied your request|You can't join")

MAS_OPCIONES = re.compile(r"Más opciones|More options")
CONFIGURACION = re.compile(r"^(Configuración|Settings)$")
PESTANA_VIDEO = re.compile(r"^(Video|Vídeo)$")
RESOLUCION_RECEPCION = re.compile(r"Resolución de recepción|Receive resolution")
SOLO_AUDIO = "Solo audio"
CERRAR_DIALOGO = re.compile(r"^(Cerrar|Close)( diálogo| dialog)?$")  # real: "Cerrar diálogo"

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
