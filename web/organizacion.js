/* Panel de organizacion: solo lo ve quien la administra (es_admin_org).
   Lista los miembros y permite sumar uno nuevo. */

const $$ = (id) => document.getElementById(id);

const panel = $$("panel-organizacion");
const lista = $$("lista-organizacion");
const formulario = $$("form-miembro");
const resultado = $$("resultado-miembro");

export async function abrirPanelOrganizacion() {
  panel.hidden = false;
  resultado.textContent = "";
  await refrescarMiembros();
}

async function refrescarMiembros() {
  const datos = await (await fetch("/api/organizacion")).json();

  if (!datos.organizacion) {
    lista.innerHTML = '<p class="vacio">No pertenecés a ninguna organización.</p>';
    formulario.hidden = true;
    return;
  }

  $$("titulo-organizacion").textContent = datos.organizacion;
  pintarConsumido(datos.consumido);

  lista.innerHTML = "";
  for (const miembro of datos.miembros) {
    const fila = document.createElement("div");
    fila.className = "fuente";

    const cabecera = document.createElement("div");
    cabecera.className = "fuente-cabecera";
    const titulo = document.createElement("div");
    titulo.className = "fuente-titulo";
    titulo.textContent = miembro.nombre;
    cabecera.append(titulo);
    if (miembro.es_admin_org) {
      const chip = document.createElement("span");
      chip.className = "chip chip-ok";
      chip.textContent = "administra";
      cabecera.appendChild(chip);
    }

    const destino = document.createElement("div");
    destino.className = "fuente-destino";
    destino.textContent = miembro.email;

    fila.append(cabecera, destino);
    lista.appendChild(fila);
  }
}

function pintarConsumido(consumido) {
  const destino = $$("cuenta-organizacion");
  if (!consumido) {
    destino.hidden = true;
    return;
  }

  destino.hidden = false;
  destino.innerHTML = "";

  const rejilla = document.createElement("div");
  rejilla.className = "tarjetas";

  const tarjetas = [
    {
      etiqueta: "Consumido",
      valor: `$${(consumido.cobrado ?? 0).toFixed(2)}`,
      pie: "desde siempre",
      destacada: true,
    },
    {
      etiqueta: "Consultas",
      valor: (consumido.consultas ?? 0).toLocaleString("es"),
      pie: `${(consumido.tokens ?? 0).toLocaleString("es")} tokens`,
    },
  ];

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

  destino.appendChild(rejilla);
}

formulario.addEventListener("submit", async (evento) => {
  evento.preventDefault();
  resultado.textContent = "";

  const respuesta = await fetch("/api/organizacion/usuarios", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      nombre: $$("nombre-miembro").value.trim(),
      email: $$("email-miembro").value.trim(),
      password: $$("password-miembro").value,
    }),
  });
  const datos = await respuesta.json();

  if (!respuesta.ok) {
    resultado.className = "resultado-prueba mal";
    resultado.textContent = datos.error || "No se pudo agregar.";
    return;
  }

  formulario.reset();
  resultado.className = "resultado-prueba bien";
  resultado.textContent = "Agregado.";
  await refrescarMiembros();
});

$$("btn-cerrar-organizacion").addEventListener("click", () => {
  panel.hidden = true;
});
