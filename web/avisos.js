/* Campanita: cuántos avisos sin ver (cada 60 s) y la lista. Tocar un aviso de
   correo o de WhatsApp le pide a Jarvis que lo lea. */

const $$ = (id) => document.getElementById(id);
const boton = $$("btn-avisos");
const contador = $$("avisos-contador");
const panel = $$("panel-avisos");
const lista = $$("lista-avisos");
let pedirAJarvis = () => {};

export function iniciarAvisos(alPedir) {
  pedirAJarvis = alPedir;
  boton.hidden = false;
  boton.addEventListener("click", abrir);
  actualizarContador();
  setInterval(actualizarContador, 60000);
}

async function actualizarContador() {
  try {
    const { no_vistos } = await (await fetch("/api/avisos/contador")).json();
    contador.textContent = no_vistos > 9 ? "9+" : String(no_vistos);
    contador.hidden = !no_vistos;
  } catch { /* sin red: se intenta en el próximo minuto */ }
}

async function abrir() {
  panel.hidden = false;
  const { avisos } = await (await fetch("/api/avisos")).json();
  lista.innerHTML = avisos.length ? "" : '<p class="vacio">No hay avisos.</p>';
  for (const aviso of avisos) lista.appendChild(fila(aviso));
}

function fila(aviso) {
  const item = document.createElement("button");
  item.type = "button";
  item.className = "aviso" + (aviso.visto ? "" : " nuevo") + (aviso.tipo === "sistema" ? " sistema" : "");
  const quien = document.createElement("strong");
  quien.textContent = aviso.remitente || (aviso.app === "whatsapp" ? "WhatsApp" : "Gmail");
  const resumen = document.createElement("span");
  // Los avisos de reunión traen los enlaces de Grabar / No grabar en su propia
  // línea (son para WhatsApp): aquí se quitan y se ofrece un botón.
  const lineas = (aviso.resumen || "").split("\n");
  resumen.textContent = lineas.filter((l) => !/^(No grabar|Grabar): /.test(l)).join(" ");
  const cuando = document.createElement("time");
  cuando.textContent = new Date(aviso.creado).toLocaleString("es");
  item.append(quien, resumen, cuando);
  item.addEventListener("click", async () => {
    await fetch(`/api/avisos/${aviso.id}/visto`, { method: "POST" });
    actualizarContador();
    panel.hidden = true;
    if (aviso.tipo === "correo" && aviso.app === "whatsapp") pedirAJarvis(`Léeme el chat de WhatsApp con id ${aviso.hilo}`);
    else if (aviso.tipo === "correo") pedirAJarvis(`Léeme el correo con id ${aviso.ref}`);
    else if (aviso.tipo === "reunion-lista" && aviso.hilo) abrirReunion(aviso.hilo);
  });
  if (aviso.tipo !== "reunion" || !aviso.hilo) return item;

  const ofreceGrabar = lineas.some((l) => l.startsWith("Grabar: "));
  const ofreceNoGrabar = lineas.some((l) => l.startsWith("No grabar: "));
  if (!ofreceGrabar && !ofreceNoGrabar) return item;
  const caja = document.createElement("div");
  caja.className = "aviso-con-accion";
  const accion = document.createElement("button");
  accion.type = "button";
  accion.className = "aviso-accion";
  accion.textContent = ofreceGrabar ? "Grabar" : "No grabar";
  accion.addEventListener("click", async () => {
    accion.disabled = true;
    const r = await fetch(`/api/reuniones/${aviso.hilo}/${ofreceGrabar ? "grabar" : "no-grabar"}`, { method: "POST" });
    accion.textContent = r.ok ? (await r.json()).mensaje : "No se pudo, inténtalo otra vez.";
  });
  caja.append(item, accion);
  return caja;
}

function abrirReunion(id) {
  // La vista Reuniones vive en la estructura (/); si recién se crea, lee el id de aquí.
  try { sessionStorage.setItem("jarvis-reunion-abrir", id); } catch { /* sin storage */ }
  if (window.top !== window) window.top.postMessage({ tipo: "ir", vista: "reuniones", id }, location.origin);
  else location.href = `/#reuniones`;
}
