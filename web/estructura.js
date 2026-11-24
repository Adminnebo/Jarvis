/* La estructura comun de Jarvis (/). Cada vista vive en un marco que se crea la primera
   vez y queda vivo (cambiar de app es instantaneo y WhatsApp no se reconecta). Las apps
   le cuentan que tienen abierto (postMessage "contexto") y Jarvis lo recibe con cada
   pregunta. Ver docs/superpowers/specs/2026-11-23-estructura-unica-design.md. */

const $ = (id) => document.getElementById(id);
const esCelular = () => matchMedia("(max-width: 900px)").matches;

const VISTAS = [
  { id: "jarvis", nombre: "Jarvis", src: () => `/asistente${location.search}`, icono: '<span class="mini-orbe"></span>' },
  { id: "whatsapp", nombre: "WhatsApp", src: () => "/apps/whatsapp",
    icono: '<svg viewBox="0 0 24 24"><path d="M12 2a10 10 0 0 0-8.6 15.1L2 22l5-1.3A10 10 0 1 0 12 2zm0 18.2a8.2 8.2 0 0 1-4.2-1.2l-.3-.2-3 .8.8-2.9-.2-.3A8.2 8.2 0 1 1 12 20.2zm4.5-6.1c-.2-.1-1.5-.7-1.7-.8-.2-.1-.4-.1-.6.1l-.8 1c-.1.2-.3.2-.5.1a6.7 6.7 0 0 1-3.3-2.9c-.3-.4.2-.4.7-1.4.1-.2 0-.3 0-.4l-.8-1.8c-.2-.5-.4-.4-.6-.4h-.5c-.2 0-.4.1-.6.3-.2.2-.8.8-.8 2s.8 2.3.9 2.5c.1.2 1.6 2.5 4 3.5 1.5.6 2.1.7 2.8.6.5-.1 1.5-.6 1.7-1.2.2-.6.2-1.1.2-1.2-.1-.1-.3-.2-.5-.3z"/></svg>' },
  { id: "correo", nombre: "Correo", src: () => "/apps/correo",
    icono: '<svg viewBox="0 0 24 24"><path d="M20 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 4l-8 5-8-5V6l8 5 8-5v2z"/></svg>' },
  { id: "calendario", nombre: "Calendario", src: () => "/apps/calendario",
    icono: '<svg viewBox="0 0 24 24"><path d="M19 4h-1V2h-2v2H8V2H6v2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2zm0 16H5V10h14v10zM7 12h5v5H7z"/></svg>' },
  { id: "reuniones", nombre: "Reuniones", src: () => "/apps/reuniones",
    icono: '<svg viewBox="0 0 24 24"><path d="M17 10.5V7a1 1 0 0 0-1-1H4a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-3.5l4 4v-11l-4 4z"/></svg>' },
];

const estado = {
  vista: null, marcos: new Map(), contextos: new Map(), ultimaApp: null,
  contextoQuitado: false, rol: "usuario", esAdminOrg: false, nombre: "Jarvis",
};

// ---------------------------------------------------------------- barra y vistas

function pintarRiel() {
  const caja = $("riel-apps");
  for (const v of VISTAS) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "riel-boton";
    b.dataset.vista = v.id;
    b.setAttribute("aria-label", v.nombre);
    b.innerHTML = `<span class="riel-icono">${v.icono}<span class="globo" hidden></span></span><span class="riel-texto">${v.nombre}</span>${v.id === "calendario" ? '<span class="proximo" hidden></span>' : ""}`;
    b.addEventListener("click", () => ir(v.id));
    caja.appendChild(b);
  }
}

function vistaDeLaDireccion() {
  const pedido = location.hash.replace("#", "");
  return VISTAS.some((v) => v.id === pedido) ? pedido : "jarvis";
}

function ir(id, { empujar = true } = {}) {
  const vista = VISTAS.find((v) => v.id === id) || VISTAS[0];
  if (estado.vista === vista.id) return;
  estado.vista = vista.id;
  if (!estado.marcos.has(vista.id)) {
    const marco = document.createElement("iframe");
    marco.src = vista.src();
    marco.title = vista.nombre;
    marco.allow = "microphone; camera; autoplay; clipboard-read; clipboard-write; fullscreen";
    $("vistas").appendChild(marco);
    estado.marcos.set(vista.id, marco);
    if (vista.id === "jarvis" && location.search) history.replaceState(null, "", "/" + location.hash);
  }
  // Escondidos con visibility y no con display: asi conservan su tamaño y las apps
  // precargadas no creen que estan en un celular.
  for (const [clave, marco] of estado.marcos) marco.classList.toggle("oculta", clave !== vista.id);
  document.querySelectorAll(".riel-boton[data-vista]").forEach((b) => b.classList.toggle("activa", b.dataset.vista === vista.id));
  document.title = vista.id === "jarvis" ? estado.nombre : `${vista.nombre} · ${estado.nombre}`;
  if (empujar) {
    const hash = vista.id === "jarvis" ? "" : `#${vista.id}`;
    if (location.hash !== hash) history.pushState(null, "", "/" + hash);
  }
  if (vista.id !== "jarvis") estado.ultimaApp = vista.id;
  else mandarContextoAlAsistente();
  pintarChip();
  cerrarMenus();
}
window.addEventListener("popstate", () => ir(vistaDeLaDireccion(), { empujar: false }));

// ---------------------------------------------------------------- mensajes de las apps

function contextoActual() {
  if (estado.contextoQuitado) return null;
  const app = estado.vista === "jarvis" ? estado.ultimaApp : estado.vista;
  return app ? estado.contextos.get(app) || null : null;
}

window.addEventListener("message", (e) => {
  if (e.origin !== location.origin || !e.data || typeof e.data !== "object") return;
  const origen = [...estado.marcos].find(([, marco]) => marco.contentWindow === e.source)?.[0];
  if (!origen) return;
  if (e.data.tipo === "contexto") {
    if (e.data.texto) estado.contextos.set(origen, { texto: String(e.data.texto).slice(0, 600), corto: String(e.data.corto || e.data.texto).slice(0, 80) });
    else estado.contextos.delete(origen);
    estado.contextoQuitado = false;
    pintarChip();
  } else if (e.data.tipo === "herramientas-usadas") {
    refrescarApps();
  } else if (e.data.tipo === "ir") {
    ir(String(e.data.vista));
    // Con id (p. ej. la campanita abre una reunión): si la vista ya estaba cargada le
    // llega "abrir"; si recién se crea, lo lee de sessionStorage al arrancar.
    if (e.data.id) estado.marcos.get(String(e.data.vista))?.contentWindow?.postMessage({ tipo: "abrir", id: String(e.data.id) }, location.origin);
  }
});

function refrescarApps() {
  for (const [clave, marco] of estado.marcos) {
    if (clave !== "jarvis") marco.contentWindow?.postMessage({ tipo: "refrescar" }, location.origin);
  }
  setTimeout(cargarResumen, 1500);
}

function mandarContextoAlAsistente() {
  const marco = estado.marcos.get("jarvis");
  const ctx = contextoActual();
  marco?.contentWindow?.postMessage({ tipo: "contexto", texto: ctx?.texto || "", corto: ctx?.corto || "" }, location.origin);
}

function pintarChip() {
  const ctx = contextoActual();
  $("chip").hidden = !ctx;
  if (ctx) $("chip-texto").textContent = `Sobre: ${ctx.corto}`;
}
$("chip-quitar").addEventListener("click", () => { estado.contextoQuitado = true; pintarChip(); mandarContextoAlAsistente(); });

// ---------------------------------------------------------------- contadores

async function cargarResumen() {
  try {
    const r = await (await fetch("/api/apps/resumen")).json();
    globo("whatsapp", r.whatsapp);
    globo("correo", r.correo);
    const proximo = document.querySelector('.riel-boton[data-vista="calendario"] .proximo');
    if (r.calendario) {
      const hora = new Date(r.calendario.inicio).toLocaleTimeString("es", { hour: "numeric", minute: "2-digit" });
      proximo.textContent = hora;
      proximo.title = `${r.calendario.titulo} · ${hora}`;
      proximo.hidden = false;
    } else proximo.hidden = true;
  } catch { /* sin red: en el proximo minuto */ }
}
function globo(vista, n) {
  const g = document.querySelector(`.riel-boton[data-vista="${vista}"] .globo`);
  if (!g) return;
  g.hidden = !n;
  g.textContent = n > 99 ? "99+" : String(n || "");
}

async function cargarAvisos() {
  try {
    const { no_vistos } = await (await fetch("/api/avisos/contador")).json();
    for (const id of ["globo-avisos", "globo-mas"]) {
      $(id).hidden = !no_vistos;
      $(id).textContent = no_vistos > 9 ? "9+" : String(no_vistos);
    }
  } catch { /* idem */ }
}

// ---------------------------------------------------------------- menus

function cerrarMenus() {
  $("menu-ajustes").hidden = true;
  $("menu-avisos").hidden = true;
  $("velo").hidden = true;
}
$("velo").addEventListener("click", cerrarMenus);

function ubicarMenu(menu, boton) {
  if (esCelular()) return;
  const r = boton.getBoundingClientRect();
  menu.style.left = `${r.right + 10}px`;
  menu.style.top = "auto";
  menu.style.bottom = `${Math.max(12, innerHeight - r.bottom)}px`;
}

const ICONOS_AJUSTES = {
  integraciones: '<path d="M20.5 11H19V7c0-1.1-.9-2-2-2h-4V3.5a2.5 2.5 0 0 0-5 0V5H4c-1.1 0-1.99.9-1.99 2v3.8H3.5c1.49 0 2.7 1.21 2.7 2.7s-1.21 2.7-2.7 2.7H2V20c0 1.1.9 2 2 2h3.8v-1.5c0-1.49 1.21-2.7 2.7-2.7s2.7 1.21 2.7 2.7V22H17c1.1 0 2-.9 2-2v-4h1.5a2.5 2.5 0 0 0 0-5z"/>',
  consumo: '<path d="M5 9.2h3V19H5zM10.6 5h2.8v14h-2.8zm5.6 8H19v6h-2.8z"/>',
  fuentes: '<path d="M12 3C7.58 3 4 4.79 4 7v10c0 2.21 3.59 4 8 4s8-1.79 8-4V7c0-2.21-3.58-4-8-4zm0 2c3.87 0 6 1.5 6 2s-2.13 2-6 2-6-1.5-6-2 2.13-2 6-2zm6 12c0 .5-2.13 2-6 2s-6-1.5-6-2v-2.23c1.61.78 3.72 1.23 6 1.23s4.39-.45 6-1.23V17zm0-4.55c-1.3.95-3.58 1.55-6 1.55s-4.7-.6-6-1.55V9.64c1.47.83 3.61 1.36 6 1.36s4.53-.53 6-1.36v2.81z"/>',
  organizacion: '<path d="M12 7V3H2v18h20V7H12zM6 19H4v-2h2v2zm0-4H4v-2h2v2zm0-4H4V9h2v2zm0-4H4V5h2v2zm4 12H8v-2h2v2zm0-4H8v-2h2v2zm0-4H8V9h2v2zm0-4H8V5h2v2zm10 12h-8v-2h2v-2h-2v-2h2v-2h-2V9h8v10zm-2-8h-2v2h2v-2zm0 4h-2v2h2v-2z"/>',
  asistente: '<path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/>',
  dispositivos: '<path d="M4 6h18V4H4c-1.1 0-2 .9-2 2v11H0v3h14v-3H4V6zm19 2h-6c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h6c.55 0 1-.45 1-1V9c0-.55-.45-1-1-1zm-1 9h-4v-7h4v7z"/>',
  memoria: '<path d="M15 9H9v6h6V9zm-2 4h-2v-2h2v2zm8-2V9h-2V7c0-1.1-.9-2-2-2h-2V3h-2v2h-2V3H9v2H7c-1.1 0-2 .9-2 2v2H3v2h2v2H3v2h2v2c0 1.1.9 2 2 2h2v2h2v-2h2v2h2v-2h2c1.1 0 2-.9 2-2v-2h2v-2h-2v-2h2zm-4 6H7V7h10v10z"/>',
  reiniciar: '<path d="M17.65 6.35A7.958 7.958 0 0 0 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0 1 12 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/>',
  avisos: '<path d="M12 22c1.1 0 2-.9 2-2h-4a2 2 0 0 0 2 2zm6-6v-5c0-3.07-1.64-5.64-4.5-6.32V4a1.5 1.5 0 0 0-3 0v.68C7.63 5.36 6 7.92 6 11v5l-2 2v1h16v-1l-2-2z"/>',
};

function abrirAjustes(boton, conAvisos = false) {
  const menu = $("menu-ajustes");
  const admin = estado.rol === "admin";
  const items = [["integraciones", "Integraciones"]];
  if (admin) {
    items.push(null, "Administración", ["consumo", "Consumo"], ["fuentes", "Fuentes"]);
    if (estado.esAdminOrg) items.push(["organizacion", "Organización"]);
    items.push(["asistente", "Asistente"], ["dispositivos", "Dispositivos"], ["memoria", "Memoria"], ["reiniciar", "Reiniciar conversación"]);
  }
  menu.innerHTML = "";
  if (conAvisos) {
    const b = document.createElement("button");
    b.innerHTML = `<svg viewBox="0 0 24 24">${ICONOS_AJUSTES.avisos}</svg>Avisos${$("globo-avisos").hidden ? "" : ` (${$("globo-avisos").textContent})`}`;
    b.addEventListener("click", () => abrirAvisos(boton));
    menu.appendChild(b);
    menu.insertAdjacentHTML("beforeend", '<div class="separador"></div>');
  }
  for (const item of items) {
    if (item === null) { menu.insertAdjacentHTML("beforeend", '<div class="separador"></div>'); continue; }
    if (typeof item === "string") { menu.insertAdjacentHTML("beforeend", `<div class="seccion">${item}</div>`); continue; }
    const [clave, texto] = item;
    const b = document.createElement("button");
    b.setAttribute("role", "menuitem");
    b.innerHTML = `<svg viewBox="0 0 24 24">${ICONOS_AJUSTES[clave]}</svg>${texto}`;
    b.addEventListener("click", () => abrirPanel(clave));
    menu.appendChild(b);
  }
  $("menu-avisos").hidden = true;
  menu.hidden = false;
  $("velo").hidden = false;
  ubicarMenu(menu, boton);
}

function abrirPanel(clave) {
  cerrarMenus();
  ir("jarvis");
  const marco = estado.marcos.get("jarvis");
  const mandar = () => marco.contentWindow?.postMessage({ tipo: "abrir-panel", panel: clave }, location.origin);
  if (marco.contentDocument?.readyState === "complete") setTimeout(mandar, 50);
  else marco.addEventListener("load", () => setTimeout(mandar, 400), { once: true });
}

async function abrirAvisos(boton) {
  const menu = $("menu-avisos");
  $("menu-ajustes").hidden = true;
  menu.hidden = false;
  $("velo").hidden = false;
  ubicarMenu(menu, boton);
  const lista = $("lista-avisos");
  lista.innerHTML = '<div class="sin-avisos">Cargando…</div>';
  try {
    const { avisos } = await (await fetch("/api/avisos")).json();
    lista.innerHTML = avisos.length ? "" : '<div class="sin-avisos">No hay avisos.</div>';
    for (const a of avisos) {
      const b = document.createElement("button");
      b.className = "aviso" + (a.visto ? "" : " nuevo");
      b.innerHTML = `<strong></strong><span></span><time></time>`;
      b.querySelector("strong").textContent = a.remitente || (a.app === "whatsapp" ? "WhatsApp" : "Correo");
      // Los avisos de reunión traen "Grabar: <enlace>" / "No grabar: <enlace>" en su
      // propia línea (para WhatsApp): aquí se quitan y se ofrece un botón.
      const lineas = (a.resumen || "").split("\n");
      b.querySelector("span").textContent = lineas.filter((l) => !/^(No grabar|Grabar): /.test(l)).join(" ");
      b.querySelector("time").textContent = new Date(a.creado).toLocaleString("es");
      b.addEventListener("click", async () => {
        cerrarMenus();
        await fetch(`/api/avisos/${a.id}/visto`, { method: "POST" });
        cargarAvisos();
        if (a.tipo === "reunion-lista" && a.hilo) {
          ir("reuniones");
          try { sessionStorage.setItem("jarvis-reunion-abrir", a.hilo); } catch { /* sin storage */ }
          estado.marcos.get("reuniones")?.contentWindow?.postMessage({ tipo: "abrir", id: a.hilo }, location.origin);
          return;
        }
        if (a.tipo !== "correo") return;
        if (a.app === "whatsapp") { ir("whatsapp"); estado.marcos.get("whatsapp")?.contentWindow?.postMessage({ tipo: "abrir", id: a.hilo }, location.origin); }
        else if (a.app === "gmail") { ir("correo"); estado.marcos.get("correo")?.contentWindow?.postMessage({ tipo: "abrir", id: a.hilo }, location.origin); }
        else preguntar(`Léeme el correo con id ${a.ref}`);
      });
      lista.appendChild(b);
      const grabar = lineas.some((l) => l.startsWith("Grabar: "));
      if (a.tipo === "reunion" && a.hilo && (grabar || lineas.some((l) => l.startsWith("No grabar: ")))) {
        const accion = document.createElement("button");
        accion.type = "button";
        accion.className = "aviso-accion";
        accion.textContent = grabar ? "Grabar esta reunión" : "No grabar";
        accion.addEventListener("click", async () => {
          accion.disabled = true;
          const r = await fetch(`/api/reuniones/${a.hilo}/${grabar ? "grabar" : "no-grabar"}`, { method: "POST" });
          accion.textContent = r.ok ? (await r.json()).mensaje : "No se pudo, inténtalo otra vez.";
        });
        lista.appendChild(accion);
      }
    }
  } catch {
    lista.innerHTML = '<div class="sin-avisos">No se pudieron cargar.</div>';
  }
}

$("btn-ajustes").addEventListener("click", (e) => abrirAjustes(e.currentTarget));
$("btn-avisos").addEventListener("click", (e) => abrirAvisos(e.currentTarget));
$("btn-mas").addEventListener("click", (e) => abrirAjustes(e.currentTarget, true));

// ---------------------------------------------------------------- Jarvis rapido

function abrirRapido(abrir = $("rapido").hidden) {
  if (esCelular()) { ir("jarvis"); return; }
  $("rapido").hidden = !abrir;
  $("btn-orbe").classList.toggle("abierto", abrir);
  if (abrir) { pintarChip(); $("rapido-texto").focus(); }
}
$("btn-orbe").addEventListener("click", () => abrirRapido());
$("rapido-cerrar").addEventListener("click", () => abrirRapido(false));
$("rapido-completo").addEventListener("click", () => { abrirRapido(false); ir("jarvis"); });
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "j") { e.preventDefault(); abrirRapido(); }
  if (e.key === "Escape") cerrarMenus();
});
window.addEventListener("message", (e) => {   // Ctrl+J tambien funciona con el foco dentro de una app
  if (e.origin === location.origin && e.data?.tipo === "atajo-jarvis") abrirRapido();
});

function burbuja(clase, texto) {
  $("rapido-hola").hidden = true;
  const div = document.createElement("div");
  div.className = `msj ${clase}`;
  div.textContent = texto;
  $("rapido-mensajes").appendChild(div);
  $("rapido-mensajes").scrollTop = $("rapido-mensajes").scrollHeight;
  return div;
}

let ocupado = false;
async function preguntar(mensaje) {
  if (!mensaje.trim() || ocupado) return;
  if ($("rapido").hidden && !esCelular()) abrirRapido(true);
  ocupado = true;
  const ctx = contextoActual();
  const mio = burbuja("yo", mensaje);
  if (ctx) mio.insertAdjacentHTML("afterbegin", `<span class="sobre"></span>`), (mio.querySelector(".sobre").textContent = `Sobre: ${ctx.corto}`);
  const estadoNodo = document.createElement("div");
  estadoNodo.className = "estado";
  estadoNodo.textContent = "Pensando…";
  $("rapido-mensajes").appendChild(estadoNodo);
  let respuesta = null, texto = "", usoHerramientas = false;
  try {
    const r = await fetch("/api/chat", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ mensaje, contexto: ctx?.texto || "" }) });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || `Error ${r.status}`);
    const lector = r.body.getReader();
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
          texto += evento.dato;
          if (!respuesta) respuesta = burbuja("jarvis", "");
          respuesta.textContent = texto;
          estadoNodo.remove();
          $("rapido-mensajes").scrollTop = $("rapido-mensajes").scrollHeight;
        } else if (evento.tipo === "herramienta") {
          usoHerramientas = true;
          estadoNodo.textContent = `Usando ${String(evento.dato).replaceAll("_", " ")}…`;
        } else if (evento.tipo === "error") {
          burbuja("error", evento.dato);
        }
      }
    }
  } catch (error) {
    burbuja("error", error.message);
  } finally {
    estadoNodo.remove();
    ocupado = false;
    if (usoHerramientas) refrescarApps();
  }
}
$("rapido-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const t = $("rapido-texto");
  const mensaje = t.value;
  t.value = "";
  t.style.height = "auto";
  preguntar(mensaje);
});
$("rapido-texto").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("rapido-form").requestSubmit(); }
});
$("rapido-texto").addEventListener("input", (e) => {
  e.target.style.height = "auto";
  e.target.style.height = Math.min(e.target.scrollHeight, 140) + "px";
});

// dictar con el reconocimiento de voz del navegador
const Reconocer = window.SpeechRecognition || window.webkitSpeechRecognition;
if (Reconocer) {
  const rec = new Reconocer();
  rec.lang = "es-ES";
  rec.interimResults = true;
  let dictando = false, base = "";
  $("rapido-dictar").hidden = false;
  $("rapido-dictar").addEventListener("click", () => {
    if (dictando) { rec.stop(); return; }
    base = $("rapido-texto").value ? $("rapido-texto").value + " " : "";
    rec.start();
  });
  rec.onstart = () => { dictando = true; $("rapido-dictar").classList.add("dictando"); };
  rec.onend = () => { dictando = false; $("rapido-dictar").classList.remove("dictando"); $("rapido-texto").focus(); };
  rec.onresult = (e) => {
    $("rapido-texto").value = base + Array.from(e.results, (r) => r[0].transcript).join("");
  };
}

// ---------------------------------------------------------------- arranque

async function arrancar() {
  pintarRiel();
  ir(vistaDeLaDireccion(), { empujar: false });
  try {
    const datos = await (await fetch("/api/estado")).json();
    Object.assign(estado, { rol: datos.rol, esAdminOrg: Boolean(datos.es_admin_org), nombre: datos.nombre || "Jarvis" });
    $("rapido-nombre").textContent = estado.nombre;
    document.querySelector('.riel-boton[data-vista="jarvis"] .riel-texto').textContent = estado.nombre;
    if (estado.vista === "jarvis") document.title = estado.nombre;
  } catch { /* sin estado: se queda con lo de usuario */ }
  cargarResumen();
  cargarAvisos();
  setInterval(cargarResumen, 60000);
  setInterval(cargarAvisos, 60000);
  // Las demas apps se precargan en silencio despues de un rato: el primer cambio ya es instantaneo.
  setTimeout(() => {
    for (const v of VISTAS) {
      if (estado.marcos.has(v.id)) continue;
      const marco = document.createElement("iframe");
      marco.src = v.src();
      marco.title = v.nombre;
      marco.classList.add("oculta");
      marco.allow = "microphone; camera; autoplay; clipboard-read; clipboard-write; fullscreen";
      $("vistas").appendChild(marco);
      estado.marcos.set(v.id, marco);
    }
  }, 4000);
}
arrancar();
