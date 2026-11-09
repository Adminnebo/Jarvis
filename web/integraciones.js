/* Panel de Integraciones: una tarjeta por app (Gmail, WhatsApp) y, si hay
   alguna conectada, la tarjeta "Avisos" con las reglas de "importante" y el
   WhatsApp donde llegan los avisos. */

const $$ = (id) => document.getElementById(id);
const panel = $$("panel-integraciones");
const lista = $$("lista-integraciones");

const APPS = {
  gmail: {
    conectar: "Conectar Gmail", cambiar: "Cambiar de cuenta",
    ruta: "/integraciones/gmail/conectar", borrar: "/api/integraciones/gmail",
    adios: (c) => `¿Desconectar ${c}? Jarvis dejará de leer y avisarte.`,
  },
  whatsapp: {
    conectar: "Conectar WhatsApp", cambiar: "Cambiar número",
    ruta: "/integraciones/whatsapp/conectar", borrar: "/api/integraciones/whatsapp",
    adios: (c) => `¿Desconectar ${c}? Seguirás usando WhatsApp en tu teléfono, pero Jarvis dejará de leer y avisarte.`,
    nota: "Escanearás un código QR con WhatsApp Business. Ábrelo al menos una vez cada 14 días o Meta corta la conexión.",
  },
};

export async function abrirPanelIntegraciones() {
  panel.hidden = false;
  await pintar();
}

async function pintar() {
  const { apps } = await (await fetch("/api/integraciones")).json();
  lista.innerHTML = "";
  for (const app of apps) lista.appendChild(APPS[app.app] ? tarjetaApp(app) : tarjetaBase(app));
  if (apps.some((a) => a.estado === "conectado")) lista.appendChild(await tarjetaAvisos());
}

function tarjetaBase(app) {
  const tarjeta = document.createElement("div");
  tarjeta.className = "fuente integracion";
  const cabecera = document.createElement("div");
  cabecera.className = "fuente-cabecera";
  const titulo = document.createElement("div");
  titulo.className = "fuente-titulo";
  titulo.textContent = app.nombre;
  cabecera.append(titulo);
  const descripcion = document.createElement("div");
  descripcion.className = "fuente-destino";
  descripcion.textContent = app.descripcion;
  tarjeta.append(cabecera, descripcion);
  return tarjeta;
}

function textoDeEstado(app) {
  if (!app.disponible) return "No disponible todavía.";
  if (app.estado === "conectado") return `Conectado como ${app.cuenta}`;
  if (app.estado === "desconectado" && app.error) return `Desconectado: ${app.error} Vuelve a conectar.`;
  return "Sin conectar.";
}

function tarjetaApp(app) {
  const datos = APPS[app.app];
  const tarjeta = tarjetaBase(app);
  const estado = document.createElement("p");
  estado.className = "integracion-estado" + (app.estado === "conectado" ? " ok" : "");
  estado.textContent = textoDeEstado(app);
  tarjeta.appendChild(estado);

  if (datos.nota && app.disponible && app.estado !== "conectado") {
    const nota = document.createElement("p");
    nota.className = "fuente-destino";
    nota.textContent = datos.nota;
    tarjeta.appendChild(nota);
  }

  const acciones = document.createElement("div");
  acciones.className = "fuente-acciones";
  if (app.disponible) {
    const conectar = document.createElement("a");
    conectar.className = "boton-mini";
    conectar.href = datos.ruta;
    conectar.textContent = app.estado === "conectado" ? datos.cambiar : datos.conectar;
    acciones.appendChild(conectar);
  }
  if (app.estado === "conectado") {
    const desconectar = document.createElement("button");
    desconectar.className = "boton-mini peligro";
    desconectar.textContent = "Desconectar";
    desconectar.addEventListener("click", async () => {
      if (!confirm(datos.adios(app.cuenta))) return;
      await fetch(datos.borrar, { method: "DELETE" });
      pintar();
    });
    acciones.appendChild(desconectar);
  }
  tarjeta.appendChild(acciones);
  return tarjeta;
}

async function tarjetaAvisos() {
  const tarjeta = tarjetaBase({
    nombre: "Avisos",
    descripcion: "Jarvis revisa tus correos y chats nuevos y te avisa solo de lo que cumpla estas reglas.",
  });
  tarjeta.appendChild(await formularioDeReglas());
  return tarjeta;
}

async function formularioDeReglas() {
  const reglas = await (await fetch("/api/avisos/reglas")).json();
  const form = document.createElement("form");
  form.className = "integracion-reglas";
  form.innerHTML = `
    <label><span>¿De qué quieres que te avise?</span>
      <textarea name="reglas" rows="4" maxlength="2000"
        placeholder="Ej.: clientes que piden cotización o reclaman, pagos y transferencias, cualquier cosa de JH o de bancos. Nada de publicidad, newsletters ni saludos."></textarea></label>
    <label><span>WhatsApp para avisos (opcional)</span>
      <input name="whatsapp" inputmode="tel" placeholder="809 555 1234"></label>
    <label class="casilla"><input type="checkbox" name="activo"> Avisarme</label>
    <div class="fuente-acciones"><button class="boton-mini" type="submit">Guardar</button>
      <span class="integracion-mensaje" role="status"></span></div>`;
  form.reglas.value = reglas.reglas || "";
  form.whatsapp.value = reglas.whatsapp ? `+${reglas.whatsapp}` : "";
  form.activo.checked = reglas.activo;
  form.addEventListener("submit", async (evento) => {
    evento.preventDefault();
    const mensaje = form.querySelector(".integracion-mensaje");
    const r = await fetch("/api/avisos/reglas", {
      method: "PUT", headers: { "content-type": "application/json" },
      body: JSON.stringify({ reglas: form.reglas.value, whatsapp: form.whatsapp.value, activo: form.activo.checked }),
    });
    const datos = await r.json();
    mensaje.textContent = r.ok ? "Guardado." : datos.error;
    mensaje.classList.toggle("mal", !r.ok);
  });
  return form;
}
