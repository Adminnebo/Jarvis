/* Lo que comparten las tres apps con la estructura comun (/):
   - solas (fuera de la estructura) redirigen a ella, a su pestaña;
   - dentro, esconden su barra propia (la de la estructura ya esta);
   - cuentan que tienen abierto (contexto para Jarvis), y atienden "refrescar" y "abrir";
   - Ctrl+J abre Jarvis aunque el foco este dentro de la app. */

export const EMBEBIDO = window.self !== window.top;

export function enEstructura(app, { refrescar = () => {}, abrir = () => {} } = {}) {
  if (!EMBEBIDO) {
    location.replace(`/#${app}`);
    return { contexto: () => {} };
  }
  document.body.classList.add("embebido");
  window.addEventListener("message", (e) => {
    if (e.origin !== location.origin || e.source !== parent || !e.data) return;
    if (e.data.tipo === "refrescar") refrescar();
    else if (e.data.tipo === "abrir" && e.data.id) abrir(String(e.data.id));
  });
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "j") {
      e.preventDefault();
      parent.postMessage({ tipo: "atajo-jarvis" }, location.origin);
    }
  });
  return {
    /** Lo que la persona tiene abierto: `texto` para Jarvis (con ids), `corto` para el chip. Null = nada. */
    contexto(texto, corto) {
      parent.postMessage({ tipo: "contexto", texto: texto || "", corto: corto || "" }, location.origin);
    },
  };
}
