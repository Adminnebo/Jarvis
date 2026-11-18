/* Panel de Integraciones: una tarjeta por app (Gmail, WhatsApp, Outlook) y, si
   hay alguna conectada, la tarjeta "Avisos" con las reglas de "importante" y el
   WhatsApp donde llegan los avisos. Outlook trae además el horario laboral. */

const $$ = (id) => document.getElementById(id);
const panel = $$("panel-integraciones");
const lista = $$("lista-integraciones");

const APPS = {
  gmail: {
    conectar: "Conectar Gmail", cambiar: "Cambiar de cuenta",
    ruta: "/integraciones/gmail/conectar", borrar: "/api/integraciones/gmail",
    adios: (c) => `¿Desconectar ${c}? Jarvis dejará de leer tu correo y tu calendario de Google.`,
    nota: "Al conectar, marca también la casilla del calendario si quieres que Jarvis use tu agenda de Google.",
    // El horario va en la tarjeta de Outlook si está conectado; si no, aquí (si dio el calendario).
    extra: (app, apps) => app.calendario && !apps.some((a) => a.app === "outlook" && a.estado === "conectado")
      ? formularioDeHorario() : null,
    avisoConectado: (app) => app.calendario === false
      ? "Jarvis todavía no puede ver tu calendario de Google: toca Cambiar de cuenta y marca la casilla del calendario."
      : "",
  },
  whatsapp: {
    conectar: "Conectar WhatsApp", cambiar: "Cambiar número",
    ruta: "/integraciones/whatsapp/conectar", borrar: "/api/integraciones/whatsapp",
    adios: (c) => `¿Desconectar ${c}? Seguirás usando WhatsApp en tu teléfono, pero Jarvis dejará de leer y avisarte.`,
    nota: "Escanearás un código QR con WhatsApp Business. Ábrelo al menos una vez cada 14 días o Meta corta la conexión.",
  },
  outlook: {
    conectar: "Conectar Outlook", cambiar: "Reconectar",
    ruta: "/integraciones/outlook/conectar", borrar: "/api/integraciones/outlook",
    adios: (c) => `¿Desconectar ${c}? Jarvis dejará de leer tu correo y tu calendario de Outlook.`,
    nota: "Entrarás con tu cuenta de Microsoft. Si tu empresa usa Microsoft 365, puede que su administrador tenga que aprobar la app la primera vez.",
    extra: () => formularioDeHorario(),
  },
};

export async function abrirPanelIntegraciones() {
  panel.hidden = false;
  await pintar();
}

async function pintar() {
  const { apps } = await (await fetch("/api/integraciones")).json();
  lista.innerHTML = "";
  for (const app of apps) lista.appendChild(APPS[app.app] ? tarjetaApp(app, apps) : tarjetaBase(app));
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

function tarjetaApp(app, apps) {
  const datos = APPS[app.app];
  const tarjeta = tarjetaBase(app);
  const estado = document.createElement("p");
  estado.className = "integracion-estado" + (app.estado === "conectado" ? " ok" : "");
  estado.textContent = textoDeEstado(app);
  tarjeta.appendChild(estado);

  const aviso = app.estado === "conectado" && datos.avisoConectado ? datos.avisoConectado(app) : "";
  if (aviso) {
    const nota = document.createElement("p");
    nota.className = "fuente-destino";
    nota.textContent = aviso;
    tarjeta.appendChild(nota);
  }
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
  const extra = datos.extra && app.estado === "conectado" ? datos.extra(app, apps) : null;
  if (extra) tarjeta.appendChild(extra);
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

const NOMBRES_DIAS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];

function formularioDeHorario() {
  const form = document.createElement("form");
  form.className = "integracion-reglas";
  form.innerHTML = `
    <span class="fuente-destino">Horario laboral (para buscar huecos libres en tu calendario)</span>
    <div class="integracion-dias">${NOMBRES_DIAS.map((d, i) =>
      `<label class="casilla"><input type="checkbox" name="dia" value="${i + 1}"> ${d}</label>`).join("")}</div>
    <label><span>Entrada</span><input name="inicio" type="time" required></label>
    <label><span>Salida</span><input name="fin" type="time" required></label>
    <div class="fuente-acciones"><button class="boton-mini" type="submit">Guardar horario</button>
      <span class="integracion-mensaje" role="status"></span></div>`;
  fetch("/api/integraciones/outlook/horario").then((r) => r.json()).then((h) => {
    form.inicio.value = h.inicio;
    form.fin.value = h.fin;
    form.dataset.zona = h.zona;
    for (const casilla of form.querySelectorAll('input[name="dia"]')) {
      casilla.checked = h.dias.includes(Number(casilla.value));
    }
  });
  form.addEventListener("submit", async (evento) => {
    evento.preventDefault();
    const mensaje = form.querySelector(".integracion-mensaje");
    const dias = [...form.querySelectorAll('input[name="dia"]:checked')].map((c) => Number(c.value));
    const r = await fetch("/api/integraciones/outlook/horario", {
      method: "PUT", headers: { "content-type": "application/json" },
      body: JSON.stringify({ inicio: form.inicio.value, fin: form.fin.value, dias,
                             zona: form.dataset.zona || "America/Santo_Domingo" }),
    });
    const datos = await r.json();
    mensaje.textContent = r.ok ? "Guardado." : datos.error;
    mensaje.classList.toggle("mal", !r.ok);
  });
  return form;
}
