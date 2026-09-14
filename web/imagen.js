/* Prepara una imagen para mandarla a la voz en vivo.

   Va por el canal de datos de WebRTC, que tiene un tope por mensaje negociado
   entre las dos puntas: pasarse hace que send() lance. Una foto de telefono
   pesa megas, asi que se reduce aqui. Primero se baja la calidad y, si no
   alcanza, el tamano. 1024 px de lado bastan para leer una etiqueta. */

const LADO_MAXIMO = 1024;
const LADO_MINIMO = 320;
const CALIDADES = [0.85, 0.7, 0.55];

export async function prepararImagen(archivo, maxCaracteres = 0) {
  if (!archivo?.type?.startsWith("image/")) throw new Error("Eso no es una imagen.");

  // from-image aplica la orientacion EXIF: sin eso las fotos verticales del
  // telefono llegan acostadas y el modelo lee el texto de lado.
  const mapa = await createImageBitmap(archivo, { imageOrientation: "from-image" });

  try {
    for (let lado = LADO_MAXIMO; lado >= LADO_MINIMO; lado = Math.round(lado * 0.75)) {
      const escala = Math.min(1, lado / Math.max(mapa.width, mapa.height));
      const lienzo = document.createElement("canvas");
      lienzo.width = Math.round(mapa.width * escala);
      lienzo.height = Math.round(mapa.height * escala);

      const pincel = lienzo.getContext("2d");
      // JPEG no tiene transparencia: sin fondo, un PNG recortado sale negro.
      pincel.fillStyle = "#fff";
      pincel.fillRect(0, 0, lienzo.width, lienzo.height);
      pincel.drawImage(mapa, 0, 0, lienzo.width, lienzo.height);

      for (const calidad of CALIDADES) {
        const url = lienzo.toDataURL("image/jpeg", calidad);
        if (!maxCaracteres || url.length <= maxCaracteres) {
          return { url, ancho: lienzo.width, alto: lienzo.height };
        }
      }
    }
  } finally {
    mapa.close();
  }

  throw new Error("La imagen no cabe en el canal de voz ni reducida.");
}
