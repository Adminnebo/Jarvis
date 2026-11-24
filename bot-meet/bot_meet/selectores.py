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
CAJA_CHAT = re.compile(r"Env(í|i)a(r)? un mensaje|Send a message")   # real: "Envía un mensaje"
# Dentro de la llamada, el botón dice "Desactivar ..." mientras está PRENDIDO.
CSS_PRENDIDOS = ('[aria-label^="Desactivar micrófono"], [aria-label^="Desactivar cámara"], '
                 '[aria-label^="Turn off microphone"], [aria-label^="Turn off camera"]')

# Calibración: por cada mosaico, su texto y sus "marcas" (clases y atributos data-*/aria-*
# de él y sus descendientes). Comparando segundos con y sin voz sale qué marca dice
# "está hablando" y dónde está el nombre.
JS_FOTO = """() => {
  const salida = [];
  for (const m of document.querySelectorAll('[data-participant-id]')) {
    const marcas = new Set();
    for (const el of [m, ...m.querySelectorAll('*')]) {
      for (const c of el.classList) marcas.add('c:' + c);
      for (const a of el.attributes) {
        if ((a.name.startsWith('data-') || a.name.startsWith('aria-')) && a.value.length <= 60
            && !a.name.startsWith('data-participant')) marcas.add('a:' + a.name + '=' + a.value);
      }
    }
    salida.push({id: m.getAttribute('data-participant-id'), texto: (m.innerText || '').trim().slice(0, 120),
                 marcas: [...marcas].sort()});
  }
  return salida;
}"""

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
