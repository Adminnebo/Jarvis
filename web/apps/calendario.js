/* Calendario dentro de Jarvis (/apps/calendario). Todo pasa por /api/apps/calendario
   (Jarvis habla con Google con el token de la persona). Al dia: cada 60 s se pide el rango.
   Ver docs/superpowers/specs/2026-11-23-apps-calendario-design.md. */

import { enEstructura } from "./comun.js";

const estructura = enEstructura("calendario", { refrescar: () => cargarEventos(true) });

const $ = (id) => document.getElementById(id);
const API = "/api/apps/calendario";
const esCelular = () => matchMedia("(max-width: 900px)").matches;
const H = 48;               // alto de una hora en la grilla (igual que --k-hora)
const PASO = 15;            // minutos a los que se ajusta crear, mover y estirar
const DIA_MS = 86400000;

const estado = {
  vista: esCelular() ? "agenda" : "semana",
  fecha: hoy(),
  calendarios: [], ocultos: new Set(leerOcultos()),
  eventos: [], cuenta: "", cargando: 0, ocupado: false,
};

// ---------------------------------------------------------------- fechas

function hoy() { const d = new Date(); d.setHours(0, 0, 0, 0); return d; }
function sumarDias(d, n) { const x = new Date(d); x.setDate(x.getDate() + n); return x; }
function mismoDia(a, b) { return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate(); }
function inicioSemana(d) { return sumarDias(d, -d.getDay()); }   // domingo, como Google en español
function ymd(d) { return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; }
function deYmd(t) { const [a, m, d] = t.slice(0, 10).split("-").map(Number); return new Date(a, m - 1, d); }
const horaTexto = (d) => d.toLocaleTimeString("es", { hour: "numeric", minute: "2-digit" });
const hhmm = (d) => `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
const minutosDelDia = (d) => d.getHours() * 60 + d.getMinutes();
const ajustar = (min) => Math.round(min / PASO) * PASO;

function inicioDe(e) { return e.todo_el_dia ? deYmd(e.inicio) : new Date(e.inicio); }
function finDe(e) { return e.todo_el_dia ? deYmd(e.fin) : new Date(e.fin); }

function rango() {
  const f = estado.fecha;
  switch (estado.vista) {
    case "dia": return { inicio: f, fin: sumarDias(f, 1), dias: [f] };
    case "tres": return { inicio: f, fin: sumarDias(f, 3), dias: [0, 1, 2].map((i) => sumarDias(f, i)) };
    case "mes": {
      const primero = new Date(f.getFullYear(), f.getMonth(), 1);
      const inicio = inicioSemana(primero);
      return { inicio, fin: sumarDias(inicio, 42), dias: Array.from({ length: 42 }, (_, i) => sumarDias(inicio, i)) };
    }
    case "agenda": return { inicio: f, fin: sumarDias(f, 31), dias: Array.from({ length: 31 }, (_, i) => sumarDias(f, i)) };
    default: {
      const inicio = inicioSemana(f);
      return { inicio, fin: sumarDias(inicio, 7), dias: Array.from({ length: 7 }, (_, i) => sumarDias(inicio, i)) };
    }
  }
}

function titulo() {
  const { inicio, fin } = rango();
  const f = estado.fecha;
  const mesAnio = (d) => d.toLocaleDateString("es", { month: "long", year: "numeric" });
  if (estado.vista === "dia") return f.toLocaleDateString("es", { day: "numeric", month: "long", year: "numeric" });
  if (estado.vista === "mes") return mesAnio(f);
  const ultimo = sumarDias(fin, -1);
  if (inicio.getMonth() === ultimo.getMonth()) return mesAnio(inicio);
  const corto = (d) => d.toLocaleDateString("es", { month: "short" }).replace(".", "");
  return inicio.getFullYear() === ultimo.getFullYear()
    ? `${corto(inicio)} – ${corto(ultimo)} ${ultimo.getFullYear()}`
    : `${corto(inicio)} ${inicio.getFullYear()} – ${corto(ultimo)} ${ultimo.getFullYear()}`;
}

// ---------------------------------------------------------------- utilidades

const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const enlazar = (t) => esc(t).replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>');
function leerOcultos() { try { return JSON.parse(localStorage.getItem("calendario-ocultos") || "[]"); } catch { return []; } }
function guardarOcultos() { try { localStorage.setItem("calendario-ocultos", JSON.stringify([...estado.ocultos])); } catch { /* sin almacenamiento */ } }
const calendarioDe = (id) => estado.calendarios.find((c) => c.id === id);
const colorDe = (e) => e.color || calendarioDe(e.calendario)?.color || "#039be5";
function textoSobre(color) {
  const c = color.replace("#", "");
  if (c.length < 6) return "#fff";
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(c.slice(i, i + 2), 16));
  return (r * 299 + g * 587 + b * 114) / 1000 > 150 ? "#1f1f1f" : "#fff";
}

let avisoReloj = null;
function avisar(texto) {
  $("aviso-texto").textContent = texto;
  $("aviso").hidden = false;
  clearTimeout(avisoReloj);
  avisoReloj = setTimeout(() => { $("aviso").hidden = true; }, 4000);
}

async function pedir(ruta, opciones = {}) {
  const r = await fetch(API + ruta, opciones);
  let datos = {};
  try { datos = await r.json(); } catch { /* sin cuerpo */ }
  if (r.status === 409 && datos.conectar) { mostrarConectar(datos.reconectar); throw new Error(datos.error); }
  if (!r.ok) throw new Error(datos.error || `Error ${r.status}`);
  return datos;
}
const json = (metodo, cuerpo) => ({ method: metodo, headers: { "content-type": "application/json" }, body: JSON.stringify(cuerpo) });

function mostrarConectar(reconectar) {
  $("conectar").hidden = false;
  if (reconectar) $("conectar-texto").textContent = "Vuelve a conectar tu Google y marca la casilla del calendario para ver tu agenda en Jarvis.";
}

// ---------------------------------------------------------------- datos

async function cargarEventos(silencioso = false) {
  const { inicio, fin } = rango();
  const visibles = estado.calendarios.filter((c) => !estado.ocultos.has(c.id)).map((c) => c.id);
  const turno = ++estado.cargando;
  if (!visibles.length) { estado.eventos = []; pintar(); return; }
  try {
    const { eventos } = await pedir(`/eventos?desde=${encodeURIComponent(inicio.toISOString())}&hasta=${encodeURIComponent(fin.toISOString())}&calendarios=${encodeURIComponent(visibles.join(","))}`);
    if (turno !== estado.cargando || estado.ocupado) return;   // llego una respuesta vieja, o se esta arrastrando
    estado.eventos = eventos;
    pintar();
  } catch (error) {
    if (!silencioso) avisar(error.message);
  }
}

function eventosVisibles() {
  return estado.eventos.filter((e) => !estado.ocultos.has(e.calendario));
}

// ---------------------------------------------------------------- menu lateral

function pintarMini() {
  const ancla = estado.miniMes || new Date(estado.fecha.getFullYear(), estado.fecha.getMonth(), 1);
  estado.miniMes = ancla;
  const inicio = inicioSemana(ancla);
  const caja = $("mini");
  caja.innerHTML = `<div class="mini-cabeza"><span>${esc(ancla.toLocaleDateString("es", { month: "long", year: "numeric" }))}</span>
    <span><button class="icono" data-mini="-1" aria-label="Mes anterior"><svg viewBox="0 0 24 24"><path d="M15.41 7.41L14 6l-6 6 6 6 1.41-1.41L10.83 12z"/></svg></button>
    <button class="icono" data-mini="1" aria-label="Mes siguiente"><svg viewBox="0 0 24 24"><path d="M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z"/></svg></button></span></div>
    <div class="mini-grilla">${["D", "L", "M", "M", "J", "V", "S"].map((l) => `<span>${l}</span>`).join("")}</div>`;
  const grilla = caja.querySelector(".mini-grilla");
  const { inicio: ri, fin: rf } = rango();
  for (let i = 0; i < 42; i++) {
    const d = sumarDias(inicio, i);
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = d.getDate();
    b.className = (d.getMonth() !== ancla.getMonth() ? "otro-mes " : "") + (mismoDia(d, hoy()) ? "hoy " : "")
      + (estado.vista !== "mes" && estado.vista !== "agenda" && d >= ri && d < rf ? "elegido" : "");
    b.addEventListener("click", () => { estado.fecha = d; if (estado.vista === "mes" || estado.vista === "agenda") estado.vista = esCelular() ? "dia" : "dia"; cerrarLado(); render(); });
    grilla.appendChild(b);
  }
  caja.querySelectorAll("[data-mini]").forEach((b) => b.addEventListener("click", () => {
    estado.miniMes = new Date(ancla.getFullYear(), ancla.getMonth() + Number(b.dataset.mini), 1);
    pintarMini();
  }));
}

function pintarCalendarios() {
  const lista = $("lista-cal");
  lista.innerHTML = "";
  for (const c of estado.calendarios) {
    const li = document.createElement("li");
    li.innerHTML = `<label><input type="checkbox"${estado.ocultos.has(c.id) ? "" : " checked"} style="accent-color:${esc(c.color)}"><span>${esc(c.nombre)}</span></label>`;
    li.querySelector("input").addEventListener("change", (e) => {
      if (e.target.checked) estado.ocultos.delete(c.id); else estado.ocultos.add(c.id);
      guardarOcultos();
      cargarEventos();
    });
    lista.appendChild(li);
  }
}

// ---------------------------------------------------------------- pintar

function render() {
  estado.miniMes = null;
  $("titulo").textContent = titulo();
  $("vistas").querySelectorAll("button").forEach((b) => b.classList.toggle("activa", b.dataset.vista === estado.vista));
  pintarMini();
  pintar();
  cargarEventos();
}

function pintar() {
  cerrarTarjeta(false);
  const centro = $("centro");
  if (estado.vista === "mes") pintarMes(centro);
  else if (estado.vista === "agenda") pintarAgenda(centro);
  else pintarSemana(centro);
}

function etiquetaEvento(e) {
  return e.todo_el_dia ? "Todo el día" : `${horaTexto(inicioDe(e))} – ${horaTexto(finDe(e))}`;
}

function claseRespuesta(e) {
  return e.mi_respuesta === "pendiente" ? " pendiente" : e.mi_respuesta === "no" ? " rechazado" : "";
}

/* Columnas para eventos que se pisan: grupos de eventos encadenados y, en cada grupo,
   la primera columna libre para cada uno. */
function columnas(lista) {
  const orden = [...lista].sort((a, b) => a.ini - b.ini || b.fin - a.fin);
  let grupo = [], finGrupo = -1;
  const cerrar = () => { const n = Math.max(...grupo.map((x) => x.col)) + 1; grupo.forEach((x) => { x.cols = n; }); grupo = []; };
  for (const x of orden) {
    if (x.ini >= finGrupo && grupo.length) cerrar();
    const ocupadas = new Set(grupo.filter((y) => y.fin > x.ini).map((y) => y.col));
    let col = 0;
    while (ocupadas.has(col)) col++;
    x.col = col;
    grupo.push(x);
    finGrupo = Math.max(finGrupo, x.fin);
  }
  if (grupo.length) cerrar();
  return orden;
}

function pintarSemana(centro) {
  const { dias } = rango();
  const plantilla = `56px repeat(${dias.length}, minmax(0, 1fr))`;
  const eventos = eventosVisibles();
  centro.innerHTML = `
    <div class="sem-cabeza" style="grid-template-columns:${plantilla}"><div class="zona-hora">${esc(Intl.DateTimeFormat().resolvedOptions().timeZone.split("/").pop().replace("_", " "))}</div>
      ${dias.map((d) => `<div class="sem-dia${mismoDia(d, hoy()) ? " hoy" : ""}" data-dia="${ymd(d)}"><div class="nombre">${esc(d.toLocaleDateString("es", { weekday: "short" }).replace(".", ""))}</div><div class="numero">${d.getDate()}</div></div>`).join("")}</div>
    <div class="sem-todo" style="grid-template-columns:${plantilla}"><div></div>${dias.map((d) => `<div class="celda" data-dia="${ymd(d)}"></div>`).join("")}</div>
    <div class="sem-cuerpo" id="sem-cuerpo"><div class="sem-grilla" style="grid-template-columns:${plantilla}">
      <div class="horas">${Array.from({ length: 23 }, (_, i) => `<span style="top:${(i + 1) * H}px">${esc(horaTexto(new Date(2000, 0, 1, i + 1)))}</span>`).join("")}</div>
      ${dias.map((d) => `<div class="col" data-dia="${ymd(d)}"></div>`).join("")}</div></div>`;
  centro.querySelectorAll(".sem-dia").forEach((n) => n.addEventListener("click", () => { estado.fecha = deYmd(n.dataset.dia); estado.vista = "dia"; render(); }));

  // todo el dia (y los que duran 24 h o mas)
  for (const e of eventos) {
    const ini = inicioDe(e), fin = finDe(e);
    const largo = e.todo_el_dia || fin - ini >= DIA_MS;
    if (!largo) continue;
    dias.forEach((d) => {
      if (fin > d && ini < sumarDias(d, 1)) {
        const chip = document.createElement("div");
        chip.className = "chip" + claseRespuesta(e);
        chip.style.background = colorDe(e);
        chip.style.color = textoSobre(colorDe(e));
        chip.textContent = e.titulo;
        chip.addEventListener("click", (ev) => abrirTarjeta(e, ev.currentTarget));
        centro.querySelector(`.sem-todo .celda[data-dia="${ymd(d)}"]`).appendChild(chip);
      }
    });
  }

  // con hora
  dias.forEach((d) => {
    const col = centro.querySelector(`.col[data-dia="${ymd(d)}"]`);
    const finDia = sumarDias(d, 1);
    const delDia = eventos.filter((e) => !e.todo_el_dia && finDe(e) - inicioDe(e) < DIA_MS && finDe(e) > d && inicioDe(e) < finDia)
      .map((e) => ({ e, ini: Math.max(0, (inicioDe(e) - d) / 60000), fin: Math.min(1440, (finDe(e) - d) / 60000) }));
    for (const x of columnas(delDia)) col.appendChild(bloqueEvento(x));
    if (mismoDia(d, hoy())) {
      const linea = document.createElement("div");
      linea.className = "ahora";
      linea.style.top = `${minutosDelDia(new Date()) / 60 * H}px`;
      col.appendChild(linea);
    }
    prepararCrear(col, d);
  });
  const cuerpo = $("sem-cuerpo");
  cuerpo.scrollTop = estado.scroll ?? Math.max(0, (Math.min(minutosDelDia(new Date()), 17 * 60) / 60 - 2) * H);
  cuerpo.addEventListener("scroll", () => { estado.scroll = cuerpo.scrollTop; });
}

function bloqueEvento({ e, ini, fin, col, cols }) {
  const div = document.createElement("div");
  const alto = Math.max(fin - ini, 20) / 60 * H;
  div.className = "ev" + (alto < 38 ? " corto" : "") + claseRespuesta(e);
  div.style.top = `${ini / 60 * H}px`;
  div.style.height = `${alto - 1}px`;
  div.style.left = `calc(${(col / cols) * 100}% + 1px)`;
  div.style.width = `calc(${(1 / cols) * 100}% - ${col === cols - 1 ? 6 : 2}px)`;
  div.style.background = colorDe(e);
  div.style.color = textoSobre(colorDe(e));
  div.innerHTML = `<div class="t">${esc(e.titulo)}</div><div class="h">${esc(etiquetaEvento(e))}</div>${e.puede_editar ? '<div class="estirar"></div>' : ""}`;
  div.dataset.id = e.id;
  prepararMover(div, e);
  return div;
}

function pintarMes(centro) {
  const { dias } = rango();
  const mes = estado.fecha.getMonth();
  const eventos = eventosVisibles();
  centro.innerHTML = `<div class="mes-cabeza">${["dom", "lun", "mar", "mié", "jue", "vie", "sáb"].map((d) => `<span>${d}</span>`).join("")}</div><div class="mes-grilla"></div>`;
  const grilla = centro.querySelector(".mes-grilla");
  for (const d of dias) {
    const celda = document.createElement("div");
    celda.className = "mes-celda" + (d.getMonth() !== mes ? " otro-mes" : "") + (mismoDia(d, hoy()) ? " hoy" : "");
    celda.innerHTML = `<button type="button" class="num">${d.getDate() === 1 ? esc(d.toLocaleDateString("es", { day: "numeric", month: "short" })) : d.getDate()}</button>`;
    celda.querySelector(".num").addEventListener("click", () => { estado.fecha = d; estado.vista = "dia"; render(); });
    const delDia = eventos.filter((e) => finDe(e) > d && inicioDe(e) < sumarDias(d, 1))
      .sort((a, b) => (b.todo_el_dia - a.todo_el_dia) || (inicioDe(a) - inicioDe(b)));
    delDia.slice(0, 3).forEach((e) => {
      const chip = document.createElement("div");
      const largo = e.todo_el_dia || finDe(e) - inicioDe(e) >= DIA_MS;
      chip.className = "chip" + (largo ? "" : " punto") + claseRespuesta(e);
      chip.style.setProperty("--c", colorDe(e));
      if (largo) { chip.style.background = colorDe(e); chip.style.color = textoSobre(colorDe(e)); chip.textContent = e.titulo; }
      else chip.innerHTML = `<span class="h">${esc(horaTexto(inicioDe(e)))}</span><span>${esc(e.titulo)}</span>`;
      chip.addEventListener("click", (ev) => { ev.stopPropagation(); abrirTarjeta(e, ev.currentTarget); });
      celda.appendChild(chip);
    });
    if (delDia.length > 3) {
      const mas = document.createElement("button");
      mas.type = "button";
      mas.className = "mas";
      mas.textContent = `${delDia.length - 3} más`;
      mas.addEventListener("click", () => { estado.fecha = d; estado.vista = "dia"; render(); });
      celda.appendChild(mas);
    }
    celda.addEventListener("click", (ev) => {
      if (ev.target !== celda) return;
      const inicio = new Date(d); inicio.setHours(9);
      abrirRapida({ inicio, fin: new Date(+inicio + 3600000), todo_el_dia: false }, celda);
    });
    grilla.appendChild(celda);
  }
}

function pintarAgenda(centro) {
  const { dias } = rango();
  const eventos = eventosVisibles();
  centro.innerHTML = '<div class="agenda"></div>';
  const caja = centro.querySelector(".agenda");
  let alguno = false;
  for (const d of dias) {
    const delDia = eventos.filter((e) => finDe(e) > d && inicioDe(e) < sumarDias(d, 1))
      .sort((a, b) => (b.todo_el_dia - a.todo_el_dia) || (inicioDe(a) - inicioDe(b)));
    if (!delDia.length) continue;
    alguno = true;
    const fila = document.createElement("div");
    fila.className = "ag-dia" + (mismoDia(d, hoy()) ? " hoy" : "");
    fila.innerHTML = `<div class="ag-fecha"><span class="numero">${d.getDate()}</span><span class="nombre">${esc(d.toLocaleDateString("es", { month: "short", weekday: "short" }).replace(/\./g, ""))}</span></div><div class="ag-lista"></div>`;
    fila.querySelector(".ag-fecha").addEventListener("click", () => { estado.fecha = d; estado.vista = "dia"; render(); });
    for (const e of delDia) {
      const item = document.createElement("div");
      item.className = "ag-evento" + claseRespuesta(e);
      if (esCelular()) { item.style.background = colorDe(e); item.style.color = textoSobre(colorDe(e)); }
      item.innerHTML = `<span class="p" style="background:${esc(colorDe(e))}"></span><span class="h">${esc(etiquetaEvento(e))}</span><span>${esc(e.titulo)}</span>`;
      item.addEventListener("click", (ev) => abrirTarjeta(e, ev.currentTarget));
      fila.querySelector(".ag-lista").appendChild(item);
    }
    caja.appendChild(fila);
  }
  if (!alguno) caja.innerHTML = '<div class="ag-vacio">No hay eventos en los próximos 30 días.</div>';
}

// ---------------------------------------------------------------- crear con clic o arrastre

function prepararCrear(col, dia) {
  col.addEventListener("pointerdown", (ev) => {
    if (ev.button !== 0 || ev.target !== col) return;
    cerrarTarjeta();
    const caja = col.getBoundingClientRect();
    const minuto = (y) => Math.max(0, Math.min(1440, ajustar(((y - caja.top) / H) * 60)));
    const desde = Math.floor(((ev.clientY - caja.top) / H) * 60 / 30) * 30;
    const fantasma = document.createElement("div");
    fantasma.className = "ev fantasma";
    fantasma.style.cssText = `left:1px;width:calc(100% - 6px);background:${calendarioPrincipal()?.color || "#039be5"};top:${desde / 60 * H}px;height:${H - 1}px`;
    fantasma.innerHTML = '<div class="t">(Sin título)</div>';
    col.appendChild(fantasma);
    let hasta = desde + 60, movio = false;
    const mover = (e) => {
      const m = minuto(e.clientY);
      if (Math.abs(m - desde) >= PASO) movio = true;
      if (!movio) return;
      const [a, b] = m >= desde ? [desde, Math.max(m, desde + PASO)] : [m, desde + 30];
      fantasma.style.top = `${a / 60 * H}px`;
      fantasma.style.height = `${(b - a) / 60 * H - 1}px`;
      hasta = b;
      fantasma.dataset.desde = a;
    };
    const soltar = () => {
      window.removeEventListener("pointermove", mover);
      window.removeEventListener("pointerup", soltar);
      const a = Number(fantasma.dataset.desde ?? desde);
      const inicio = new Date(+dia + a * 60000);
      const fin = new Date(+dia + (movio ? hasta : a + 60) * 60000);
      fantasma.querySelector(".t").insertAdjacentHTML("afterend", `<div class="h">${esc(horaTexto(inicio))} – ${esc(horaTexto(fin))}</div>`);
      abrirRapida({ inicio, fin, todo_el_dia: false }, fantasma, () => fantasma.remove());
    };
    window.addEventListener("pointermove", mover);
    window.addEventListener("pointerup", soltar);
  });
}

const calendarioPrincipal = () => estado.calendarios.find((c) => c.principal && c.puede_editar) || estado.calendarios.find((c) => c.puede_editar);

// ---------------------------------------------------------------- mover y estirar

function prepararMover(div, e) {
  div.addEventListener("pointerdown", (ev) => {
    if (ev.button !== 0) return;
    const estirando = ev.target.classList.contains("estirar");
    if (!e.puede_editar || ev.pointerType === "touch") return;   // en el telefono: tocar abre la tarjeta
    ev.preventDefault();
    const cols = [...document.querySelectorAll(".col")].map((c) => ({ el: c, caja: c.getBoundingClientRect(), dia: deYmd(c.dataset.dia) }));
    const colInicial = cols.findIndex((c) => c.el === div.parentElement);
    const [x0, y0] = [ev.clientX, ev.clientY];
    const ini0 = inicioDe(e), fin0 = finDe(e);
    let movido = false, nuevoIni = ini0, nuevoFin = fin0;
    const mover = (m) => {
      const dy = ajustar(((m.clientY - y0) / H) * 60);
      if (!movido && Math.hypot(m.clientX - x0, m.clientY - y0) < 5) return;
      if (!movido) { movido = true; estado.ocupado = true; div.classList.add("arrastrando"); cerrarTarjeta(); }
      if (estirando) {
        nuevoFin = new Date(Math.max(+fin0 + dy * 60000, +ini0 + PASO * 60000));
        div.style.height = `${(nuevoFin - ini0) / 3600000 * H - 1}px`;
      } else {
        const destino = cols.findIndex((c) => m.clientX >= c.caja.left && m.clientX < c.caja.right);
        const dc = destino >= 0 ? destino - colInicial : 0;
        nuevoIni = new Date(+ini0 + dc * DIA_MS + dy * 60000);
        nuevoFin = new Date(+nuevoIni + (fin0 - ini0));
        const col = cols[Math.max(0, colInicial + dc)];
        if (col && div.parentElement !== col.el) col.el.appendChild(div);
        div.style.top = `${minutosDelDia(nuevoIni) / 60 * H}px`;
        div.style.left = "1px";
        div.style.width = "calc(100% - 6px)";
      }
      div.querySelector(".h").textContent = `${horaTexto(nuevoIni)} – ${horaTexto(nuevoFin)}`;
    };
    const soltar = () => {
      window.removeEventListener("pointermove", mover);
      window.removeEventListener("pointerup", soltar);
      estado.ocupado = false;
      if (!movido) { abrirTarjeta(e, div); return; }
      div.classList.remove("arrastrando");
      if (+nuevoIni === +ini0 && +nuevoFin === +fin0) { pintar(); return; }
      guardarCambio(e, { inicio: nuevoIni.toISOString(), fin: nuevoFin.toISOString() });
    };
    window.addEventListener("pointermove", mover);
    window.addEventListener("pointerup", soltar);
  });
}

function preguntarSerie(texto) {
  return new Promise((resolver) => {
    $("serie-titulo").textContent = texto;
    $("capa-serie").querySelector('input[value="0"]').checked = true;
    $("capa-serie").hidden = false;
    const fin = (valor) => { $("capa-serie").hidden = true; $("serie-aceptar").onclick = $("serie-cancelar").onclick = null; resolver(valor); };
    $("serie-aceptar").onclick = () => fin($("capa-serie").querySelector("input:checked").value === "1");
    $("serie-cancelar").onclick = () => fin(null);
  });
}

async function guardarCambio(e, cambios) {
  let todos = false;
  if (e.recurrente) {
    todos = await preguntarSerie("Editar evento recurrente");
    if (todos === null) { pintar(); return; }
  }
  const antes = { ...e };
  Object.assign(e, cambios);   // se ve ya
  pintar();
  try {
    const nuevo = await pedir(`/eventos/${encodeURIComponent(e.calendario)}/${encodeURIComponent(e.id)}?todos=${todos ? 1 : 0}`, json("PATCH", cambios));
    if (todos) cargarEventos(true); else Object.assign(e, nuevo, { calendario: e.calendario });
    pintar();
  } catch (error) {
    Object.assign(e, antes);
    pintar();
    avisar(`No se pudo cambiar: ${error.message}`);
  }
}

// ---------------------------------------------------------------- tarjeta del evento

let alCerrarTarjeta = null;
function cerrarTarjeta(conLimpieza = true) {
  $("tarjeta").hidden = true;
  if (conLimpieza && alCerrarTarjeta) alCerrarTarjeta();
  alCerrarTarjeta = null;
}

function ubicar(cerca) {
  const t = $("tarjeta");
  if (esCelular() || !cerca) return;
  const r = cerca.getBoundingClientRect();
  const ancho = t.offsetWidth, alto = t.offsetHeight;
  let x = r.right + 8;
  if (x + ancho > innerWidth - 12) x = r.left - ancho - 8;
  if (x < 12) x = Math.max(12, (innerWidth - ancho) / 2);
  const y = Math.min(Math.max(60, r.top), innerHeight - alto - 12);
  t.style.left = `${x}px`;
  t.style.top = `${y}px`;
}

const ICONO = {
  editar: '<path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04a.996.996 0 0 0 0-1.41l-2.34-2.34a.996.996 0 0 0-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/>',
  borrar: '<path d="M15 4V3H9v1H4v2h1v13c0 1.1.9 2 2 2h10c1.1 0 2-.9 2-2V6h1V4h-5zm2 15H7V6h10v13zM9 8h2v9H9zm4 0h2v9h-2z"/>',
  cerrar: '<path d="M19 6.4L17.6 5 12 10.6 6.4 5 5 6.4 10.6 12 5 17.6 6.4 19 12 13.4 17.6 19 19 17.6 13.4 12z"/>',
  lugar: '<path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5a2.5 2.5 0 0 1 0-5 2.5 2.5 0 0 1 0 5z"/>',
  video: '<path d="M17 10.5V7c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1-1v-3.5l4 4v-11l-4 4z"/>',
  personas: '<path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"/>',
  texto: '<path d="M14 17H4v2h10v-2zm6-8H4v2h16V9zM4 15h16v-2H4v2zM4 5v2h16V5H4z"/>',
  calendario: '<path d="M19 4h-1V2h-2v2H8V2H6v2H5c-1.11 0-2 .9-2 2v14a2 2 0 0 0 2 2h14c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 16H5V10h14v10z"/>',
  aviso: '<path d="M12 22c1.1 0 2-.9 2-2h-4c0 1.1.9 2 2 2zm6-6v-5c0-3.07-1.63-5.64-4.5-6.32V4c0-.83-.67-1.5-1.5-1.5s-1.5.67-1.5 1.5v.68C7.64 5.36 6 7.92 6 11v5l-2 2v1h16v-1l-2-2z"/>',
};
const svg = (n) => `<svg viewBox="0 0 24 24">${ICONO[n]}</svg>`;

function cuandoTexto(e) {
  const ini = inicioDe(e), fin = finDe(e);
  const dia = (d) => d.toLocaleDateString("es", { weekday: "long", day: "numeric", month: "long" });
  if (e.todo_el_dia) {
    const ultimo = sumarDias(fin, -1);
    return mismoDia(ini, ultimo) ? dia(ini) : `${dia(ini)} – ${dia(ultimo)}`;
  }
  return mismoDia(ini, fin) ? `${dia(ini)} · ${horaTexto(ini)} – ${horaTexto(fin)}` : `${dia(ini)}, ${horaTexto(ini)} – ${dia(fin)}, ${horaTexto(fin)}`;
}

function abrirTarjeta(e, cerca) {
  cerrarTarjeta();
  estructura.contexto(`Calendario (Google): evento id ${e.id} en el calendario ${e.calendario}, «${e.titulo}», ${cuandoTexto(e)}`
    + (e.recurrente ? " (se repite)" : ""), `evento «${String(e.titulo).slice(0, 50)}»`);
  const t = $("tarjeta");
  const marca = { si: "✓", no: "✕", quizas: "?", pendiente: "·" };
  const cal = calendarioDe(e.calendario);
  t.innerHTML = `
    <div class="tarjeta-arriba">
      ${e.puede_editar ? `<button class="icono" data-t="editar" aria-label="Editar">${svg("editar")}</button><button class="icono" data-t="borrar" aria-label="Borrar">${svg("borrar")}</button>` : ""}
      <button class="icono" data-t="cerrar" aria-label="Cerrar">${svg("cerrar")}</button></div>
    <div class="t-fila"><span class="t-cuadro" style="background:${esc(colorDe(e))}"></span><div><div class="t-titulo">${esc(e.titulo)}</div><div class="t-sub">${esc(cuandoTexto(e))}</div></div></div>
    ${e.meet ? `<div class="t-fila">${svg("video")}<div><a class="boton-meet" href="${esc(e.meet)}" target="_blank" rel="noopener">Unirse con Google Meet</a><div class="t-sub">${esc(e.meet.replace(/^https?:\/\//, ""))}</div></div></div>` : ""}
    ${e.ubicacion ? `<div class="t-fila">${svg("lugar")}<div>${enlazar(e.ubicacion)}</div></div>` : ""}
    ${e.invitados.length ? `<div class="t-fila">${svg("personas")}<div><div>${e.invitados.length} invitado${e.invitados.length === 1 ? "" : "s"}</div>
      ${e.invitados.map((i) => `<div class="t-invitado"><span class="marca">${marca[i.estado] || ""}</span>${esc(i.nombre || i.correo)}${i.organizador ? ' <span class="t-sub">· Organizador</span>' : ""}</div>`).join("")}</div></div>` : ""}
    ${e.descripcion ? `<div class="t-fila">${svg("texto")}<div class="t-desc">${e.descripcion.includes("<") ? limpiarHtml(e.descripcion) : enlazar(e.descripcion)}</div></div>` : ""}
    ${e.aviso_min != null ? `<div class="t-fila">${svg("aviso")}<div>${esc(textoAviso(e.aviso_min))}</div></div>` : ""}
    <div class="t-fila">${svg("calendario")}<div>${esc(cal?.nombre || e.calendario)}</div></div>
    ${e.mi_respuesta && !e.soy_organizador ? `<div class="t-respuesta"><span>¿Asistirás?</span>${["si", "no", "quizas"].map((r) =>
      `<button type="button" data-r="${r}" class="${e.mi_respuesta === r ? "elegida" : ""}">${{ si: "Sí", no: "No", quizas: "Quizás" }[r]}</button>`).join("")}</div>` : ""}`;
  t.hidden = false;
  ubicar(cerca);
  t.querySelector('[data-t="cerrar"]').addEventListener("click", () => cerrarTarjeta());
  t.querySelector('[data-t="editar"]')?.addEventListener("click", () => { cerrarTarjeta(); abrirEditor(e); });
  t.querySelector('[data-t="borrar"]')?.addEventListener("click", () => borrarEvento(e));
  t.querySelectorAll("[data-r]").forEach((b) => b.addEventListener("click", () => responder(e, b.dataset.r)));
}

function limpiarHtml(html) {   // las descripciones de Google traen HTML simple: solo texto y enlaces
  const doc = new DOMParser().parseFromString(html, "text/html");
  const salida = [];
  const recorrer = (n) => {
    for (const h of n.childNodes) {
      if (h.nodeType === 3) salida.push(esc(h.textContent));
      else if (h.nodeName === "BR") salida.push("<br>");
      else if (h.nodeName === "A" && /^https?:/i.test(h.getAttribute("href") || "")) salida.push(`<a href="${esc(h.getAttribute("href"))}" target="_blank" rel="noopener noreferrer">${esc(h.textContent)}</a>`);
      else { recorrer(h); if (["P", "DIV", "LI"].includes(h.nodeName)) salida.push("<br>"); }
    }
  };
  recorrer(doc.body);
  return salida.join("");
}

function textoAviso(min) {
  if (!min) return "Al comenzar";
  if (min % 1440 === 0) return `${min / 1440} día${min === 1440 ? "" : "s"} antes`;
  if (min % 60 === 0) return `${min / 60} hora${min === 60 ? "" : "s"} antes`;
  return `${min} minutos antes`;
}

async function borrarEvento(e) {
  let todos = false;
  if (e.recurrente) {
    todos = await preguntarSerie("Borrar evento recurrente");
    if (todos === null) return;
  }
  cerrarTarjeta();
  const antes = estado.eventos;
  estado.eventos = estado.eventos.filter((x) => (todos ? x.recurrente !== e.recurrente && x.id !== e.id : x.id !== e.id));
  pintar();
  try {
    await pedir(`/eventos/${encodeURIComponent(e.calendario)}/${encodeURIComponent(e.id)}?todos=${todos ? 1 : 0}`, { method: "DELETE" });
    avisar("Evento borrado.");
  } catch (error) {
    estado.eventos = antes;
    pintar();
    avisar(`No se pudo borrar: ${error.message}`);
  }
}

async function responder(e, respuesta) {
  const antes = e.mi_respuesta;
  e.mi_respuesta = respuesta;
  $("tarjeta").querySelectorAll("[data-r]").forEach((b) => b.classList.toggle("elegida", b.dataset.r === respuesta));
  try {
    const nuevo = await pedir(`/eventos/${encodeURIComponent(e.calendario)}/${encodeURIComponent(e.id)}/respuesta`, json("POST", { respuesta }));
    Object.assign(e, nuevo, { calendario: e.calendario });
    pintar();
  } catch (error) {
    e.mi_respuesta = antes;
    avisar(`No se pudo responder: ${error.message}`);
  }
}

// ---------------------------------------------------------------- crear rapido

function abrirRapida(borrador, cerca, alCerrar = null) {
  const cal = calendarioPrincipal();
  if (!cal) { avisar("No tienes ningún calendario donde puedas crear eventos."); alCerrar?.(); return; }
  cerrarTarjeta();
  const t = $("tarjeta");
  const e = { titulo: "", calendario: cal.id, todo_el_dia: borrador.todo_el_dia,
    inicio: borrador.todo_el_dia ? ymd(borrador.inicio) : borrador.inicio.toISOString(),
    fin: borrador.todo_el_dia ? ymd(borrador.fin) : borrador.fin.toISOString(), invitados: [] };
  t.innerHTML = `<div class="tarjeta-arriba"><button class="icono" data-t="cerrar" aria-label="Cerrar">${svg("cerrar")}</button></div>
    <form class="rapida"><input name="titulo" placeholder="Añade un título" autocomplete="off">
      <div class="t-sub">${esc(cuandoTexto(e))}</div><div class="t-sub">${esc(cal.nombre)}</div>
      <div class="rapida-botones"><button type="button" data-t="mas">Más opciones</button><button type="submit" class="boton-azul">Guardar</button></div></form>`;
  t.hidden = false;
  alCerrarTarjeta = alCerrar;
  ubicar(cerca);
  const form = t.querySelector("form");
  form.titulo.focus();
  t.querySelector('[data-t="cerrar"]').addEventListener("click", () => cerrarTarjeta());
  t.querySelector('[data-t="mas"]').addEventListener("click", () => { e.titulo = form.titulo.value; cerrarTarjeta(); abrirEditor(e, true); });
  form.addEventListener("submit", (ev) => { ev.preventDefault(); e.titulo = form.titulo.value; cerrarTarjeta(); crearEvento(e); });
}

async function crearEvento(datos) {
  const temporal = { ...datos, id: `tmp-${Date.now()}`, puede_editar: false, invitados: [], mi_respuesta: null, meet: null, ubicacion: datos.ubicacion || "",
    descripcion: datos.descripcion || "", titulo: datos.titulo || "(Sin título)" };
  estado.eventos.push(temporal);
  pintar();
  try {
    const nuevo = await pedir("/eventos", json("POST", datos));
    Object.assign(temporal, nuevo);
    pintar();
    avisar("Evento guardado.");
  } catch (error) {
    estado.eventos = estado.eventos.filter((x) => x !== temporal);
    pintar();
    avisar(`No se pudo guardar: ${error.message}`);
  }
}

// ---------------------------------------------------------------- editor completo

let editando = null;
function abrirEditor(e, nuevo = false) {
  editando = { e, nuevo };
  const f = $("editor");
  const ini = inicioDe(e), fin = finDe(e);
  f.titulo.value = e.titulo === "(Sin título)" ? "" : e.titulo || "";
  f.todo_el_dia.checked = Boolean(e.todo_el_dia);
  f.fecha_inicio.value = ymd(ini);
  f.fecha_fin.value = ymd(e.todo_el_dia ? sumarDias(fin, -1) : fin);
  f.hora_inicio.value = e.todo_el_dia ? "09:00" : hhmm(ini);
  f.hora_fin.value = e.todo_el_dia ? "10:00" : hhmm(fin);
  f.calendario.innerHTML = estado.calendarios.filter((c) => c.puede_editar).map((c) =>
    `<option value="${esc(c.id)}"${c.id === e.calendario ? " selected" : ""}>${esc(c.nombre)}</option>`).join("");
  f.calendario.disabled = !nuevo;
  f.invitados.value = (e.invitados || []).filter((i) => !i.yo).map((i) => i.correo).join(", ");
  f.meet.checked = false;
  f.meet.closest("label").hidden = Boolean(e.meet);
  f.ubicacion.value = e.ubicacion || "";
  f.descripcion.value = e.descripcion && e.descripcion.includes("<") ? new DOMParser().parseFromString(e.descripcion, "text/html").body.innerText : e.descripcion || "";
  f.aviso_min.value = e.aviso_min != null ? String(e.aviso_min) : nuevo ? "10" : "";
  $("editor-error").textContent = "";
  ajustarHoras();
  $("capa-editor").hidden = false;
  f.titulo.focus();
}
function ajustarHoras() {
  const f = $("editor");
  f.hora_inicio.hidden = f.hora_fin.hidden = f.todo_el_dia.checked;
}
$("editor").todo_el_dia.addEventListener("change", ajustarHoras);
$("editor-cerrar").addEventListener("click", () => { $("capa-editor").hidden = true; editando = null; });
$("editor").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  if (!editando) return;
  const f = $("editor");
  const todo = f.todo_el_dia.checked;
  let inicio, fin;
  if (todo) {
    inicio = f.fecha_inicio.value;
    fin = ymd(sumarDias(deYmd(f.fecha_fin.value || f.fecha_inicio.value), 1));
  } else {
    inicio = new Date(`${f.fecha_inicio.value}T${f.hora_inicio.value || "09:00"}`).toISOString();
    fin = new Date(`${f.fecha_fin.value || f.fecha_inicio.value}T${f.hora_fin.value || "10:00"}`).toISOString();
  }
  if (new Date(todo ? deYmd(fin) : fin) <= new Date(todo ? deYmd(inicio) : inicio)) {
    $("editor-error").textContent = "El final tiene que ser después del comienzo.";
    return;
  }
  const datos = {
    titulo: f.titulo.value.trim(), inicio, fin, todo_el_dia: todo,
    invitados: f.invitados.value.split(/[,;\s]+/).map((x) => x.trim()).filter((x) => x.includes("@")),
    ubicacion: f.ubicacion.value, descripcion: f.descripcion.value,
  };
  if (f.meet.checked) datos.meet = true;
  if (f.aviso_min.value !== "") datos.aviso_min = Number(f.aviso_min.value);
  const { e, nuevo } = editando;
  $("capa-editor").hidden = true;
  editando = null;
  if (nuevo) crearEvento({ ...datos, calendario: f.calendario.value });
  else {
    // conservar a los invitados que no se tocaron, incluida la propia persona
    const yo = (e.invitados || []).filter((i) => i.yo).map((i) => i.correo);
    if (datos.invitados.length || (e.invitados || []).length) datos.invitados = [...new Set([...yo, ...datos.invitados])];
    else delete datos.invitados;
    guardarCambio(e, datos);
  }
});

// ---------------------------------------------------------------- navegacion

function mover(direccion) {
  const pasos = { dia: 1, tres: 3, semana: 7, agenda: 30 };
  if (estado.vista === "mes") estado.fecha = new Date(estado.fecha.getFullYear(), estado.fecha.getMonth() + direccion, 1);
  else estado.fecha = sumarDias(estado.fecha, direccion * pasos[estado.vista]);
  render();
}
$("btn-ant").addEventListener("click", () => mover(-1));
$("btn-sig").addEventListener("click", () => mover(1));
$("btn-hoy").addEventListener("click", () => { estado.fecha = hoy(); render(); });
$("vistas").addEventListener("click", (e) => {
  const v = e.target.closest("[data-vista]")?.dataset.vista;
  if (!v) return;
  estado.vista = v;
  render();
});
function cerrarLado() { document.body.classList.remove("lado-abierto"); }
$("btn-menu").addEventListener("click", () => {
  if (esCelular()) document.body.classList.toggle("lado-abierto");
  else $("app").classList.toggle("sin-lado");
});
$("velo").addEventListener("click", cerrarLado);
function crearAhora() {
  const inicio = new Date(estado.fecha);
  const ahora = new Date();
  inicio.setHours(mismoDia(inicio, ahora) ? ahora.getHours() + 1 : 9, 0, 0, 0);
  cerrarLado();
  abrirEditor({ titulo: "", calendario: calendarioPrincipal()?.id, todo_el_dia: false, inicio: inicio.toISOString(),
    fin: new Date(+inicio + 3600000).toISOString(), invitados: [] }, true);
}
$("btn-crear").addEventListener("click", crearAhora);
$("btn-crear-flotante").addEventListener("click", crearAhora);
document.addEventListener("keydown", (e) => {
  if (e.target.closest?.("input, textarea, select, [contenteditable]")) { if (e.key === "Escape") e.target.blur(); return; }
  if (e.key === "Escape") { if (!$("capa-editor").hidden) $("capa-editor").hidden = true; else cerrarTarjeta(); return; }
  const teclas = { d: "dia", w: "semana", s: "semana", m: "mes", a: "agenda" };
  if (teclas[e.key]) { estado.vista = esCelular() && teclas[e.key] === "semana" ? "tres" : teclas[e.key]; render(); }
  else if (e.key === "t") $("btn-hoy").click();
  else if (e.key === "j" || e.key === "n") mover(1);
  else if (e.key === "k" || e.key === "p") mover(-1);
  else if (e.key === "c") crearAhora();
});
document.addEventListener("pointerdown", (e) => {
  if ($("tarjeta").hidden || $("tarjeta").contains(e.target) || e.target.closest(".ev, .chip, .ag-evento, .col, .mes-celda")) return;
  cerrarTarjeta();
});
window.addEventListener("resize", () => { if (esCelular() && estado.vista === "semana") { estado.vista = "tres"; render(); } });

// ---------------------------------------------------------------- arranque

async function arrancar() {
  try {
    const datos = await pedir("/estado");
    if (!datos.conectado) { mostrarConectar(datos.reconectar); return; }
    $("cuenta").textContent = datos.cuenta;
    if (!datos.lista) { $("franja").hidden = false; document.body.classList.add("con-franja"); }
    const { calendarios } = await pedir("/calendarios");
    estado.calendarios = calendarios;
    pintarCalendarios();
    render();
    setInterval(() => { if (!estado.ocupado && $("capa-editor").hidden && $("tarjeta").hidden && document.visibilityState === "visible") cargarEventos(true); }, 60000);
    setInterval(() => { const linea = document.querySelector(".ahora"); if (linea) linea.style.top = `${minutosDelDia(new Date()) / 60 * H}px`; }, 60000);
  } catch (error) {
    if ($("conectar").hidden) $("centro").innerHTML = `<div class="ag-vacio">${esc(error.message)}</div>`;
  }
}
arrancar();
