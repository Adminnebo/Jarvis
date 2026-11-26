/* Cuánto oye el micrófono de este teléfono, para la sala de una reunión presencial.

   Mide cada 50 ms y se queda con el máximo de cada ventana de 250 ms (la voz sube y
   baja muy rápido); cada 2 s manda las ventanas a /api/salas/<codigo>/niveles con la
   hora del servidor. No manda audio: solo esos números. Lo usan la página del
   participante (sala.js) y el teléfono que graba (grabadora.js).
   Ver docs/superpowers/specs/2026-11-26-reuniones-calibracion-y-sala-design.md. */

const VENTANA_MS = 250;
const ENVIO_MS = 2000;
const MAX_PENDIENTES = 80;   // 20 s sin red; más viejo se descarta

/** Micrófono para medir: sin control de ganancia, que emparejaría a los que hablan lejos. */
export function abrirMicrofonoParaNiveles() {
  return navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: false, noiseSuppression: true, autoGainControl: false } });
}

export class EmisorNiveles {
  /** sala: {codigo, participante, token, ahora_ms}; alParar(): la reunión terminó. */
  constructor(stream, sala, { alParar = () => {} } = {}) {
    this.sala = sala;
    this.alParar = alParar;
    this.desfase = (sala.ahora_ms || Date.now()) - Date.now();   // reloj del servidor − el de aquí
    this.pendientes = [];
    this.desde = null;
    this.maximo = 0;
    this.ultimo = 0;
    this.cambiarMicrofono(stream);
  }

  cambiarMicrofono(stream) {
    try { this.ctx?.close(); } catch { /* nada */ }
    this.ctx = new AudioContext();
    this.ctx.resume?.().catch(() => {});
    this.analizador = this.ctx.createAnalyser();
    this.analizador.fftSize = 1024;
    this.ctx.createMediaStreamSource(stream).connect(this.analizador);
    this.datos = new Float32Array(this.analizador.fftSize);
  }

  /** 0..1, el nivel crudo (RMS) de este instante. */
  medir() {
    this.analizador.getFloatTimeDomainData(this.datos);
    let suma = 0;
    for (const v of this.datos) suma += v * v;
    return Math.sqrt(suma / this.datos.length);
  }

  empezar() {
    this.inicioVentana = Date.now();
    this.medicion = setInterval(() => {
      this.maximo = Math.max(this.maximo, this.medir());
      this.ultimo = this.maximo;
      const ahora = Date.now();
      if (ahora - this.inicioVentana >= VENTANA_MS) {
        if (this.desde === null) this.desde = this.inicioVentana + this.desfase;
        this.pendientes.push(Number(this.maximo.toFixed(4)));
        if (this.pendientes.length > MAX_PENDIENTES) {   // sin red mucho rato: se suelta lo más viejo
          this.pendientes.shift();
          this.desde += VENTANA_MS;
        }
        this.maximo = 0;
        this.inicioVentana += VENTANA_MS;
      }
    }, 50);
    this.envio = setInterval(() => this.enviar(), ENVIO_MS);
  }

  async enviar() {
    if (!this.pendientes.length || this.enviando) return;
    this.enviando = true;
    const niveles = this.pendientes.splice(0);
    const desde = this.desde;
    this.desde = null;
    try {
      const r = await fetch(`/api/salas/${this.sala.codigo}/niveles`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ participante: this.sala.participante, token: this.sala.token, desde_ms: Math.round(desde), niveles }),
      });
      if (r.status === 401) { this.parar(); this.alParar("token"); return; }
      if (!r.ok) throw new Error(String(r.status));
      if ((await r.json()).seguir === false) { this.parar(); this.alParar("terminada"); }
    } catch {
      // Sin red: se vuelven a poner adelante (las ventanas son seguidas, así que el
      // inicio vuelve a ser el de este paquete) y salen en el próximo envío.
      this.pendientes = niveles.concat(this.pendientes);
      this.desde = desde;
      const sobra = this.pendientes.length - MAX_PENDIENTES;
      if (sobra > 0) {
        this.pendientes.splice(0, sobra);
        this.desde += sobra * VENTANA_MS;
      }
    } finally {
      this.enviando = false;
    }
  }

  parar() {
    clearInterval(this.medicion);
    clearInterval(this.envio);
    try { this.ctx?.close(); } catch { /* nada */ }
  }
}
