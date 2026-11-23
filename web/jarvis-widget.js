/* Jarvis dentro de un panel (portaljh). Se carga desde el dominio de Jarvis:
 *
 *   <script src="https://asistente.neboaiconsulting.com/jarvis-widget.js" defer></script>
 *   JarvisWidget.init({ panel: "cobranzas", getToken: () => token, getContexto: () => ({ texto, corto }) });
 *
 * Habla con Jarvis con el token de Supabase del panel (sin cookies). Solo aparece si la
 * persona puede usar Jarvis. Todo vive en un shadow root: no toca los estilos del panel.
 * Ver docs/superpowers/specs/2026-11-23-jarvis-en-paneles-jh-design.md.
 */
(function () {
  "use strict";
  if (window.JarvisWidget && window.JarvisWidget.init) return;

  var BASE = (function () {
    try { return new URL(document.currentScript.src).origin; } catch (e) { return "https://asistente.neboaiconsulting.com"; }
  })();

  var CSS = [
    ":host{all:initial}",
    "*{box-sizing:border-box;font-family:Inter,system-ui,-apple-system,'Segoe UI',sans-serif}",
    ".orbe{position:fixed;right:20px;bottom:88px;z-index:2147483000;width:52px;height:52px;border-radius:50%;border:0;cursor:pointer;",
    "background:radial-gradient(circle at 35% 30%,#d6eaff,#4da3ff 50%,#1b5fae);box-shadow:0 0 0 1px rgba(77,163,255,.4),0 6px 22px rgba(27,95,174,.55);",
    "display:grid;place-items:center;transition:transform .15s}",
    ".orbe:hover{transform:scale(1.07)}.orbe:focus-visible{outline:2px solid #4da3ff;outline-offset:3px}",
    ".orbe span{width:16px;height:16px;border-radius:50%;background:rgba(255,255,255,.85);filter:blur(3px)}",
    ".panel{position:fixed;right:20px;bottom:20px;z-index:2147483001;width:390px;height:min(620px,calc(100vh - 40px));display:flex;flex-direction:column;",
    "background:#111113;color:#ececf0;border:1px solid #26262b;border-radius:18px;box-shadow:0 24px 60px rgba(0,0,0,.45);overflow:hidden;font-size:14px;line-height:1.45}",
    ".panel[hidden],.chip[hidden],.dictar[hidden]{display:none}",
    "header{height:54px;flex:none;display:flex;align-items:center;gap:10px;padding:0 8px 0 14px;border-bottom:1px solid #232327}",
    "header .mini{width:24px;height:24px;border-radius:50%;background:radial-gradient(circle at 35% 30%,#d6eaff,#4da3ff 50%,#1b5fae);flex:none}",
    "header strong{flex:1;font-weight:600}header small{color:#8b8b94;font-weight:400;margin-left:6px}",
    ".icono{width:34px;height:34px;border-radius:50%;border:0;background:none;color:#8b8b94;cursor:pointer;display:grid;place-items:center}",
    ".icono:hover{background:rgba(255,255,255,.08);color:#ececf0}.icono svg{width:20px;height:20px;fill:currentColor}",
    ".msjs{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:10px}",
    ".hola{margin:auto 0;text-align:center;padding:0 10px}.hola p{margin:0 0 8px}.tenue{color:#8b8b94;font-size:13px}",
    ".m{max-width:88%;padding:9px 12px;border-radius:14px;white-space:pre-wrap;overflow-wrap:anywhere}",
    ".m.yo{align-self:flex-end;background:#4da3ff;color:#04101f;border-bottom-right-radius:4px}",
    ".m.j{align-self:flex-start;background:#17171b;border:1px solid #26262b;border-bottom-left-radius:4px}",
    ".m.err{align-self:flex-start;color:#ff6b6b;background:rgba(255,92,92,.08)}",
    ".m .sobre{display:block;font-size:11px;opacity:.75;margin-bottom:3px}",
    ".est{align-self:flex-start;font-size:12px;color:#8b8b94;display:flex;gap:8px;align-items:center}",
    ".est:before{content:'';width:8px;height:8px;border-radius:50%;background:#4da3ff;animation:l 1s infinite}@keyframes l{50%{opacity:.25}}",
    ".chip{margin:0 12px 8px;display:flex;align-items:center;gap:8px;padding:5px 5px 5px 12px;border-radius:16px;background:rgba(77,163,255,.14);color:#4da3ff;font-size:12.5px}",
    ".chip span{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
    ".chip button{width:22px;height:22px;border-radius:50%;border:0;background:none;color:inherit;cursor:pointer;font-size:16px;line-height:1}",
    "form{display:flex;align-items:flex-end;gap:4px;margin:0 12px 12px;padding:5px 5px 5px 14px;border:1px solid #26262b;border-radius:22px;background:#17171b}",
    "form:focus-within{border-color:#4da3ff}",
    "textarea{flex:1;resize:none;border:0;outline:none;background:none;color:#ececf0;font-size:14px;max-height:140px;padding:7px 0}",
    "textarea::placeholder{color:#6f6f78}.enviar{color:#4da3ff}.dictando{color:#ff6b6b}",
    "@media (max-width:600px){.panel{right:0;bottom:0;width:100%;height:100%;border-radius:0}.orbe{right:14px;bottom:84px}}",
  ].join("");

  var SVG = {
    cerrar: '<svg viewBox="0 0 24 24"><path d="M19 6.4L17.6 5 12 10.6 6.4 5 5 6.4 10.6 12 5 17.6 6.4 19 12 13.4 17.6 19 19 17.6 13.4 12z"/></svg>',
    nuevo: '<svg viewBox="0 0 24 24"><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/></svg>',
    mic: '<svg viewBox="0 0 24 24"><path d="M12 15c1.7 0 3-1.3 3-3V5c0-1.7-1.3-3-3-3S9 3.3 9 5v7c0 1.7 1.3 3 3 3zm5.3-3c0 3-2.5 5.1-5.3 5.1S6.7 15 6.7 12H5c0 3.4 2.7 6.2 6 6.7V22h2v-3.3c3.3-.5 6-3.3 6-6.7h-1.7z"/></svg>',
    enviar: '<svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>',
  };

  var opciones = null, raiz = null, nombre = "Jarvis", ocupado = false, ignorado = null;

  function token() { try { return opciones.getToken() || ""; } catch (e) { return ""; } }
  function contexto() {
    try {
      var c = opciones.getContexto ? opciones.getContexto() : null;
      if (!c || !c.texto) return null;
      return { texto: String(c.texto).slice(0, 600), corto: String(c.corto || c.texto).slice(0, 80) };
    } catch (e) { return null; }
  }
  function contextoActual() {
    var c = contexto();
    return c && c.texto !== ignorado ? c : null;
  }
  function $(sel) { return raiz.querySelector(sel); }

  function pintarChip() {
    var c = contextoActual();
    $(".chip").hidden = !c;
    if (c) $(".chip span").textContent = "Sobre: " + c.corto;
  }

  function burbuja(clase, texto) {
    $(".hola").hidden = true;
    var d = document.createElement("div");
    d.className = "m " + clase;
    d.textContent = texto;
    $(".msjs").appendChild(d);
    $(".msjs").scrollTop = $(".msjs").scrollHeight;
    return d;
  }

  function abrir(si) {
    var panel = $(".panel");
    if (si === undefined) si = panel.hidden;
    panel.hidden = !si;
    $(".orbe").hidden = si;
    if (si) { pintarChip(); $("textarea").focus(); }
  }

  async function preguntar(mensaje) {
    if (!mensaje.trim() || ocupado) return;
    ocupado = true;
    var c = contextoActual();
    var mio = burbuja("yo", mensaje);
    if (c) { var s = document.createElement("span"); s.className = "sobre"; s.textContent = "Sobre: " + c.corto; mio.prepend(s); }
    var est = document.createElement("div");
    est.className = "est";
    est.textContent = "Pensando…";
    $(".msjs").appendChild(est);
    var resp = null, texto = "", herramientas = false;
    try {
      var r = await fetch(BASE + "/api/chat", {
        method: "POST", credentials: "omit",
        headers: { "Content-Type": "application/json", "Authorization": "Bearer " + token() },
        body: JSON.stringify({ mensaje: mensaje, panel: opciones.panel, contexto: c ? c.texto : "" }),
      });
      if (!r.ok) {
        var dato = await r.json().catch(function () { return {}; });
        throw new Error(dato.error || (r.status === 401 ? "Tu sesión venció: recarga el panel." : "Error " + r.status));
      }
      var lector = r.body.getReader(), dec = new TextDecoder(), pend = "";
      while (true) {
        var paso = await lector.read();
        if (paso.done) break;
        pend += dec.decode(paso.value, { stream: true });
        var bloques = pend.split("\n\n");
        pend = bloques.pop();
        for (var i = 0; i < bloques.length; i++) {
          var linea = bloques[i].split("\n").find(function (l) { return l.indexOf("data: ") === 0; });
          if (!linea) continue;
          var ev = JSON.parse(linea.slice(6));
          if (ev.tipo === "texto") {
            texto += ev.dato;
            if (!resp) resp = burbuja("j", "");
            resp.textContent = texto;
            est.remove();
            $(".msjs").scrollTop = $(".msjs").scrollHeight;
          } else if (ev.tipo === "herramienta") {
            herramientas = true;
            est.textContent = ev.dato === "consultar_panel" ? "Consultando el panel…" : "Usando " + String(ev.dato).replace(/_/g, " ") + "…";
          } else if (ev.tipo === "error") {
            burbuja("err", ev.dato);
          }
        }
      }
    } catch (e) {
      burbuja("err", e.message);
    } finally {
      est.remove();
      ocupado = false;
      if (herramientas) window.dispatchEvent(new CustomEvent("jarvis:herramientas"));
    }
  }

  function montar() {
    var host = document.createElement("div");
    host.id = "jarvis-widget";
    document.body.appendChild(host);
    raiz = host.attachShadow({ mode: "open" });
    raiz.innerHTML = "<style>" + CSS + "</style>" +
      '<button class="orbe" type="button" aria-label="Pregúntale a ' + nombre + ' (Ctrl+J)" title="Pregúntale a ' + nombre + ' (Ctrl+J)"><span></span></button>' +
      '<section class="panel" hidden role="dialog" aria-label="' + nombre + '">' +
        '<header><span class="mini"></span><strong></strong>' +
        '<button class="icono nuevo" type="button" title="Nueva conversación en pantalla" aria-label="Limpiar">' + SVG.nuevo + '</button>' +
        '<button class="icono cerrar" type="button" aria-label="Cerrar">' + SVG.cerrar + '</button></header>' +
        '<div class="msjs"><div class="hola"><p>Pregúntame lo que necesites de este panel.</p>' +
        '<p class="tenue">Veo lo que tienes abierto y puedo consultar los datos que tú puedes ver aquí.</p></div></div>' +
        '<div class="chip" hidden><span></span><button type="button" aria-label="No usar esto">×</button></div>' +
        '<form><textarea rows="1" placeholder="Escribe o dicta…"></textarea>' +
        '<button class="icono dictar" type="button" aria-label="Dictar" hidden>' + SVG.mic + '</button>' +
        '<button class="icono enviar" type="submit" aria-label="Enviar">' + SVG.enviar + '</button></form>' +
      "</section>";
    $("header strong").textContent = nombre;
    $(".orbe").addEventListener("click", function () { abrir(true); });
    $(".cerrar").addEventListener("click", function () { abrir(false); });
    $(".nuevo").addEventListener("click", function () {
      $(".msjs").querySelectorAll(".m,.est").forEach(function (n) { n.remove(); });
      $(".hola").hidden = false;
    });
    $(".chip button").addEventListener("click", function () { var c = contexto(); ignorado = c ? c.texto : null; pintarChip(); });
    var area = $("textarea");
    $("form").addEventListener("submit", function (e) {
      e.preventDefault();
      var m = area.value;
      area.value = "";
      area.style.height = "auto";
      preguntar(m);
    });
    area.addEventListener("keydown", function (e) {
      e.stopPropagation();   // que los atajos del panel no se coman lo que se escribe
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("form").requestSubmit(); }
      if (e.key === "Escape") abrir(false);
    });
    area.addEventListener("input", function () { area.style.height = "auto"; area.style.height = Math.min(area.scrollHeight, 140) + "px"; });
    document.addEventListener("keydown", function (e) {
      if ((e.ctrlKey || e.metaKey) && (e.key === "j" || e.key === "J")) { e.preventDefault(); abrir(); }
    });
    // Dictado: se graba con el microfono y Jarvis lo pasa a texto (/api/dictado). El
    // reconocimiento del navegador solo servia en Chrome/Edge de escritorio y fallaba callado.
    if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder) {
      var boton = $(".dictar"), grabadora = null, flujo = null, trozos = [], aviso = null, tope = null;
      boton.hidden = false;
      var avisar = function (t) {
        if (!t) { if (aviso) aviso.remove(); aviso = null; return; }
        if (!aviso) { aviso = document.createElement("div"); aviso.className = "est"; $(".msjs").appendChild(aviso); $(".hola").hidden = true; }
        aviso.textContent = t;
        $(".msjs").scrollTop = $(".msjs").scrollHeight;
      };
      var soltar = function () {
        if (flujo) flujo.getTracks().forEach(function (t) { t.stop(); });
        flujo = null; grabadora = null; clearTimeout(tope);
        boton.classList.remove("dictando");
        boton.setAttribute("aria-label", "Dictar");
      };
      var motivo = function (e) {
        var n = e && e.name;
        if (n === "NotAllowedError" || n === "SecurityError")
          return "El navegador bloqueó el micrófono. Permítelo en el candado de la barra de direcciones (y en la configuración del sistema si hace falta) y vuelve a intentar.";
        if (n === "NotFoundError") return "No encontré ningún micrófono conectado.";
        if (n === "NotReadableError") return "Otra aplicación está usando el micrófono; ciérrala y vuelve a intentar.";
        return "No pude usar el micrófono: " + ((e && e.message) || "error desconocido");
      };
      var transcribir = async function (blob) {
        if (!blob.size) { avisar(null); return; }
        avisar("Transcribiendo…");
        try {
          var datos = new FormData();
          var ext = (blob.type.indexOf("mp4") >= 0) ? "mp4" : (blob.type.indexOf("ogg") >= 0 ? "ogg" : "webm");
          datos.append("audio", blob, "dictado." + ext);
          var r = await fetch(BASE + "/api/dictado", { method: "POST", credentials: "omit",
            headers: { "Authorization": "Bearer " + token() }, body: datos });
          var d = await r.json().catch(function () { return {}; });
          if (!r.ok) throw new Error(d.error || (r.status === 401 ? "Tu sesión venció: recarga el panel." : "Error " + r.status));
          avisar(null);
          if (d.texto) {
            area.value = (area.value ? area.value.replace(/\s*$/, " ") : "") + d.texto;
            area.dispatchEvent(new Event("input"));
          } else burbuja("err", "No se entendió nada en la grabación.");
        } catch (e) { avisar(null); burbuja("err", e.message); }
        area.focus();
      };
      boton.addEventListener("click", async function () {
        if (grabadora) { grabadora.stop(); return; }
        try {
          flujo = await navigator.mediaDevices.getUserMedia({ audio: true });
        } catch (e) { soltar(); burbuja("err", motivo(e)); return; }
        trozos = [];
        try { grabadora = new MediaRecorder(flujo); } catch (e) { soltar(); burbuja("err", motivo(e)); return; }
        grabadora.ondataavailable = function (e) { if (e.data && e.data.size) trozos.push(e.data); };
        grabadora.onstop = function () {
          var tipo = (grabadora && grabadora.mimeType) || "audio/webm";
          soltar();
          transcribir(new Blob(trozos, { type: tipo }));
        };
        grabadora.start();
        boton.classList.add("dictando");
        boton.setAttribute("aria-label", "Terminar dictado");
        avisar("Escuchando… toca el micrófono para terminar.");
        tope = setTimeout(function () { if (grabadora) grabadora.stop(); }, 120000);
      });
    }
    // El contexto cambia mientras el panel esta abierto: el chip se mantiene al dia.
    setInterval(function () { if (!$(".panel").hidden) pintarChip(); }, 1500);
  }

  async function init(config) {
    if (opciones) return;
    opciones = config || {};
    if (!opciones.panel || typeof opciones.getToken !== "function") return;
    // Solo quien puede usar Jarvis lo ve. Se espera el token: el panel puede tardar en tenerlo.
    for (var intento = 0; intento < 20 && !token(); intento++) await new Promise(function (r) { setTimeout(r, 500); });
    if (!token()) return;
    try {
      var r = await fetch(BASE + "/api/estado", { credentials: "omit", headers: { "Authorization": "Bearer " + token() } });
      if (!r.ok) return;
      var estado = await r.json();
      nombre = estado.nombre || "Jarvis";
    } catch (e) { return; }
    if (document.body) montar(); else document.addEventListener("DOMContentLoaded", montar);
  }

  window.JarvisWidget = { init: init, abrir: function () { if (raiz) abrir(true); } };
})();
