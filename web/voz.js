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

function crearPuerta(flujo, pista, ajustes, alMedir, alCambiar) {
  const umbral = ajustes?.umbral ?? 0.045;
  const sostenido = ajustes?.sostenido_ms ?? 220;

  const contexto = new (window.AudioContext || window.webkitAudioContext)();
  const analizador = contexto.createAnalyser();
  analizador.fftSize = 512;
  contexto.createMediaStreamSource(flujo).connect(analizador);

  const muestras = new Float32Array(analizador.fftSize);
  let jarvisHablando = false;
  let vozDesde = 0;
  let cerradoDesde = 0;

  // Solo para la traza: cuando cambia, y por que.
  let abierto = true;
  function avisarCambio(motivo) {
    if (!pista || pista.enabled === abierto) return;
    abierto = pista.enabled;
    alCambiar?.(abierto, motivo);
  }

  // Si algo va mal y nadie avisa de que Jarvis termino, el microfono se
  // quedaria cerrado para siempre y pareceria que dejo de oir. Pasado este
  // tiempo se reabre por las malas.
  const MAXIMO_CERRADO = 25000;

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
      cerradoDesde = 0;
      return;
    }

    // Red de seguridad: nunca dejar el microfono cerrado indefinidamente.
    if (cerradoDesde && performance.now() - cerradoDesde > MAXIMO_CERRADO) {
      jarvisHablando = false;
      pista.enabled = true;
      vozDesde = 0;
      cerradoDesde = 0;
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
    avisarCambio("voz encima de Jarvis");
  }, 40);

  return {
    jarvisEmpiezaAHablar() {
      // Solo actua en el cambio de estado. Antes se llamaba en cada fragmento
      // de voz —varias veces por segundo— y cada llamada reiniciaba el
      // contador, asi que nunca se acumulaban los milisegundos necesarios
      // para interrumpirlo.
      if (jarvisHablando) return;
      jarvisHablando = true;
      vozDesde = 0;
      cerradoDesde = performance.now();
      pista.enabled = false;
      avisarCambio("Jarvis habla");
    },
    jarvisTermina(motivo = "Jarvis termina") {
      jarvisHablando = false;
      vozDesde = 0;
      cerradoDesde = 0;
      if (pista) pista.enabled = true;
      avisarCambio(motivo);
    },
    cerrar() {
      clearInterval(reloj);
      contexto.close().catch(() => {});
    },
  };
}


/* Espera a tener los candidatos ICE que OpenAI necesita.

   OpenAI contesta en ice-lite y solo le sirve un candidato alcanzable desde
   fuera: el srflx que da el STUN. Llega a las pocas decenas de milisegundos,
   pero Chrome no declara el gathering "complete" hasta que la conexion ya esta
   hecha, asi que esperar a eso agotaba siempre el tope: tres segundos de
   silencio en cada arranque. Ahora se sigue en cuanto hay uno, con un margen
   corto para que entre el de la otra interfaz si la hay.

   Hay que crearla ANTES de setLocalDescription: los candidatos empiezan a
   llegar ahi y uno perdido volveria a costar el tope entero. */
function esperarCandidatos(conexion, tope = 3000, margen = 150) {
  if (conexion.iceGatheringState === "complete") return Promise.resolve();

  return new Promise((listo) => {
    let reloj = setTimeout(terminar, tope);

    function terminar() {
      conexion.removeEventListener("icegatheringstatechange", alCambiar);
      conexion.removeEventListener("icecandidate", alCandidato);
      clearTimeout(reloj);
      listo();
    }
    function alCambiar() {
      if (conexion.iceGatheringState === "complete") terminar();
    }
    function alCandidato(evento) {
      if (!evento.candidate) return terminar();   // fin de candidatos
      if (evento.candidate.type === "srflx" || evento.candidate.type === "relay") {
        clearTimeout(reloj);
        reloj = setTimeout(terminar, margen);
      }
    }
    conexion.addEventListener("icegatheringstatechange", alCambiar);
    conexion.addEventListener("icecandidate", alCandidato);
  });
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

  /* Traza para diagnosticar. El audio va directo a OpenAI, asi que el
     servidor no ve cuando se detecto voz, cuando se corto una respuesta ni
     por que un turno quedo sin contestar. Aqui se anota lo que pasa por
     dentro y se manda al log cada pocos segundos. No cambia nada de la
     conversacion. */
  const traza = [];
  const trazaDesde = performance.now();

  function paso(e, d = "") {
    traza.push({ t: (performance.now() - trazaDesde) / 1000, e, d: String(d ?? "") });
    if (traza.length > 200) traza.shift();
  }

  function mandarTraza(alCerrar = false) {
    if (!traza.length) return;
    fetch("/api/voz/traza", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pasos: traza.splice(0) }),
      keepalive: alCerrar,
    }).catch(() => {});   // diagnosticar nunca debe estorbar la conversacion
  }

  const relojTraza = setInterval(mandarTraza, 5000);

  const PASOS = {
    "input_audio_buffer.speech_started": "habla empieza",
    "input_audio_buffer.speech_stopped": "habla termina",
    "response.created": "respuesta creada",
    "output_audio_buffer.started": "audio empieza",
    "output_audio_buffer.stopped": "audio termina",
    "output_audio_buffer.cleared": "audio cortado",
  };

  function trazar(evento) {
    if (PASOS[evento.type]) return paso(PASOS[evento.type]);
    if (evento.type === "error") return paso("error", evento.error?.message);
    if (evento.type !== "response.done") return;
    // Como acabo y que traia: es lo que dice si Jarvis contesto, si lo
    // cortaron o si no dijo nada.
    const respuesta = evento.response || {};
    const motivo = respuesta.status_details?.reason || respuesta.status_details?.type;
    const partes = (respuesta.output || []).map((item) => {
      if (item.type === "function_call") return `llama ${item.name}`;
      const dicho = (item.content || []).map((c) => c.transcript || c.text || "").join(" ").trim();
      return dicho ? `dice ${dicho.length} letras` : `${item.type} vacio`;
    });
    paso("respuesta fin",
         `${respuesta.status || "?"}${motivo ? ": " + motivo : ""} · ${partes.join(", ") || "sin nada"}`);
  }

  function enviar(mensaje) {
    if (canal?.readyState === "open") canal.send(JSON.stringify(mensaje));
  }

  /* Una sola respuesta puede estar viva a la vez. Pedir otra antes de que
     termine devuelve "Conversation already has an active response in
     progress" y el turno se pierde.

     Pasaba siempre que Jarvis usaba una herramienta: el aviso de que la
     herramienta acabo llega ANTES de que la respuesta se cierre, y con dos
     herramientas en el mismo turno se pedia dos veces. Aqui se anota que hace
     falta una respuesta y se lanza cuando de verdad se puede. */

  let respuestaActiva = false;
  let herramientasEnCurso = 0;
  let respuestaPendiente = false;

  function pedirRespuesta() {
    respuestaPendiente = true;
    intentarResponder();
  }

  function intentarResponder() {
    if (!respuestaPendiente || respuestaActiva || herramientasEnCurso > 0) return;
    respuestaPendiente = false;
    paso("pide respuesta");
    enviar({ type: "response.create" });
  }

  async function conectar() {
    avisar("onEstado", "conectando", "Conectando...");

    const respuesta = await fetch("/api/voz/config");
    const datos = await respuesta.json();
    if (!respuesta.ok) throw new Error(datos.error || "No pude abrir la sesion de voz");
    modeloEnUso = datos.modelo;

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
                           avisar("onNivel", nivel, umbral, abierto),
                         (abierto, motivo) =>
                           paso(abierto ? "micro abre" : "micro cierra", motivo));

    // OpenAI contesta en modo ice-lite: no hace chequeos de conectividad por
    // su cuenta, asi que el navegador tiene que aportar candidatos validos.
    // Sin STUN solo junta candidatos de red local y la conexion no se
    // establece: la pantalla se quedaba en "Conectando..." para siempre.
    conexion = new RTCPeerConnection({
      iceServers: [{ urls: ["stun:stun.l.google.com:19302"] }],
    });

    audio = new Audio();
    audio.autoplay = true;
    conexion.ontrack = (evento) => {
      audio.srcObject = evento.streams[0];
    };

    conexion.addTrack(pista, microfono);

    canal = conexion.createDataChannel("oai-events");
    canal.addEventListener("message", (mensaje) => manejar(JSON.parse(mensaje.data)));
    canal.addEventListener("open", () => {
      paso("canal abierto");
      avisar("onEstado", "listo", "Te escucho");
    });

    // Sin esto, un ICE que no cuaja deja la pantalla en "Conectando..." sin
    // decir nada. Mejor avisar que quedarse mudo.
    conexion.oniceconnectionstatechange = () => {
      const e = conexion.iceConnectionState;
      if (e === "checking") avisar("onEstado", "conectando", "Enlazando audio...");
      if (e === "failed") {
        avisar("onError",
          "No se pudo establecer el audio con OpenAI. " +
          "Suele ser la red: prueba con otra wifi o con datos del telefono.");
        cerrar();
      }
    };

    conexion.onconnectionstatechange = () => {
      if (["failed", "disconnected"].includes(conexion.connectionState) && !cerrada) {
        avisar("onError", "Se perdio la conexion de voz.");
        cerrar();
      }
    };

    const oferta = await conexion.createOffer();
    // Hay que esperar a tener los candidatos: `oferta.sdp` es la version de
    // antes de recolectarlos, y OpenAI necesita que vengan dentro. Enviando
    // esa version la negociacion respondia bien pero nunca conectaba.
    const candidatos = esperarCandidatos(conexion);
    await conexion.setLocalDescription(oferta);
    await candidatos;

    // El intercambio va por nuestro servidor: llamar a api.openai.com desde
    // aqui lo bloquea CORS salvo en localhost, y ademas expondria la clave.
    const sdp = await fetch("/api/voz/sdp", {
      method: "POST",
      body: conexion.localDescription.sdp,
      headers: { "Content-Type": "application/sdp" },
    });

    if (!sdp.ok) {
      const detalle = await sdp.json().catch(() => ({}));
      throw new Error(detalle.error || `No se pudo negociar la conexion (${sdp.status})`);
    }

    await conexion.setRemoteDescription({ type: "answer", sdp: await sdp.text() });
    sesionDesde = performance.now();
    return datos;
  }

  async function manejar(evento) {
    try { trazar(evento); } catch { /* la traza nunca corta la conversacion */ }
    switch (evento.type) {
      // --- Lo que dice el usuario ---
      case "input_audio_buffer.speech_started":
        avisar("onEstado", "escuchando", "Te escucho...");
        break;

      case "conversation.item.input_audio_transcription.completed":
        if (evento.transcript?.trim()) avisar("onUsuario", evento.transcript.trim());
        // La transcripcion se cobra aparte, por duracion, y su uso solo llega
        // aqui. El modelo lo pone el servidor, que es quien lo eligio.
        anotarConsumo(evento.usage, "transcripcion");
        break;

      // --- Lo que responde Jarvis ---
      case "output_audio_buffer.started":
        puerta?.jarvisEmpiezaAHablar();
        break;

      case "output_audio_buffer.stopped":
      case "output_audio_buffer.cleared":
        puerta?.jarvisTermina("termino el audio");
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

      case "response.created":
        respuestaActiva = true;
        break;

      case "response.output_item.done":
        if (evento.item?.type === "function_call") resolverFuncion(evento.item);
        break;

      case "response.done":
        respuestaActiva = false;
        puerta?.jarvisTermina("termino la respuesta");
        avisar("onEstado", "listo", "Te escucho");
        // El uso solo llega aqui: en voz no pasa por nuestro servidor.
        anotarConsumo(evento.response?.usage);
        // Si mientras tanto acabo una herramienta, ahora si toca responder.
        intentarResponder();
        break;

      case "error":
        // Un error deja la respuesta cerrada; si no lo reflejamos, el resto
        // de la sesion se queda esperando a una respuesta que ya no existe.
        respuestaActiva = false;
        avisar("onError", evento.error?.message || "Error en la sesion de voz.");
        intentarResponder();
        break;
    }
  }

  /* El gasto de la voz solo se ve aqui: el audio va directo entre el
     navegador y OpenAI, asi que el servidor no puede contarlo por su cuenta.
     Se le reenvia cada uso y, al cerrar, cuanto duro la sesion, que es lo que
     permite calcular el costo por minuto. */

  let modeloEnUso = null;
  let sesionDesde = null;

  function anotarConsumo(uso, modo = "voz") {
    if (!uso) return;
    const cuerpo = modo === "voz" ? { modelo: modeloEnUso, uso } : { modo, uso };
    fetch("/api/consumo/voz", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cuerpo),
    }).catch(() => {});   // contabilizar nunca debe estorbar la conversacion
  }

  function anotarSesion() {
    if (!sesionDesde) return;
    const segundos = (performance.now() - sesionDesde) / 1000;
    sesionDesde = null;
    if (segundos < 1) return;
    // keepalive para que salga aunque se cierre la pestana justo despues.
    fetch("/api/consumo/voz", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ modelo: modeloEnUso, segundos_sesion: segundos }),
      keepalive: true,
    }).catch(() => {});
  }

  const ESPERA_HERRAMIENTA = 25000;

  async function resolverFuncion(item) {
    avisar("onHerramienta", item.name);
    herramientasEnCurso++;
    const inicio = performance.now();

    let resultado;
    try {
      // Con tiempo limite: si una base no responde y esperasemos para siempre,
      // el turno nunca se cerraria y Jarvis se quedaria mudo.
      const corte = AbortSignal.timeout(ESPERA_HERRAMIENTA);
      const respuesta = await fetch("/api/herramienta", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ nombre: item.name, argumentos: item.arguments || "{}" }),
        signal: corte,
      });
      const datos = await respuesta.json();
      resultado = datos.resultado;
      // Lo que la herramienta manda al chat va a la pantalla, no al modelo.
      if (datos.adjuntos?.length) avisar("onAdjuntos", datos.adjuntos);
    } catch (error) {
      resultado = error.name === "TimeoutError"
        ? `La consulta ${item.name} tardo demasiado. Dilo y ofrece reintentar.`
        : `Error al ejecutar ${item.name}: ${error.message}`;
    } finally {
      // Pase lo que pase hay que devolver algo y soltar el contador, o el
      // turno se queda colgado.
      try {
        enviar({
          type: "conversation.item.create",
          item: {
            type: "function_call_output",
            call_id: item.call_id,
            output: resultado ?? `Error desconocido en ${item.name}.`,
          },
        });
      } finally {
        paso("herramienta vuelve", `${item.name} ${Math.round(performance.now() - inicio)} ms`);
        herramientasEnCurso--;
        pedirRespuesta();
      }
    }
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
    pedirRespuesta();
  }

  /* Cuantos caracteres caben en un mensaje del canal de datos.

     El tope lo negocian el navegador y OpenAI al conectar. 0 es "sin tope
     conocido". Se reservan unos bytes para el sobre JSON que envuelve la
     imagen. */
  function espacioParaImagen() {
    const tope = conexion?.sctp?.maxMessageSize;
    return tope && Number.isFinite(tope) ? tope - 512 : 0;
  }

  /* Mete una imagen en la conversacion. A proposito no pide respuesta:
     adjuntar no es preguntar, y Jarvis describiendo cada foto sin que nadie
     se lo pida estorba. La pregunta llega despues, hablada o escrita, y el
     modelo ya tiene la imagen delante. */
  function adjuntarImagen(urlDeDatos) {
    if (canal?.readyState !== "open") {
      throw new Error("La voz en vivo todavia no esta conectada.");
    }
    canal.send(JSON.stringify({
      type: "conversation.item.create",
      item: {
        type: "message",
        role: "user",
        content: [{ type: "input_image", image_url: urlDeDatos }],
      },
    }));
  }

  function silenciar(silencio) {
    if (pista) pista.enabled = !silencio;
  }

  function cerrar() {
    cerrada = true;
    anotarSesion();
    paso("sesion cerrada");
    clearInterval(relojTraza);
    mandarTraza(true);
    puerta?.cerrar();
    pista?.stop();
    canal?.close();
    conexion?.close();
    if (audio) audio.srcObject = null;
    conexion = canal = pista = audio = puerta = null;
    avisar("onCierre");
  }

  return { conectar, cerrar, escribir, silenciar, adjuntarImagen, espacioParaImagen };
}
