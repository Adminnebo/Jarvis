/* Panel de dispositivos: vincular un reloj por codigo y administrar los que
   ya estan vinculados. Mismo patron visual que fuentes.js (tarjeta + mini
   botones), pero mas chico: no hay formulario, solo un boton que pide un
   codigo. */

const $$ = (id) => document.getElementById(id);

const panel = $$("panel-dispositivos");
const lista = $$("lista-dispositivos");
const cajaCodigo = $$("codigo-vinculo");

let temporizadorCodigo = null;

export async function abrirPanelDispositivos() {
  panel.hidden = false;
  ocultarCodigo();
  await refrescarListaDispositivos();
}

async function refrescarListaDispositivos() {
  const { dispositivos } = await (await fetch("/api/dispositivos")).json();

  if (!dispositivos.length) {
    lista.innerHTML =
      '<p class="vacio">Todavia no vinculaste ningun reloj.</p>';
    return;
  }

  lista.innerHTML = "";
  for (const dispositivo of dispositivos) {
    lista.appendChild(tarjetaDeDispositivo(dispositivo));
  }
}

function tarjetaDeDispositivo(dispositivo) {
  const tarjeta = document.createElement("div");
  tarjeta.className = "fuente";

  const cabecera = document.createElement("div");
  cabecera.className = "fuente-cabecera";

  const titulo = document.createElement("div");
  titulo.className = "fuente-titulo";
  titulo.textContent = dispositivo.nombre;

  cabecera.append(titulo);

  const destino = document.createElement("div");
  destino.className = "fuente-destino";
  destino.textContent = dispositivo.ultimo_uso
    ? `Ultimo uso: ${formatearFecha(dispositivo.ultimo_uso)}`
    : "Todavia no lo uso";

  const acciones = document.createElement("div");
  acciones.className = "fuente-acciones";
  const btnRevocar = document.createElement("button");
  btnRevocar.className = "boton-mini peligro";
  btnRevocar.textContent = "Revocar";
  btnRevocar.addEventListener("click", async () => {
    if (!confirm(`Revocar "${dispositivo.nombre}"? Dejara de poder hablar con Jarvis.`)) return;
    await fetch(`/api/dispositivos/${dispositivo.id}`, { method: "DELETE" });
    refrescarListaDispositivos();
  });
  acciones.appendChild(btnRevocar);

  tarjeta.append(cabecera, destino, acciones);
  return tarjeta;
}

function formatearFecha(iso) {
  try {
    return new Date(iso).toLocaleString("es");
  } catch {
    return iso;
  }
}

// --------------------------------------------------------------------------
// Generar y mostrar el codigo de vinculo
// --------------------------------------------------------------------------

function ocultarCodigo() {
  clearInterval(temporizadorCodigo);
  cajaCodigo.hidden = true;
}

$$("btn-vincular-reloj").addEventListener("click", async () => {
  const { codigo, vence_en } = await (await fetch("/api/dispositivos/codigo", {
    method: "POST",
  })).json();

  mostrarCodigo(codigo, vence_en);
});

function mostrarCodigo(codigo, segundos) {
  clearInterval(temporizadorCodigo);
  cajaCodigo.hidden = false;

  let restantes = segundos;
  const pintar = () => {
    const minutos = Math.floor(restantes / 60);
    const segs = String(restantes % 60).padStart(2, "0");
    $$("codigo-vinculo-texto").textContent = codigo;
    $$("codigo-vinculo-vence").textContent =
      restantes > 0 ? `Vence en ${minutos}:${segs}` : "Vencio. Genera uno nuevo.";
  };

  pintar();
  temporizadorCodigo = setInterval(() => {
    restantes -= 1;
    if (restantes <= 0) {
      clearInterval(temporizadorCodigo);
      // Un codigo vencido ya no vincula: se refresca la lista por si igual
      // alguien alcanzo a usarlo justo antes.
      refrescarListaDispositivos();
    }
    pintar();
  }, 1000);
}

$$("btn-cerrar-dispositivos").addEventListener("click", () => {
  panel.hidden = true;
  ocultarCodigo();
});
