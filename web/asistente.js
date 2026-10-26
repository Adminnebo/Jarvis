/* Panel del asistente: nombre, foto y videos de cada organizacion. Solo para
   el super admin (el servidor lo exige; esconder el boton es comodidad). */

const $$ = (id) => document.getElementById(id);
const ESTADOS = [["reposo", "En reposo"], ["escuchando", "Escuchando"], ["hablando", "Hablando"]];
let organizacion = null;
let sondeo = null;

async function pedir(url, opciones = {}) {
  const r = await fetch(url, opciones);
  const datos = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(datos.error || `Error ${r.status}`);
  return datos;
}

export async function abrirPanelAsistente() {
  $$("panel-asistente").hidden = false;
  const { organizaciones } = await pedir("/api/organizaciones");
  const select = $$("asistente-org");
  select.innerHTML = "";
  for (const o of organizaciones) select.add(new Option(o.nombre, o.id));
  organizacion = select.value || null;
  select.onchange = () => { organizacion = select.value; refrescar(); };
  await refrescar();
}

function cerrar() {
  $$("panel-asistente").hidden = true;
  clearTimeout(sondeo);
}

function aviso(texto) { $$("asistente-aviso").textContent = texto || ""; }

function pintar(datos) {
  $$("asistente-nombre").value = datos.nombre || "";
  const foto = $$("asistente-foto");
  foto.hidden = !datos.foto_url;
  if (datos.foto_url) foto.src = datos.foto_url;

  const caja = $$("asistente-videos");
  caja.innerHTML = "";
  let enCurso = false;
  for (const [estado, titulo] of ESTADOS) {
    const v = datos.videos[estado];
    enCurso ||= v.trabajo_estado === "generando";
    const fila = document.createElement("div");
    fila.className = "asistente-video";
    const situacion = v.trabajo_estado === "generando" ? "Generando…"
      : v.trabajo_estado === "error" ? `Falló: ${v.error}` : v.url ? "Listo" : "Sin video";
    fila.innerHTML = `<strong>${titulo}</strong><span class="vacio"></span>`;
    fila.querySelector("span").textContent = situacion;
    if (v.url) {
      const video = document.createElement("video");
      Object.assign(video, { src: v.url, muted: true, loop: true, autoplay: true, playsInline: true });
      fila.prepend(video);
    }
    const boton = document.createElement("button");
    boton.className = "boton-texto";
    boton.textContent = v.url ? "Regenerar" : "Generar";
    boton.disabled = v.trabajo_estado === "generando" || !datos.foto || !datos.higgsfield;
    boton.onclick = () => generar([estado], datos);
    fila.append(boton);
    caja.append(fila);
  }
  $$("asistente-generar-todo").disabled = enCurso || !datos.foto || !datos.higgsfield;
  $$("asistente-generar-todo").onclick = () => generar(ESTADOS.map(([e]) => e), datos);
  if (!datos.higgsfield) aviso("Falta la clave de Higgsfield en el servidor: no se puede generar.");

  clearTimeout(sondeo);
  if (enCurso) sondeo = setTimeout(refrescar, 5000);
}

async function refrescar() {
  if (!organizacion) { aviso("No hay organizaciones."); return; }
  try {
    pintar(await pedir(`/api/asistente/${encodeURIComponent(organizacion)}`));
  } catch (error) { aviso(error.message); }
}

async function generar(estados, datos) {
  const costo = datos.costo_por_video ? ` (unos ${datos.costo_por_video * estados.length} créditos)` : "";
  if (!confirm(`¿Generar ${estados.length} video${estados.length > 1 ? "s" : ""} con Higgsfield${costo}?`)) return;
  aviso("Pidiendo los videos…");
  try {
    pintar(await pedir(`/api/asistente/${encodeURIComponent(organizacion)}/generar`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ estados }),
    }));
    aviso("Higgsfield está generando. Tarda unos minutos; podés cerrar este panel.");
  } catch (error) { aviso(error.message); }
}

$$("btn-cerrar-asistente").onclick = cerrar;
$$("asistente-guardar-nombre").onclick = async () => {
  try {
    pintar(await pedir(`/api/asistente/${encodeURIComponent(organizacion)}`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nombre: $$("asistente-nombre").value }),
    }));
    aviso("Nombre guardado.");
  } catch (error) { aviso(error.message); }
};
$$("asistente-archivo").onchange = async (e) => {
  const archivo = e.target.files[0];
  if (!archivo) return;
  const cuerpo = new FormData();
  cuerpo.append("foto", archivo);
  aviso("Subiendo la foto…");
  try {
    pintar(await pedir(`/api/asistente/${encodeURIComponent(organizacion)}/foto`, { method: "POST", body: cuerpo }));
    aviso("Foto guardada. Ahora podés generar los videos.");
  } catch (error) { aviso(error.message); }
  e.target.value = "";
};
