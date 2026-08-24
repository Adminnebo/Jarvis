/* Modo voz en vivo (OpenAI Realtime sobre WebRTC).

   El audio va directo del microfono a OpenAI y vuelve como audio, sin pasar
   por nuestro servidor. Lo unico que pedimos al backend es la credencial
   efimera y la ejecucion de las herramientas locales.

   Las herramientas de Supabase no aparecen aqui: OpenAI las resuelve contra
   el MCP en sus propios servidores. */

/* Puerta local de microfono.

   El detector de OpenAI solo mide energia: un portazo la supera igual que una
   voz, y `interrupt_response` es todo o nada. Subir el umbral no distingue —
   solo obliga a gritar.

   Asi que filtramos aqui, antes de que el audio salga de la maquina. Mientras
   Jarvis habla el microfono queda cerrado y solo se abre si el nivel se
   mantiene alto durante varios ciclos seguidos: un golpe o una tos duran un
   instante, una persona hablando no. Cuando Jarvis calla, el microfono queda
   siempre abierto para no perder ni una silaba. */

function crearPuerta(flujo, pista, ajustes, alMedir) {
  const umbral = ajustes?.umbral ?? 0.045;
  const sostenido = ajustes?.sostenido_ms ?? 220;

  const contexto = new (window.AudioContext || window.webkitAudioContext)();
  const analizador = contexto.createAnalyser();
  analizador.fftSize = 512;
  contexto.createMediaStreamSource(flujo).connect(analizador);

  const muestras = new Float32Array(analizador.fftSize);
  let jarvisHablando = false;
  let vozDesde = 0;

  function volumen() {
    analizador.getFloatTimeDomainData(muestras);
    let suma = 0;
    for (const valor of muestras) suma += valor * valor;
    return Math.sqrt(suma / muestras.length);
  }

  const reloj = setInterval(() => {
    if (!pista) return;

    const nivel = volumen();
    // El medidor sirve para calibrar: se ve si el ruido de fondo roza el
    // umbral y hay que subirlo, o si tu voz no llega y hay que bajarlo.
    alMedir?.(nivel, umbral, pista.enabled);

    if (!jarvisHablando) {
      pista.enabled = true;
      vozDesde = 0;
      return;
    }

    if (nivel >= umbral) {
      if (!vozDesde) vozDesde = performance.now();
      // Sostenido el tiempo suficiente: es alguien hablando, dejalo pasar.
      if (performance.now() - vozDesde >= sostenido) pista.enabled = true;
    } else {
      vozDesde = 0;
      pista.enabled = false;
    }
  }, 40);

  return {
    jarvisEmpiezaAHablar() {
      jarvisHablando = true;
      vozDesde = 0;
      pista.enabled = false;
    },
    jarvisTermina() {
      jarvisHablando = false;
      vozDesde = 0;
      if (pista) pista.enabled = true;
    },
    cerrar() {
      clearInterval(reloj);
      contexto.close().catch(() => {});
    },
  };
}


export function crearSesionDeVoz(eventos) {
  let conexion = null;
  let canal = null;
  let pista = null;
  let audio = null;
  let puerta = null;
  let cerrada = false;

  function avisar(nombre, ...argumentos) {
    eventos[nombre]?.(...argumentos);
  }

  function enviar(mensaje) {
    if (canal?.readyState === "open") canal.send(JSON.stringify(mensaje));
  }

  async function conectar() {
    avisar("onEstado", "conectando", "Conectando...");

    const respuesta = await fetch("/api/voz/token", { method: "POST" });
    const datos = await respuesta.json();
    if (!respuesta.ok) throw new Error(datos.error || "No pude abrir la sesion de voz");

    // El microfono se pide despues del token: si OpenAI rechaza la sesion,
    // no molestamos al usuario con el permiso del navegador.
    // El navegador limpia el audio antes de enviarlo; OpenAI vuelve a
    // filtrarlo con noise_reduction. Las dos capas suman en un sitio ruidoso.
    const microfono = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
    pista = microfono.getAudioTracks()[0];
    puerta = crearPuerta(microfono, pista, datos.puerta,
                         (nivel, umbral, abierto) =>
                           avisar("onNivel", nivel, umbral, abierto));

    conexion = new RTCPeerConnection();

    audio = new Audio();
    audio.autoplay = true;
    conexion.ontrack = (evento) => {
      audio.srcObject = evento.streams[0];
    };

    conexion.addTrack(pista, microfono);

    canal = conexion.createDataChannel("oai-events");
    canal.addEventListener("message", (mensaje) => manejar(JSON.parse(mensaje.data)));
    canal.addEventListener("open", () => avisar("onEstado", "listo", "Te escucho"));

    conexion.onconnectionstatechange = () => {
      if (["failed", "disconnected"].includes(conexion.connectionState) && !cerrada) {
        avisar("onError", "Se perdio la conexion de voz.");
        cerrar();
      }
    };

    const oferta = await conexion.createOffer();
    await conexion.setLocalDescription(oferta);

    const sdp = await fetch("https://api.openai.com/v1/realtime/calls", {
      method: "POST",
      body: oferta.sdp,
      headers: {
        Authorization: `Bearer ${datos.token}`,
        "Content-Type": "application/sdp",
      },
    });

    if (!sdp.ok) throw new Error(`OpenAI rechazo la conexion (${sdp.status})`);

    await conexion.setRemoteDescription({ type: "answer", sdp: await sdp.text() });
    return datos;
  }

  async function manejar(evento) {
    switch (evento.type) {
      // --- Lo que dice el usuario ---
      case "input_audio_buffer.speech_started":
        avisar("onEstado", "escuchando", "Te escucho...");
        break;

      case "conversation.item.input_audio_transcription.completed":
        if (evento.transcript?.trim()) avisar("onUsuario", evento.transcript.trim());
        break;

      // --- Lo que responde Jarvis ---
      case "output_audio_buffer.started":
        puerta?.jarvisEmpiezaAHablar();
        break;

      case "output_audio_buffer.stopped":
      case "output_audio_buffer.cleared":
        puerta?.jarvisTermina();
        break;

      case "response.output_audio_transcript.delta":
        // Respaldo por si el navegador no emite los eventos del buffer.
        puerta?.jarvisEmpiezaAHablar();
        avisar("onRespuestaParcial", evento.delta);
        break;

      case "response.output_audio_transcript.done":
        avisar("onRespuestaCompleta", evento.transcript || "");
        break;

      case "response.output_item.added":
        if (evento.item?.type === "mcp_call") {
          avisar("onHerramienta", `${evento.item.server_label || "MCP"}`);
        }
        break;

      case "response.output_item.done":
        if (evento.item?.type === "function_call") await resolverFuncion(evento.item);
        break;

      case "response.done":
        puerta?.jarvisTermina();
        avisar("onEstado", "listo", "Te escucho");
        break;

      case "error":
        avisar("onError", evento.error?.message || "Error en la sesion de voz.");
        break;
    }
  }

  async function resolverFuncion(item) {
    avisar("onHerramienta", item.name);

    let resultado;
    try {
      const respuesta = await fetch("/api/herramienta", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ nombre: item.name, argumentos: item.arguments || "{}" }),
      });
      resultado = (await respuesta.json()).resultado;
    } catch (error) {
      resultado = `Error al ejecutar ${item.name}: ${error.message}`;
    }

    enviar({
      type: "conversation.item.create",
      item: {
        type: "function_call_output",
        call_id: item.call_id,
        output: resultado,
      },
    });
    enviar({ type: "response.create" });
  }

  function escribir(texto) {
    enviar({
      type: "conversation.item.create",
      item: {
        type: "message",
        role: "user",
        content: [{ type: "input_text", text: texto }],
      },
    });
    enviar({ type: "response.create" });
  }

  function silenciar(silencio) {
    if (pista) pista.enabled = !silencio;
  }

  function cerrar() {
    cerrada = true;
    puerta?.cerrar();
    pista?.stop();
    canal?.close();
    conexion?.close();
    if (audio) audio.srcObject = null;
    conexion = canal = pista = audio = puerta = null;
    avisar("onCierre");
  }

  return { conectar, cerrar, escribir, silenciar };
}
