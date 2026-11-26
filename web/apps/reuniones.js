/* Reuniones grabadas por el bot de Meet: lista a la izquierda, detalle a la derecha
   (en el celular, una debajo de la otra). Vive dentro de la estructura comun (/#reuniones).
   Un enlace /apps/reuniones#<id> (el del WhatsApp) deja el id en sessionStorage antes de
   que comun.js redirija a la estructura, y aqui se abre al cargar. */
import { EMBEBIDO, enEstructura } from "./comun.js";
import * as grabadora from "./grabadora.js";

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

const estructura = enEstructura("reuniones", { refrescar: () => { cargarLista(); cargarEnCurso(); }, abrir: (id) => abrir(id) });

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
  sub.textContent = `${hora(x.inicio)} · ${ESTADOS[x.estado] || x.estado}` + (x.tipo === "presencial" ? " · en persona" : "")
    + (x.incompleta ? " · grabación incompleta" : "");
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

  const genericas = x.hablantes.filter((v) => /^(Hablante|Participante) /.test(v.etiqueta));
  if (genericas.length) {
    const voces = document.createElement("div");
    voces.className = "voces";
    for (const v of genericas) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "voz";
      b.textContent = v.nombre;
      b.title = v.nombre === v.etiqueta ? "Tocar para poner el nombre" : `${v.etiqueta} · tocar para cambiar`;
      b.addEventListener("click", async () => {
        const a = prompt(`¿Quién es «${v.etiqueta}»? (vacío = sin nombre)`, v.nombre === v.etiqueta ? "" : v.nombre);
        if (a === null) return;
        const r = await fetch(`/api/reuniones/${encodeURIComponent(id)}/nombres`, {
          method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ de: v.etiqueta, a }) });
        if (r.ok) abrir(id);
      });
      voces.append(b);
    }
    seccion(caja, "Quién habló (toca para corregir)", voces);
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

// ---------------------------------------------------------------- presencial
// El teléfono o la computadora graban la reunión en la sala (grabadora.js).
const NOTA = {
  web: "Deja la pantalla prendida y Jarvis abierto: si bloqueas el teléfono, la grabación se pausa.",
  nativo: "Puedes bloquear el teléfono: sigue grabando (lo ves en la notificación).",
};

function pintarPresencial(e = grabadora.estado()) {
  $("presencial-empezar").hidden = e.grabando;
  $("presencial-grabando").hidden = !e.grabando;
  if (!e.grabando) return;
  $("presencial-titulo").textContent = e.titulo;
  $("presencial-reloj").textContent = desde(new Date(Date.now() - e.segundos * 1000).toISOString());
  $("presencial-nota").textContent = (e.nativo ? NOTA.nativo : NOTA.web)
    + (e.pausaS ? ` Estuvo en pausa ${Math.max(1, Math.round(e.pausaS / 60))} min.` : "");
}

function prepararPresencial() {
  if (!grabadora.puedeGrabar()) {
    $("presencial-empezar").disabled = true;
    $("presencial-mensaje").textContent = "Este navegador no puede grabar audio.";
  }
  $("presencial-empezar").addEventListener("click", async () => {
    const titulo = prompt("¿Cómo se llama la reunión? (opcional)", "");
    if (titulo === null) return;
    const boton = $("presencial-empezar");
    boton.disabled = true;
    $("presencial-mensaje").textContent = "Pidiendo el micrófono…";
    try {
      await grabadora.empezar(titulo);
      $("presencial-mensaje").textContent = "";
      cargarEnCurso();
    } catch (error) {
      $("presencial-mensaje").textContent = error?.name === "NotAllowedError"
        ? "Jarvis no tiene permiso para usar el micrófono. Actívalo en el navegador y vuelve a intentar."
        : error?.message || "No pude empezar la grabación.";
    } finally {
      boton.disabled = !grabadora.puedeGrabar();
    }
  });
  $("presencial-terminar").addEventListener("click", async () => {
    if (!confirm("¿Terminar la grabación? Jarvis la resume en unos minutos.")) return;
    $("presencial-terminar").disabled = true;
    await grabadora.terminar("usuario");
    $("presencial-terminar").disabled = false;
    $("presencial-mensaje").textContent = "Listo. Te aviso cuando esté el resumen.";
    setTimeout(() => { cargarEnCurso(); cargarLista(); }, 3000);
  });
  grabadora.alCambiar((e) => { pintarPresencial(e); cargarEnCurso(); });
  pintarPresencial();
  setInterval(() => {
    const e = grabadora.estado();
    if (!e.grabando) return;
    pintarPresencial(e);
    $("presencial-nivel").style.transform = `scaleX(${grabadora.nivel().toFixed(2)})`;
  }, 250);
}

// ---------------------------------------------------------------- en curso
// Lo que el bot tiene agendado, esperando entrar o grabando: cada 15 s se pide de nuevo
// y el reloj de "grabando hace" corre cada segundo sin pedir nada.
let todasEnCurso = [];
const desde = (iso) => {
  const s = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  const h = Math.floor(s / 3600);
  return h ? `${h} h ${String(Math.floor(s / 60) % 60).padStart(2, "0")} min` : mmss(s);
};

function textoEstado(x) {
  if (x.estado === "grabando" && x.grabando_desde)
    return `${x.tipo === "presencial" ? "En persona · " : ""}Grabando · ${desde(x.grabando_desde)}`;
  if (x.estado === "esperando") return "Esperando que lo admitan";
  return `Agendada · ${new Date(x.inicio).toLocaleTimeString("es", { hour: "numeric", minute: "2-digit" })}`;
}

function pintarEnCurso() {
  const caja = $("en-curso");
  // La que se graba en este aparato ya tiene su tarjeta grande arriba.
  const aqui = grabadora.estado().id;
  const enCurso = todasEnCurso.filter((x) => x.id !== aqui);
  caja.hidden = !enCurso.length;
  caja.replaceChildren();
  if (!enCurso.length) return;
  const t = document.createElement("h2");
  t.textContent = enCurso.some((x) => x.estado === "grabando") ? "Grabando ahora" : "Próximas del bot";
  caja.append(t);
  for (const x of enCurso) {
    const fila = document.createElement("div");
    fila.className = "en-curso-fila" + (x.estado === "grabando" ? " vivo" : "");
    const info = document.createElement("div");
    const nombre = document.createElement("strong");
    nombre.textContent = x.titulo;
    const estado = document.createElement("span");
    estado.className = "estado";
    estado.dataset.id = x.id;
    estado.textContent = textoEstado(x);
    info.append(nombre, estado);
    const boton = document.createElement("button");
    boton.type = "button";
    const presencial = x.tipo === "presencial";
    boton.textContent = presencial ? "Terminar" : x.estado === "agendada" ? "No grabar" : "Sacar al bot";
    boton.addEventListener("click", async () => {
      const pregunta = presencial
        ? `¿Terminar la grabación de «${x.titulo}»? Lo grabado hasta ahora se resume igual.`
        : x.estado === "agendada"
          ? `¿Cancelar la grabación de «${x.titulo}»?`
          : `¿Sacar al bot de «${x.titulo}»? Sale para todos; lo grabado hasta ahora se resume igual.`;
      if (!confirm(pregunta)) return;
      boton.disabled = true;
      if (presencial && grabadora.estado().id === x.id) {   // se graba en este aparato
        await grabadora.terminar("usuario");
        estado.textContent = "Listo. Te aviso cuando esté el resumen.";
      } else {   // en otro aparato: se entera al subir el próximo pedazo
        const r = await fetch(`/api/reuniones/${encodeURIComponent(x.id)}/sacar`, { method: "POST" });
        estado.textContent = r.ok ? (await r.json()).mensaje : "No se pudo, inténtalo otra vez.";
      }
      setTimeout(() => { cargarEnCurso(); cargarLista(); }, 4000);
    });
    fila.append(info, boton);
    caja.append(fila);
  }
}

async function cargarEnCurso() {
  try {
    const r = await fetch("/api/reuniones/en-curso");
    todasEnCurso = r.ok ? (await r.json()).reuniones : [];
  } catch { /* sin red: se reintenta en la próxima vuelta */ }
  pintarEnCurso();
}

setInterval(() => {
  for (const x of todasEnCurso) {
    const e = document.querySelector(`.en-curso .estado[data-id="${x.id}"]`);
    if (e && x.estado === "grabando" && x.grabando_desde) e.textContent = textoEstado(x);
  }
}, 1000);
setInterval(cargarEnCurso, 15000);

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
    if (r.ok) { form.reset(); cargarLista(); cargarEnCurso(); }
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
  await Promise.all([cargarLista(), cargarEnCurso()]);
  let inicial = null;
  try { inicial = sessionStorage.getItem(PENDIENTE); sessionStorage.removeItem(PENDIENTE); } catch { /* nada */ }
  if (inicial) abrir(inicial);
}

prepararPresencial();
