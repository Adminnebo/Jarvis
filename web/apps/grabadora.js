/* Grabar una reunión presencial y subirla en pedazos de 5 min.

   En el navegador: un MediaRecorder NUEVO por pedazo (los fragmentos de timeslice no
   se pueden leer solos, solo el primero trae cabecera). Cada pedazo se guarda primero
   en IndexedDB y se borra al subirse (200 o 409): un corte de red no pierde nada y lo
   pendiente se sube al volver a abrir Reuniones.
   En el APK de Android lo hace el plugin nativo GrabadoraPresencial, que sigue con la
   pantalla apagada y sube él mismo; aquí solo se le pasa la reunión y se lee su estado.
   Ver docs/superpowers/specs/2026-11-26-reuniones-presenciales-design.md. */

import { EmisorNiveles, abrirMicrofonoParaNiveles } from "./niveles.js";

const TIPOS = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"];
const BD = "jarvis-grabadora";
const PRUEBA_S = Number(new URLSearchParams(location.search).get("pedazo_s")) || 0;   // ?pedazo_s=10 para probar

const nativo = () => {
  const C = window.Capacitor;
  return C?.isNativePlatform?.() ? C.Plugins?.GrabadoraPresencial || null : null;
};

export const puedeGrabar = () => !!(nativo() || (window.MediaRecorder && navigator.mediaDevices?.getUserMedia));

// ---------------------------------------------------------------- IndexedDB
function abrirBD() {
  return new Promise((ok, mal) => {
    const p = indexedDB.open(BD, 1);
    p.onupgradeneeded = () => {
      p.result.createObjectStore("reuniones", { keyPath: "id" });
      p.result.createObjectStore("pedazos", { keyPath: ["reunion", "n"] });
    };
    p.onsuccess = () => ok(p.result);
    p.onerror = () => mal(p.error);
  });
}
async function tx(tienda, modo, fn) {
  const bd = await abrirBD();
  return new Promise((ok, mal) => {
    const t = bd.transaction(tienda, modo);
    const pedido = fn(t.objectStore(tienda));
    t.oncomplete = () => ok(pedido?.result);
    t.onerror = () => mal(t.error);
  });
}
const poner = (tienda, valor) => tx(tienda, "readwrite", (s) => s.put(valor));
const quitar = (tienda, clave) => tx(tienda, "readwrite", (s) => s.delete(clave));
const todos = (tienda) => tx(tienda, "readonly", (s) => s.getAll());

// ---------------------------------------------------------------- estado
let g = null;   // la grabación en curso de esta pestaña
const oyentes = new Set();
export const alCambiar = (fn) => { oyentes.add(fn); return () => oyentes.delete(fn); };
const avisar = () => oyentes.forEach((fn) => { try { fn(estado()); } catch { /* un oyente roto no frena */ } });

export function estado() {
  if (!g) return { grabando: false };
  return { grabando: true, id: g.id, titulo: g.titulo, nativo: !!g.nativo, sala: g.sala || null,
           segundos: Math.max(0, Math.round((Date.now() - g.inicioMs) / 1000)), pausaS: g.pausaS || 0 };
}

// ---------------------------------------------------------------- micrófono y muestras
let microfono = null;   // abierto antes de grabar (calibración): lo reusa la grabación

/** Abre el micrófono (lo pide al navegador una sola vez) y prepara la barrita. En una
 *  sala va sin control de ganancia: si no, emparejaría a quien habla lejos y cerca. */
export async function abrirMicrofono({ sala = false } = {}) {
  if (!microfono || !microfono.getAudioTracks().some((t) => t.readyState === "live")) {
    microfono = sala ? await abrirMicrofonoParaNiveles() : await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    prepararNivel(microfono);
  }
  return microfono;
}

export function soltarMicrofono() {
  microfono?.getTracks().forEach((t) => t.stop());
  microfono = null;
}

/** Graba `segundos` con el micrófono abierto y devuelve el audio (la muestra de una voz). */
export async function grabarMuestra(segundos = 6) {
  const stream = await abrirMicrofono();
  const tipo = TIPOS.find((t) => window.MediaRecorder.isTypeSupported?.(t)) || "";
  const rec = new MediaRecorder(stream, tipo ? { mimeType: tipo } : undefined);
  const partes = [];
  rec.ondataavailable = (e) => { if (e.data?.size) partes.push(e.data); };
  const listo = new Promise((ok) => { rec.onstop = ok; });
  rec.start();
  await new Promise((ok) => setTimeout(ok, segundos * 1000));
  rec.stop();
  await listo;
  return new Blob(partes, { type: (rec.mimeType || tipo || "audio/webm").split(";")[0] });
}

async function subirMuestras(id, token, muestras) {
  const fallidas = [];
  for (const m of muestras) {
    try {
      const r = await fetch(`/api/reuniones/${id}/voces?nombre=${encodeURIComponent(m.nombre)}`, {
        method: "POST", headers: { authorization: `Bearer ${token}`, "content-type": m.blob.type }, body: m.blob });
      if (!r.ok) fallidas.push(m.nombre);
    } catch { fallidas.push(m.nombre); }
  }
  return fallidas;
}

// ---------------------------------------------------------------- empezar
/** muestras: [{nombre, blob}] de la calibración (vacío = sin calibrar).
 *  sala: cada participante entra con su teléfono (salas.py); este también manda niveles.
 *  En el APK una sala graba desde la página: el servicio nativo no deja medir a la vez. */
export async function empezar(titulo = "", { muestras = [], sala = false } = {}) {
  if (g) return estado();
  const plugin = sala ? null : nativo();
  let stream = null;
  if (!plugin) stream = await abrirMicrofono({ sala });   // el micrófono primero: si lo niegan, no se crea la reunión
  const r = await fetch("/api/reuniones/presencial", {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ titulo, sala }) });
  if (!r.ok) {
    soltarMicrofono();
    throw new Error("No pude empezar la grabación. Inténtalo otra vez.");
  }
  const x = await r.json();
  const pedazoS = PRUEBA_S || x.pedazo_s;
  const fallidas = muestras.length ? await subirMuestras(x.id, x.token, muestras) : [];
  if (plugin) {
    soltarMicrofono();   // el servicio nativo necesita el micrófono libre
    try {
      await plugin.iniciar({ reunionId: x.id, token: x.token, titulo: x.titulo, base: location.origin,
                             pedazoS, maxS: x.max_s });
    } catch (error) {   // sin permiso de micrófono en Android: la reunión no sirve
      await fetch(`/api/reuniones/${x.id}/sacar`, { method: "POST" }).catch(() => {});
      throw new Error("Jarvis necesita permiso de micrófono para grabar.");
    }
    g = { id: x.id, titulo: x.titulo, inicioMs: Date.now(), nativo: true };
    vigilarNativo();
    avisar();
    return { ...estado(), fallidas };
  }
  await poner("reuniones", { id: x.id, token: x.token, titulo: x.titulo, terminada: false });
  g = { id: x.id, token: x.token, titulo: x.titulo, inicioMs: Date.now(), stream, n: 0, pedazoS, maxS: x.max_s };
  microfono = null;   // ahora es de la grabación: terminar() lo cierra
  if (x.sala) {
    g.sala = { codigo: x.sala, link: x.link };
    g.emisor = new EmisorNiveles(stream, { codigo: x.sala, participante: x.participante, token: x.participante_token,
                                           ahora_ms: x.ahora_ms });
    g.emisor.empezar();
  }
  nuevoPedazo();
  mantenerPantalla();
  avisar();
  return { ...estado(), fallidas };
}

function nuevoPedazo() {
  const tipo = TIPOS.find((t) => window.MediaRecorder.isTypeSupported?.(t)) || "";
  const rec = new MediaRecorder(g.stream, { ...(tipo ? { mimeType: tipo } : {}), audioBitsPerSecond: 24000 });
  const id = g.id;
  const n = ++g.n;
  const inicio_s = Math.round((Date.now() - g.inicioMs) / 1000);
  const partes = [];
  rec.ondataavailable = (e) => { if (e.data?.size) partes.push(e.data); };
  rec.detenido = new Promise((listo) => {
    rec.onstop = async () => {
      const blob = new Blob(partes, { type: (rec.mimeType || tipo || "audio/webm").split(";")[0] });
      if (blob.size) {
        await poner("pedazos", { reunion: id, n, inicio_s, blob });
        subirPendientes();
      }
      listo();
    };
  });
  rec.start();
  g.rec = rec;
  g.corte = setTimeout(rotar, g.pedazoS * 1000);
}

function rotar() {
  if (!g || g.nativo) return;
  if ((Date.now() - g.inicioMs) / 1000 >= g.maxS) { terminar("maximo"); return; }
  const viejo = g.rec;
  nuevoPedazo();          // el nuevo arranca antes de cortar el viejo: casi sin hueco
  try { viejo.stop(); } catch { /* ya estaba parado */ }
}

// ---------------------------------------------------------------- pantalla, pausas y nivel
async function mantenerPantalla() {
  try { g.wake = await navigator.wakeLock?.request("screen"); } catch { /* sin Wake Lock: sigue igual */ }
}

document.addEventListener("visibilitychange", async () => {
  if (!g || g.nativo) return;
  if (document.visibilityState === "hidden") { g.ocultoDesde = Date.now(); return; }
  mantenerPantalla();
  const vivo = g.stream.getAudioTracks().some((t) => t.readyState === "live");
  if (vivo) return;
  // El navegador cortó el micrófono (pantalla bloqueada, otra app): sigue en un pedazo nuevo.
  clearTimeout(g.corte);
  try { if (g.rec.state !== "inactive") g.rec.stop(); } catch { /* ya parado */ }
  g.pausaS = (g.pausaS || 0) + Math.round((Date.now() - (g.ocultoDesde || Date.now())) / 1000);
  try {
    g.stream = await abrirMicrofono({ sala: !!g.sala });
    microfono = null;
    g.emisor?.cambiarMicrofono(g.stream);
    nuevoPedazo();
  } catch {
    terminar("usuario");
  }
  avisar();
});

window.addEventListener("beforeunload", (e) => {
  if (g && !g.nativo) { e.preventDefault(); e.returnValue = ""; }
});

let analizador = null;
function prepararNivel(stream) {
  try {
    const ctx = new AudioContext();
    ctx.resume?.().catch(() => {});   // nace suspendido si se crea después de un await
    analizador = ctx.createAnalyser();
    analizador.fftSize = 512;
    ctx.createMediaStreamSource(stream).connect(analizador);
  } catch { analizador = null; }
}
/** 0..1: cuánto oye el micrófono ahora (para la barrita). */
export function nivel() {
  if (!analizador) return 0;
  const datos = new Uint8Array(analizador.fftSize);
  analizador.getByteTimeDomainData(datos);
  let suma = 0;
  for (const v of datos) suma += ((v - 128) / 128) ** 2;
  return Math.min(1, Math.sqrt(suma / datos.length) * 4);
}

// ---------------------------------------------------------------- terminar
export async function terminar(motivo = "usuario") {
  if (!g) return;
  const actual = g;
  g = null;
  if (actual.nativo) {
    await nativo()?.terminar().catch(() => {});
    avisar();
    return;
  }
  clearTimeout(actual.corte);
  actual.emisor?.parar();
  const listo = actual.rec?.detenido;
  try { if (actual.rec.state !== "inactive") actual.rec.stop(); } catch { /* ya parado */ }
  await listo;
  actual.stream.getTracks().forEach((t) => t.stop());
  try { await actual.wake?.release(); } catch { /* nada */ }
  const guardada = (await todos("reuniones")).find((x) => x.id === actual.id);
  if (guardada) await poner("reuniones", { ...guardada, terminada: true, motivo });
  avisar();
  await subirPendientes();
}

// ---------------------------------------------------------------- subir
let subiendo = false, otraVez = false, espera = 5000, reintento = null;

function reintentar() {
  clearTimeout(reintento);
  reintento = setTimeout(subirPendientes, espera);
  espera = Math.min(espera * 2, 60000);
}

export async function subirPendientes() {
  if (subiendo) { otraVez = true; return; }
  subiendo = true;
  try {
    const reuniones = Object.fromEntries((await todos("reuniones")).map((r) => [r.id, r]));
    const pedazos = (await todos("pedazos")).sort((a, b) => a.n - b.n);
    for (const p of pedazos) {
      const r = reuniones[p.reunion];
      if (!r) { await quitar("pedazos", [p.reunion, p.n]); continue; }
      let resp;
      try {
        resp = await fetch(`/api/reuniones/${p.reunion}/audio?n=${p.n}&inicio_s=${p.inicio_s}`, {
          method: "POST", headers: { authorization: `Bearer ${r.token}`, "content-type": p.blob.type }, body: p.blob });
      } catch { reintentar(); return; }
      if (resp.status === 401 || resp.status === 404) { await olvidar(p.reunion); continue; }
      if (!resp.ok && resp.status !== 409) { reintentar(); return; }
      await quitar("pedazos", [p.reunion, p.n]);
      const cuerpo = resp.ok ? await resp.json().catch(() => ({})) : {};
      if (cuerpo.parar && g?.id === p.reunion) terminar("sacada");
    }
    espera = 5000;
    const quedan = new Set((await todos("pedazos")).map((p) => p.reunion));
    for (const r of Object.values(reuniones)) {
      if (!r.terminada || quedan.has(r.id)) continue;
      try {
        const resp = await fetch(`/api/reuniones/${r.id}/eventos`, {
          method: "POST", headers: { authorization: `Bearer ${r.token}`, "content-type": "application/json" },
          body: JSON.stringify({ tipo: "terminado", motivo: r.motivo || "usuario" }) });
        if (resp.ok || resp.status === 401) await quitar("reuniones", r.id);
        else reintentar();
      } catch { reintentar(); }
    }
  } finally {
    subiendo = false;
    if (otraVez) { otraVez = false; subirPendientes(); }
  }
}

async function olvidar(reunion) {
  for (const p of await todos("pedazos")) if (p.reunion === reunion) await quitar("pedazos", [p.reunion, p.n]);
  await quitar("reuniones", reunion);
}

window.addEventListener("online", () => subirPendientes());

// ---------------------------------------------------------------- APK
function vigilarNativo() {
  const plugin = nativo();
  if (!plugin) return;
  const vuelta = setInterval(async () => {
    const e = await plugin.estado().catch(() => null);
    if (!e?.grabando) { clearInterval(vuelta); g = null; avisar(); }
  }, 2000);
}

// ---------------------------------------------------------------- al cargar
(async () => {
  const plugin = nativo();
  if (plugin) {   // la app se cerró y se volvió a abrir mientras el servicio graba
    const e = await plugin.estado().catch(() => null);
    if (e?.grabando) {
      g = { id: e.reunionId, titulo: e.titulo, inicioMs: Date.now() - e.segundos * 1000, nativo: true };
      vigilarNativo();
      avisar();
    }
    return;
  }
  try {
    // Una grabación de una pestaña que se cerró o recargó no se puede seguir: se cierra con lo que hay.
    for (const r of await todos("reuniones")) {
      if (!r.terminada) await poner("reuniones", { ...r, terminada: true, motivo: "usuario" });
    }
    subirPendientes();
  } catch { /* sin IndexedDB (modo privado viejo): no hay nada pendiente */ }
})();
