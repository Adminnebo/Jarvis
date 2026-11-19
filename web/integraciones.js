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
    // Con Zernio (plan B) se escanea con WhatsApp Business; con Evolution, desde "Dispositivos vinculados".
    nota: "Escanearás un código QR desde tu teléfono. Si pasas más de 14 días sin abrir WhatsApp, se desvincula y tendrás que conectarlo de nuevo.",
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
  if (app.disponible && app.vincular) {
    // WhatsApp por Evolution: se vincula aquí mismo con un QR (o un código), sin salir de Jarvis.
    const conectar = document.createElement("button");
    conectar.className = "boton-mini";
    conectar.textContent = app.estado === "conectado" ? datos.cambiar : datos.conectar;
    conectar.addEventListener("click", () => {
      acciones.hidden = true;
      tarjeta.appendChild(bloqueDeVinculo(() => { acciones.hidden = false; }));
    });
    acciones.appendChild(conectar);
  } else if (app.disponible) {
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

/* Vincular WhatsApp: muestra el QR que da Evolution (se renueva solo) o, si la
   persona está en el mismo teléfono, un código de 8 letras para "Vincular con
   número de teléfono". Sondea cada 3 s hasta que queda conectado. */
function bloqueDeVinculo(alCerrar) {
  const bloque = document.createElement("div");
  bloque.className = "vinculo";
  bloque.innerHTML = `
    <p class="vinculo-mensaje" role="status">Preparando…</p>
    <img class="vinculo-qr" alt="Código QR para vincular WhatsApp" hidden>
    <p class="vinculo-codigo" hidden></p>
    <ol class="vinculo-pasos fuente-destino">
      <li>Abre WhatsApp en tu teléfono.</li>
      <li>Toca <b>⋮</b> (o Ajustes) → <b>Dispositivos vinculados</b> → <b>Vincular un dispositivo</b>.</li>
      <li class="vinculo-paso-qr">Apunta la cámara a este código.</li>
      <li class="vinculo-paso-codigo" hidden>Toca <b>Vincular con número de teléfono</b> y escribe el código.</li>
    </ol>
    <form class="integracion-reglas vinculo-numero" hidden>
      <label><span>Tu número de WhatsApp</span><input name="numero" inputmode="tel" placeholder="809 555 1234"></label>
      <div class="fuente-acciones"><button class="boton-mini" type="submit">Pedir código</button></div>
    </form>
    <div class="fuente-acciones">
      <button type="button" class="boton-mini vinculo-cambiar">Estoy en este teléfono: usar un código</button>
      <button type="button" class="boton-mini vinculo-cancelar">Cancelar</button>
    </div>`;
  const $ = (sel) => bloque.querySelector(sel);
  let temporizador = null;
  let vivo = true;

  const cerrar = () => {
    vivo = false;
    clearTimeout(temporizador);
    bloque.remove();
    alCerrar();
  };

  function mostrar(datos) {
    if (!vivo) return;
    if (datos.error) {
      $(".vinculo-mensaje").textContent = datos.error;
      $(".vinculo-mensaje").classList.add("integracion-mensaje", "mal");
      return;
    }
    if (datos.estado === "conectado") {
      vivo = false;
      clearTimeout(temporizador);
      $(".vinculo-mensaje").textContent = `Listo: conectado como ${datos.cuenta}.`;
      setTimeout(pintar, 1200);
      return;
    }
    if (datos.estado === "sin_conectar") return;
    const conCodigo = Boolean(datos.codigo);
    $(".vinculo-mensaje").classList.remove("integracion-mensaje", "mal");
    $(".vinculo-mensaje").textContent = conCodigo ? "Tu código para vincular:" : "Escanea este código con WhatsApp:";
    $(".vinculo-qr").hidden = conCodigo || !datos.qr;
    if (datos.qr && !conCodigo) $(".vinculo-qr").src = datos.qr;
    $(".vinculo-codigo").hidden = !conCodigo;
    if (conCodigo) $(".vinculo-codigo").textContent = datos.codigo.replace(/^(.{4})(.{4})$/, "$1-$2");
    $(".vinculo-paso-qr").hidden = conCodigo;
    $(".vinculo-paso-codigo").hidden = !conCodigo;
  }

  async function pedir(metodo, cuerpo) {
    try {
      const r = await fetch("/api/integraciones/whatsapp/vincular", metodo === "POST"
        ? { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(cuerpo) }
        : {});
      return await r.json();
    } catch {
      return { error: "Sin conexión con Jarvis. Reintentando…" };
    }
  }

  async function sondear() {
    if (!vivo) return;
    mostrar(await pedir("GET"));
    if (vivo) temporizador = setTimeout(sondear, 3000);
  }

  $(".vinculo-cancelar").addEventListener("click", cerrar);
  $(".vinculo-cambiar").addEventListener("click", () => {
    $(".vinculo-cambiar").hidden = true;
    $(".vinculo-numero").hidden = false;
    $(".vinculo-numero").numero.focus();
  });
  $(".vinculo-numero").addEventListener("submit", async (evento) => {
    evento.preventDefault();
    clearTimeout(temporizador);
    $(".vinculo-mensaje").textContent = "Pidiendo el código…";
    const datos = await pedir("POST", { numero: $(".vinculo-numero").numero.value });
    mostrar(datos);
    if (!datos.error) { $(".vinculo-numero").hidden = true; temporizador = setTimeout(sondear, 3000); }
  });

  pedir("POST", {}).then((datos) => {
    mostrar(datos);
    if (!datos.error) temporizador = setTimeout(sondear, 3000);
  });
  return bloque;
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
