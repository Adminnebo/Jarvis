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
  resumen.textContent = aviso.resumen;
  const cuando = document.createElement("time");
  cuando.textContent = new Date(aviso.creado).toLocaleString("es");
  item.append(quien, resumen, cuando);
  item.addEventListener("click", async () => {
    await fetch(`/api/avisos/${aviso.id}/visto`, { method: "POST" });
    actualizarContador();
    panel.hidden = true;
    if (aviso.tipo === "correo" && aviso.app === "whatsapp") pedirAJarvis(`Léeme el chat de WhatsApp con id ${aviso.hilo}`);
    else if (aviso.tipo === "correo") pedirAJarvis(`Léeme el correo con id ${aviso.ref}`);
  });
  return item;
}
