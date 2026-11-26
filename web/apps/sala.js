/* La página del participante de una sala presencial (/sala/<codigo>).

   Se entra sin cuenta (con el nombre) o con la sesión de Jarvis (el nombre sale de la
   cuenta). Una vez dentro, el teléfono solo manda cuánto oye su micrófono (niveles.js)
   hasta que la reunión termina. Lo que se necesita para volver a entrar al recargar
   queda en sessionStorage. */
import { EmisorNiveles, abrirMicrofonoParaNiveles } from "./niveles.js";

const $ = (id) => document.getElementById(id);
const codigo = location.pathname.split("/").filter(Boolean).pop();
const CLAVE = `jarvis-sala-${codigo}`;
let emisor = null, stream = null, pantalla = null;

function mostrar(seccion) {
  for (const id of ["entrar", "dentro", "fin"]) $(id).hidden = id !== seccion;
}

function terminar(texto = "La reunión terminó. ¡Gracias!") {
  emisor?.parar();
  stream?.getTracks().forEach((t) => t.stop());
  try { pantalla?.release(); } catch { /* nada */ }
  try { sessionStorage.removeItem(CLAVE); } catch { /* nada */ }
  $("texto-fin").textContent = texto;
  mostrar("fin");
}

async function mantenerPantalla() {
  try { pantalla = await navigator.wakeLock?.request("screen"); } catch { /* sin Wake Lock: sigue igual */ }
}

async function adentro(sala) {
  stream = await abrirMicrofonoParaNiveles();
  emisor = new EmisorNiveles(stream, sala, { alParar: (por) => terminar(por === "token"
    ? "Esta entrada ya no vale. Vuelve a abrir el link para entrar otra vez." : undefined) });
  emisor.empezar();
  $("yo").textContent = sala.nombre;
  mostrar("dentro");
  mantenerPantalla();
  setInterval(() => {
    if (emisor) $("nivel").style.transform = `scaleX(${Math.min(1, emisor.ultimo * 6).toFixed(2)})`;
  }, 150);
}

document.addEventListener("visibilitychange", async () => {
  if (document.visibilityState !== "visible" || !emisor) return;
  mantenerPantalla();
  if (stream.getAudioTracks().some((t) => t.readyState === "live")) return;
  // El navegador cortó el micrófono (pantalla bloqueada): se vuelve a abrir.
  try {
    stream = await abrirMicrofonoParaNiveles();
    emisor.cambiarMicrofono(stream);
    $("mensaje-dentro").textContent = "";
  } catch {
    $("mensaje-dentro").textContent = "Se perdió el micrófono. Recarga la página para volver a entrar.";
  }
});

async function iniciar() {
  let datos;
  try {
    const r = await fetch(`/api/salas/${encodeURIComponent(codigo)}`);
    if (r.status === 404) { $("titulo").textContent = "Esta sala no existe"; mostrar("fin"); $("texto-fin").textContent = "Revisa el link que te pasaron."; return; }
    datos = await r.json();
  } catch {
    $("titulo").textContent = "Sin conexión";
    return;
  }
  $("titulo").textContent = datos.titulo;
  document.title = `${datos.titulo} · Jarvis`;
  if (!datos.abierta) { terminar("Esta reunión ya terminó."); return; }

  let guardada = null;
  try { guardada = JSON.parse(sessionStorage.getItem(CLAVE) || "null"); } catch { /* nada */ }
  if (guardada) {   // recargó la página: sigue con la misma entrada
    try { await adentro(guardada); return; } catch { /* se pide entrar de nuevo */ }
  }
  if (datos.nombre) {
    $("nombre").value = datos.nombre;
    $("caja-nombre").hidden = true;
  }
  mostrar("entrar");
}

$("boton-entrar").addEventListener("click", async () => {
  const boton = $("boton-entrar");
  const nombre = $("nombre").value.trim();
  if (!nombre) { $("mensaje").textContent = "Escribe tu nombre."; $("nombre").focus(); return; }
  boton.disabled = true;
  $("mensaje").textContent = "";
  try {
    stream = await abrirMicrofonoParaNiveles();   // primero el permiso: sin micrófono no sirve entrar
    stream.getTracks().forEach((t) => t.stop());
    const r = await fetch(`/api/salas/${encodeURIComponent(codigo)}/unirse`, {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ nombre }) });
    const x = await r.json();
    if (!r.ok) {
      if (r.status === 409) { terminar("Esta reunión ya terminó."); return; }
      throw new Error(x.error || "No pude entrar.");
    }
    const sala = { codigo, ...x };
    try { sessionStorage.setItem(CLAVE, JSON.stringify(sala)); } catch { /* nada */ }
    await adentro(sala);
  } catch (error) {
    $("mensaje").textContent = error?.name === "NotAllowedError"
      ? "Necesitas permitir el micrófono para entrar (solo se usa para saber cuándo hablas)."
      : error?.message || "No pude entrar. Inténtalo otra vez.";
  } finally {
    boton.disabled = false;
  }
});

iniciar();
