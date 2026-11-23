/* Bandeja de Gmail dentro de Jarvis (/apps/correo). Todo pasa por /api/apps/correo
   (Jarvis habla con Gmail con el token de la persona). Lo nuevo se pide cada 25 s.
   Ver docs/superpowers/specs/2026-11-23-apps-correo-design.md. */

const $ = (id) => document.getElementById(id);
const API = "/api/apps/correo";
const esCelular = () => matchMedia("(max-width: 900px)").matches;

const CARPETAS = [
  { id: "INBOX", nombre: "Recibidos", icono: '<path d="M19 3H4.99C3.88 3 3 3.9 3 5l.01 14c0 1.1.88 2 1.99 2H19c1.1 0 2-.9 2-2V5a2 2 0 0 0-2-2zm0 12h-4c0 1.66-1.35 3-3 3s-3-1.34-3-3H4.99V5H19v10z"/>' },
  { id: "STARRED", nombre: "Destacados", icono: '<path d="M22 9.24l-7.19-.62L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21 12 17.27 18.18 21l-1.63-7.03L22 9.24zM12 15.4l-3.76 2.27 1-4.28-3.32-2.88 4.38-.38L12 6.1l1.71 4.04 4.38.38-3.32 2.88 1 4.28L12 15.4z"/>' },
  { id: "SENT", nombre: "Enviados", icono: '<path d="M3 20v-6l8-2-8-2V4l19 8-19 8z"/>' },
  { id: "DRAFT", nombre: "Borradores", icono: '<path d="M14 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z"/>' },
  { id: "", nombre: "Todos", icono: '<path d="M20 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 14H4V8l8 5 8-5v10zm-8-7L4 6h16l-8 5z"/>' },
  { id: "SPAM", nombre: "Spam", icono: '<path d="M15.73 3H8.27L3 8.27v7.46L8.27 21h7.46L21 15.73V8.27L15.73 3zM12 17.3c-.72 0-1.3-.58-1.3-1.3s.58-1.3 1.3-1.3 1.3.58 1.3 1.3-.58 1.3-1.3 1.3zm1-4.3h-2V7h2v6z"/>' },
  { id: "TRASH", nombre: "Papelera", icono: '<path d="M15 4V3H9v1H4v2h1v13c0 1.1.9 2 2 2h10c1.1 0 2-.9 2-2V6h1V4h-5zm2 15H7V6h10v13zM9 8h2v9H9zm4 0h2v9h-2z"/>' },
];
const ICONO = {
  archivar: '<path d="M20.54 5.23l-1.39-1.68C18.88 3.21 18.47 3 18 3H6c-.47 0-.88.21-1.16.55L3.46 5.23C3.17 5.57 3 6.02 3 6.5V19c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V6.5c0-.48-.17-.93-.46-1.27zM12 17.5L6.5 12H10v-2h4v2h3.5L12 17.5zM5.12 5l.81-1h12l.94 1H5.12z"/>',
  eliminar: '<path d="M15 4V3H9v1H4v2h1v13c0 1.1.9 2 2 2h10c1.1 0 2-.9 2-2V6h1V4h-5zm2 15H7V6h10v13zM9 8h2v9H9zm4 0h2v9h-2z"/>',
  no_leido: '<path d="M20 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 4l-8 5-8-5V6l8 5 8-5v2z"/>',
  leido: '<path d="M18.83 7h-2.6L10.5 4 4 7.4V17c-1.1 0-2-.9-2-2V7.17c0-.53.32-1.09.8-1.34L10.5 2l7.54 3.83c.43.23.73.7.79 1.17zM20 8H7c-1.1 0-2 .9-2 2v9c0 1.1.9 2 2 2h13c1.1 0 2-.9 2-2v-9c0-1.1-.9-2-2-2zm0 3.67L13.5 15 7 11.67V10l6.5 3.33L20 10v1.67z"/>',
  mover: '<path d="M17.63 5.84C17.27 5.33 16.67 5 16 5L5 5.01C3.9 5.01 3 5.9 3 7v10c0 1.1.9 1.99 2 1.99L16 19c.67 0 1.27-.33 1.63-.84L22 12l-4.37-6.16zM16 17H5V7h11l3.55 5L16 17z"/>',
  spam: '<path d="M15.73 3H8.27L3 8.27v7.46L8.27 21h7.46L21 15.73V8.27L15.73 3zM19 14.9L14.9 19H9.1L5 14.9V9.1L9.1 5h5.8L19 9.1v5.8zM11 7h2v6h-2zm0 8h2v2h-2z"/>',
  restaurar: '<path d="M13 3a9 9 0 0 0-9 9H1l3.89 3.89.07.14L9 12H6c0-3.87 3.13-7 7-7s7 3.13 7 7-3.13 7-7 7c-1.93 0-3.68-.79-4.94-2.06l-1.42 1.42A8.954 8.954 0 0 0 13 21a9 9 0 0 0 0-18z"/>',
  responder: '<path d="M10 9V5l-7 7 7 7v-4.1c5 0 8.5 1.6 11 5.1-1-5-4-10-11-11z"/>',
  todos: '<path d="M7 8V5l-7 7 7 7v-3l-4-4 4-4zm6 1V5l-7 7 7 7v-4.1c5 0 8.5 1.6 11 5.1-1-5-4-10-11-11z"/>',
  reenviar: '<path d="M14 9V5l7 7-7 7v-4.1c-5 0-8.5 1.6-11 5.1 1-5 4-10 11-11z"/>',
  estrella: '<path d="M22 9.24l-7.19-.62L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21 12 17.27 18.18 21l-1.63-7.03L22 9.24zM12 15.4l-3.76 2.27 1-4.28-3.32-2.88 4.38-.38L12 6.1l1.71 4.04 4.38.38-3.32 2.88 1 4.28L12 15.4z"/>',
  estrella_llena: '<path d="M12 17.27L18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21z"/>',
  clip: '<path d="M16.5 6v11.5c0 2.21-1.79 4-4 4s-4-1.79-4-4V5a2.5 2.5 0 0 1 5 0v10.5c0 .55-.45 1-1 1s-1-.45-1-1V6H10v9.5a2.5 2.5 0 0 0 5 0V5c0-2.21-1.79-4-4-4S7 2.79 7 5v12.5c0 3.04 2.46 5.5 5.5 5.5s5.5-2.46 5.5-5.5V6h-1.5z"/>',
  etiqueta: '<path d="M17.63 5.84C17.27 5.33 16.67 5 16 5L5 5.01C3.9 5.01 3 5.9 3 7v10c0 1.1.9 1.99 2 1.99L16 19c.67 0 1.27-.33 1.63-.84L22 12l-4.37-6.16z"/>',
};
const svg = (nombre) => `<svg viewBox="0 0 24 24">${ICONO[nombre] || ""}</svg>`;
const NOMBRE_ACCION = { archivar: "Archivar", eliminar: "Eliminar", leido: "Marcar como leído", no_leido: "Marcar como no leído",
  mover: "Mover a", spam: "Marcar como spam", restaurar: "Sacar de la papelera", no_spam: "No es spam" };

const estado = {
  cuenta: "", modificar: false, historyId: null,
  etiquetas: [], carpeta: "INBOX", categoria: "primary", busqueda: "",
  hilos: [], paginas: [""], indice: 0, siguiente: null,
  elegidos: new Set(), abierto: null, deshacer: null,
};

// ---------------------------------------------------------------- utilidades

const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const COLORES = ["#c5221f", "#e8710a", "#1e8e3e", "#1a73e8", "#9334e6", "#d01884", "#00796b", "#5f6368", "#b06000", "#3949ab"];
function avatar(nombre, clase = "") {
  const letra = (String(nombre || "?").replace(/[^\p{L}\p{N}]/gu, "")[0] || "?").toUpperCase();
  let h = 0;
  for (const c of String(nombre || "")) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return `<div class="avatar ${clase}" style="background:${COLORES[h % COLORES.length]}">${esc(letra)}</div>`;
}
function fechaCorta(ms) {
  if (!ms) return "";
  const d = new Date(ms), hoy = new Date();
  if (d.toDateString() === hoy.toDateString()) return d.toLocaleTimeString("es", { hour: "numeric", minute: "2-digit" });
  if (d.getFullYear() === hoy.getFullYear()) return d.toLocaleDateString("es", { day: "numeric", month: "short" });
  return d.toLocaleDateString("es", { day: "2-digit", month: "2-digit", year: "2-digit" });
}
function fechaLarga(ms) {
  if (!ms) return "";
  const d = new Date(ms);
  const dias = Math.floor((Date.now() - ms) / 86400000);
  const texto = d.toLocaleString("es", { day: "numeric", month: "short", year: d.getFullYear() === new Date().getFullYear() ? undefined : "numeric", hour: "numeric", minute: "2-digit" });
  return dias >= 1 && dias < 30 ? `${texto} (hace ${dias} día${dias === 1 ? "" : "s"})` : texto;
}
const tamano = (b) => !b ? "" : b < 1024 ? `${b} B` : b < 1048576 ? `${Math.round(b / 1024)} KB` : `${(b / 1048576).toFixed(1)} MB`;

async function pedir(ruta, opciones = {}) {
  const r = await fetch(API + ruta, opciones);
  let datos = {};
  try { datos = await r.json(); } catch { /* sin cuerpo */ }
  if (r.status === 409 && datos.conectar) { $("conectar").hidden = false; throw new Error(datos.error); }
  if (r.status === 403 && datos.reconectar) { mostrarFranja(); throw new Error(datos.error); }
  if (!r.ok) throw new Error(datos.error || `Error ${r.status}`);
  return datos;
}
function mostrarFranja() { $("franja").hidden = false; document.body.classList.add("con-franja"); }

let avisoReloj = null;
function avisar(texto, deshacer = null) {
  $("aviso-texto").textContent = texto;
  $("aviso-deshacer").hidden = !deshacer;
  estado.deshacer = deshacer;
  $("aviso").hidden = false;
  clearTimeout(avisoReloj);
  avisoReloj = setTimeout(() => { $("aviso").hidden = true; estado.deshacer = null; }, 6000);
}
$("aviso-deshacer").addEventListener("click", () => {
  const accion = estado.deshacer;
  $("aviso").hidden = true;
  estado.deshacer = null;
  if (accion) accion();
});

// ---------------------------------------------------------------- menu

function nombreCarpeta(id) {
  return CARPETAS.find((c) => c.id === id)?.nombre || estado.etiquetas.find((e) => e.id === id)?.nombre || "Correo";
}

function pintarMenu() {
  const noLeidos = Object.fromEntries(estado.etiquetas.map((e) => [e.id, e]));
  $("carpetas").innerHTML = "";
  for (const c of CARPETAS) {
    const dato = noLeidos[c.id];
    const cuenta = c.id === "DRAFT" ? dato?.total : ["INBOX", "SPAM"].includes(c.id) ? dato?.no_leidos : 0;
    $("carpetas").appendChild(itemMenu(c.id, c.nombre, `<svg viewBox="0 0 24 24">${c.icono}</svg>`, cuenta));
  }
  const propias = estado.etiquetas.filter((e) => e.propia).sort((a, b) => a.nombre.localeCompare(b.nombre));
  $("etiquetas-titulo").hidden = !propias.length;
  $("etiquetas").innerHTML = "";
  for (const e of propias) {
    $("etiquetas").appendChild(itemMenu(e.id, e.nombre, `<span class="punto" style="background:${esc(e.color || "#8f8f8f")}"></span>`, e.no_leidos));
  }
}
function itemMenu(id, nombre, icono, cuenta) {
  const li = document.createElement("li");
  li.className = "carpeta" + (id === estado.carpeta && !estado.busqueda ? " activa" : "");
  li.innerHTML = `${icono}<span class="nombre">${esc(nombre)}</span><span class="cuenta">${cuenta ? cuenta.toLocaleString("es") : ""}</span>`;
  li.addEventListener("click", () => {
    document.body.classList.remove("menu-abierto");
    irA(id);
  });
  return li;
}

async function cargarEtiquetas() {
  try {
    const { etiquetas } = await pedir("/etiquetas");
    estado.etiquetas = etiquetas;
    pintarMenu();
  } catch { /* el menu queda como estaba */ }
}

function irA(carpeta) {
  estado.carpeta = carpeta;
  estado.busqueda = "";
  $("buscar").value = "";
  $("buscar-limpiar").hidden = true;
  estado.categoria = "primary";
  cerrarHilo(false);
  cargarLista(true);
  pintarMenu();
}

// ---------------------------------------------------------------- lista

function consulta() {
  if (estado.busqueda) return estado.busqueda;
  if (estado.carpeta !== "INBOX") return "";
  // Principal es lo que queda fuera de las otras pestañas (asi lo arma Gmail): no todos los
  // correos traen la categoria "primary", y pedirla dejaba Principal vacia.
  return estado.categoria === "primary" ? "-category:promotions -category:social" : `category:${estado.categoria}`;
}

async function cargarLista(desdeElPrincipio = false, silencioso = false) {
  if (desdeElPrincipio) { estado.paginas = [""]; estado.indice = 0; estado.elegidos.clear(); }
  const etiqueta = estado.busqueda ? "" : estado.carpeta;
  const pagina = estado.paginas[estado.indice] || "";
  $("pestanas").hidden = Boolean(estado.carpeta !== "INBOX" || estado.busqueda);
  $("titulo-movil").textContent = estado.busqueda ? `Resultados de «${estado.busqueda}»` : nombreCarpeta(estado.carpeta);
  if (!silencioso) { $("filas").innerHTML = '<li class="cargando">Cargando…</li>'; $("vacio").hidden = true; }
  try {
    const datos = await pedir(`/hilos?etiqueta=${encodeURIComponent(etiqueta)}&q=${encodeURIComponent(consulta())}&pagina=${encodeURIComponent(pagina)}`);
    estado.hilos = datos.hilos;
    estado.siguiente = datos.siguiente;
    pintarLista();
  } catch (error) {
    if (!silencioso) $("filas").innerHTML = `<li class="cargando">${esc(error.message)}</li>`;
  }
}

function pintarLista() {
  const filas = $("filas");
  filas.innerHTML = "";
  $("vacio").hidden = estado.hilos.length > 0;
  if (!estado.hilos.length) {
    $("vacio").textContent = estado.busqueda ? "No hay mensajes que coincidan con tu búsqueda." : `No hay conversaciones en ${nombreCarpeta(estado.carpeta)}.`;
  }
  for (const h of estado.hilos) filas.appendChild(filaDe(h));
  const desde = estado.indice * 50 + 1;
  $("paginas-texto").textContent = estado.hilos.length ? `${desde}–${desde + estado.hilos.length - 1}` : "";
  $("pag-ant").disabled = estado.indice === 0;
  $("pag-sig").disabled = !estado.siguiente;
  pintarSeleccion();
}

function quienes(h) {
  if (estado.carpeta === "SENT" || estado.carpeta === "DRAFT") {
    const para = (h.para || []).map((c) => c.split("@")[0]).join(", ");
    return `<span>${estado.carpeta === "DRAFT" ? '<span style="color:#f28b82">Borrador</span>' : `Para: ${esc(para || "(sin destinatario)")}`}</span>`;
  }
  const nombres = h.remitentes.slice(-3).join(", ");
  return esc(nombres) + (h.cantidad > 1 ? ` <small>${h.cantidad}</small>` : "");
}

function filaDe(h) {
  const li = document.createElement("li");
  li.className = "fila" + (h.no_leido ? "" : " leida") + (estado.elegidos.has(h.id) ? " elegida" : "");
  li.dataset.id = h.id;
  const estrella = `<button type="button" class="estrella${h.destacado ? " si" : ""}" aria-label="${h.destacado ? "Quitar estrella" : "Destacar"}">${svg(h.destacado ? "estrella_llena" : "estrella")}</button>`;
  li.innerHTML = `
    <label class="casilla" aria-label="Seleccionar"><input type="checkbox"${estado.elegidos.has(h.id) ? " checked" : ""}></label>
    ${estrella}
    ${avatar(h.remitentes[0] || h.para?.[0] || "?")}
    <span class="quien">${quienes(h)}</span>
    <span class="centro"><span class="asunto">${esc(h.asunto)}</span> - ${esc(h.fragmento)}</span>
    ${h.adjuntos ? `<span class="clip">${svg("clip")}</span>` : ""}
    <span class="fecha">${esc(fechaCorta(h.fecha))}</span>
    <span class="rapidas">${["archivar", "eliminar", h.no_leido ? "leido" : "no_leido"].map((a) =>
      `<button type="button" class="icono" data-accion="${a}" aria-label="${NOMBRE_ACCION[a]}" title="${NOMBRE_ACCION[a]}">${svg(a)}</button>`).join("")}</span>
    <div class="cuerpo-movil">
      <div class="linea1"><span class="quien">${quienes(h)}</span><span class="fecha">${esc(fechaCorta(h.fecha))}</span></div>
      <div class="linea2"><div class="textos"><div class="asunto-m">${esc(h.asunto)}</div><div class="fragmento-m">${esc(h.fragmento)}</div></div>${estrella}</div>
    </div>`;
  // en celular el avatar y el nombre van dentro del bloque movil; en computadora, sueltos
  if (esCelular()) {
    li.querySelectorAll(":scope > .quien, :scope > .estrella, :scope > .fecha").forEach((n) => n.remove());
  } else {
    li.querySelector(".cuerpo-movil").remove();
  }
  li.addEventListener("click", (e) => {
    if (e.target.closest(".casilla")) return;
    const accion = e.target.closest("[data-accion]")?.dataset.accion;
    if (accion) { e.stopPropagation(); hacer(accion, [h.id]); return; }
    if (e.target.closest(".estrella")) { e.stopPropagation(); hacer(h.destacado ? "quitar_estrella" : "destacar", [h.id]); return; }
    if (e.target.closest(".avatar") && esCelular()) { elegir(h.id, !estado.elegidos.has(h.id)); return; }
    if (esCelular() && estado.elegidos.size) { elegir(h.id, !estado.elegidos.has(h.id)); return; }
    abrirHilo(h);
  });
  li.querySelector(".casilla input")?.addEventListener("change", (e) => elegir(h.id, e.target.checked));
  let presion = null;   // mantener presionado en celular = elegir
  li.addEventListener("touchstart", () => { presion = setTimeout(() => { presion = null; elegir(h.id, true); }, 500); }, { passive: true });
  ["touchend", "touchmove"].forEach((ev) => li.addEventListener(ev, () => clearTimeout(presion), { passive: true }));
  return li;
}

function elegir(id, si) {
  if (si) estado.elegidos.add(id); else estado.elegidos.delete(id);
  const fila = $("filas").querySelector(`.fila[data-id="${CSS.escape(id)}"]`);
  fila?.classList.toggle("elegida", si);
  const casilla = fila?.querySelector(".casilla input");
  if (casilla) casilla.checked = si;
  pintarSeleccion();
}

function accionesPara(ids) {
  const hilos = estado.hilos.filter((h) => ids.includes(h.id));
  const algunoNoLeido = hilos.some((h) => h.no_leido);
  const lista = [];
  if (estado.carpeta === "TRASH") lista.push("restaurar");
  else if (estado.carpeta === "SPAM") lista.push("no_spam", "eliminar");
  else {
    if (estado.carpeta !== "") lista.push("archivar");
    lista.push("spam", "eliminar");
  }
  lista.push(algunoNoLeido ? "leido" : "no_leido", "mover");
  return lista;
}

function botonesDeAccion(contenedor, ids, alHacer) {
  contenedor.innerHTML = "";
  for (const accion of accionesPara(ids)) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "icono";
    b.title = b.ariaLabel = NOMBRE_ACCION[accion];
    b.innerHTML = svg(accion === "no_spam" ? "restaurar" : accion);
    b.addEventListener("click", () => (accion === "mover" ? elegirEtiqueta(ids, alHacer) : hacer(accion, ids, alHacer)));
    contenedor.appendChild(b);
  }
}

function pintarSeleccion() {
  const ids = [...estado.elegidos];
  $("acciones-seleccion").hidden = !ids.length;
  $("todos").checked = ids.length > 0 && ids.length === estado.hilos.length;
  $("todos").indeterminate = ids.length > 0 && ids.length < estado.hilos.length;
  document.body.classList.toggle("eligiendo", ids.length > 0);
  if (ids.length) botonesDeAccion($("acciones-seleccion"), ids);
}
$("todos").addEventListener("change", (e) => {
  estado.elegidos = e.target.checked ? new Set(estado.hilos.map((h) => h.id)) : new Set();
  pintarLista();
});

// ---------------------------------------------------------------- acciones

const CONTRARIA = { archivar: "a_recibidos", eliminar: "restaurar", restaurar: "eliminar", spam: "no_spam", no_spam: "spam",
  leido: "no_leido", no_leido: "leido", destacar: "quitar_estrella", quitar_estrella: "destacar" };
const SALE_DE_LA_LISTA = { archivar: ["INBOX"], eliminar: "*", spam: "*", no_spam: ["SPAM"], restaurar: ["TRASH"], mover: ["INBOX"] };

async function hacer(accion, ids, alHacer = null, etiqueta = "", esDeshacer = false) {
  const antes = estado.hilos.map((h) => ({ ...h }));
  // en pantalla, ya
  const sale = SALE_DE_LA_LISTA[accion];
  if (sale === "*" || (sale && sale.includes(estado.carpeta)) || (accion === "mover" && estado.carpeta === "INBOX")) {
    estado.hilos = estado.hilos.filter((h) => !ids.includes(h.id));
  } else {
    for (const h of estado.hilos.filter((x) => ids.includes(x.id))) {
      if (accion === "leido") h.no_leido = false;
      if (accion === "no_leido") h.no_leido = true;
      if (accion === "destacar") h.destacado = true;
      if (accion === "quitar_estrella") h.destacado = false;
    }
  }
  ids.forEach((id) => estado.elegidos.delete(id));
  pintarLista();
  if (alHacer) alHacer(accion);
  try {
    await pedir("/acciones", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ ids, accion, etiqueta }) });
  } catch (error) {
    estado.hilos = antes;
    pintarLista();
    avisar(`No se pudo: ${error.message}`);
    return;
  }
  cargarEtiquetas();
  if (esDeshacer) { cargarLista(false, true); return; }
  const uno = ids.length === 1;
  const hecho = (singular) => (uno ? singular : singular.replace(/^(\w+)a\b/, "$1as"));
  const textos = { archivar: "archivada", eliminar: "movida a la papelera", spam: "marcada como spam", no_spam: "movida a Recibidos",
    restaurar: "sacada de la papelera", leido: "marcada como leída", no_leido: "marcada como no leída",
    mover: `movida a ${nombreCarpeta(etiqueta)}`, a_recibidos: "movida a Recibidos" };
  if (textos[accion]) {
    const deshacer = accion === "mover"
      ? () => { hacer("quitar_etiqueta", ids, null, etiqueta, true); hacer("a_recibidos", ids, null, "", true); }
      : CONTRARIA[accion] ? () => hacer(CONTRARIA[accion], ids, null, "", true) : null;
    avisar(`${uno ? "Conversación" : `${ids.length} conversaciones`} ${hecho(textos[accion])}.`, deshacer);
  }
}

function elegirEtiqueta(ids, alHacer) {
  const lista = $("lista-mover");
  lista.innerHTML = "";
  const opciones = [...estado.etiquetas.filter((e) => e.propia), { id: "INBOX", nombre: "Recibidos" }];
  for (const e of opciones) {
    const li = document.createElement("li");
    li.innerHTML = `<button type="button">${esc(e.nombre)}</button>`;
    li.querySelector("button").addEventListener("click", () => {
      $("capa-etiquetas").hidden = true;
      if (e.id === "INBOX") hacer("a_recibidos", ids, alHacer);
      else hacer("mover", ids, alHacer, e.id);
    });
    lista.appendChild(li);
  }
  $("capa-etiquetas").hidden = false;
}
$("mover-cancelar").addEventListener("click", () => { $("capa-etiquetas").hidden = true; });

// ---------------------------------------------------------------- leer

async function abrirHilo(resumen) {
  if (estado.carpeta === "DRAFT") { abrirBorrador(resumen.id); return; }
  estado.abierto = resumen.id;
  $("vista-lista").hidden = true;
  $("vista-hilo").hidden = false;
  document.body.classList.add("leyendo");
  if (esCelular()) history.pushState({ hilo: resumen.id }, "");
  $("hilo").innerHTML = `<div class="hilo-asunto"><h2>${esc(resumen.asunto)}</h2></div><div class="cargando">Cargando…</div>`;
  botonesDeAccion($("acciones-hilo"), [resumen.id], (accion) => { if (accion !== "leido" && accion !== "no_leido") cerrarHilo(); });
  if (resumen.no_leido) { resumen.no_leido = false; }
  try {
    const datos = await pedir(`/hilos/${encodeURIComponent(resumen.id)}`);
    if (estado.abierto !== resumen.id) return;
    pintarHilo(resumen, datos);
    cargarEtiquetas();
  } catch (error) {
    $("hilo").querySelector(".cargando").textContent = error.message;
  }
}

function cerrarHilo(volverAtras = true) {
  if (!estado.abierto) return;
  estado.abierto = null;
  $("vista-hilo").hidden = true;
  $("vista-lista").hidden = false;
  document.body.classList.remove("leyendo");
  pintarLista();
  if (volverAtras && history.state?.hilo) history.back();
}
$("btn-volver").addEventListener("click", () => cerrarHilo());
window.addEventListener("popstate", () => { if (estado.abierto) cerrarHilo(false); });

function pintarHilo(resumen, datos) {
  const caja = $("hilo");
  const etiquetasHilo = (resumen.etiquetas || []).map((id) => estado.etiquetas.find((e) => e.id === id && e.propia)).filter(Boolean);
  caja.innerHTML = `<div class="hilo-asunto"><h2>${esc(resumen.asunto)}</h2>${etiquetasHilo.map((e) => `<span class="chip">${esc(e.nombre)}</span>`).join("")}</div>`;
  datos.mensajes.forEach((m, i) => {
    const ultimo = i === datos.mensajes.length - 1;
    caja.appendChild(bloqueMensaje(m, !(ultimo || m.no_leido), datos.cuenta));
  });
  const ultimo = datos.mensajes[datos.mensajes.length - 1];
  const botones = document.createElement("div");
  botones.className = "responder-botones";
  botones.innerHTML = `<button type="button" class="boton-borde" data-modo="responder">${svg("responder")}Responder</button>
    <button type="button" class="boton-borde" data-modo="todos">${svg("todos")}Responder a todos</button>
    <button type="button" class="boton-borde" data-modo="reenviar">${svg("reenviar")}Reenviar</button>`;
  botones.addEventListener("click", (e) => {
    const modo = e.target.closest("[data-modo]")?.dataset.modo;
    if (modo) responder(modo, ultimo, datos.cuenta, resumen.id);
  });
  caja.appendChild(botones);
}

function bloqueMensaje(m, plegado, cuenta) {
  const div = document.createElement("article");
  div.className = "mensaje" + (plegado ? " plegado" : "");
  const otros = [m.para, m.cc].filter(Boolean).join(", ");
  div.innerHTML = `
    <div class="mensaje-cabeza">${avatar(m.de.nombre, "grande")}
      <span class="nombre">${esc(m.de.nombre)}</span><span class="correo">&lt;${esc(m.de.correo)}&gt;</span>
      <span class="fecha">${esc(fechaLarga(m.fecha))}</span></div>
    <div class="mensaje-para">para ${esc(otros.replaceAll(cuenta, "mí") || "mí")}</div>
    <div class="fragmento">${esc(m.fragmento)}</div>
    <div class="imagenes" hidden>Las imágenes no se muestran.<button type="button">Mostrar imágenes</button></div>
    <div class="mensaje-cuerpo"></div>
    <div class="adjuntos"></div>`;
  let pintado = false;
  const pintar = (conImagenes = false) => {
    pintado = true;
    const cuerpo = div.querySelector(".mensaje-cuerpo");
    cuerpo.innerHTML = "";
    cuerpo.appendChild(marcoDelCorreo(m.html, conImagenes));
    div.querySelector(".imagenes").hidden = !m.imagenes_remotas || conImagenes;
  };
  div.querySelector(".imagenes button").addEventListener("click", () => pintar(true));
  div.querySelector(".mensaje-cabeza").addEventListener("click", () => {
    div.classList.toggle("plegado");
    if (!pintado && !div.classList.contains("plegado")) pintar();
  });
  if (!plegado) pintar();
  const adjuntos = div.querySelector(".adjuntos");
  for (const a of m.adjuntos) {
    const url = `${API}/adjunto/${encodeURIComponent(a.mensaje)}/${encodeURIComponent(a.id)}?nombre=${encodeURIComponent(a.nombre)}&tipo=${encodeURIComponent(a.tipo)}`;
    const ext = (a.nombre.split(".").pop() || "").slice(0, 4).toUpperCase();
    const enlace = document.createElement("a");
    enlace.className = "adjunto";
    enlace.href = url + (a.tipo.startsWith("image/") || a.tipo === "application/pdf" ? "&ver=1" : "");
    enlace.target = "_blank";
    enlace.rel = "noopener";
    enlace.innerHTML = `<div class="vista">${a.tipo.startsWith("image/") ? `<img alt="" loading="lazy" src="${esc(url)}&ver=1">` : `<span class="tipo${ext === "PDF" ? "" : " otro"}">${esc(ext || "ARCH")}</span>`}</div>
      <div class="pie">${esc(a.nombre)}<small>${esc(tamano(a.tamano))}</small></div>`;
    adjuntos.appendChild(enlace);
  }
  return div;
}

/* El correo va en un iframe aislado: sin scripts (sandbox sin allow-scripts), los enlaces
   en otra pestaña, y las imagenes remotas bloqueadas por CSP hasta "Mostrar imagenes".
   allow-same-origin solo deja que esta pagina mida el alto del correo: sin scripts adentro,
   el correo no puede usarlo para nada. */
function marcoDelCorreo(html, conImagenes) {
  const marco = document.createElement("iframe");
  marco.setAttribute("sandbox", "allow-same-origin allow-popups allow-popups-to-escape-sandbox");
  marco.setAttribute("referrerpolicy", "no-referrer");
  marco.title = "Contenido del correo";
  const politica = `default-src 'none'; style-src 'unsafe-inline' ${conImagenes ? "https: http:" : ""}; font-src data: ${conImagenes ? "https:" : ""}; img-src data: ${conImagenes ? "https: http:" : ""}`;
  marco.srcdoc = `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${politica}">
    <base target="_blank"><style>html,body{margin:0}body{padding:16px;font:14px/1.5 Roboto,Arial,sans-serif;color:#222;background:#fff;overflow-wrap:anywhere}
    img{max-width:100%;height:auto}table{max-width:100%}${conImagenes ? "" : 'img:not([src^="data:"]){visibility:hidden}'}blockquote{margin:0 0 0 .8ex;border-left:1px solid #ccc;padding-left:1ex}</style></head><body>${html}</body></html>`;
  const ajustar = () => {
    try { marco.style.height = (marco.contentDocument.documentElement.scrollHeight + 2) + "px"; } catch { marco.style.height = "400px"; }
  };
  marco.addEventListener("load", () => {
    ajustar();
    marco.contentDocument?.querySelectorAll("img").forEach((img) => img.addEventListener("load", ajustar));
    setTimeout(ajustar, 400);
  });
  return marco;
}

// ---------------------------------------------------------------- redactar

const redactor = { borradorId: null, hilo: null, responder: null, adjuntos: [], originales: [], cambios: 0, guardando: false, reloj: null };

function abrirRedactor({ para = "", cc = "", asunto = "", html = "", hilo = null, responderA = null, originales = [], borradorId = null, titulo = "Mensaje nuevo" } = {}) {
  Object.assign(redactor, { borradorId, hilo, responder: responderA, adjuntos: [], originales, cambios: 0 });
  $("r-para").value = para;
  $("r-cc").value = cc;
  $("r-cco").value = "";
  $("r-fila-cc").hidden = !cc;
  $("r-fila-cco").hidden = true;
  $("r-asunto").value = asunto;
  $("r-editor").innerHTML = html;
  $("r-error").textContent = "";
  $("r-estado").textContent = "";
  $("redactor-titulo").textContent = titulo;
  $("redactor").hidden = false;
  $("redactor").classList.remove("minimizado");
  pintarAdjuntos();
  (para ? $("r-editor") : $("r-para")).focus();
  if (para) { // cursor al principio del texto, antes de la cita
    const rango = document.createRange();
    rango.setStart($("r-editor"), 0);
    rango.collapse(true);
    getSelection().removeAllRanges();
    getSelection().addRange(rango);
  }
}

function pintarAdjuntos() {
  const lista = $("r-adjuntos");
  lista.innerHTML = "";
  const todos = [...redactor.originales.map((a) => ({ ...a, original: true })), ...redactor.adjuntos.map((f) => ({ nombre: f.name, tamano: f.size, archivo: f }))];
  todos.forEach((a) => {
    const li = document.createElement("li");
    li.innerHTML = `<span>${esc(a.nombre)}</span><small>${esc(tamano(a.tamano))}</small><button type="button" class="icono chico" aria-label="Quitar"><svg viewBox="0 0 24 24"><path d="M19 6.4L17.6 5 12 10.6 6.4 5 5 6.4 10.6 12 5 17.6 6.4 19 12 13.4 17.6 19 19 17.6 13.4 12z"/></svg></button>`;
    li.querySelector("button").addEventListener("click", () => {
      if (a.original) redactor.originales = redactor.originales.filter((x) => x !== redactor.originales.find((o) => o.id === a.id));
      else redactor.adjuntos = redactor.adjuntos.filter((f) => f !== a.archivo);
      pintarAdjuntos();
      cambio();
    });
    lista.appendChild(li);
  });
}

function formulario() {
  const datos = new FormData();
  datos.append("para", $("r-para").value);
  datos.append("cc", $("r-cc").value);
  datos.append("cco", $("r-cco").value);
  datos.append("asunto", $("r-asunto").value);
  datos.append("html", $("r-editor").innerHTML);
  if (redactor.hilo) datos.append("hilo", redactor.hilo);
  if (redactor.borradorId) datos.append("borrador_id", redactor.borradorId);
  if (redactor.responder) {
    datos.append("responder_message_id", redactor.responder.message_id || "");
    datos.append("responder_referencias", redactor.responder.referencias || "");
  }
  if (redactor.originales.length) datos.append("adjuntos_originales", JSON.stringify(redactor.originales));
  for (const f of redactor.adjuntos) datos.append("adjuntos", f, f.name);
  return datos;
}

const vacio = () => !$("r-para").value.trim() && !$("r-asunto").value.trim() && !$("r-editor").textContent.trim() && !redactor.adjuntos.length;

async function guardarBorrador() {
  if (!estado.modificar || redactor.guardando || $("redactor").hidden || vacio()) return;
  redactor.guardando = true;
  const cambiosAntes = redactor.cambios;
  $("r-estado").textContent = "Guardando…";
  try {
    const { id } = await pedir("/borrador", { method: "PUT", body: formulario() });
    redactor.borradorId = id;
    $("r-estado").textContent = "Borrador guardado";
  } catch {
    $("r-estado").textContent = "";
  } finally {
    redactor.guardando = false;
    if (redactor.cambios !== cambiosAntes) programarGuardado();
  }
}
function programarGuardado() {
  clearTimeout(redactor.reloj);
  redactor.reloj = setTimeout(guardarBorrador, 3000);
}
function cambio() { redactor.cambios += 1; programarGuardado(); }
["r-para", "r-cc", "r-cco", "r-asunto"].forEach((id) => $(id).addEventListener("input", cambio));
$("r-editor").addEventListener("input", cambio);

$("r-enviar").addEventListener("click", async () => {
  if (![$("r-para"), $("r-cc"), $("r-cco")].some((c) => c.value.trim())) {
    $("r-error").textContent = "Indica al menos un destinatario.";
    return;
  }
  clearTimeout(redactor.reloj);
  $("r-enviar").disabled = true;
  $("r-error").textContent = "";
  $("r-estado").textContent = "Enviando…";
  try {
    await pedir("/enviar", { method: "POST", body: formulario() });
    $("redactor").hidden = true;
    avisar("Mensaje enviado.");
    cargarEtiquetas();
    if (estado.abierto && estado.abierto === redactor.hilo) {
      const resumen = estado.hilos.find((h) => h.id === estado.abierto) || { id: estado.abierto, asunto: $("r-asunto").value, etiquetas: [] };
      abrirHilo(resumen);
    } else cargarLista(false, true);
  } catch (error) {
    $("r-error").textContent = error.message;
    $("r-estado").textContent = "";
  } finally {
    $("r-enviar").disabled = false;
  }
});

$("r-descartar").addEventListener("click", async () => {
  clearTimeout(redactor.reloj);
  $("redactor").hidden = true;
  if (redactor.borradorId) {
    try { await pedir(`/borrador/${encodeURIComponent(redactor.borradorId)}`, { method: "DELETE" }); } catch { /* ya no estaba */ }
    if (estado.carpeta === "DRAFT") cargarLista(false, true);
  }
  avisar("Borrador descartado.");
});
$("redactor-cerrar").addEventListener("click", async (e) => {
  e.stopPropagation();
  clearTimeout(redactor.reloj);
  await guardarBorrador();
  $("redactor").hidden = true;
  if (!vacio() && estado.modificar) avisar("Borrador guardado.");
});
$("redactor-minimizar").addEventListener("click", (e) => { e.stopPropagation(); $("redactor").classList.toggle("minimizado"); });
$("redactor-cabecera").addEventListener("click", () => $("redactor").classList.remove("minimizado"));
$("r-mostrar-cc").addEventListener("click", () => { $("r-fila-cc").hidden = false; $("r-fila-cco").hidden = false; $("r-cc").focus(); });
$("r-adjuntar").addEventListener("click", () => $("r-archivos").click());
$("r-archivos").addEventListener("change", (e) => {
  redactor.adjuntos.push(...e.target.files);
  e.target.value = "";
  const total = redactor.adjuntos.reduce((s, f) => s + f.size, 0) + redactor.originales.reduce((s, a) => s + (a.tamano || 0), 0);
  $("r-error").textContent = total > 25 * 1024 * 1024 ? "Los adjuntos pasan de 25 MB: Gmail no los acepta." : "";
  pintarAdjuntos();
  cambio();
});
$("r-formato").addEventListener("mousedown", (e) => e.preventDefault());   // no perder la seleccion del editor
$("r-formato").addEventListener("click", (e) => {
  const cmd = e.target.closest("[data-cmd]")?.dataset.cmd;
  if (!cmd) return;
  if (cmd === "createLink") {
    const url = prompt("Dirección del enlace:", "https://");
    if (url && /^(https?:|mailto:)/i.test(url)) document.execCommand("createLink", false, url);
  } else document.execCommand(cmd);
  cambio();
});

function abrirNuevo() { abrirRedactor(); }
$("btn-redactar").addEventListener("click", abrirNuevo);
$("btn-redactar-flotante").addEventListener("click", abrirNuevo);

/* El HTML de un correo que se cita o reenvia entra al editor, que vive en esta pagina:
   sin <style> (cambiaria toda la pagina), sin scripts y sin imagenes remotas (rastreo). */
function limpiarParaCitar(html) {
  const doc = new DOMParser().parseFromString(`<body>${html}</body>`, "text/html");
  doc.querySelectorAll("style, script, link, meta, title, iframe, object, embed, form, base").forEach((n) => n.remove());
  doc.querySelectorAll("img").forEach((img) => { if (!/^data:/i.test(img.getAttribute("src") || "")) img.remove(); });
  doc.querySelectorAll("*").forEach((n) => {
    for (const attr of [...n.attributes]) if (/^on/i.test(attr.name) || /^\s*javascript:/i.test(attr.value)) n.removeAttribute(attr.name);
  });
  return doc.body.innerHTML;
}

function citaDe(m) {
  return `<br><br><div class="gmail_quote">El ${esc(fechaLarga(m.fecha))}, ${esc(m.de.nombre)} &lt;${esc(m.de.correo)}&gt; escribió:<br>
    <blockquote style="margin:0 0 0 .8ex;border-left:1px solid #ccc;padding-left:1ex">${limpiarParaCitar(m.html)}</blockquote></div>`;
}

function responder(modo, m, cuenta, hiloId) {
  const asuntoBase = (m.asunto || "").replace(/^((re|rv|fw|fwd)\s*:\s*)+/i, "");
  if (modo === "reenviar") {
    abrirRedactor({
      asunto: `Fwd: ${asuntoBase}`, titulo: `Fwd: ${asuntoBase}`, originales: m.adjuntos,
      html: `<br><br>---------- Mensaje reenviado ---------<br>De: ${esc(m.de.nombre)} &lt;${esc(m.de.correo)}&gt;<br>Fecha: ${esc(m.fecha_texto)}<br>Asunto: ${esc(m.asunto)}<br>Para: ${esc(m.para)}<br><br>${limpiarParaCitar(m.html)}`,
    });
    $("r-para").focus();
    return;
  }
  const propio = (cuenta || "").toLowerCase();
  const de = m.de.correo.toLowerCase() === propio ? m.para : `${m.de.nombre} <${m.de.correo}>`;
  let cc = "";
  if (modo === "todos") {
    const separar = (t) => String(t || "").split(",").map((x) => x.trim()).filter(Boolean);
    cc = [...separar(m.para), ...separar(m.cc)].filter((d) => !d.toLowerCase().includes(propio) && !d.toLowerCase().includes(m.de.correo.toLowerCase())).join(", ");
  }
  abrirRedactor({ para: de, cc, asunto: `Re: ${asuntoBase}`, titulo: `Re: ${asuntoBase}`, html: citaDe(m), hilo: hiloId,
    responderA: { message_id: m.message_id, referencias: m.referencias } });
}

async function abrirBorrador(hiloId) {
  try {
    const datos = await pedir(`/hilos/${encodeURIComponent(hiloId)}`);
    const m = datos.mensajes[datos.mensajes.length - 1];
    const { id } = await pedir(`/borrador-de/${encodeURIComponent(m.id)}`);
    abrirRedactor({ para: m.para, cc: m.cc, asunto: m.asunto, html: limpiarParaCitar(m.html), borradorId: id, originales: m.adjuntos,
      hilo: datos.mensajes.length > 1 ? hiloId : null, titulo: m.asunto || "Borrador" });
  } catch (error) {
    avisar(error.message);
  }
}

// ---------------------------------------------------------------- busqueda, paginas, pestañas, menu

$("buscar-form").addEventListener("submit", (e) => {
  e.preventDefault();
  estado.busqueda = $("buscar").value.trim();
  $("buscar-limpiar").hidden = !estado.busqueda;
  cerrarHilo(false);
  cargarLista(true);
  pintarMenu();
});
$("buscar-limpiar").addEventListener("click", () => irA(estado.carpeta));
$("pestanas").addEventListener("click", (e) => {
  const boton = e.target.closest("[data-cat]");
  if (!boton) return;
  estado.categoria = boton.dataset.cat;
  $("pestanas").querySelectorAll("button").forEach((b) => b.classList.toggle("activa", b === boton));
  cargarLista(true);
});
$("pag-sig").addEventListener("click", () => {
  if (!estado.siguiente) return;
  estado.paginas[estado.indice + 1] = estado.siguiente;
  estado.indice += 1;
  cargarLista();
});
$("pag-ant").addEventListener("click", () => {
  if (!estado.indice) return;
  estado.indice -= 1;
  cargarLista();
});
$("btn-recargar").addEventListener("click", () => { cargarLista(false); cargarEtiquetas(); });
$("btn-menu").addEventListener("click", () => {
  if (esCelular()) document.body.classList.toggle("menu-abierto");
  else $("menu").hidden = !$("menu").hidden, $("app").style.gridTemplateColumns = $("menu").hidden ? "0 1fr" : "";
});
$("velo").addEventListener("click", () => document.body.classList.remove("menu-abierto"));
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (!$("capa-etiquetas").hidden) $("capa-etiquetas").hidden = true;
  else if (document.body.classList.contains("menu-abierto")) document.body.classList.remove("menu-abierto");
  else if (estado.abierto && document.activeElement?.closest?.("#redactor") == null) cerrarHilo();
});

// ---------------------------------------------------------------- lo nuevo

async function revisarCambios() {
  if (!estado.historyId || document.visibilityState !== "visible") return;
  try {
    const { historyId, hay } = await pedir(`/cambios?desde=${encodeURIComponent(estado.historyId)}`);
    estado.historyId = historyId;
    if (!hay) return;
    cargarEtiquetas();
    if (!estado.abierto && estado.indice === 0 && !estado.elegidos.size) cargarLista(false, true);
  } catch { /* se reintenta en la proxima vuelta */ }
}

// ---------------------------------------------------------------- arranque

async function arrancar() {
  try {
    const datos = await pedir("/estado");
    if (!datos.conectado) { $("conectar").hidden = false; return; }
    Object.assign(estado, { cuenta: datos.cuenta, modificar: datos.modificar, historyId: datos.historyId });
    $("cuenta").textContent = datos.cuenta;
    $("avatar-propio").outerHTML = avatar(datos.cuenta, "avatar-propio");
    if (!datos.modificar) mostrarFranja();
    pintarMenu();
    await Promise.all([cargarEtiquetas(), cargarLista(true)]);
    setInterval(revisarCambios, 25000);
    document.addEventListener("visibilitychange", revisarCambios);
  } catch (error) {
    $("filas").innerHTML = `<li class="cargando">${esc(error.message)}</li>`;
  }
}
arrancar();
