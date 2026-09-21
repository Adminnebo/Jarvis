/* Interfaz de Jarvis.

   Dos modos que comparten memoria e historial:
     - texto: escribes o dictas con la Web Speech API, responde el backend.
     - voz en vivo: audio directo con OpenAI Realtime sobre WebRTC. */

import { crearSesionDeVoz } from "./voz.js";
import { abrirPanelFuentes } from "./fuentes.js";
import { abrirPanelConsumo } from "./consumo.js";
import { prepararImagen } from "./imagen.js";
import { abrirPanelDispositivos } from "./dispositivos.js";
import { abrirPanelOrganizacion } from "./organizacion.js";

const $ = (id) => document.getElementById(id);

const orbe = $("orbe");
const pieOrbe = $("pie-orbe");
const conversacion = $("conversacion");
const campo = $("campo");
const btnMicrofono = $("btn-microfono");
const casillaManosLibres = $("manos-libres");
const puntoEstado = $("punto-estado");

const btnVivo = $("btn-vivo");
const btnImagen = $("btn-imagen");
const archivoImagen = $("archivo-imagen");

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

/* Imagenes y fichas tecnicas que manda Jarvis. Cada una abre el archivo
   original en otra pestana: la miniatura es para reconocerla, no para leerla. */
function burbujaDeAdjuntos(adjuntos) {
  const nodo = burbuja("jarvis adjuntos");
  for (const adjunto of adjuntos) {
    // Las cotizaciones se abren por Jarvis (bucket privado): su enlace pide
    // uno firmado cada vez, asi que no caduca en el historial.
    const destino = /^\/api\//.test(adjunto.enlace || "") ? adjunto.enlace : adjunto.url;
    if (!/^(https?:\/\/|\/api\/)/.test(destino || "")) continue;

    const enlace = document.createElement("a");
    enlace.href = destino;
    enlace.target = "_blank";
    enlace.rel = "noopener";
    enlace.title = adjunto.archivo || adjunto.titulo;

    if (adjunto.tipo === "imagen") {
      enlace.className = "adjunto-imagen";
      const imagen = document.createElement("img");
      imagen.src = adjunto.url;
      imagen.alt = adjunto.titulo;
      imagen.loading = "lazy";
      imagen.onload = alFinal;
      const pie = document.createElement("span");
      pie.textContent = adjunto.titulo;
      enlace.append(imagen, pie);
    } else {
      enlace.className = "adjunto-ficha";
      enlace.textContent = adjunto.tipo === "cotizacion"
        ? adjunto.titulo
        : `Ficha técnica · ${adjunto.titulo}`;
    }
    nodo.appendChild(enlace);
  }
  alFinal();
  return nodo;
}

// Lo que queda en el historial como texto, para el modelo y por si falla la
// miniatura: que se mando, no las URLs.
function resumenDeAdjuntos(adjuntos) {
  const nombres = { imagen: "imagen", ficha: "ficha técnica", cotizacion: "cotización" };
  return `[Enviado al chat: ${adjuntos.map((a) => `${nombres[a.tipo] || a.tipo} de ${a.titulo}`).join(", ")}]`;
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

    if (!respuesta.ok) {
      // Si el servidor explico que paso, eso vale mas que el numero del estado.
      const motivo = await respuesta.json().then((d) => d.error).catch(() => null);
      throw new Error(motivo || `El servidor respondio ${respuesta.status}`);
    }

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
        } else if (evento.tipo === "adjuntos") {
          burbujaDeAdjuntos(evento.dato);
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

async function guardarTurno(role, content, adjuntos = null) {
  try {
    await fetch("/api/conversacion/agregar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(adjuntos ? { role, content, adjuntos } : { role, content }),
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
  btnImagen.hidden = false;

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

    onAdjuntos: (adjuntos) => {
      burbujaDeAdjuntos(adjuntos);
      guardarTurno("assistant", resumenDeAdjuntos(adjuntos), adjuntos);
    },

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
  btnImagen.hidden = true;
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
// Imagenes en la voz en vivo
// --------------------------------------------------------------------------

btnImagen.addEventListener("click", () => archivoImagen.click());

archivoImagen.addEventListener("change", async () => {
  const archivo = archivoImagen.files?.[0];
  // Vaciarlo permite elegir la misma foto dos veces seguidas.
  archivoImagen.value = "";
  // La sesion puede cerrarse mientras se reduce la foto; se usa la de ahora.
  const sesion = sesionViva;
  if (!archivo || !sesion) return;

  try {
    const { url } = await prepararImagen(archivo, sesion.espacioParaImagen());
    sesion.adjuntarImagen(url);

    const nodo = burbuja("usuario imagen");
    const miniatura = document.createElement("img");
    miniatura.src = url;
    miniatura.alt = "Imagen adjunta";
    nodo.appendChild(miniatura);
    miniatura.onload = alFinal;

    // El historial es texto: queda constancia, no la foto.
    guardarTurno("user", "[Imagen adjunta]");
    estadoVisual("escuchando", "Imagen adjunta. Preguntame sobre ella.");
  } catch (error) {
    burbuja("error", `No pude adjuntar la imagen: ${error.message}`);
  }
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
$("btn-consumo").addEventListener("click", abrirPanelConsumo);
$("btn-dispositivos").addEventListener("click", abrirPanelDispositivos);
$("btn-organizacion").addEventListener("click", abrirPanelOrganizacion);

// --------------------------------------------------------------------------
// Volver al panel
// --------------------------------------------------------------------------

// La marca la pone /entrar al llegar desde un panel. Vive en sessionStorage:
// es de esta pestana, y abrir Jarvis por su cuenta en otra no la hereda.
function leerMarca(clave) {
  try {
    return sessionStorage.getItem(clave);
  } catch {
    return null;
  }
}

function vieneDeUnPanel() {
  return leerMarca("jarvis_desde_panel") === "1";
}

$("btn-volver").addEventListener("click", () => {
  // Los tres paneles abren Jarvis en otra pestana: cerrarla deja a la persona
  // en el panel exactamente donde estaba, en la conversacion o la cotizacion
  // que tenia abierta.
  window.close();

  // Si el navegador no dejo cerrarla -Jarvis no se abrio desde el boton del
  // panel-, se va al panel. Si se cerro, esto ya no corre.
  setTimeout(() => {
    const origen = leerMarca("jarvis_panel_origen");
    if (origen) location.href = origen;
  }, 200);
});

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

    // Las funciones de arriba son solo del super admin (rol "admin"). Esto es
    // comodidad, no seguridad: lo que importa -consumo, fuentes,
    // organizaciones- el servidor ya lo niega con un 403.
    const esSuperAdmin = estado.rol === "admin";
    for (const nodo of document.querySelectorAll("[data-super-admin]")) {
      nodo.hidden = !esSuperAdmin;
    }
    $("btn-organizacion").hidden = !(esSuperAdmin && estado.es_admin_org);

    if (vieneDeUnPanel()) {
      $("nombre-usuario").textContent = estado.usuario;
      $("nombre-usuario").hidden = false;
      $("btn-volver").hidden = false;
    }
    if (!sesionViva) {
      $("meta").textContent =
        `${estado.modelo} · ${estado.hechos_recordados} recuerdos`;
    }

    puntoEstado.className = `punto ${estado.clave_configurada ? "ok" : "problema"}`;

    const insignia = $("insignia-supabase");
    insignia.hidden = !(esSuperAdmin && estado.conectores?.supabase);
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
    if (mensaje.adjuntos?.length) {
      // En voz el mensaje es solo el resumen; en texto trae la respuesta.
      if (!mensaje.content.startsWith("[Enviado al chat")) {
        burbuja("jarvis", mensaje.content);
      }
      burbujaDeAdjuntos(mensaje.adjuntos);
      continue;
    }
    burbuja(mensaje.role === "user" ? "usuario" : "jarvis", mensaje.content || "");
  }

  enReposo();
})();

// La barra superior es sticky y su alto cambia con el ancho (los botones bajan
// de linea en pantallas angostas). Publicamos ese alto en --alto-barra para que
// la barra de entrada y los paneles arranquen justo debajo, sin taparse.
(function medirAltoBarra() {
  const barra = document.querySelector(".barra");
  if (!barra) return;
  const aplicar = () =>
    document.documentElement.style.setProperty("--alto-barra", barra.offsetHeight + "px");
  aplicar();
  window.addEventListener("resize", aplicar);
  if (window.ResizeObserver) new ResizeObserver(aplicar).observe(barra);
})();
