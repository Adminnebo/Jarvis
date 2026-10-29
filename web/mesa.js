/* La mesa de cotizaciones en pantalla.

   Es la misma mesa que usa la voz (original + variantes, guardada en el
   servidor): esta tabla solo la muestra y deja cambiar precios a mano. Los
   numeros los calcula el servidor; aqui solo se adelanta el margen mientras
   se escribe un precio, para verlo antes de soltarlo.

   Se vuelve a pintar cuando una herramienta de la mesa termina (voz o chat)
   y cuando se cambia algo aqui. Lo que se cambia a mano se le cuenta a Jarvis
   con `alCambiarAMano`, para que la proxima respuesta ya lo sepa. */

const $m = (id) => document.getElementById(id);

const panel = $m("panel-mesa");
const pestanas = $m("mesa-pestanas");
const cabecera = $m("mesa-cabecera");
const cuerpo = $m("mesa-cuerpo");
const pie = $m("mesa-pie");
const boton = $m("btn-mesa");

const dinero = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const entero = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });
const pct = (valor) => (valor == null ? "—" : `${valor.toFixed(1)}\u00a0%`);

let vista = null;          // lo ultimo que mando el servidor
let anterior = null;       // la vista de antes, para marcar lo que cambio
let enEspera = null;       // una vista que llego mientras se escribia un precio
let eventos = {};

export function configurarMesa(manejadores) {
  eventos = manejadores;
  boton.addEventListener("click", () => {
    panel.hidden = !panel.hidden;
    sincronizarCuerpo();
  });
  $m("btn-cerrar-mesa").addEventListener("click", () => {
    panel.hidden = true;
    sincronizarCuerpo();
  });
  // En el telefono el panel va abajo, encima de la barra de escribir, y se
  // puede plegar para ver solo las cifras.
  const plegar = $m("btn-plegar-mesa");
  plegar.addEventListener("click", () => {
    const plegada = panel.classList.toggle("plegada");
    plegar.setAttribute("aria-expanded", String(!plegada));
  });
  const entrada = document.querySelector(".entrada");
  if (entrada && window.ResizeObserver) {
    new ResizeObserver(() => document.documentElement.style.setProperty(
      "--alto-entrada", `${entrada.offsetHeight}px`)).observe(entrada);
  }
  // El panel se cierra tambien con Escape (app.js), y ahi no pasa por aqui.
  new MutationObserver(sincronizarCuerpo).observe(panel, { attributes: true, attributeFilter: ["hidden"] });
  refrescar({ abrir: false, primeraVez: true });
}

/* Trae la mesa y la pinta.
   abrir: true      -> abre el panel si hay algo que mostrar.
   abrir: "cambio"  -> lo abre solo si la mesa cambio desde la ultima vez. */
export async function refrescar({ abrir = false, primeraVez = false } = {}) {
  let nueva;
  try {
    const respuesta = await fetch("/api/mesa");
    if (!respuesta.ok) return;
    nueva = await respuesta.json();
  } catch {
    return;
  }
  const cambio = JSON.stringify(nueva) !== JSON.stringify(vista);
  aplicar(nueva, primeraVez);
  const hay = nueva.cotizaciones.length > 0;
  if (!hay) panel.hidden = true;
  else if (abrir === true || (abrir === "cambio" && cambio)) panel.hidden = false;
  sincronizarCuerpo();
}

function aplicar(nueva, primeraVez = false) {
  // Si alguien esta escribiendo un precio, no se le borra lo que escribe.
  if (panel.contains(document.activeElement) && document.activeElement.tagName === "INPUT") {
    enEspera = nueva;
    return;
  }
  anterior = primeraVez ? nueva : vista;
  vista = nueva;
  enEspera = null;
  boton.hidden = !vista.cotizaciones.length;
  pintar();
}

function sincronizarCuerpo() {
  document.body.classList.toggle("con-mesa", !panel.hidden);
}

function activa() {
  return vista.cotizaciones.find((c) => c.id === vista.activa) || vista.cotizaciones.at(-1);
}

// --------------------------------------------------------------------------
// Pintar
// --------------------------------------------------------------------------

function pintar() {
  if (!vista.cotizaciones.length) {
    pestanas.innerHTML = cabecera.innerHTML = cuerpo.innerHTML = pie.innerHTML = "";
    return;
  }
  const cot = activa();
  const antes = anterior?.cotizaciones.find((c) => c.id === cot.id);

  pestanas.replaceChildren(...vista.cotizaciones.map((c) => {
    const pestana = document.createElement("button");
    pestana.type = "button";
    pestana.className = "mesa-pestana";
    pestana.setAttribute("role", "tab");
    pestana.setAttribute("aria-selected", String(c.id === cot.id));
    pestana.textContent = c.original ? c.nombre.replace(" (original)", " · original") : c.nombre;
    if (anterior && !anterior.cotizaciones.some((a) => a.id === c.id)) pestana.classList.add("nueva");
    pestana.addEventListener("click", () => elegir(c.id));
    return pestana;
  }));

  pestanas.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest", inline: "nearest" });

  cabecera.replaceChildren();
  const quien = document.createElement("p");
  quien.className = "mesa-cliente";
  quien.textContent = [cot.cliente, cot.fecha].filter(Boolean).join(" · ");
  cabecera.append(quien);
  if (cot.original) {
    const nota = document.createElement("p");
    nota.className = "mesa-nota";
    nota.textContent = "La original no se cambia: si editas un precio, se arma una copia «ajustada».";
    cabecera.append(nota);
  }

  const tabla = document.createElement("table");
  tabla.innerHTML = `<thead><tr>
      <th class="num">#</th><th>Producto</th><th class="num col-cant">Cant.</th>
      <th class="num col-costo">Costo</th><th class="num">Precio</th><th class="num">Margen</th>
      <th class="num col-ganancia">Ganancia</th>
    </tr></thead>`;
  const filas = document.createElement("tbody");
  for (const linea of cot.lineas) filas.append(fila(cot, linea, antes));
  tabla.append(filas);
  const scroll = document.createElement("div");
  scroll.className = "tabla-scroll mesa-tabla";
  scroll.append(tabla);
  cuerpo.replaceChildren(scroll);

  pintarPie(cot);
}

function fila(cot, linea, antes) {
  const tr = document.createElement("tr");
  tr.dataset.n = linea.n;
  if (linea.costo && linea.precio < linea.costo) tr.classList.add("a-perdida");
  const previa = antes?.lineas.find((l) => l.n === linea.n);
  if (previa && previa.precio !== linea.precio) tr.classList.add("cambio");

  const producto = document.createElement("td");
  producto.className = "mesa-producto";
  const nombre = document.createElement("span");
  nombre.className = "mesa-descripcion";
  nombre.textContent = linea.descripcion;
  nombre.title = `${linea.descripcion} (cod ${linea.codigo})`;
  const codigo = document.createElement("span");
  codigo.className = "mesa-codigo";
  codigo.textContent = `cod ${linea.codigo}${linea.ajuste && !cot.original ? ` · ${linea.ajuste}` : ""}`;
  const movil = document.createElement("span");
  movil.className = "mesa-movil";
  movil.textContent = `${entero.format(linea.cantidad)} ${linea.unidad.toLowerCase()} · ` +
    (linea.costo ? `costo ${dinero.format(linea.costo)}` : "sin costo");
  producto.append(nombre, codigo, movil);
  if (linea.costo_cotizado && Math.abs(linea.costo_cotizado - (linea.costo || 0)) >= 0.005) {
    const entonces = document.createElement("span");
    entonces.className = "mesa-entonces";
    entonces.textContent = `al cotizar: costo ${dinero.format(linea.costo_cotizado)} · ${pct(linea.margen_cotizado)}`;
    producto.append(entonces);
  }

  const precio = document.createElement("input");
  precio.type = "text";
  precio.inputMode = "decimal";
  precio.className = "mesa-precio";
  precio.value = dinero.format(linea.precio);
  precio.setAttribute("aria-label", `Precio de ${linea.descripcion}`);

  const margen = celda(pct(linea.margen), "num mesa-margen");
  const textoGanancia = (valor) => (valor == null ? "—" : dinero.format(valor));
  const ganancia = celda(textoGanancia(linea.ganancia), "num col-ganancia");
  const restaurar = () => {
    precio.value = dinero.format(linea.precio);
    margen.textContent = pct(linea.margen);
    ganancia.textContent = textoGanancia(linea.ganancia);
  };
  precio.addEventListener("focus", () => precio.select());
  precio.addEventListener("input", () => {
    // Adelanto local: el numero de verdad lo da el servidor al soltar.
    const valor = leerPrecio(precio.value);
    if (valor && linea.costo) {
      margen.textContent = pct(((valor - linea.costo) / linea.costo) * 100);
      ganancia.textContent = textoGanancia((valor - linea.costo) * linea.cantidad);
    } else {
      margen.textContent = pct(linea.margen);
      ganancia.textContent = textoGanancia(linea.ganancia);
    }
    adelantarGeneral(cot, linea.n, valor);
  });
  precio.addEventListener("keydown", (evento) => {
    if (evento.key === "Enter") precio.blur();
    if (evento.key === "Escape") {
      evento.stopPropagation();
      restaurar();
      precio.blur();
    }
  });
  precio.addEventListener("blur", () => {
    const valor = leerPrecio(precio.value);
    if (!valor || Math.abs(valor - linea.precio) < 0.005) {
      restaurar();
      if (enEspera) aplicar(enEspera);
      else pintarPie(cot);
      return;
    }
    cambiarPrecio(cot, linea, valor);
  });
  const celdaPrecio = document.createElement("td");
  celdaPrecio.className = "num";
  celdaPrecio.append(precio);

  tr.append(
    celda(linea.n, "num tenue"),
    producto,
    celda(entero.format(linea.cantidad), "num col-cant"),
    celda(linea.costo ? dinero.format(linea.costo) : "sin costo", `num col-costo${linea.costo ? "" : " tenue"}`),
    celdaPrecio,
    margen,
    ganancia,
  );
  return tr;
}

function celda(texto, clase = "") {
  const td = document.createElement("td");
  td.className = clase;
  td.textContent = texto;
  return td;
}

function leerPrecio(texto) {
  const valor = Number(String(texto).replace(/[^\d.]/g, ""));
  return Number.isFinite(valor) && valor > 0 ? valor : null;
}

function pintarPie(cot, adelanto = null) {
  const margen = adelanto ? adelanto.margen : cot.margen;
  const piso = vista.piso;
  const rompe = piso != null && margen != null && margen < piso;

  pie.replaceChildren();
  const cifras = document.createElement("div");
  cifras.className = "mesa-cifras";
  cifras.append(
    cifra("Total", `RD$ ${dinero.format(adelanto ? adelanto.total : cot.total)}`),
    cifra("Ganancia", `RD$ ${dinero.format(adelanto ? adelanto.ganancia : cot.ganancia)}`),
    cifra(adelanto ? "Margen (sin guardar)" : "Margen general", pct(margen), rompe ? "mal" : ""),
  );
  if (cot.margen_cotizado != null && Math.abs(cot.margen_cotizado - cot.margen) >= 0.5) {
    cifras.append(cifra("Cuando se cotizó", pct(cot.margen_cotizado), "tenue"));
  }
  pie.append(cifras);

  const avisos = [];
  if (cot.a_perdida.length) avisos.push(`A pérdida: producto ${cot.a_perdida.join(", ")}.`);
  if (cot.sin_costo.length) avisos.push(`Sin costo (fuera del cálculo): producto ${cot.sin_costo.join(", ")}.`);
  if (avisos.length) {
    const nodo = document.createElement("p");
    nodo.className = "mesa-aviso";
    nodo.textContent = avisos.join(" ");
    pie.append(nodo);
  }

  const acciones = document.createElement("div");
  acciones.className = "mesa-acciones";
  const etiqueta = document.createElement("label");
  etiqueta.className = "mesa-piso";
  etiqueta.textContent = "Piso ";
  const campoPiso = document.createElement("input");
  campoPiso.type = "text";
  campoPiso.inputMode = "decimal";
  campoPiso.placeholder = "—";
  campoPiso.value = piso == null ? "" : String(piso);
  campoPiso.setAttribute("aria-label", "Margen general minimo, sobre el costo");
  campoPiso.addEventListener("keydown", (evento) => {
    if (evento.key === "Enter") campoPiso.blur();
    if (evento.key === "Escape") { evento.stopPropagation(); campoPiso.value = piso ?? ""; campoPiso.blur(); }
  });
  campoPiso.addEventListener("blur", () => {
    const texto = campoPiso.value.trim();
    if (texto === String(piso ?? "")) { if (enEspera) aplicar(enEspera); return; }
    fijarPiso(texto);
  });
  etiqueta.append(campoPiso, " %");
  if (piso != null && margen != null) {
    const estado = document.createElement("span");
    estado.className = rompe ? "mal" : "bien";
    const diferencia = Math.abs(margen - piso).toFixed(1);
    estado.textContent = rompe ? ` le faltan ${diferencia} pts` : ` le sobran ${diferencia} pts`;
    etiqueta.append(estado);
  }
  acciones.append(etiqueta);

  if (!cot.original) acciones.append(botonEmitir(cot));
  pie.append(acciones);
}

function cifra(nombre, valor, clase = "") {
  const nodo = document.createElement("div");
  nodo.className = `mesa-cifra ${clase}`;
  const etiqueta = document.createElement("span");
  etiqueta.textContent = nombre;
  const numero = document.createElement("strong");
  numero.textContent = valor;
  nodo.append(etiqueta, numero);
  return nodo;
}

// El margen general mientras se escribe un precio, con la misma cuenta que el
// servidor: ganancia sobre costo, solo de las lineas que tienen costo.
function adelantarGeneral(cot, n, precio) {
  if (!precio) return pintarPie(cot);
  let costo = 0, venta = 0, total = 0;
  for (const l of cot.lineas) {
    const p = l.n === n ? precio : l.precio;
    total += p * l.cantidad;
    if (!l.costo) continue;
    costo += l.costo * l.cantidad;
    venta += p * l.cantidad;
  }
  pintarPie(cot, {
    total, ganancia: venta - costo, margen: costo ? ((venta - costo) / costo) * 100 : null,
  });
}

function botonEmitir(cot) {
  // Dos toques: emitir crea una cotizacion real con su PDF.
  const emitir = document.createElement("button");
  emitir.type = "button";
  emitir.className = "boton-primario mesa-emitir";
  emitir.textContent = "Emitir esta";
  let armado = null;
  emitir.addEventListener("click", async () => {
    if (!armado) {
      emitir.textContent = `¿Emitir «${cot.nombre}»? Toca otra vez`;
      emitir.classList.add("armado");
      armado = setTimeout(() => {
        armado = null;
        emitir.textContent = "Emitir esta";
        emitir.classList.remove("armado");
      }, 4000);
      return;
    }
    clearTimeout(armado);
    emitir.disabled = true;
    emitir.textContent = "Emitiendo…";
    try {
      const respuesta = await fetch("/api/herramienta", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ nombre: "emitir_cotizacion", argumentos: JSON.stringify({ cuales: cot.id }) }),
      });
      const datos = await respuesta.json();
      eventos.alEmitir?.(cot.nombre, datos.resultado, datos.adjuntos || []);
    } catch (error) {
      eventos.alError?.(`No se pudo emitir: ${error.message}`);
    }
    refrescar();
  });
  return emitir;
}

// --------------------------------------------------------------------------
// Cambios desde la tabla
// --------------------------------------------------------------------------

async function cambiarPrecio(cot, linea, precio) {
  const datos = await pedir("/api/mesa/precio", { cotizacion: cot.id, linea: linea.n, precio: String(precio) });
  if (!datos) return;
  aplicar(datos.vista);
  eventos.alCambiarAMano?.(datos.nota, datos.corto);
}

async function elegir(id) {
  if (id === vista.activa) return;
  const datos = await pedir("/api/mesa/elegir", { cotizacion: id });
  if (datos) aplicar(datos);
}

async function fijarPiso(texto) {
  const datos = await pedir("/api/mesa/elegir", { piso: texto });
  if (!datos) return;
  aplicar(datos);
  const nota = datos.piso == null
    ? "Quito el piso de margen desde la tabla de la pantalla."
    : `Puso desde la tabla de la pantalla un piso de ${datos.piso} % de margen general.`;
  eventos.alCambiarAMano?.(nota, nota);
}

async function pedir(url, cuerpoPeticion) {
  try {
    const respuesta = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cuerpoPeticion),
    });
    const datos = await respuesta.json();
    if (!respuesta.ok) throw new Error(datos.error || `El servidor respondio ${respuesta.status}`);
    return datos;
  } catch (error) {
    eventos.alError?.(error.message);
    refrescar();
    return null;
  }
}
