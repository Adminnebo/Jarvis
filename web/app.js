/* Interfaz de Jarvis.

   Dos modos que comparten memoria e historial:
     - texto: escribes o dictas con la Web Speech API, responde el backend.
     - voz en vivo: audio directo con OpenAI Realtime sobre WebRTC. */

import { crearSesionDeVoz } from "./voz.js";
import { abrirPanelFuentes } from "./fuentes.js";

const $ = (id) => document.getElementById(id);

const orbe = $("orbe");
const pieOrbe = $("pie-orbe");
const conversacion = $("conversacion");
const campo = $("campo");
const btnMicrofono = $("btn-microfono");
const casillaManosLibres = $("manos-libres");
const puntoEstado = $("punto-estado");

const btnVivo = $("btn-vivo");

let ocupado = false;       // hay una respuesta en curso
let escuchando = false;    // el microfono esta abierto
let queremosEscuchar = false;
let sesionViva = null;     // sesion de voz en vivo, si esta activa

// --------------------------------------------------------------------------
// Estado visual
// --------------------------------------------------------------------------

function estadoVisual(modo, texto) {
  orbe.classList.remove("escuchando", "pensando", "hablando");
  if (modo) orbe.classList.add(modo);
  pieOrbe.textContent = texto;
}

function enReposo() {
  estadoVisual(
    null,
    casillaManosLibres.checked
      ? 'Escuchando. Di "Jarvis" para empezar.'
      : "Presiona el microfono o escribe"
  );
}

// --------------------------------------------------------------------------
// Burbujas de conversacion
// --------------------------------------------------------------------------

function burbuja(clase, texto = "") {
  const nodo = document.createElement("div");
  nodo.className = `mensaje ${clase}`;
  nodo.textContent = texto;
  conversacion.appendChild(nodo);
  conversacion.scrollTop = conversacion.scrollHeight;
  return nodo;
}

function alFinal() {
  conversacion.scrollTop = conversacion.scrollHeight;
}

// --------------------------------------------------------------------------
// Voz de salida
// --------------------------------------------------------------------------

let vozElegida = null;

function elegirVoz() {
  const voces = speechSynthesis.getVoices();
  if (!voces.length) return;
  // Preferimos una voz en espanol; si no hay, la que sea.
  vozElegida =
    voces.find((v) => /^es-(MX|US|419)/i.test(v.lang)) ||
    voces.find((v) => v.lang.toLowerCase().startsWith("es")) ||
    voces[0];
}
elegirVoz();
speechSynthesis.onvoiceschanged = elegirVoz;

const colaDeVoz = [];
let hablando = false;

function decir(texto) {
  const limpio = texto
    .replace(/[*_`#>]/g, "")          // restos de markdown
    .replace(/https?:\/\/\S+/g, "")   // los enlaces no se leen bien
    .trim();
  if (!limpio) return;

  colaDeVoz.push(limpio);
  if (!hablando) siguienteFrase();
}

function siguienteFrase() {
  const frase = colaDeVoz.shift();
  if (frase === undefined) {
    hablando = false;
    if (!ocupado) {
      enReposo();
      if (queremosEscuchar) abrirMicrofono();
    }
    return;
  }

  hablando = true;
  // Mientras Jarvis habla cerramos el microfono para no oirse a si mismo.
  cerrarMicrofono();
  orbe.classList.add("hablando");

  const locucion = new SpeechSynthesisUtterance(frase);
  if (vozElegida) locucion.voice = vozElegida;
  locucion.lang = vozElegida?.lang || "es-MX";
  locucion.rate = 1.03;
  locucion.onend = () => {
    orbe.classList.remove("hablando");
    siguienteFrase();
  };
  locucion.onerror = locucion.onend;
  speechSynthesis.speak(locucion);
}

function callar() {
  colaDeVoz.length = 0;
  speechSynthesis.cancel();
  hablando = false;
  orbe.classList.remove("hablando");
}

// --------------------------------------------------------------------------
// Voz de entrada
// --------------------------------------------------------------------------

const Reconocimiento =
  window.SpeechRecognition || window.webkitSpeechRecognition;

let reconocimiento = null;

if (Reconocimiento) {
  reconocimiento = new Reconocimiento();
  reconocimiento.lang = "es-MX";
  reconocimiento.continuous = true;
  reconocimiento.interimResults = true;

  reconocimiento.onstart = () => {
    escuchando = true;
    btnMicrofono.classList.add("activo");
    if (!ocupado && !hablando) estadoVisual("escuchando", "Te escucho...");
  };

  reconocimiento.onend = () => {
    escuchando = false;
    btnMicrofono.classList.remove("activo");
    // El navegador corta la escucha cada cierto tiempo; la reabrimos.
    if (queremosEscuchar && !hablando && !ocupado) {
      setTimeout(abrirMicrofono, 250);
    } else if (!queremosEscuchar && !ocupado && !hablando) {
      enReposo();
    }
  };

  reconocimiento.onerror = (evento) => {
    if (evento.error === "not-allowed" || evento.error === "service-not-allowed") {
      queremosEscuchar = false;
      casillaManosLibres.checked = false;
      burbuja("error", "El navegador bloqueo el microfono. Permitelo y vuelve a intentar.");
    }
    // 'no-speech' y 'aborted' son normales: los ignoramos y onend reabre.
  };

  reconocimiento.onresult = (evento) => {
    let parcial = "";
    let definitivo = "";

    for (let i = evento.resultIndex; i < evento.results.length; i++) {
      const texto = evento.results[i][0].transcript;
      if (evento.results[i].isFinal) definitivo += texto;
      else parcial += texto;
    }

    if (parcial && !ocupado) estadoVisual("escuchando", parcial.trim());
    if (!definitivo.trim()) return;

    const orden = casillaManosLibres.checked
      ? extraerTrasPalabraClave(definitivo)
      : definitivo.trim();

    if (orden === null) return;  // manos libres sin palabra clave: seguimos oyendo

    if (!casillaManosLibres.checked) cerrarMicrofono();

    if (!orden) {
      estadoVisual("escuchando", "Dime.");
      return;
    }
    enviar(orden);
  };
} else {
  btnMicrofono.disabled = true;
  btnMicrofono.title = "Este navegador no reconoce voz. Usa Chrome o Edge.";
  casillaManosLibres.disabled = true;
}

// El reconocimiento en espanol suele escribir mal el nombre; aceptamos variantes.
const PALABRA_CLAVE = /\b(jarvis|yarvis|harvis|charvis|jarbis|yarbis)\b/i;

function extraerTrasPalabraClave(texto) {
  const encontrada = texto.match(PALABRA_CLAVE);
  if (!encontrada) return null;
  return texto.slice(encontrada.index + encontrada[0].length).trim();
}

function abrirMicrofono() {
  if (!reconocimiento || escuchando) return;
  try {
    reconocimiento.start();
  } catch {
    // start() lanza si ya estaba arrancando; no hay nada que hacer.
  }
}

function cerrarMicrofono() {
  if (!reconocimiento || !escuchando) return;
  try {
    reconocimiento.stop();
  } catch {
    /* ignorado */
  }
}

btnMicrofono.addEventListener("click", () => {
  callar();
  if (escuchando) {
    queremosEscuchar = false;
    cerrarMicrofono();
  } else {
    queremosEscuchar = casillaManosLibres.checked;
    abrirMicrofono();
  }
});

casillaManosLibres.addEventListener("change", () => {
  queremosEscuchar = casillaManosLibres.checked;
  if (queremosEscuchar) abrirMicrofono();
  else cerrarMicrofono();
  if (!ocupado && !hablando) enReposo();
});

// Barra espaciadora como pulsar-para-hablar, salvo mientras se escribe.
// Cuenta cualquier campo de texto, no solo el del chat: en los formularios
// de fuentes un espacio abriria el microfono en medio de una contrasena.
function escribiendo() {
  const activo = document.activeElement;
  return activo && (
    activo.tagName === "INPUT" ||
    activo.tagName === "TEXTAREA" ||
    activo.tagName === "SELECT" ||
    activo.isContentEditable
  );
}

document.addEventListener("keydown", (evento) => {
  if (evento.code === "Space" && !escribiendo()) {
    evento.preventDefault();
    btnMicrofono.click();
  }
});

// --------------------------------------------------------------------------
// Conversacion con el backend
// --------------------------------------------------------------------------

campo.addEventListener("keydown", (evento) => {
  if (evento.key !== "Enter" || !campo.value.trim()) return;

  const texto = campo.value.trim();
  campo.value = "";

  // En vivo el texto entra por el canal de datos y sale hablado.
  if (sesionViva) {
    burbuja("usuario", texto);
    guardarTurno("user", texto);
    sesionViva.escribir(texto);
  } else {
    enviar(texto);
  }
});

async function enviar(mensaje) {
  if (ocupado) return;
  ocupado = true;
  callar();
  cerrarMicrofono();

  burbuja("usuario", mensaje);
  estadoVisual("pensando", "Pensando...");

  const nodoRespuesta = burbuja("jarvis");
  let completo = "";
  let porDecir = "";

  try {
    const respuesta = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mensaje }),
    });

    if (!respuesta.ok) throw new Error(`El servidor respondio ${respuesta.status}`);

    const lector = respuesta.body.getReader();
    const decodificador = new TextDecoder();
    let pendiente = "";

    while (true) {
      const { value, done } = await lector.read();
      if (done) break;

      pendiente += decodificador.decode(value, { stream: true });
      const bloques = pendiente.split("\n\n");
      pendiente = bloques.pop();

      for (const bloque of bloques) {
        const linea = bloque.split("\n").find((l) => l.startsWith("data: "));
        if (!linea) continue;

        const evento = JSON.parse(linea.slice(6));

        if (evento.tipo === "texto") {
          completo += evento.dato;
          porDecir += evento.dato;
          nodoRespuesta.textContent = completo;
          alFinal();

          // Hablamos frase por frase para no esperar a que termine todo.
          const corte = porDecir.search(/[.!?\n](?=\s|$)/);
          if (corte !== -1) {
            decir(porDecir.slice(0, corte + 1));
            porDecir = porDecir.slice(corte + 1);
          }
        } else if (evento.tipo === "herramienta") {
          estadoVisual("pensando", `Consultando ${evento.dato}...`);
        } else if (evento.tipo === "aviso") {
          // Algo degradado, pero la respuesta sigue en camino.
          burbuja("error", evento.dato);
          conversacion.insertBefore(nodoRespuesta, null);
        } else if (evento.tipo === "error") {
          nodoRespuesta.remove();
          burbuja("error", evento.dato);
          completo = "";
          porDecir = "";
        }
      }
    }

    if (porDecir.trim()) decir(porDecir);
    if (!completo && nodoRespuesta.isConnected) nodoRespuesta.remove();
  } catch (error) {
    nodoRespuesta.remove();
    burbuja("error", `No pude conectar con el servidor: ${error.message}`);
  } finally {
    ocupado = false;
    if (!hablando) {
      enReposo();
      if (queremosEscuchar) abrirMicrofono();
    }
    cargarEstado();
  }
}

// --------------------------------------------------------------------------
// Modo voz en vivo
// --------------------------------------------------------------------------

let burbujaViva = null;   // burbuja que se va llenando mientras Jarvis habla

const medidor = $("medidor");
const barraMedidor = $("medidor-barra");
const umbralMedidor = $("medidor-umbral");

async function guardarTurno(role, content) {
  try {
    await fetch("/api/conversacion/agregar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role, content }),
    });
  } catch {
    // Que falle el guardado no debe cortar la conversacion.
  }
}

async function abrirVozEnVivo() {
  // El modo texto y el de voz se pelean por el microfono.
  callar();
  queremosEscuchar = false;
  casillaManosLibres.checked = false;
  cerrarMicrofono();
  btnMicrofono.disabled = true;
  casillaManosLibres.disabled = true;

  btnVivo.classList.add("activo");
  btnVivo.textContent = "Cortar";
  campo.placeholder = "Escribe y te responde hablando...";
  medidor.hidden = false;

  sesionViva = crearSesionDeVoz({
    onEstado: (modo, texto) => {
      const animacion = { escuchando: "escuchando", conectando: "pensando" }[modo] || null;
      estadoVisual(animacion, texto);
    },

    onUsuario: (texto) => {
      burbuja("usuario", texto);
      guardarTurno("user", texto);
    },

    onRespuestaParcial: (fragmento) => {
      if (!burbujaViva) burbujaViva = burbuja("jarvis");
      burbujaViva.textContent += fragmento;
      orbe.classList.add("hablando");
      alFinal();
    },

    onRespuestaCompleta: (texto) => {
      orbe.classList.remove("hablando");
      if (texto.trim()) guardarTurno("assistant", texto.trim());
      burbujaViva = null;
      cargarEstado();
    },

    onNivel: (nivel, umbral, abierto) => {
      // Escala fija: por encima de 0.15 ya es voz claramente alta.
      const porcentaje = (valor) => Math.min(100, (valor / 0.15) * 100);
      barraMedidor.style.width = `${porcentaje(nivel)}%`;
      barraMedidor.classList.toggle("abierto", abierto);
      umbralMedidor.style.left = `${porcentaje(umbral)}%`;
    },

    onHerramienta: (nombre) => estadoVisual("pensando", `Consultando ${nombre}...`),

    onError: (mensaje) => burbuja("error", mensaje),

    onCierre: () => cerrarVozEnVivo(),
  });

  try {
    const datos = await sesionViva.conectar();
    burbuja("jarvis", "").remove();
    estadoVisual("escuchando", "En vivo. Habla cuando quieras.");
    $("meta").textContent = `${datos.modelo} · en vivo`;
  } catch (error) {
    burbuja("error", `No pude abrir la voz en vivo: ${error.message}`);
    cerrarVozEnVivo();
  }
}

function cerrarVozEnVivo() {
  const sesion = sesionViva;
  sesionViva = null;
  sesion?.cerrar();

  burbujaViva = null;
  medidor.hidden = true;
  barraMedidor.style.width = "0%";
  btnVivo.classList.remove("activo");
  btnVivo.textContent = "Voz en vivo";
  btnMicrofono.disabled = !Reconocimiento;
  casillaManosLibres.disabled = !Reconocimiento;
  campo.placeholder = "Escribe algo...";
  orbe.classList.remove("hablando");
  enReposo();
  cargarEstado();
}

btnVivo.addEventListener("click", () => {
  if (sesionViva) cerrarVozEnVivo();
  else abrirVozEnVivo();
});

// --------------------------------------------------------------------------
// Panel de memoria
// --------------------------------------------------------------------------

const panel = $("panel-memoria");

$("btn-memoria").addEventListener("click", async () => {
  panel.hidden = false;
  const { hechos } = await (await fetch("/api/memoria")).json();
  const lista = $("lista-memoria");

  if (!hechos.length) {
    lista.innerHTML = '<p class="vacio">Todavia no recuerdo nada. Cuentame algo.</p>';
    return;
  }

  lista.innerHTML = "";
  for (const hecho of hechos.slice().reverse()) {
    const nodo = document.createElement("div");
    nodo.className = "hecho";

    const cabecera = document.createElement("div");
    cabecera.className = "hecho-cabecera";

    const etiqueta = document.createElement("span");
    etiqueta.className = "etiqueta";
    etiqueta.textContent = hecho.categoria;

    const borrar = document.createElement("button");
    borrar.textContent = "×";
    borrar.title = "Olvidar";
    borrar.addEventListener("click", async () => {
      await fetch(`/api/memoria/${hecho.id}`, { method: "DELETE" });
      nodo.remove();
      cargarEstado();
    });

    cabecera.append(etiqueta, borrar);

    const contenido = document.createElement("div");
    contenido.textContent = hecho.contenido;

    nodo.append(cabecera, contenido);
    lista.appendChild(nodo);
  }
});

$("btn-cerrar-panel").addEventListener("click", () => {
  panel.hidden = true;
});

$("btn-fuentes").addEventListener("click", abrirPanelFuentes);

// --------------------------------------------------------------------------
// Cerrar paneles: Escape y clic en el fondo
// --------------------------------------------------------------------------

function capasAbiertas() {
  // En orden del documento, asi que la ultima es la que esta mas encima.
  return [...document.querySelectorAll(".modal:not([hidden]), .panel:not([hidden])")];
}

document.addEventListener("keydown", (evento) => {
  if (evento.key !== "Escape") return;
  const encima = capasAbiertas().at(-1);
  if (encima) {
    encima.hidden = true;
    evento.preventDefault();
  }
});

// Clic en el fondo oscuro del modal, no en su contenido.
for (const modal of document.querySelectorAll(".modal")) {
  modal.addEventListener("click", (evento) => {
    if (evento.target === modal) modal.hidden = true;
  });
}

$("btn-reiniciar").addEventListener("click", async () => {
  await fetch("/api/conversacion/reiniciar", { method: "POST" });
  conversacion.innerHTML = "";
  callar();
  enReposo();
});

// --------------------------------------------------------------------------
// Arranque
// --------------------------------------------------------------------------

// --------------------------------------------------------------------------
// Bombillo de version
// --------------------------------------------------------------------------

/* Azul encendido: esta pagina es la ultima version publicada.
   Ambar parpadeando: el servidor ya desplego otra y tu navegador tiene la
   vieja en cache. Pulsando recarga saltandose la cache. */

const bombillo = $("bombillo");
const bombilloTexto = $("bombillo-texto");
const ledVersion = $("led-version");
const ledDatos = $("led-datos");

let versionCargada = null;
let avisoVersion = "";
let avisoDatos = "";

function actualizarTitulo() {
  bombillo.title = [avisoVersion, avisoDatos].filter(Boolean).join("\n");
}

async function vigilarVersion() {
  let datos;
  try {
    datos = await (await fetch("/api/version", { cache: "no-store" })).json();
  } catch {
    return;   // sin conexion no se puede saber; se deja como esta
  }

  if (versionCargada === null) {
    versionCargada = datos.completa;
    bombilloTexto.textContent = datos.version;
  }

  const alDia = datos.completa === versionCargada;
  ledVersion.classList.toggle("on", alDia);
  ledVersion.classList.toggle("desfasado", !alDia);
  bombillo.classList.toggle("recargable", !alDia);

  avisoVersion = alDia
    ? `Version ${datos.version} — la ultima publicada`
    : `Hay una version nueva (${datos.version}). Pulsa para recargar.`;
  actualizarTitulo();
}

async function vigilarDatos() {
  let salud;
  try {
    salud = await (await fetch("/api/fuentes/salud")).json();
  } catch {
    return;
  }

  const todasOk = salud.todas_ok;
  ledDatos.classList.toggle("on", todasOk);
  ledDatos.classList.toggle("fallo", salud.total > 0 && !todasOk);

  if (!salud.total) {
    avisoDatos = "Sin bases de datos configuradas";
  } else if (todasOk) {
    const detalle = salud.fuentes
      .map((f) => `${f.nombre}: ${f.latencia_ms} ms`)
      .join("\n");
    avisoDatos = `${salud.conectadas} de ${salud.total} bases conectadas\n${detalle}`;
  } else {
    const caidas = salud.fuentes.filter((f) => !f.ok)
      .map((f) => `${f.nombre}: ${f.mensaje}`)
      .join("\n");
    avisoDatos = `Bases con problema:\n${caidas}`;
  }
  actualizarTitulo();
}

bombillo.addEventListener("click", () => {
  if (bombillo.classList.contains("recargable")) location.reload();
});

// Cada minuto basta: es para enterarse de un despliegue, no para vigilar.
setInterval(() => { vigilarVersion(); vigilarDatos(); }, 60000);

async function cargarEstado() {
  try {
    const estado = await (await fetch("/api/estado")).json();

    $("titulo").textContent = estado.nombre;
    document.title = estado.nombre;
    if (!sesionViva) {
      $("meta").textContent =
        `${estado.modelo} · ${estado.hechos_recordados} recuerdos`;
    }

    puntoEstado.className = `punto ${estado.clave_configurada ? "ok" : "problema"}`;

    const insignia = $("insignia-supabase");
    insignia.hidden = !estado.conectores?.supabase;
    if (estado.conectores?.supabase) {
      const lectura = estado.conectores.supabase_solo_lectura;
      insignia.textContent = lectura ? "Supabase · lectura" : "Supabase · escritura";
      insignia.classList.toggle("insignia-alerta", !lectura);
      insignia.title = estado.conectores.supabase_proyecto
        ? `Proyecto ${estado.conectores.supabase_proyecto}`
        : "Todos tus proyectos";
    }

    return estado;
  } catch {
    puntoEstado.className = "punto problema";
    return null;
  }
}

(async function iniciar() {
  vigilarVersion();
  vigilarDatos();
  const estado = await cargarEstado();

  if (estado && !estado.clave_configurada) {
    burbuja(
      "error",
      "Falta tu clave de OpenAI. Abre el archivo .env en la carpeta jarvis, " +
      "pon tu clave en OPENAI_API_KEY y reinicia el servidor."
    );
  }

  for (const mensaje of estado?.historial || []) {
    burbuja(mensaje.role === "user" ? "usuario" : "jarvis", mensaje.content || "");
  }

  enReposo();
})();
