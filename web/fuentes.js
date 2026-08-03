/* Panel de fuentes de datos: alta, prueba de conexion, esquema y consola SQL.

   Los formularios no estan escritos a mano: se dibujan a partir de
   /api/fuentes/tipos, asi que agregar un motor en el backend lo hace aparecer
   aqui sin tocar este archivo. */

const $$ = (id) => document.getElementById(id);

let TIPOS = {};
let editando = null;   // id de la fuente en edicion, o null si es nueva

const panel = $$("panel-fuentes");
const lista = $$("lista-fuentes");
const formulario = $$("form-fuente");
const camposContenedor = $$("campos-fuente");
const resultadoPrueba = $$("resultado-prueba");

// --------------------------------------------------------------------------
// Carga y listado
// --------------------------------------------------------------------------

export async function abrirPanelFuentes() {
  panel.hidden = false;
  if (!Object.keys(TIPOS).length) {
    TIPOS = await (await fetch("/api/fuentes/tipos")).json();
    llenarSelectorDeTipo();
  }
  await refrescarLista();
}

function llenarSelectorDeTipo() {
  const selector = $$("tipo-fuente");
  selector.innerHTML = "";
  for (const [clave, definicion] of Object.entries(TIPOS)) {
    const opcion = document.createElement("option");
    opcion.value = clave;
    opcion.textContent = definicion.etiqueta;
    selector.appendChild(opcion);
  }
  selector.addEventListener("change", () => dibujarCampos(selector.value));
  dibujarCampos(selector.value);
}

async function refrescarLista() {
  const { fuentes } = await (await fetch("/api/fuentes")).json();

  if (!fuentes.length) {
    lista.innerHTML =
      '<p class="vacio">No hay fuentes conectadas. Agrega una abajo.</p>';
    return;
  }

  lista.innerHTML = "";
  for (const fuente of fuentes) {
    lista.appendChild(tarjetaDeFuente(fuente));
  }
}

function tarjetaDeFuente(fuente) {
  const tarjeta = document.createElement("div");
  tarjeta.className = "fuente" + (fuente.activa ? "" : " inactiva");

  const cabecera = document.createElement("div");
  cabecera.className = "fuente-cabecera";

  const titulo = document.createElement("div");
  titulo.className = "fuente-titulo";
  titulo.textContent = fuente.nombre;

  const etiquetas = document.createElement("div");
  etiquetas.className = "fuente-etiquetas";
  etiquetas.append(
    chip(TIPOS[fuente.tipo]?.etiqueta || fuente.tipo, "tipo"),
    chip(fuente.solo_lectura ? "solo lectura" : "escritura",
         fuente.solo_lectura ? "ok" : "alerta"),
  );
  if (!fuente.activa) etiquetas.appendChild(chip("desactivada", "apagado"));

  cabecera.append(titulo, etiquetas);

  const destino = document.createElement("div");
  destino.className = "fuente-destino";
  destino.textContent = describir(fuente);

  const acciones = document.createElement("div");
  acciones.className = "fuente-acciones";
  acciones.append(
    boton("Probar", () => probarGuardada(fuente, estado)),
    boton("Tablas", () => verEsquema(fuente.id, estado)),
    boton("Consultar", () => abrirConsola(fuente)),
    boton("Editar", () => cargarEnFormulario(fuente)),
    boton("Borrar", async () => {
      if (!confirm(`Borrar la fuente "${fuente.nombre}"?`)) return;
      await fetch(`/api/fuentes/${fuente.id}`, { method: "DELETE" });
      refrescarLista();
    }, "peligro"),
  );

  const estado = document.createElement("div");
  estado.className = "fuente-estado";

  tarjeta.append(cabecera, destino, acciones, estado);
  return tarjeta;
}

function describir(fuente) {
  const c = fuente.config || {};
  if (fuente.tipo === "supabase") {
    return `proyecto ${c.project_ref || "?"}${c.url ? " · conexion directa" : " · via MCP"}`;
  }
  if (c.url) return "cadena de conexion";
  const instancia = c.instancia ? `\\${c.instancia}` : "";
  return `${c.usuario || "?"}@${c.host || "?"}${instancia}:${c.puerto || "?"}/${c.base || "?"}`;
}

function chip(texto, clase) {
  const nodo = document.createElement("span");
  nodo.className = `chip chip-${clase}`;
  nodo.textContent = texto;
  return nodo;
}

function boton(texto, alPulsar, clase = "") {
  const nodo = document.createElement("button");
  nodo.className = `boton-mini ${clase}`;
  nodo.textContent = texto;
  nodo.addEventListener("click", alPulsar);
  return nodo;
}

// --------------------------------------------------------------------------
// Formulario dinamico
// --------------------------------------------------------------------------

function dibujarCampos(tipo, valores = {}) {
  const definicion = TIPOS[tipo];
  camposContenedor.innerHTML = "";
  if (!definicion) return;

  const nota = document.createElement("p");
  nota.className = "ayuda-tipo";
  nota.textContent = definicion.descripcion;
  camposContenedor.appendChild(nota);

  for (const campo of definicion.campos) {
    const fila = document.createElement("div");
    fila.className = "campo";

    const etiqueta = document.createElement("label");
    etiqueta.textContent = campo.etiqueta + (campo.requerido ? " *" : "");
    etiqueta.htmlFor = `campo-${campo.nombre}`;

    let entrada;
    if (campo.tipo === "booleano") {
      entrada = document.createElement("input");
      entrada.type = "checkbox";
      entrada.checked = valores[campo.nombre] ?? campo.por_defecto;
      fila.classList.add("campo-casilla");
    } else {
      entrada = document.createElement("input");
      entrada.type = campo.tipo === "secreto" ? "password" : "text";
      if (campo.tipo === "numero") entrada.inputMode = "numeric";
      entrada.placeholder = campo.ejemplo || "";
      // Los secretos llegan enmascarados: se dejan vacios y solo se envian
      // si el usuario escribe uno nuevo.
      entrada.value = campo.tipo === "secreto"
        ? ""
        : (valores[campo.nombre] ?? campo.por_defecto ?? "");
      if (campo.tipo === "secreto" && valores[campo.nombre]) {
        entrada.placeholder = `guardado (${valores[campo.nombre]}) — deja vacio para conservarlo`;
      }
    }

    entrada.id = `campo-${campo.nombre}`;
    entrada.dataset.campo = campo.nombre;
    entrada.dataset.tipo = campo.tipo;

    fila.append(etiqueta, entrada);

    if (campo.ayuda) {
      const ayuda = document.createElement("small");
      ayuda.textContent = campo.ayuda;
      fila.appendChild(ayuda);
    }

    camposContenedor.appendChild(fila);
  }
}

function leerFormulario() {
  const config = {};
  for (const entrada of camposContenedor.querySelectorAll("[data-campo]")) {
    config[entrada.dataset.campo] =
      entrada.dataset.tipo === "booleano" ? entrada.checked : entrada.value.trim();
  }

  return {
    id: editando,
    nombre: $$("nombre-fuente").value.trim(),
    tipo: $$("tipo-fuente").value,
    notas: $$("notas-fuente").value.trim(),
    solo_lectura: $$("solo-lectura-fuente").checked,
    activa: $$("activa-fuente").checked,
    config,
  };
}

function cargarEnFormulario(fuente) {
  editando = fuente.id;
  $$("nombre-fuente").value = fuente.nombre;
  $$("tipo-fuente").value = fuente.tipo;
  $$("notas-fuente").value = fuente.notas || "";
  $$("solo-lectura-fuente").checked = fuente.solo_lectura;
  $$("activa-fuente").checked = fuente.activa;
  dibujarCampos(fuente.tipo, fuente.config);

  $$("titulo-formulario").textContent = `Editando: ${fuente.nombre}`;
  $$("btn-cancelar-edicion").hidden = false;
  resultadoPrueba.textContent = "";
  formulario.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function limpiarFormulario() {
  editando = null;
  $$("nombre-fuente").value = "";
  $$("notas-fuente").value = "";
  $$("solo-lectura-fuente").checked = true;
  $$("activa-fuente").checked = true;
  dibujarCampos($$("tipo-fuente").value);
  $$("titulo-formulario").textContent = "Agregar fuente";
  $$("btn-cancelar-edicion").hidden = true;
  resultadoPrueba.textContent = "";
  resultadoPrueba.className = "resultado-prueba";
}

// --------------------------------------------------------------------------
// Probar, guardar, explorar
// --------------------------------------------------------------------------

function mostrarResultado(nodo, resultado) {
  nodo.className = `resultado-prueba ${resultado.ok ? "bien" : "mal"}`;
  if (resultado.ok) {
    const partes = [`Conectado en ${resultado.latencia_ms} ms`];
    if (resultado.base) partes.push(`base "${resultado.base}"`);
    if (resultado.tablas != null) partes.push(`${resultado.tablas} tablas`);
    nodo.textContent = partes.join(" · ");
    if (resultado.version) nodo.title = resultado.version;
  } else {
    nodo.textContent = resultado.mensaje;
  }
}

$$("btn-probar-fuente").addEventListener("click", async () => {
  resultadoPrueba.className = "resultado-prueba";
  resultadoPrueba.textContent = "Probando...";
  const resultado = await (await fetch("/api/fuentes/probar", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(leerFormulario()),
  })).json();
  mostrarResultado(resultadoPrueba, resultado);
});

async function probarGuardada(fuente, nodo) {
  nodo.className = "fuente-estado";
  nodo.textContent = "Probando...";
  const resultado = await (await fetch("/api/fuentes/probar", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: fuente.id, tipo: fuente.tipo, config: {} }),
  })).json();
  nodo.className = `fuente-estado ${resultado.ok ? "bien" : "mal"}`;
  nodo.textContent = resultado.ok
    ? `Conectado en ${resultado.latencia_ms} ms${resultado.tablas != null ? ` · ${resultado.tablas} tablas` : ""}`
    : resultado.mensaje;
}

formulario.addEventListener("submit", async (evento) => {
  evento.preventDefault();
  const respuesta = await fetch("/api/fuentes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(leerFormulario()),
  });
  const datos = await respuesta.json();

  if (!respuesta.ok) {
    resultadoPrueba.className = "resultado-prueba mal";
    resultadoPrueba.textContent = datos.error || "No se pudo guardar.";
    return;
  }

  limpiarFormulario();
  await refrescarLista();
});

$$("btn-cancelar-edicion").addEventListener("click", limpiarFormulario);
$$("btn-cerrar-fuentes").addEventListener("click", () => { panel.hidden = true; });

async function verEsquema(id, nodo) {
  nodo.className = "fuente-estado";
  nodo.textContent = "Leyendo esquema...";
  const datos = await (await fetch(`/api/fuentes/${id}/esquema`)).json();

  if (datos.error) {
    nodo.className = "fuente-estado mal";
    nodo.textContent = datos.error;
    return;
  }

  nodo.className = "fuente-estado";
  nodo.innerHTML = "";
  const detalle = document.createElement("details");
  detalle.open = true;

  const resumen = document.createElement("summary");
  resumen.textContent = `${datos.tablas.length} tablas`;
  detalle.appendChild(resumen);

  const cuerpo = document.createElement("div");
  cuerpo.className = "esquema-tablas";
  for (const tabla of datos.tablas) {
    const fila = document.createElement("div");
    fila.className = "esquema-tabla";
    const nombre = document.createElement("strong");
    nombre.textContent = tabla.tabla;
    const columnas = document.createElement("span");
    columnas.textContent = tabla.columnas;
    fila.append(nombre, columnas);
    cuerpo.appendChild(fila);
  }
  detalle.appendChild(cuerpo);
  nodo.appendChild(detalle);
}

// --------------------------------------------------------------------------
// Consola SQL
// --------------------------------------------------------------------------

const consola = $$("consola-sql");
let fuenteEnConsola = null;

function abrirConsola(fuente) {
  fuenteEnConsola = fuente;
  consola.hidden = false;
  $$("consola-titulo").textContent = `Consultar: ${fuente.nombre}`;
  $$("consola-nota").textContent = fuente.solo_lectura
    ? "Solo lectura: unicamente SELECT."
    : "Esta fuente permite escritura. Cuidado.";
  $$("consola-salida").innerHTML = "";
  $$("consola-sql-texto").focus();
}

$$("btn-cerrar-consola").addEventListener("click", () => { consola.hidden = true; });

$$("btn-ejecutar-sql").addEventListener("click", ejecutarSql);
$$("consola-sql-texto").addEventListener("keydown", (evento) => {
  if (evento.key === "Enter" && (evento.ctrlKey || evento.metaKey)) ejecutarSql();
});

async function ejecutarSql() {
  const sql = $$("consola-sql-texto").value.trim();
  const salida = $$("consola-salida");
  if (!sql || !fuenteEnConsola) return;

  salida.innerHTML = '<p class="vacio">Ejecutando...</p>';

  const inicio = performance.now();
  const respuesta = await fetch(`/api/fuentes/${fuenteEnConsola.id}/consultar`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sql }),
  });
  const datos = await respuesta.json();
  const tardanza = Math.round(performance.now() - inicio);

  if (datos.error) {
    salida.innerHTML = "";
    const error = document.createElement("p");
    error.className = "resultado-prueba mal";
    error.textContent = datos.error;
    salida.appendChild(error);
    return;
  }

  if (!datos.filas.length) {
    salida.innerHTML = `<p class="vacio">Sin resultados (${tardanza} ms)</p>`;
    return;
  }

  salida.innerHTML = "";
  const meta = document.createElement("p");
  meta.className = "consola-meta";
  meta.textContent = `${datos.total} filas · ${tardanza} ms`;
  salida.appendChild(meta);
  salida.appendChild(tabla(datos.filas));
}

function tabla(filas) {
  const envoltorio = document.createElement("div");
  envoltorio.className = "tabla-scroll";

  const tabla = document.createElement("table");
  const columnas = Object.keys(filas[0]);

  const cabecera = document.createElement("thead");
  const filaCabecera = document.createElement("tr");
  for (const columna of columnas) {
    const celda = document.createElement("th");
    celda.textContent = columna;
    filaCabecera.appendChild(celda);
  }
  cabecera.appendChild(filaCabecera);

  const cuerpo = document.createElement("tbody");
  for (const fila of filas) {
    const tr = document.createElement("tr");
    for (const columna of columnas) {
      const celda = document.createElement("td");
      const valor = fila[columna];
      celda.textContent =
        valor === null ? "—"
        : typeof valor === "object" ? JSON.stringify(valor)
        : String(valor);
      if (valor === null) celda.className = "nulo";
      tr.appendChild(celda);
    }
    cuerpo.appendChild(tr);
  }

  tabla.append(cabecera, cuerpo);
  envoltorio.appendChild(tabla);
  return envoltorio;
}
