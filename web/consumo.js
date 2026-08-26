/* Tablero de consumo: tokens y dolares, con filtros.

   La pregunta que tiene que contestar de un vistazo es "cuanto me cuesta un
   minuto hablando", asi que esa cifra va arriba y grande; el resto es
   desglose. */

const $c = (id) => document.getElementById(id);

const panelConsumo = $c("panel-consumo");

export async function abrirPanelConsumo() {
  panelConsumo.hidden = false;
  await cargarConsumo();
}

function dinero(valor, decimales = 4) {
  if (valor === null || valor === undefined) return "—";
  return `$${valor.toFixed(decimales)}`;
}

function numero(valor) {
  if (valor === null || valor === undefined) return "—";
  return Math.round(valor).toLocaleString("es");
}

// --------------------------------------------------------------------------
// Carga y pintado
// --------------------------------------------------------------------------

async function cargarConsumo() {
  const parametros = new URLSearchParams({
    periodo: $c("filtro-periodo").value,
    modo: $c("filtro-modo").value,
    modelo: $c("filtro-modelo").value,
  });

  let datos;
  try {
    datos = await (await fetch(`/api/consumo?${parametros}`)).json();
  } catch {
    $c("resumen-consumo").innerHTML =
      '<p class="resultado-prueba mal">No pude leer el consumo.</p>';
    return;
  }

  llenarModelos(datos.modelos);
  pintarResumen(datos.totales);
  pintarPorModelo(datos.por_modelo, datos.precios);
  pintarDetalle(datos.registros);
}

function llenarModelos(modelos) {
  const selector = $c("filtro-modelo");
  const elegido = selector.value;
  // Se reconstruye porque puede aparecer un modelo nuevo entre cargas.
  selector.innerHTML = '<option value="todos">Todos</option>';
  for (const modelo of modelos) {
    const opcion = document.createElement("option");
    opcion.value = modelo;
    opcion.textContent = modelo;
    selector.appendChild(opcion);
  }
  selector.value = modelos.includes(elegido) ? elegido : "todos";
}

function pintarResumen(totales) {
  const tarjetas = [
    {
      etiqueta: "Costo por minuto hablando",
      valor: dinero(totales.costo_por_minuto_voz, 4),
      pie: totales.tokens_por_minuto_voz
        ? `${numero(totales.tokens_por_minuto_voz)} tokens/min`
        : "sin sesiones de voz todavia",
      destacada: true,
    },
    {
      etiqueta: "Gasto total",
      valor: dinero(totales.costo, 4),
      pie: `${numero(totales.consultas)} consultas`,
    },
    {
      etiqueta: "Tokens",
      valor: numero(totales.tokens),
      pie: "entrada + salida",
    },
    {
      etiqueta: "Minutos de voz",
      valor: totales.minutos_voz ? totales.minutos_voz.toFixed(1) : "0",
      pie: dinero(totales.costo_voz, 4) + " en voz",
    },
  ];

  $c("resumen-consumo").innerHTML = "";
  const rejilla = document.createElement("div");
  rejilla.className = "tarjetas";

  for (const t of tarjetas) {
    const tarjeta = document.createElement("div");
    tarjeta.className = "tarjeta" + (t.destacada ? " destacada" : "");
    tarjeta.innerHTML = `
      <span class="tarjeta-etiqueta"></span>
      <strong class="tarjeta-valor"></strong>
      <span class="tarjeta-pie"></span>`;
    tarjeta.querySelector(".tarjeta-etiqueta").textContent = t.etiqueta;
    tarjeta.querySelector(".tarjeta-valor").textContent = t.valor;
    tarjeta.querySelector(".tarjeta-pie").textContent = t.pie;
    rejilla.appendChild(tarjeta);
  }
  $c("resumen-consumo").appendChild(rejilla);
}

const COLUMNAS = [
  { titulo: "Modelo", saca: (f) => f.modelo },
  { titulo: "Modo", saca: (f) => f.modo },
  { titulo: "Consultas", saca: (f) => numero(f.consultas) },
  { titulo: "Tokens", saca: (f) => numero(f.tokens) },
  { titulo: "Costo", saca: (f) => dinero(f.costo, 4) },
  { titulo: "$/consulta", saca: (f) => dinero(f.costo_por_consulta, 5) },
  { titulo: "$/minuto", saca: (f) => dinero(f.costo_por_minuto, 4) },
  { titulo: "$/segundo", saca: (f) => dinero(f.costo_por_segundo, 6) },
  { titulo: "Tokens/min", saca: (f) => numero(f.tokens_por_minuto) },
  { titulo: "Tokens/seg", saca: (f) => (f.tokens_por_segundo ?? "—") },
  { titulo: "Audio in", saca: (f) => numero(f.entrada_audio) },
  { titulo: "Audio out", saca: (f) => numero(f.salida_audio) },
  { titulo: "Texto in", saca: (f) => numero(f.entrada_texto) },
  { titulo: "Texto out", saca: (f) => numero(f.salida_texto) },
  { titulo: "Cache", saca: (f) => numero(f.cache_texto + f.cache_audio) },
];

function pintarPorModelo(filas, precios) {
  const destino = $c("tabla-consumo");
  destino.innerHTML = "<h3>Por modelo</h3>";

  if (!filas.length) {
    destino.innerHTML += '<p class="vacio">Nada registrado en este periodo.</p>';
    return;
  }

  destino.appendChild(tablaDe(COLUMNAS, filas));

  // Avisar si algun precio no esta confirmado: el costo seria orientativo.
  const dudosos = filas
    .map((f) => f.modelo)
    .filter((m) => precios[m] && precios[m].confirmado === false);

  if (dudosos.length) {
    const aviso = document.createElement("p");
    aviso.className = "nota-precio";
    aviso.textContent =
      `Precio estimado para ${[...new Set(dudosos)].join(", ")}. ` +
      "Ajustalo en data/precios.json si no cuadra con tu factura.";
    destino.appendChild(aviso);
  }

  const faltantes = filas.map((f) => f.modelo).filter((m) => !precios[m]);
  if (faltantes.length) {
    const aviso = document.createElement("p");
    aviso.className = "resultado-prueba mal";
    aviso.textContent =
      `Sin precio para ${[...new Set(faltantes)].join(", ")}: ` +
      "su costo sale en cero. Agregalo en data/precios.json.";
    destino.appendChild(aviso);
  }
}

const COLUMNAS_DETALLE = [
  { titulo: "Cuando", saca: (r) => (r.cuando || "").replace("T", " ").slice(5) },
  { titulo: "Modo", saca: (r) => r.modo },
  { titulo: "Modelo", saca: (r) => r.modelo },
  { titulo: "Tokens", saca: (r) => numero(r.tokens) },
  { titulo: "Costo", saca: (r) => dinero(r.costo, 6) },
  { titulo: "Segundos", saca: (r) => (r.segundos ?? "—") },
];

function pintarDetalle(registros) {
  const destino = $c("detalle-consumo");
  destino.innerHTML = "";
  if (!registros.length) return;

  const detalle = document.createElement("details");
  const resumen = document.createElement("summary");
  resumen.textContent = `Detalle por consulta (${registros.length})`;
  detalle.append(resumen, tablaDe(COLUMNAS_DETALLE, registros));
  destino.appendChild(detalle);
}

function tablaDe(columnas, filas) {
  const envoltorio = document.createElement("div");
  envoltorio.className = "tabla-scroll";

  const tabla = document.createElement("table");

  const cabecera = document.createElement("thead");
  const filaCabecera = document.createElement("tr");
  for (const columna of columnas) {
    const celda = document.createElement("th");
    celda.textContent = columna.titulo;
    filaCabecera.appendChild(celda);
  }
  cabecera.appendChild(filaCabecera);

  const cuerpo = document.createElement("tbody");
  for (const fila of filas) {
    const tr = document.createElement("tr");
    for (const columna of columnas) {
      const celda = document.createElement("td");
      celda.textContent = columna.saca(fila);
      tr.appendChild(celda);
    }
    cuerpo.appendChild(tr);
  }

  tabla.append(cabecera, cuerpo);
  envoltorio.appendChild(tabla);
  return envoltorio;
}

// --------------------------------------------------------------------------
// Controles
// --------------------------------------------------------------------------

for (const id of ["filtro-periodo", "filtro-modo", "filtro-modelo"]) {
  $c(id).addEventListener("change", cargarConsumo);
}

$c("btn-refrescar-consumo").addEventListener("click", cargarConsumo);
$c("btn-cerrar-consumo").addEventListener("click", () => {
  panelConsumo.hidden = true;
});

$c("btn-borrar-consumo").addEventListener("click", async () => {
  if (!confirm("Borrar todo el historial de consumo?")) return;
  await fetch("/api/consumo", { method: "DELETE" });
  cargarConsumo();
});
