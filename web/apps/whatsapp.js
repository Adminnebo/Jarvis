/* WhatsApp dentro de Jarvis (/apps/whatsapp). Todo pasa por /api/apps/whatsapp
   (Jarvis habla con Evolution); lo nuevo llega por Server-Sent Events.
   Ver docs/superpowers/specs/2026-11-20-apps-whatsapp-design.md. */

const $ = (id) => document.getElementById(id);
const API = "/api/apps/whatsapp";
const esCelular = () => matchMedia("(max-width: 900px)").matches;
const tactil = () => matchMedia("(pointer: coarse)").matches;

const estado = {
  chats: [],            // de /chats, mas los que se van creando
  abierto: null,        // jid del chat abierto
  mensajes: new Map(),  // jid -> [mensaje]
  pagina: new Map(),    // jid -> ultima pagina cargada
  sinMas: new Set(),    // jids sin mensajes mas viejos
  cita: null,           // {id, texto, mia, quien}
  filtro: "",
  temporal: 0,
};

// ---------------------------------------------------------------- utilidades

const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const enlazar = (t) => esc(t).replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>');
const numeroLegible = (jid) => {
  const d = String(jid || "").split("@")[0].replace(/\D/g, "");
  if (!String(jid).endsWith("@s.whatsapp.net") || !d) return "";
  return d.length === 11 && d.startsWith("1") ? `+1 ${d.slice(1, 4)}-${d.slice(4, 7)}-${d.slice(7)}` : `+${d}`;
};
const nombreDe = (chat) => chat?.nombre || numeroLegible(chat?.id) || chat?.telefono && `+${chat.telefono}` || "Desconocido";

function hora(segundos) {
  return new Date(segundos * 1000).toLocaleTimeString("es", { hour: "numeric", minute: "2-digit" });
}
function diaDe(segundos) {
  const d = new Date(segundos * 1000); d.setHours(0, 0, 0, 0);
  return d.getTime();
}
function etiquetaDia(segundos) {
  const hoy = new Date(); hoy.setHours(0, 0, 0, 0);
  const dias = Math.round((hoy.getTime() - diaDe(segundos)) / 86400000);
  if (dias === 0) return "Hoy";
  if (dias === 1) return "Ayer";
  const d = new Date(segundos * 1000);
  if (dias < 7) return d.toLocaleDateString("es", { weekday: "long" });
  return d.toLocaleDateString("es", { day: "2-digit", month: "2-digit", year: "numeric" });
}
function horaDeLista(segundos) {
  if (!segundos) return "";
  const dias = Math.round((diaDe(Date.now() / 1000) - diaDe(segundos)) / 86400000);
  if (dias === 0) return hora(segundos);
  if (dias === 1) return "Ayer";
  if (dias < 7) return new Date(segundos * 1000).toLocaleDateString("es", { weekday: "long" });
  return new Date(segundos * 1000).toLocaleDateString("es", { day: "2-digit", month: "2-digit", year: "2-digit" });
}
const ICONOS = { "[imagen]": "📷", "[video]": "🎥", "[nota de voz]": "🎤", "[audio]": "🎵" };
const NOMBRES = { "📷": "Foto", "🎥": "Video", "🎤": "Nota de voz", "🎵": "Audio" };
function bonito(texto) {   // "[imagen] mira" -> "📷 mira"; "[nota de voz]" -> "🎤 Nota de voz"
  let t = String(texto || "");
  for (const [marca, icono] of Object.entries(ICONOS)) {
    if (t.startsWith(marca)) { const resto = t.slice(marca.length).trim(); return `${icono} ${resto || NOMBRES[icono]}`; }
  }
  const doc = t.match(/^\[archivo(?::\s*([^\]]+))?\]\s*(.*)$/);
  if (doc) return `📄 ${doc[2] || doc[1] || "Documento"}`;
  return t;
}
const duracion = (s) => `${Math.floor((s || 0) / 60)}:${String(Math.floor((s || 0) % 60)).padStart(2, "0")}`;
const tamano = (b) => !b ? "" : b < 1024 ? `${b} B` : b < 1048576 ? `${Math.round(b / 1024)} kB` : `${(b / 1048576).toFixed(1)} MB`;

const SVG = {
  persona: '<svg viewBox="0 0 212 212"><path fill="#6a7175" d="M106 0C47 0 0 47 0 106s47 106 106 106 106-47 106-106S165 0 106 0z"/><path fill="#cfd4d6" d="M173 171c-17 17-40 27-67 27s-50-10-67-27c6-21 31-37 67-37s61 16 67 37zM106 48a37 37 0 1 1 0 74 37 37 0 0 1 0-74z"/></svg>',
  check: '<svg class="check" viewBox="0 0 16 11"><path d="M2 5.8l2.9 2.9L11.6 1.3" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  doble: (leido) => `<svg class="check${leido ? " leido" : ""}" viewBox="0 0 16 11"><path d="M1 5.8l2.9 2.9L10.6 1.3M7.2 8.2l.6.6 6.7-7.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
  reloj: '<svg class="check reloj" viewBox="0 0 16 16"><path d="M9.75 7.713H8.244V5.359a.5.5 0 0 0-.5-.5H7.65a.5.5 0 0 0-.5.5v2.947a.5.5 0 0 0 .5.5h.094l.003-.001.003.001h2a.5.5 0 0 0 .5-.5v-.094a.5.5 0 0 0-.5-.5zm0-5.263h-3.5c-1.82 0-3.3 1.48-3.3 3.3v3.5c0 1.82 1.48 3.3 3.3 3.3h3.5c1.82 0 3.3-1.48 3.3-3.3v-3.5c0-1.82-1.48-3.3-3.3-3.3zm2.2 6.8a2.2 2.2 0 0 1-2.2 2.2h-3.5a2.2 2.2 0 0 1-2.2-2.2v-3.5a2.2 2.2 0 0 1 2.2-2.2h3.5a2.2 2.2 0 0 1 2.2 2.2v3.5z"/></svg>',
  error: '<svg class="check error" viewBox="0 0 24 24"><path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>',
  responder: '<svg viewBox="0 0 24 24"><path d="M10 9V5l-7 7 7 7v-4.1c5 0 8.5 1.6 11 5.1-1-5-4-10-11-11z"/></svg>',
  play: '<svg viewBox="0 0 34 34"><path d="M8.5 8.7c0-1.7 1.2-2.4 2.6-1.5l14.4 8.3c1.4.8 1.4 2.2 0 3l-14.4 8.3c-1.4.8-2.6.2-2.6-1.5V8.7z"/></svg>',
  pausa: '<svg viewBox="0 0 34 34"><path d="M9.2 25c0 .5.4 1 .9 1h3.6c.5 0 .9-.4.9-1V9c0-.5-.4-.9-.9-.9h-3.6c-.4-.1-.9.3-.9.9v16zm11-17c-.5 0-1 .4-1 .9V25c0 .5.4 1 1 1h3.6c.5 0 1-.4 1-1V9c0-.5-.4-.9-1-.9h-3.6z"/></svg>',
  micro: '<svg viewBox="0 0 24 24"><path d="M12 15c1.7 0 3-1.3 3-3V5c0-1.7-1.3-3-3-3S9 3.3 9 5v7c0 1.7 1.3 3 3 3zm5.3-3c0 3-2.5 5.1-5.3 5.1S6.7 15 6.7 12H5c0 3.4 2.7 6.2 6 6.7V22h2v-3.3c3.3-.5 6-3.3 6-6.7h-1.7z"/></svg>',
  bajar: '<svg viewBox="0 0 24 24"><path d="M12 16l-5-5h3V4h4v7h3l-5 5zm-7 2h14v2H5z"/></svg>',
};

function marcaDeEstado(m) {
  if (m.entrante) return "";
  if (m.fallo) return SVG.error;
  if (m.estado === "pendiente" || !m.estado) return SVG.reloj;
  if (m.estado === "enviado") return SVG.check;
  return SVG.doble(m.estado === "leido");
}

function avatar(el, jid, grande = false) {
  el.innerHTML = SVG.persona;
  el.classList.toggle("avatar-grande", grande);
  if (!jid) return;
  const img = new Image();
  img.alt = "";
  img.loading = "lazy";
  img.onload = () => el.appendChild(img);
  img.src = `${API}/foto/${encodeURIComponent(jid)}`;
}

async function pedir(ruta, opciones = {}) {
  const r = await fetch(API + ruta, opciones);
  let datos = {};
  try { datos = await r.json(); } catch { /* respuesta sin cuerpo */ }
  if (r.status === 409 && datos.vincular) { mostrarVincular(); throw new Error(datos.error); }
  if (!r.ok) throw new Error(datos.error || `Error ${r.status}`);
  return datos;
}

// ---------------------------------------------------------------- lista de chats

function resumenDe(chat) {
  const iconos = { imagen: "📷 Foto", video: "🎥 Video", nota: "🎤 Nota de voz", audio: "🎵 Audio", documento: "📄 Documento", sticker: "🗒️ Sticker" };
  const texto = String(chat.ultimo || "").replace(/^\[[^\]]*\]\s*/, "").trim();
  if (chat.ultimo_tipo && chat.ultimo_tipo !== "texto") {
    return texto && !["nota", "sticker"].includes(chat.ultimo_tipo) ? `${iconos[chat.ultimo_tipo].split(" ")[0]} ${texto}` : iconos[chat.ultimo_tipo];
  }
  return bonito(chat.ultimo || "");
}

function pintarLista() {
  const lista = $("lista");
  const filtro = estado.filtro.trim().toLowerCase();
  const digitos = filtro.replace(/\D/g, "");
  const chats = estado.chats
    .filter((c) => !filtro || nombreDe(c).toLowerCase().includes(filtro) || (c.ultimo || "").toLowerCase().includes(filtro)
      || (digitos.length >= 3 && (c.telefono || c.id).includes(digitos)))
    .sort((a, b) => (b.actualizado || 0) - (a.actualizado || 0));
  lista.innerHTML = "";
  if (!chats.length) {
    lista.innerHTML = `<li class="lista-vacia">${filtro ? "No se encontraron chats." : "Aún no hay chats."}</li>`;
    if (digitos.length >= 8) {
      const li = document.createElement("li");
      li.className = "lista-vacia";
      li.innerHTML = `<button class="enlace-chat" type="button" style="color:var(--wa-acento)">Abrir chat con ${esc(filtro)}</button>`;
      li.querySelector("button").addEventListener("click", () => abrirChat(digitos));
      lista.appendChild(li);
    }
    return;
  }
  for (const chat of chats) lista.appendChild(itemDeChat(chat));
}

function itemDeChat(chat) {
  const li = document.createElement("li");
  li.className = "chat-item" + (chat.id === estado.abierto ? " activo" : "") + (chat.no_leidos ? " no-leido" : "");
  li.dataset.jid = chat.id;
  li.innerHTML = `
    <div class="avatar"></div>
    <div class="chat-item-cuerpo">
      <div class="chat-item-fila"><span class="chat-item-nombre">${esc(nombreDe(chat))}</span>
        <span class="chat-item-hora">${esc(horaDeLista(chat.actualizado))}</span></div>
      <div class="chat-item-fila"><span class="chat-item-ultimo">${chat.ultimo_mio ? marcaDeEstado({ entrante: false, estado: chat.ultimo_estado || "enviado" }) : ""}<span>${esc(resumenDe(chat))}</span></span>
        ${chat.no_leidos ? `<span class="contador">${chat.no_leidos}</span>` : ""}</div>
    </div>`;
  avatar(li.querySelector(".avatar"), chat.id, true);
  li.addEventListener("click", () => abrirChat(chat.id));
  return li;
}

function chatDe(jid) {
  let chat = estado.chats.find((c) => c.id === jid);
  if (!chat) {
    chat = { id: jid, nombre: null, telefono: jid.split("@")[0].replace(/\D/g, ""), ultimo: "", no_leidos: 0, actualizado: 0 };
    estado.chats.push(chat);
  }
  return chat;
}

async function cargarChats() {
  const { chats } = await pedir("/chats");
  const abiertos = new Map(estado.chats.map((c) => [c.id, c]));
  estado.chats = chats.map((c) => ({ ...abiertos.get(c.id), ...c }));
  pintarLista();
}

// ---------------------------------------------------------------- conversacion

async function abrirChat(jidOTexto) {
  let jid = jidOTexto;
  $("emojis").hidden = true; $("adjuntar-menu").hidden = true;
  if (!jid.includes("@")) {   // numero nuevo: el servidor dice como queda
    const datos = await pedir(`/chats/${encodeURIComponent(jid)}/mensajes`);
    jid = datos.jid;
    estado.mensajes.set(jid, datos.mensajes);
    estado.pagina.set(jid, 1);
  }
  const chat = chatDe(jid);
  estado.abierto = jid;
  quitarCita();
  $("vacio").hidden = true;
  $("conversacion").hidden = false;
  $("chat-nombre").textContent = nombreDe(chat);
  $("chat-sub").textContent = chat.nombre ? numeroLegible(jid) : "";
  avatar($("chat-avatar"), jid);
  if (esCelular() && !document.body.classList.contains("en-chat")) {
    document.body.classList.add("en-chat");
    history.pushState({ chat: jid }, "");
  }
  pintarLista();
  if (!estado.mensajes.has(jid)) {
    $("mensajes").innerHTML = '<div class="cargando-mas">Cargando…</div>';
    try {
      const datos = await pedir(`/chats/${encodeURIComponent(jid)}/mensajes`);
      estado.mensajes.set(jid, datos.mensajes);
      estado.pagina.set(jid, 1);
    } catch (error) {
      $("mensajes").innerHTML = `<div class="cargando-mas">${esc(error.message)}</div>`;
      return;
    }
  }
  if (estado.abierto !== jid) return;
  pintarMensajes(true);
  marcarLeidos(jid);
  if (!tactil()) $("texto").focus();
}

function cerrarChat() {
  estado.abierto = null;
  document.body.classList.remove("en-chat");
  if (!esCelular()) { $("conversacion").hidden = true; $("vacio").hidden = false; }
  pintarLista();
}

function marcarLeidos(jid) {
  const chat = chatDe(jid);
  const ids = (estado.mensajes.get(jid) || []).filter((m) => m.entrante && !m.leidoPorMi).slice(-50);
  if (!ids.length && !chat.no_leidos) return;
  ids.forEach((m) => { m.leidoPorMi = true; });
  chat.no_leidos = 0;
  pintarLista();
  if (ids.length) {
    pedir(`/chats/${encodeURIComponent(jid)}/leido`, {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ ids: ids.map((m) => m.id) }),
    }).catch(() => {});
  }
}

function pintarMensajes(alFinal = false) {
  const caja = $("mensajes");
  const lista = estado.mensajes.get(estado.abierto) || [];
  const arriba = caja.scrollTop;
  const pegado = alFinal || caja.scrollHeight - caja.scrollTop - caja.clientHeight < 80;
  caja.innerHTML = estado.sinMas.has(estado.abierto) || lista.length < 30 ? "" : '<div class="cargando-mas" id="mas">Cargando mensajes anteriores…</div>';
  let dia = null, anterior = null;
  for (const m of lista) {
    const d = diaDe(m.momento);
    if (d !== dia) {
      dia = d;
      const sep = document.createElement("div");
      sep.className = "separador";
      sep.textContent = etiquetaDia(m.momento);
      caja.appendChild(sep);
      anterior = null;
    }
    const primera = !anterior || anterior.entrante !== m.entrante;
    caja.appendChild(filaDe(m, primera));
    anterior = m;
  }
  caja.scrollTop = pegado ? caja.scrollHeight : arriba;
  estado.pegado = pegado;
  if (!caja.observado) {   // el contenido crece sin evento propio: se mira cada fila
    caja.observado = new ResizeObserver(bajar);
  }
  caja.observado.disconnect();
  caja.querySelectorAll(".fila").forEach((f) => caja.observado.observe(f));
}

async function cargarAnteriores() {
  const jid = estado.abierto;
  if (!jid || estado.sinMas.has(jid) || estado.cargandoMas) return;
  estado.cargandoMas = true;
  const caja = $("mensajes");
  const pagina = (estado.pagina.get(jid) || 1) + 1;
  try {
    const { mensajes } = await pedir(`/chats/${encodeURIComponent(jid)}/mensajes?pagina=${pagina}`);
    if (estado.abierto !== jid) return;
    const actuales = estado.mensajes.get(jid) || [];
    const ids = new Set(actuales.map((m) => m.id));
    const nuevos = mensajes.filter((m) => !ids.has(m.id));
    if (!nuevos.length) estado.sinMas.add(jid);
    estado.pagina.set(jid, pagina);
    estado.mensajes.set(jid, [...nuevos, ...actuales].sort((a, b) => a.momento - b.momento));
    const altoAntes = caja.scrollHeight;
    pintarMensajes();
    caja.scrollTop = caja.scrollHeight - altoAntes;
  } catch { /* se reintenta al volver a subir */ } finally {
    estado.cargandoMas = false;
  }
}

function filaDe(m, primera) {
  const fila = document.createElement("div");
  fila.className = "fila" + (m.entrante ? "" : " mia") + (primera ? " primera" : "");
  fila.dataset.id = m.id;
  const burbuja = document.createElement("div");
  burbuja.className = "burbuja";
  const meta = `<span class="meta">${esc(hora(m.momento))}${marcaDeEstado(m)}</span>`;
  let html = "";
  if (m.cita) {
    const mia = (estado.mensajes.get(estado.abierto) || []).find((x) => x.id === m.cita.id);
    const deMi = mia ? !mia.entrante : false;
    html += `<div class="cita${deMi ? " mia" : ""}" data-ir="${esc(m.cita.id)}"><div class="cita-quien">${deMi ? "Tú" : esc(nombreDe(chatDe(estado.abierto)))}</div><div class="cita-texto">${esc(bonito(m.cita.texto))}</div></div>`;
  }
  const archivo = m.temporalUrl || (m.id && !m.temporal ? `${API}/archivo/${encodeURIComponent(m.id)}` : "");
  switch (m.tipo) {
    case "imagen":
      html += `<img class="foto" alt="Foto" src="${esc(m.archivo?.miniatura || archivo)}" data-grande="${esc(archivo)}"${m.archivo?.ancho ? ` style="aspect-ratio:${m.archivo.ancho}/${m.archivo.alto}"` : ""}>`;
      if (!m.texto) burbuja.classList.add("solo-foto");
      break;
    case "video":
      html += `<div class="video-caja" data-video="${esc(archivo)}">${m.archivo?.miniatura ? `<img alt="" src="${esc(m.archivo.miniatura)}">` : "<video muted></video>"}<div class="play"><span>${SVG.play}</span></div></div>`;
      break;
    case "nota":
    case "audio":
      html += `<div class="audio" data-src="${esc(archivo)}">
        ${m.tipo === "nota" ? `<div class="avatar audio-avatar"></div>` : `<div class="audio-icono">${SVG.micro}</div>`}
        <button class="audio-boton" type="button" aria-label="Reproducir">${SVG.play}</button>
        <div class="audio-centro"><input type="range" min="0" max="100" value="0" aria-label="Avance"><span class="audio-dur">${duracion(m.archivo?.segundos)}</span></div></div>`;
      break;
    case "documento": {
      const nombre = m.archivo?.nombre || "Documento";
      const ext = (nombre.split(".").pop() || "").slice(0, 4).toUpperCase();
      html += `<a class="documento" href="${esc(archivo)}" download="${esc(nombre)}" target="_blank" rel="noopener">
        <span class="documento-icono${ext === "PDF" ? "" : " otro"}">${esc(ext)}</span>
        <span class="documento-datos"><span class="documento-nombre">${esc(nombre)}</span><span class="documento-tam">${esc([ext, tamano(m.archivo?.tamano)].filter(Boolean).join(" · "))}</span></span>
        <span class="documento-bajar">${SVG.bajar}</span></a>`;
      break;
    }
    case "sticker":
      html += `<img class="sticker" alt="Sticker" src="${esc(archivo)}" loading="lazy">`;
      burbuja.classList.add("sin-burbuja");
      break;
  }
  if (m.texto) html += `<span class="texto">${enlazar(m.texto)}</span>`;
  html += meta;
  if (m.fallo) html += `<button class="reintentar" type="button">Reintentar</button>`;
  html += `<button class="responder" type="button" aria-label="Responder">${SVG.responder}</button>`;
  burbuja.innerHTML = html;
  fila.appendChild(burbuja);

  if (m.tipo === "nota") avatar(burbuja.querySelector(".audio-avatar"), m.entrante ? estado.abierto : null);
  if (m.tipo === "imagen" && archivo && m.archivo?.miniatura && !m.temporalUrl) {
    const foto = burbuja.querySelector(".foto");
    const real = new Image();
    real.onload = () => { foto.src = real.src; };
    real.src = archivo;   // la miniatura se ve al instante; la foto real llega despues
  }
  burbuja.querySelector(".foto")?.addEventListener("click", (e) => abrirVisor(e.target.dataset.grande || e.target.src));
  burbuja.querySelector(".video-caja")?.addEventListener("click", function () {
    if (this.querySelector("video[src]")) return;
    this.innerHTML = `<video controls autoplay playsinline src="${esc(this.dataset.video)}"></video>`;
  });
  const audio = burbuja.querySelector(".audio");
  if (audio) prepararAudio(audio, m);
  burbuja.querySelector(".cita")?.addEventListener("click", (e) => irA(e.currentTarget.dataset.ir));
  burbuja.querySelector(".responder").addEventListener("click", () => citar(m));
  burbuja.querySelector(".reintentar")?.addEventListener("click", () => reintentar(m));
  if (tactil()) deslizarParaCitar(fila, m);
  return fila;
}

let audioSonando = null;
function prepararAudio(caja, m) {
  const boton = caja.querySelector(".audio-boton");
  const barra = caja.querySelector("input");
  const dur = caja.querySelector(".audio-dur");
  let sonido = null;
  boton.addEventListener("click", () => {
    if (!sonido) {
      sonido = new Audio(caja.dataset.src);
      sonido.addEventListener("timeupdate", () => {
        if (sonido.duration) barra.value = (sonido.currentTime / sonido.duration) * 100;
        dur.textContent = duracion(sonido.currentTime);
      });
      sonido.addEventListener("ended", () => { boton.innerHTML = SVG.play; barra.value = 0; dur.textContent = duracion(m.archivo?.segundos); });
      sonido.addEventListener("pause", () => { boton.innerHTML = SVG.play; });
      sonido.addEventListener("play", () => { boton.innerHTML = SVG.pausa; });
      barra.addEventListener("input", () => { if (sonido.duration) sonido.currentTime = (barra.value / 100) * sonido.duration; });
    }
    if (sonido.paused) {
      if (audioSonando && audioSonando !== sonido) audioSonando.pause();
      audioSonando = sonido;
      sonido.play().catch(() => { dur.textContent = "No se pudo reproducir"; });
    } else sonido.pause();
  });
}

function irA(id) {
  const fila = $("mensajes").querySelector(`.fila[data-id="${CSS.escape(id)}"]`);
  if (!fila) return;
  fila.scrollIntoView({ block: "center", behavior: "smooth" });
  fila.classList.add("resaltado");
  setTimeout(() => fila.classList.remove("resaltado"), 1500);
}

function deslizarParaCitar(fila, m) {
  let x0 = null;
  fila.addEventListener("touchstart", (e) => { x0 = e.touches[0].clientX; }, { passive: true });
  fila.addEventListener("touchmove", (e) => {
    if (x0 === null) return;
    const dx = Math.max(0, Math.min(80, e.touches[0].clientX - x0));
    fila.style.transform = `translateX(${dx}px)`;
  }, { passive: true });
  fila.addEventListener("touchend", (e) => {
    const dx = (e.changedTouches[0]?.clientX ?? x0) - x0;
    fila.style.transform = "";
    x0 = null;
    if (dx > 60) citar(m);
  });
}

// ---------------------------------------------------------------- citar

function citar(m) {
  estado.cita = { id: m.id, texto: m.texto || resumenDe({ ultimo_tipo: m.tipo, ultimo: "" }) || "Mensaje", mia: !m.entrante };
  $("cita").hidden = false;
  $("cita").querySelector(".cita").classList.toggle("mia", !m.entrante);
  $("cita-quien").textContent = m.entrante ? nombreDe(chatDe(estado.abierto)) : "Tú";
  $("cita-texto").textContent = bonito(estado.cita.texto);
  $("texto").focus();
}
function quitarCita() {
  estado.cita = null;
  $("cita").hidden = true;
}

// ---------------------------------------------------------------- enviar

function agregarMensaje(jid, m) {
  const lista = estado.mensajes.get(jid) || [];
  const i = lista.findIndex((x) => x.id === m.id);
  if (i >= 0) lista[i] = { ...lista[i], ...m, temporalUrl: lista[i].temporalUrl };
  else lista.push(m);
  lista.sort((a, b) => a.momento - b.momento);
  estado.mensajes.set(jid, lista);
  const chat = chatDe(jid);
  const ultimo = lista[lista.length - 1];
  if (ultimo === m || ultimo.id === m.id) {
    Object.assign(chat, {
      ultimo: m.texto, ultimo_tipo: m.tipo, ultimo_mio: !m.entrante, ultimo_estado: m.estado,
      ultimo_id: m.id, actualizado: Math.max(chat.actualizado || 0, m.momento),
    });
  }
  if (jid === estado.abierto) pintarMensajes();
  pintarLista();
}

function temporal(jid, datos) {
  const m = {
    id: `tmp-${++estado.temporal}`, temporal: true, jid, entrante: false, momento: Date.now() / 1000, estado: "pendiente",
    cita: estado.cita ? { id: estado.cita.id, texto: estado.cita.texto } : null, archivo: null, texto: "", tipo: "texto", ...datos,
  };
  agregarMensaje(jid, m);
  return m;
}

async function confirmarEnvio(jid, m, promesa) {
  try {
    const { id, jid: real } = await promesa;
    const lista = estado.mensajes.get(jid) || [];
    const yaLlego = lista.find((x) => x.id === id && x !== m);
    if (yaLlego) estado.mensajes.set(jid, lista.filter((x) => x !== m));   // el evento en vivo llego antes
    else Object.assign(m, { id: id || m.id, temporal: false, estado: m.estado === "pendiente" ? "enviado" : m.estado, fallo: false });
    if (real && real !== jid) { estado.mensajes.set(real, estado.mensajes.get(jid)); estado.mensajes.delete(jid); }
  } catch (error) {
    Object.assign(m, { fallo: true, error: error.message });
  }
  if (jid === estado.abierto) pintarMensajes();
  pintarLista();
}

function enviarTexto() {
  const texto = $("texto").value.trim();
  const jid = estado.abierto;
  if (!texto || !jid) return;
  const cita = estado.cita;
  $("texto").value = "";
  ajustarCaja();
  quitarCita();
  const m = temporal(jid, { texto, cita: cita ? { id: cita.id, texto: cita.texto } : null });
  m.reenviar = () => pedir(`/chats/${encodeURIComponent(jid)}/mensajes`, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ texto, cita: cita ? { id: cita.id, texto: cita.texto } : null }),
  });
  confirmarEnvio(jid, m, m.reenviar());
}

function enviarArchivo(archivo, pie, nota = false) {
  const jid = estado.abierto;
  const cita = estado.cita;
  quitarCita();
  const tipo = nota ? "nota" : archivo.type.startsWith("image/") ? "imagen" : archivo.type.startsWith("video/") ? "video" : "documento";
  const url = URL.createObjectURL(archivo);
  const m = temporal(jid, {
    tipo, texto: nota ? "" : pie, temporalUrl: url,
    archivo: { nombre: archivo.name, tamano: archivo.size, mime: archivo.type, segundos: archivo.segundos || null, miniatura: tipo === "imagen" ? url : null },
  });
  m.reenviar = () => {
    const datos = new FormData();
    datos.append(nota ? "audio" : "archivo", archivo, archivo.name);
    if (!nota) datos.append("pie", pie || "");
    if (cita) datos.append("cita", JSON.stringify({ id: cita.id, texto: cita.texto }));
    return pedir(`/chats/${encodeURIComponent(jid)}/${nota ? "nota" : "archivo"}`, { method: "POST", body: datos });
  };
  confirmarEnvio(jid, m, m.reenviar());
}

function reintentar(m) {
  if (!m.reenviar) return;
  Object.assign(m, { fallo: false, estado: "pendiente" });
  pintarMensajes();
  confirmarEnvio(m.jid, m, m.reenviar());
}

// ---------------------------------------------------------------- barra de escribir

function ajustarCaja() {
  const caja = $("texto");
  caja.style.height = "auto";
  caja.style.height = Math.min(caja.scrollHeight, 120) + "px";
  $("escribir").classList.toggle("con-texto", Boolean(caja.value.trim()));
  $("btn-enviar").setAttribute("aria-label", caja.value.trim() ? "Enviar" : "Grabar nota de voz");
}

$("texto").addEventListener("input", ajustarCaja);
$("texto").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !tactil()) { e.preventDefault(); enviarTexto(); }
});
$("btn-enviar").addEventListener("click", () => ($("texto").value.trim() ? enviarTexto() : empezarGrabacion()));
$("cita-quitar").addEventListener("click", quitarCita);

const EMOJIS = {
  "Caritas": "😀😃😄😁😆😅😂🤣😊😇🙂🙃😉😌😍🥰😘😗😙😚😋😛😝😜🤪🤨🧐🤓😎🤩🥳😏😒😞😔😟😕🙁😣😖😫😩🥺😢😭😤😠😡🤬🤯😳🥵🥶😱😨😰😥😓🤗🤔🤭🤫🤥😶😐😑😬🙄😯😦😧😮😲🥱😴🤤😪😵🤐🥴🤢🤮🤧😷🤒🤕🤑🤠",
  "Gestos": "👋🤚🖐✋🖖👌🤌🤏✌🤞🤟🤘🤙👈👉👆👇☝👍👎✊👊🤛🤜👏🙌👐🤲🤝🙏💪",
  "Corazones": "❤🧡💛💚💙💜🖤🤍🤎💔❣💕💞💓💗💖💘💝",
  "Cosas": "🎉🎊🎁🎈🔥✨⭐🌟💯✅❌⚠️📌📎📄📷📞💰💵🏠🚗📦🛒⏰📅✔",
};
function pintarEmojis() {
  const caja = $("emojis");
  if (caja.childElementCount) return;
  for (const [grupo, lista] of Object.entries(EMOJIS)) {
    const h = document.createElement("h4");
    h.textContent = grupo;
    caja.appendChild(h);
    for (const emoji of Array.from(new Intl.Segmenter("es", { granularity: "grapheme" }).segment(lista), (s) => s.segment)) {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = emoji;
      b.addEventListener("click", () => {
        const t = $("texto");
        const [a, z] = [t.selectionStart ?? t.value.length, t.selectionEnd ?? t.value.length];
        t.value = t.value.slice(0, a) + emoji + t.value.slice(z);
        t.selectionStart = t.selectionEnd = a + emoji.length;
        ajustarCaja();
        if (!tactil()) t.focus();
      });
      caja.appendChild(b);
    }
  }
}
$("btn-emoji").addEventListener("click", (e) => {
  e.stopPropagation();
  pintarEmojis();
  $("emojis").hidden = !$("emojis").hidden;
  $("adjuntar-menu").hidden = true;
});
$("btn-adjuntar").addEventListener("click", (e) => {
  e.stopPropagation();
  $("adjuntar-menu").hidden = !$("adjuntar-menu").hidden;
  $("emojis").hidden = true;
});
document.addEventListener("click", (e) => {
  if (!$("emojis").contains(e.target)) $("emojis").hidden = true;
  if (!$("adjuntar-menu").contains(e.target)) $("adjuntar-menu").hidden = true;
});
$("adjuntar-menu").addEventListener("click", (e) => {
  const tipo = e.target.closest("button")?.dataset.tipo;
  if (!tipo) return;
  $("adjuntar-menu").hidden = true;
  $(tipo === "documento" ? "archivo-doc" : "archivo-medios").click();
});
for (const id of ["archivo-doc", "archivo-medios"]) {
  $(id).addEventListener("change", (e) => {
    const archivo = e.target.files[0];
    e.target.value = "";
    if (archivo) mostrarPrevia(archivo);
  });
}

// vista previa antes de enviar
let previa = null;
function mostrarPrevia(archivo) {
  if (archivo.size > 16 * 1024 * 1024) { alert("El archivo pasa de 16 MB: WhatsApp no lo acepta."); return; }
  previa = archivo;
  const cuerpo = $("previa-cuerpo");
  const url = URL.createObjectURL(archivo);
  cuerpo.innerHTML = archivo.type.startsWith("image/") ? `<img alt="" src="${url}">`
    : archivo.type.startsWith("video/") ? `<video controls src="${url}"></video>`
    : `<div class="documento"><span class="documento-icono${/pdf$/i.test(archivo.name) ? "" : " otro"}">${esc((archivo.name.split(".").pop() || "").slice(0, 4).toUpperCase())}</span><span class="documento-datos"><span class="documento-nombre">${esc(archivo.name)}</span><span class="documento-tam">${esc(tamano(archivo.size))}</span></span></div>`;
  $("previa-nombre").textContent = archivo.name;
  $("previa-pie").value = "";
  $("previa").hidden = false;
  if (!tactil()) $("previa-pie").focus();
}
function cerrarPrevia() { $("previa").hidden = true; previa = null; $("previa-cuerpo").innerHTML = ""; }
$("previa-cerrar").addEventListener("click", cerrarPrevia);
$("previa-enviar").addEventListener("click", () => {
  if (!previa) return;
  const [archivo, pie] = [previa, $("previa-pie").value.trim()];
  cerrarPrevia();
  enviarArchivo(archivo, pie);
});
$("previa-pie").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); $("previa-enviar").click(); } });

// visor de fotos
function abrirVisor(src) { $("visor-img").src = src; $("visor").hidden = false; }
$("visor-cerrar").addEventListener("click", () => { $("visor").hidden = true; });
$("visor").addEventListener("click", (e) => { if (e.target === $("visor")) $("visor").hidden = true; });

// ---------------------------------------------------------------- notas de voz

const grabacion = { recorder: null, partes: [], inicio: 0, reloj: null, stream: null };
async function empezarGrabacion() {
  if (!estado.abierto || grabacion.recorder) return;
  try {
    grabacion.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch {
    alert("Jarvis necesita permiso para usar el micrófono.");
    return;
  }
  const tipo = ["audio/ogg;codecs=opus", "audio/webm;codecs=opus", "audio/mp4"].find((t) => MediaRecorder.isTypeSupported?.(t)) || "";
  grabacion.recorder = new MediaRecorder(grabacion.stream, tipo ? { mimeType: tipo } : undefined);
  grabacion.partes = [];
  grabacion.recorder.ondataavailable = (e) => { if (e.data.size) grabacion.partes.push(e.data); };
  grabacion.recorder.start();
  grabacion.inicio = Date.now();
  $("grabando").hidden = false;
  $("grabar-tiempo").textContent = "0:00";
  grabacion.reloj = setInterval(() => { $("grabar-tiempo").textContent = duracion((Date.now() - grabacion.inicio) / 1000); }, 250);
}
function terminarGrabacion(enviar) {
  const { recorder, stream } = grabacion;
  if (!recorder) return;
  clearInterval(grabacion.reloj);
  $("grabando").hidden = true;
  const segundos = Math.round((Date.now() - grabacion.inicio) / 1000);
  recorder.onstop = () => {
    stream.getTracks().forEach((t) => t.stop());
    const mime = recorder.mimeType || "audio/webm";
    const blob = new Blob(grabacion.partes, { type: mime });
    grabacion.recorder = null;
    if (!enviar || segundos < 1 || !blob.size) return;
    const archivo = new File([blob], `nota.${mime.includes("ogg") ? "ogg" : mime.includes("mp4") ? "m4a" : "webm"}`, { type: mime });
    archivo.segundos = segundos;
    enviarArchivo(archivo, "", true);
  };
  recorder.stop();
}
$("grabar-enviar").addEventListener("click", () => terminarGrabacion(true));
$("grabar-descartar").addEventListener("click", () => terminarGrabacion(false));

// ---------------------------------------------------------------- en vivo

let fuente = null;
let cortado = false;
function escuchar() {
  fuente?.close();
  fuente = new EventSource(`${API}/eventos`);
  fuente.onopen = () => {
    $("franja").hidden = true;
    if (cortado) { cortado = false; recargar(); }
  };
  fuente.onerror = () => { cortado = true; $("franja").hidden = false; };
  fuente.onmessage = (e) => {
    let evento;
    try { evento = JSON.parse(e.data); } catch { return; }
    if (evento.tipo === "mensaje") recibir(evento.mensaje);
    else if (evento.tipo === "estado") cambiarEstado(evento);
    else if (evento.tipo === "conexion" && evento.estado === "close") $("franja").hidden = false;
    else if (evento.tipo === "conexion" && evento.estado === "open") $("franja").hidden = true;
  };
}

function recibir(m) {
  const jid = m.jid;
  const lista = estado.mensajes.get(jid);
  if (!m.entrante && lista) {   // lo mio: puede ser el temporal que ya esta en pantalla
    const pendiente = lista.find((x) => x.temporal && !x.fallo && x.tipo === m.tipo && (x.texto || "") === (m.texto || ""));
    if (pendiente) {
      Object.assign(pendiente, { id: m.id, temporal: false, estado: m.estado || "enviado" });
      if (jid === estado.abierto) pintarMensajes();
      pintarLista();
      return;
    }
  }
  if (lista || jid === estado.abierto) agregarMensaje(jid, m);
  else {
    const chat = chatDe(jid);
    Object.assign(chat, { ultimo: m.texto, ultimo_tipo: m.tipo, ultimo_mio: !m.entrante, ultimo_estado: m.estado,
      actualizado: m.momento, nombre: chat.nombre || (m.entrante ? m.nombre : null) });
    pintarLista();
  }
  const chat = chatDe(jid);
  if (m.entrante) {
    if (!chat.nombre && m.nombre) chat.nombre = m.nombre;
    if (jid === estado.abierto && document.visibilityState === "visible") marcarLeidos(jid);
    else { chat.no_leidos = (chat.no_leidos || 0) + 1; pintarLista(); }
  }
}

function cambiarEstado({ id, jid, estado: nuevo }) {
  const orden = { pendiente: 0, enviado: 1, entregado: 2, leido: 3 };
  const m = (estado.mensajes.get(jid) || []).find((x) => x.id === id);
  if (m && (orden[nuevo] ?? 0) > (orden[m.estado] ?? -1)) {
    m.estado = nuevo;
    if (jid === estado.abierto) pintarMensajes();
  }
  const chat = estado.chats.find((c) => c.id === jid);
  if (chat && chat.ultimo_id === id) { chat.ultimo_estado = nuevo; pintarLista(); }
}

async function recargar() {
  try {
    await cargarChats();
    const jid = estado.abierto;
    if (jid) {
      const { mensajes } = await pedir(`/chats/${encodeURIComponent(jid)}/mensajes`);
      const temporales = (estado.mensajes.get(jid) || []).filter((m) => m.temporal);
      estado.mensajes.set(jid, [...mensajes, ...temporales]);
      estado.pagina.set(jid, 1);
      pintarMensajes(true);
    }
  } catch { /* la proxima reconexion lo intenta de nuevo */ }
}

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && estado.abierto) marcarLeidos(estado.abierto);
});

// ---------------------------------------------------------------- navegacion

$("btn-atras").addEventListener("click", () => history.state?.chat ? history.back() : cerrarChat());
window.addEventListener("popstate", () => { if (document.body.classList.contains("en-chat")) cerrarChat(); });
// Fotos, videos, fuentes y la animacion de entrada cambian el alto despues de pintar:
// si estaba abajo del todo, que siga abajo.
const bajar = () => { if (estado.pegado) $("mensajes").scrollTop = $("mensajes").scrollHeight; };
$("mensajes").addEventListener("load", bajar, true);
$("mensajes").addEventListener("loadedmetadata", bajar, true);
new ResizeObserver(bajar).observe($("mensajes"));
$("mensajes").addEventListener("scroll", () => {
  const caja = $("mensajes");
  estado.pegado = caja.scrollHeight - caja.scrollTop - caja.clientHeight < 80;
  if (caja.scrollTop < 60) cargarAnteriores();
});
$("buscar").addEventListener("input", (e) => { estado.filtro = e.target.value; pintarLista(); });
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (!$("visor").hidden) $("visor").hidden = true;
  else if (!$("previa").hidden) cerrarPrevia();
  else if (!$("nuevo").hidden) $("nuevo").hidden = true;
  else if (grabacion.recorder) terminarGrabacion(false);
  else if (estado.cita) quitarCita();
  else if (estado.abierto && !esCelular()) cerrarChat();
});

function abrirNuevo() {
  $("nuevo").hidden = false;
  $("nuevo-error").textContent = "";
  $("nuevo-form").numero.value = "";
  $("nuevo-form").numero.focus();
}
$("btn-nuevo").addEventListener("click", abrirNuevo);
$("btn-nuevo-flotante").addEventListener("click", abrirNuevo);
$("nuevo-cancelar").addEventListener("click", () => { $("nuevo").hidden = true; });
$("nuevo-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await abrirChat(e.target.numero.value.replace(/\D/g, ""));
    $("nuevo").hidden = true;
  } catch (error) {
    $("nuevo-error").textContent = error.message;
  }
});

// ---------------------------------------------------------------- vincular

let sondeo = null;
function mostrarVincular() {
  if (!$("vincular").hidden) return;
  $("vincular").hidden = false;
  pedirVinculo({});
}
async function pedirVinculo(cuerpo) {
  clearTimeout(sondeo);
  $("vincular-error").textContent = "";
  try {
    const r = await fetch("/api/integraciones/whatsapp/vincular", {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(cuerpo),
    });
    const datos = await r.json();
    if (!r.ok) throw new Error(datos.error || "No se pudo preparar la conexión.");
    pintarVinculo(datos);
  } catch (error) {
    $("vincular-error").textContent = error.message;
  }
}
function pintarVinculo(datos) {
  if (datos.estado === "conectado") { location.reload(); return; }
  $("vincular-cargando").hidden = Boolean(datos.qr || datos.codigo);
  $("vincular-img").hidden = !datos.qr || Boolean(datos.codigo);
  if (datos.qr) $("vincular-img").src = datos.qr;
  $("vincular-numero").hidden = !datos.codigo;
  if (datos.codigo) {
    $("vincular-numero").textContent = datos.codigo.replace(/^(.{4})(.{4})$/, "$1-$2");
    $("vincular-paso").textContent = "Toca «Vincular con el número de teléfono» y escribe este código.";
  }
  sondeo = setTimeout(async () => {
    try { pintarVinculo(await (await fetch("/api/integraciones/whatsapp/vincular")).json()); }
    catch { sondeo = setTimeout(() => pintarVinculo({}), 3000); }
  }, 3000);
}
$("vincular-codigo").addEventListener("click", () => { $("vincular-form").hidden = false; $("vincular-form").numero.focus(); });
$("vincular-form").addEventListener("submit", (e) => {
  e.preventDefault();
  $("vincular-form").hidden = true;
  pedirVinculo({ numero: e.target.numero.value });
});

// ---------------------------------------------------------------- arranque

async function arrancar() {
  try {
    const { conectado, cuenta } = await pedir("/estado");
    if (!conectado) { mostrarVincular(); return; }
    $("cuenta").textContent = cuenta ? `· ${cuenta}` : "";
    avatar($("avatar-propio"), null);
    await cargarChats();
    escuchar();
    const pedido = new URLSearchParams(location.search).get("chat");
    if (pedido) abrirChat(pedido);
  } catch (error) {
    if ($("vincular").hidden) $("lista").innerHTML = `<li class="lista-vacia">${esc(error.message)}</li>`;
  }
}
arrancar();
