/* Reuniones grabadas por el bot de Meet: lista a la izquierda, detalle a la derecha
   (en el celular, una debajo de la otra). Vive dentro de la estructura comun (/#reuniones).
   Un enlace /apps/reuniones#<id> (el del WhatsApp) deja el id en sessionStorage antes de
   que comun.js redirija a la estructura, y aqui se abre al cargar. */
import { EMBEBIDO, enEstructura } from "./comun.js";

const PENDIENTE = "jarvis-reunion-abrir";
if (!EMBEBIDO && location.hash.length > 1) {
  try { sessionStorage.setItem(PENDIENTE, location.hash.slice(1)); } catch { /* sin storage: abre la lista */ }
}

const $ = (id) => document.getElementById(id);
const ESTADOS = {
  propuesta: "Sin pedir", agendada: "Agendada", esperando: "Esperando que lo admitan", grabando: "Grabando",
  procesando: "Procesando", lista: "Lista", rechazada: "No lo admitieron", fallida: "No pudo entrar",
  cancelada: "Cancelada", sin_bot: "Sin bot libre",
};
const hora = (iso) => new Date(iso).toLocaleString("es", { dateStyle: "medium", timeStyle: "short" });
const mmss = (s) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
let abierta = null;

const estructura = enEstructura("reuniones", { refrescar: () => cargarLista(), abrir: (id) => abrir(id) });

async function cargarLista() {
  const r = await fetch("/api/reuniones");
  const { reuniones = [] } = r.ok ? await r.json() : {};
  const lista = $("lista");
  lista.replaceChildren();
  if (!reuniones.length) {
    lista.innerHTML = '<p class="vacio">Todavía no hay reuniones grabadas. Actívalas en Integraciones o con el botón Grabar del aviso de cada reunión.</p>';
    return;
  }
  for (const x of reuniones) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "fila" + (x.id === abierta ? " activa" : "");
    b.dataset.id = x.id;
    const t = document.createElement("strong");
    t.textContent = x.titulo;
    const d = document.createElement("span");
    d.textContent = `${hora(x.inicio)} · ${ESTADOS[x.estado] || x.estado}`;
    b.append(t, d);
    b.addEventListener("click", () => abrir(x.id));
    lista.append(b);
  }
}

function seccion(caja, titulo, nodo) {
  const s = document.createElement("section");
  const h = document.createElement("h2");
  h.textContent = titulo;
  s.append(h, nodo);
  caja.append(s);
}

async function abrir(id) {
  abierta = id;
  document.querySelectorAll(".fila").forEach((f) => f.classList.toggle("activa", f.dataset.id === id));
  const caja = $("detalle");
  const r = await fetch(`/api/reuniones/${encodeURIComponent(id)}`);
  if (!r.ok) {
    caja.innerHTML = '<p class="vacio">No encontré esa reunión.</p>';
    estructura.contexto(null);
    return;
  }
  const x = await r.json();
  caja.replaceChildren();
  const h = document.createElement("h1");
  h.textContent = x.titulo;
  const sub = document.createElement("p");
  sub.className = "sub";
  sub.textContent = `${hora(x.inicio)} · ${ESTADOS[x.estado] || x.estado}` + (x.incompleta ? " · grabación incompleta" : "");
  caja.append(h, sub);
  estructura.contexto(`Reuniones: reunión grabada «${x.titulo}» del ${hora(x.inicio)}, id ${x.id}`, x.titulo);
  if (x.estado !== "lista") return;

  const resumen = document.createElement("p");
  resumen.textContent = x.resumen || "";
  seccion(caja, "Resumen", resumen);

  if (x.tareas.length) {
    const ul = document.createElement("ul");
    for (const t of x.tareas) {
      const li = document.createElement("li");
      li.textContent = `${t.quien || "?"}: ${t.que || ""}` + (t.cuando ? ` (${t.cuando})` : "");
      ul.append(li);
    }
    seccion(caja, "Tareas", ul);
  }

  if (!x.audio_borrado && x.pedazos.length) {
    const audio = document.createElement("audio");
    audio.controls = true;
    audio.preload = "none";
    let actual = 0;
    const cargar = async (i) => {
      actual = i;
      const p = await fetch(`/api/reuniones/${encodeURIComponent(id)}/audio/${x.pedazos[i]}`);
      if (p.ok) audio.src = (await p.json()).url;
    };
    audio.addEventListener("ended", async () => {
      if (actual + 1 < x.pedazos.length) { await cargar(actual + 1); audio.play(); }
    });
    await cargar(0);
    seccion(caja, x.pedazos.length > 1 ? `Audio (${x.pedazos.length} partes de 5 min, siguen solas)` : "Audio", audio);
  }

  const texto = document.createElement("div");
  texto.className = "transcripcion";
  for (const l of x.transcripcion) {
    const p = document.createElement("p");
    const q = document.createElement("b");
    q.textContent = `${mmss(l.t)} ${l.quien}: `;
    p.append(q, document.createTextNode(l.texto));
    texto.append(p);
  }
  seccion(caja, "Transcripción", texto);
}

$("grabar-link").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  const boton = form.querySelector("button");
  const mensaje = $("mensaje-link");
  boton.disabled = true;
  mensaje.textContent = "Mandando el bot…";
  try {
    const r = await fetch("/api/reuniones/grabar-link", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ url: form.url.value.trim() }),
    });
    const datos = await r.json();
    mensaje.textContent = r.ok ? `${datos.mensaje} Admítelo cuando pida entrar.` : datos.mensaje;
    mensaje.classList.toggle("mal", !r.ok);
    if (r.ok) { form.reset(); cargarLista(); }
  } catch {
    mensaje.textContent = "No se pudo, inténtalo otra vez.";
    mensaje.classList.add("mal");
  } finally {
    boton.disabled = false;
  }
});

// Suelta (fuera de la estructura) la página ya se está yendo a /#reuniones: si siguiera,
// podría leer y borrar el id pendiente antes que la vista de verdad (pasaba en celular).
if (EMBEBIDO) {
  await cargarLista();
  let inicial = null;
  try { inicial = sessionStorage.getItem(PENDIENTE); sessionStorage.removeItem(PENDIENTE); } catch { /* nada */ }
  if (inicial) abrir(inicial);
}
