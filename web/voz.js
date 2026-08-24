/* Modo voz en vivo (OpenAI Realtime sobre WebRTC).

   El audio va directo del microfono a OpenAI y vuelve como audio, sin pasar
   por nuestro servidor. Lo unico que pedimos al backend es la credencial
   efimera y la ejecucion de las herramientas locales.

   Las herramientas de Supabase no aparecen aqui: OpenAI las resuelve contra
   el MCP en sus propios servidores. */

export function crearSesionDeVoz(eventos) {
  let conexion = null;
  let canal = null;
  let pista = null;
  let audio = null;
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
      case "response.output_audio_transcript.delta":
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
    pista?.stop();
    canal?.close();
    conexion?.close();
    if (audio) audio.srcObject = null;
    conexion = canal = pista = audio = null;
    avisar("onCierre");
  }

  return { conectar, cerrar, escribir, silenciar };
}
