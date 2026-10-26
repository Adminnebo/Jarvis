/* El avatar del asistente: tres videos (reposo, escuchando, hablando) dibujados
   en un canvas con un holograma sutil. Sin videos, la foto animada (MediaPipe
   ubica ojos y boca); sin foto, queda el orbe de siempre.

   El estado se toma de las clases que app.js ya le pone al orbe (escuchando,
   pensando, hablando): asi no hay que tocar la logica de voz. El orbe se
   esconde con CSS pero sigue recibiendo esas clases. */

const W = 480, H = 600;
const FUNDIDO_MS = 300, EMPALME_MS = 400;
const MEDIAPIPE = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14";

const lienzo = document.getElementById("avatar");
const ctx = lienzo.getContext("2d");
const orbe = document.getElementById("orbe");
const capa = Object.assign(document.createElement("canvas"), { width: W, height: H });
const cc = capa.getContext("2d");
const tinte = Object.assign(document.createElement("canvas"), { width: W, height: H });
const tc = tinte.getContext("2d");

let videos = {};            // estado -> <video>
let foto = null;            // { base, pt } para la foto animada
let actual = "reposo", anterior = null, desde = 0;
let nivelVoz = 0;           // 0..1, lo empuja app.js en la voz en vivo
let cuadrosLentos = 0, sinEfecto = false, ultimo = 0;
let configurado = "";       // para no recargar si nada cambio

export function nivelDeVoz(valor) { nivelVoz = Math.max(0, Math.min(1, valor)); }

function estadoDelOrbe() {
  if (orbe.classList.contains("hablando")) return "hablando";
  if (orbe.classList.contains("escuchando") || orbe.classList.contains("pensando")) return "escuchando";
  return "reposo";
}

new MutationObserver(() => {
  const nuevo = estadoDelOrbe();
  if (nuevo !== actual) { anterior = actual; actual = nuevo; desde = performance.now(); }
}).observe(orbe, { attributes: true, attributeFilter: ["class"] });

/* Cada estado son DOS copias del mismo video: cuando a la que se ve le quedan
   EMPALME_MS, la otra arranca desde el principio y se funden. Asi el bucle no
   muestra el salto entre el ultimo cuadro y el primero. */
function nuevoVideo(url) {
  const copia = () => Object.assign(document.createElement("video"),
    { src: url, muted: true, loop: false, playsInline: true, preload: "auto" });
  const par = { a: copia(), b: copia(), activa: "a" };
  par.a.play().catch(() => {});
  return par;
}

/** La llama app.js con estado.asistente cada vez que carga /api/estado. */
export async function configurarAvatar(asistente) {
  const clave = JSON.stringify(asistente || {});
  if (clave === configurado) return;
  configurado = clave;
  const urls = asistente?.videos || {};
  videos = {};
  for (const [estado, url] of Object.entries(urls)) if (url) videos[estado] = nuevoVideo(url);
  foto = null;
  if (!videos.reposo && asistente?.foto) foto = await prepararFoto(asistente.foto).catch(() => null);
  const hay = Boolean(videos.reposo || foto);
  lienzo.hidden = !hay;
  document.body.classList.toggle("con-avatar", hay);
  if (hay && !ultimo) requestAnimationFrame(dibujar);
}

// ---------------------------------------------------------------- foto animada

async function prepararFoto(url) {
  const { FaceLandmarker, FilesetResolver } = await import(`${MEDIAPIPE}/vision_bundle.mjs`);
  const resolver = await FilesetResolver.forVisionTasks(`${MEDIAPIPE}/wasm`);
  const detector = await FaceLandmarker.createFromOptions(resolver, {
    baseOptions: { modelAssetPath: "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task" },
    runningMode: "IMAGE", numFaces: 1,
  });
  const img = new Image();
  await new Promise((ok, mal) => { img.onload = ok; img.onerror = mal; img.src = url; });
  const lm = detector.detect(img).faceLandmarks[0];
  if (!lm) return null;
  const xs = lm.map((p) => p.x * img.width), ys = lm.map((p) => p.y * img.height);
  const cx = (Math.min(...xs) + Math.max(...xs)) / 2, cy = (Math.min(...ys) + Math.max(...ys)) / 2;
  const escala = (W * 0.42) / (Math.max(...xs) - Math.min(...xs));
  const x0 = cx - W / 2 / escala, y0 = cy - (H * 0.36) / escala;
  const base = Object.assign(document.createElement("canvas"), { width: W, height: H });
  base.getContext("2d").drawImage(img, x0, y0, W / escala, H / escala, 0, 0, W, H);
  const P = (i) => ({ x: (lm[i].x * img.width - x0) * escala, y: (lm[i].y * img.height - y0) * escala });
  return {
    base,
    pt: { la: P(13), lb: P(14), ci: P(61), cd: P(291), me: P(152),
          ojos: [{ ar: P(159), ab: P(145), a: P(33), b: P(133) }, { ar: P(386), ab: P(374), a: P(362), b: P(263) }] },
    parpadeo: 0, proximo: performance.now() + 2500,
  };
}

function dibujarFoto(t, apertura) {
  const { base, pt } = foto;
  const r = Math.sin(t / 1300) * 0.01 + (actual === "escuchando" ? 0.02 : 0);
  cc.save(); cc.translate(W / 2, H * 0.6); cc.rotate(Math.sin(t / 2700) * 0.01); cc.scale(1 + r, 1 + r); cc.translate(-W / 2, -H * 0.6);
  cc.drawImage(base, 0, 0);
  if (t > foto.proximo) { foto.parpadeo = t; foto.proximo = t + 2000 + Math.random() * 4000; }
  const f = (t - foto.parpadeo) / 150, cierre = f < 2 ? 1 - Math.abs(1 - f) : 0;
  for (const o of pt.ojos) if (cierre > 0) {
    const x = Math.min(o.a.x, o.b.x) - 5, w = Math.abs(o.b.x - o.a.x) + 10, h = Math.max(o.ab.y - o.ar.y, 5) + 8, y = o.ar.y - 6;
    cc.save(); cc.beginPath(); cc.ellipse(x + w / 2, y + h / 2, w / 2, h / 2, 0, 0, 7); cc.clip();
    cc.drawImage(base, x, y - h * 0.6, w, h * 0.6, x, y, w, h * cierre); cc.restore();
  }
  if (apertura > 0.02) {
    const d = apertura * (pt.me.y - pt.la.y) * 0.22, an = pt.cd.x - pt.ci.x, x = pt.ci.x - an * 0.45, w = an * 1.9;
    const yc = (pt.la.y + pt.lb.y) / 2, al = (pt.me.y - yc) + an * 0.15;
    cc.save(); cc.beginPath(); cc.ellipse(x + w / 2, yc + al / 2, w / 2, al / 2 + d, 0, 0, 7); cc.clip();
    cc.drawImage(base, x, yc, w, al, x, yc + d, w, al); cc.restore();
    cc.fillStyle = "#2a0d0e"; cc.beginPath(); cc.ellipse((pt.ci.x + pt.cd.x) / 2, yc + d / 2, an * 0.36, d / 2 + 1, 0, 0, 7); cc.fill();
  }
  cc.restore();
}

// ---------------------------------------------------------------- videos

function cuadroDe(par, alfa) {
  if (!par) return;
  const activa = par[par.activa], otra = par[par.activa === "a" ? "b" : "a"];
  if (activa.readyState < 2) return;
  if (activa.paused && !activa.ended) activa.play().catch(() => {});
  const resto = (activa.duration - activa.currentTime) * 1000;
  // Empalme: la otra copia arranca desde 0 y se funde encima mientras termina esta.
  if (resto < EMPALME_MS && otra.paused) { otra.currentTime = 0; otra.play().catch(() => {}); }
  cc.globalAlpha = alfa;
  cc.drawImage(activa, 0, 0, W, H);
  if (!otra.paused && otra.readyState >= 2) {
    cc.globalAlpha = alfa * Math.min(1, 1 - Math.max(0, resto) / EMPALME_MS);
    cc.drawImage(otra, 0, 0, W, H);
  }
  cc.globalAlpha = 1;
  if (activa.ended) { activa.pause(); par.activa = par.activa === "a" ? "b" : "a"; }
}

// ---------------------------------------------------------------- holograma

function holograma(t, apertura) {
  // Bordes desvanecidos: el busto flota, sin recuadro.
  cc.globalCompositeOperation = "destination-in";
  const m = cc.createRadialGradient(W / 2, H * 0.42, W * 0.18, W / 2, H * 0.5, W * 0.62);
  m.addColorStop(0, "#000"); m.addColorStop(1, "rgba(0,0,0,0)");
  cc.fillStyle = m; cc.fillRect(0, 0, W, H);
  cc.globalCompositeOperation = "source-over";

  ctx.clearRect(0, 0, W, H);
  ctx.drawImage(capa, 0, 0);
  if (sinEfecto) return;
  // Velo azul por luminancia (35 %).
  tc.clearRect(0, 0, W, H);
  tc.filter = "grayscale(1) contrast(1.25) brightness(1.15)"; tc.drawImage(capa, 0, 0); tc.filter = "none";
  tc.globalCompositeOperation = "multiply"; tc.fillStyle = "#6fc3ff"; tc.fillRect(0, 0, W, H);
  tc.globalCompositeOperation = "destination-in"; tc.drawImage(capa, 0, 0); tc.globalCompositeOperation = "source-over";
  ctx.globalAlpha = 0.35; ctx.drawImage(tinte, 0, 0); ctx.globalAlpha = 1;
  // Lineas finas que bajan y un barrido suave.
  ctx.globalCompositeOperation = "source-atop"; ctx.fillStyle = "#000";
  const off = (t / 40) % 4;
  ctx.globalAlpha = 0.12; for (let y = off - 4; y < H; y += 4) ctx.fillRect(0, y, W, 1);
  ctx.fillStyle = "rgba(77,163,255,.5)"; ctx.globalAlpha = 0.16; ctx.fillRect(0, (t / 9) % (H + 80) - 40, W, 18);
  ctx.globalAlpha = 1; ctx.globalCompositeOperation = "source-over";
  lienzo.style.filter = `drop-shadow(0 0 ${8 + apertura * 12}px rgba(77,163,255,.55))`;
}

// ---------------------------------------------------------------- bucle

function dibujar(t) {
  requestAnimationFrame(dibujar);
  if (lienzo.hidden) { ultimo = 0; return; }
  // Si el dispositivo no da los cuadros (>2 s por debajo de 20 fps), sin efecto.
  if (ultimo && t - ultimo > 50) { if (++cuadrosLentos > 40) sinEfecto = true; } else cuadrosLentos = 0;
  ultimo = t;

  const apertura = actual === "hablando"
    ? (nivelVoz || Math.max(0, Math.sin(t / 95) * 0.6 + Math.sin(t / 37) * 0.3 + 0.15)) : 0;
  cc.clearRect(0, 0, W, H);
  if (videos.reposo) {
    const mezcla = Math.min(1, (t - desde) / FUNDIDO_MS);
    if (anterior && mezcla < 1) cuadroDe(videos[anterior] || videos.reposo, 1);
    cuadroDe(videos[actual] || videos.reposo, anterior ? mezcla : 1);
  } else if (foto) {
    dibujarFoto(t, apertura);
  }
  holograma(t, apertura);
}
