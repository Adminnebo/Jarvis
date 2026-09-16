"""El HTML de una cotizacion, identico al que arma n8n para Camila.

Es un port del nodo "Con imagenes" del flujo 2.2 generar_cotizacion: mismo CSS,
misma paginacion por altura estimada y mismo pie. Cambian el numero (JV-) y el
"Usuario", que es quien la pidio en Jarvis.

No calcula precios: recibe las lineas ya resueltas por cotizaciones.py. Si se
toca el CSS de las filas o la imagen, hay que mover tambien los parametros de
altura de abajo, igual que en el original.
"""

import html
import math

LOGO_URL = "https://bewpkmgcnzukyouplbwm.supabase.co/storage/v1/object/public/JH-Iconos/JH%20LG_page-0001.jpg"
ICON_WA_URL = "https://bewpkmgcnzukyouplbwm.supabase.co/storage/v1/object/public/JH-Iconos/whatsapp.png"
ICON_IG_URL = "https://bewpkmgcnzukyouplbwm.supabase.co/storage/v1/object/public/JH-Iconos/instagram.png"
ICON_FLAG_US_URL = "https://bewpkmgcnzukyouplbwm.supabase.co/storage/v1/object/public/JH-Iconos/flag.png"
QR_URL = "https://bewpkmgcnzukyouplbwm.supabase.co/storage/v1/object/public/JH-Iconos/QR.jpeg"

# Paginacion: el pie es position:fixed y no reserva espacio, asi que el unico
# freno contra el solapamiento es este presupuesto de alto por pagina.
ALTO_FILAS_PAGINA = 560   # px para filas en paginas normales  -> 7 filas
ALTO_FILAS_ULTIMA = 330   # px en la ultima, que comparte con totales y firmas

ALTO_IMG = 64          # = max-height de .prod-img
PADDING_FILA = 12      # = padding vertical de la celda (6+6) + bordes
ALTO_LINEA = 11        # alto de linea a 8pt
CHARS_POR_LINEA = 30   # caben ~30 chars en la columna Descripcion
CHARS_REF = 14         # ~14 chars en la columna Referencia


def _esc(valor) -> str:
    return html.escape("" if valor is None else str(valor), quote=True)


def _fmt(numero) -> str:
    return f"{float(numero or 0):,.2f}"


def alto_fila(linea: dict) -> int:
    descripcion = str(linea.get("descripcion") or "").strip()
    lineas_desc = max(1, math.ceil(len(descripcion) / CHARS_POR_LINEA))
    lineas_ref = max(1, math.ceil(len(str(linea.get("referencia") or "")) / CHARS_REF))
    alto_texto = max(lineas_desc, lineas_ref) * ALTO_LINEA
    return max(ALTO_IMG, alto_texto) + PADDING_FILA


def paginar(lineas: list[dict]) -> list[list[dict]]:
    bloques: list[list[dict]] = []
    actual: list[dict] = []
    alto = 0

    for linea in lineas:
        h = alto_fila(linea)
        if alto + h > ALTO_FILAS_PAGINA and actual:
            bloques.append(actual)
            actual, alto = [], 0
        actual.append(linea)
        alto += h
    if actual:
        bloques.append(actual)
    if not bloques:
        bloques.append([])

    # La ultima pagina tiene menos espacio: lo que no cabe pasa a una nueva,
    # que se vuelve a comprobar porque ahora es ella la ultima.
    for _ in range(100):
        ultima = bloques[-1]
        h = sum(alto_fila(l) for l in ultima)
        if h <= ALTO_FILAS_ULTIMA or len(ultima) <= 1:
            break
        movidas: list[dict] = []
        while h > ALTO_FILAS_ULTIMA and len(ultima) > 1:
            linea = ultima.pop()
            movidas.insert(0, linea)
            h -= alto_fila(linea)
        bloques.append(movidas)

    return bloques


def _encabezado(num_pagina: int, total_paginas: int, numero: str, fecha: str,
                cliente: dict, usuario: str) -> str:
    codigo = str(cliente.get("codigo") or "")
    codigo_html = f'<div class="client-code-clean">({_esc(codigo)})</div>' if codigo else ""
    return f"""
  <div class="page-header">
    <div class="header-row">
      <div class="header-cell brand-cell">
        <img src="{LOGO_URL}" alt="JH">
      </div>
      <div class="header-cell company-cell">
        <h1>JH ELECTROALAMBRES SRL</h1>
        <div class="address">
          Calle Benito Moncion #21, La Vega<br>
          (809)-242-3585<br>
          130332584
        </div>
      </div>
      <div class="header-cell docinfo-cell">
        <div class="doc-title">COTIZACION</div>
        <div class="doc-row"><b>No.</b> {_esc(numero)}</div>
        <div class="doc-row"><b>Fecha:</b> {_esc(fecha)}</div>
      </div>
    </div>
    <div class="client-header-row">
      <span class="client-title">DATOS DEL CLIENTE</span>
      <span class="usuario-label">Usuario: <span class="usuario-value">{_esc(usuario)}</span></span>
    </div>
    <div class="client-box">
      {codigo_html}

      <div class="client-name">{_esc(cliente.get("nombre"))}</div>
      <table class="client-data-table">
        <tr>
          <td class="col-label"><b>Direccion:</b></td>
          <td class="col-value">{_esc(cliente.get("direccion"))}</td>
          <td class="col-spacer"></td>
          <td class="col-label"><b>Sector:</b></td>
          <td>{_esc(cliente.get("sector") or "")}</td>
        </tr>
        <tr>
          <td><b>Ciudad:</b></td>
          <td>{_esc(cliente.get("ciudad"))}</td>
          <td></td>
          <td><b>Email:</b></td>
          <td>{_esc(cliente.get("email") or "")}</td>
        </tr>
        <tr>
          <td><b>Rnc:</b></td>
          <td>{_esc(cliente.get("rnc"))} &nbsp;&nbsp;<b>Tel.:</b> {_esc(cliente.get("telefono"))}</td>
          <td></td>
          <td><b>Contacto:</b></td>
          <td>{_esc(cliente.get("contacto") or "")}</td>
        </tr>
      </table>
      <div class="page-num">Page {num_pagina} of {total_paginas}</div>
    </div>
  </div>"""


_COLUMNAS = """
  <thead>
    <tr>
      <th style="width:13%; text-align:center">Imagen</th>
      <th style="width:8%">Codigo</th>
      <th style="width:13%">Referencia</th>
      <th style="width:8%; text-align:center">Cantidad</th>
      <th style="width:27%; text-align:center">Descripción</th>
      <th style="width:8%" class="num">ITBIS</th>
      <th style="width:11%; text-align:center">Precio Con ITBIS</th>
      <th style="width:12%" class="num">Sub Total</th>
    </tr>
  </thead>"""

_PIE = f"""
  <div class="page-footer">
    <div class="footer-col footer-col-left">
      <div class="footer-text-block">
        <div class="footer-generated">Cotización generada automáticamente mediante tecnología inteligente</div>
        <div class="footer-nebo"><b>NEBO AI</b></div>
        <div class="footer-brand"><b>LM CONSULTING GROUP USA LLC</b></div>
        <div class="footer-brand"><b>Lucas Marte</b>&nbsp;&nbsp;|&nbsp;&nbsp;<b>Doctorado en IA y Big Data</b></div>
      </div>
    </div>
    <div class="footer-col footer-col-center">
      <img src="{ICON_FLAG_US_URL}" alt="US" style="width:auto;height:14px;vertical-align:middle;margin-right:6px;"><span class="footer-registered">Empresa registrada en Miami</span>
    </div>
    <div class="footer-col footer-col-right">
      <div class="footer-contact-line"><img src="{ICON_WA_URL}" alt="WA" style="width:20px;height:20px;vertical-align:middle;margin-right:5px;"><span>WhatsApp: 809-627-8739</span></div>
      <div class="footer-contact-line"><img src="{ICON_IG_URL}" alt="IG" style="width:20px;height:20px;vertical-align:middle;margin-right:5px;"><span>Instagram: @lucasmarte_</span></div>
    </div>
    <div class="footer-col footer-col-qr">
      <img src="{QR_URL}" alt="QR" class="qr-img">
      <div class="qr-caption">Escanea para<br>contactarnos</div>
    </div>
  </div>"""


def _fila(linea: dict, imagen: str) -> str:
    # onerror oculta la imagen si el archivo no existe (404): celda vacia en
    # vez de un icono roto.
    celda = (
        f'<img src="{_esc(imagen)}" class="prod-img" alt="" onerror="this.style.visibility=\'hidden\'">'
        if imagen else '<div class="prod-img-empty"></div>'
    )
    return f"""
      <tr>
        <td class="img-cell">{celda}</td>
        <td>{_esc(linea["codigo"])}</td>
        <td>{_esc(linea.get("referencia"))}</td>
        <td class="ctr">{_fmt(linea["cantidad"])}</td>
        <td class="cen">{_esc(linea.get("descripcion"))}</td>
        <td class="num">{_fmt(linea["itbis_linea"])}</td>
        <td class="num">{_fmt(linea["precio_unitario"])}</td>
        <td class="num">{_fmt(linea["subtotal_linea"])}</td>
      </tr>"""


def generar(numero: str, fecha: str, cliente: dict, lineas: list[dict],
            totales: dict, usuario: str, imagenes: dict[str, str] | None = None) -> str:
    """El documento completo. `imagenes` es codigo -> URL de la foto."""
    imagenes = imagenes or {}
    bloques = paginar(list(lineas))
    total_paginas = len(bloques)

    paginas = ""
    for indice, bloque in enumerate(bloques):
        es_ultima = indice == total_paginas - 1
        filas = "".join(_fila(l, imagenes.get(str(l["codigo"]).strip(), "")) for l in bloque)
        cierre = ""
        if es_ultima:
            cierre = f"""
    <section class="footer-row">
      <table class="footer-table">
        <tr>
          <td class="footer-left">
            <div class="obs-row">
              <span class="obs-label">Observaciones</span>
              <span class="qty-articles"><b>Cantidad de Artículos:</b> {len(lineas)}</span>
            </div>
            <div class="legal">
              <em>COTIZACION SUJETA A CAMBIOS DE PRECIOS SIN PREVIO AVISO<br>O VALIDA POR 48 HORAS</em>
            </div>
          </td>
          <td class="footer-right">
            <table class="totals">
              <tr><td class="lbl">SubTotal RD$:</td><td class="val">{_fmt(totales["subtotal"])}</td></tr>
              <tr><td class="lbl">Itbis RD$:</td><td class="val">{_fmt(totales["itbis"])}</td></tr>
              <tr><td class="lbl">Total RD$:</td><td class="val">{_fmt(totales["total"])}</td></tr>
            </table>
          </td>
        </tr>
      </table>
      <div class="signatures">
        <table class="sig-table">
          <tr>
            <td><div class="sig">Realizado por</div></td>
            <td><div class="sig">Autorizado por</div></td>
          </tr>
        </table>
      </div>
      {_PIE}
    </section>"""

        paginas += f"""
  <div class="{'page-break' if indice > 0 else ''}">
    {_encabezado(indice + 1, total_paginas, numero, fecha, cliente, usuario)}
    <table class="products" style="margin-top: 14px;">
      {_COLUMNAS}
      <tbody>{filas}</tbody>
    </table>
    {cierre}
  </div>"""

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>Cotizacion {_esc(numero)}</title>
<style>{CSS}</style>
</head>
<body>
{paginas}
</body>
</html>"""


# Copiado tal cual del flujo de n8n. El pie fijo depende del margen de 2 mm
# de @page: no subirlo.
CSS = """
  @page { size: Letter; margin: 7mm 10mm 2mm 10mm; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: Arial, Helvetica, sans-serif;
    font-size: 9pt;
    color: #000;
    line-height: 1.3;
    padding-bottom: 80px;
  }

  .page-break { page-break-before: always; }

  .page-header { padding-bottom: 2px; }
  .header-row { display: table; width: 100%; }
  .header-cell { display: table-cell; vertical-align: bottom; }

  .brand-cell { width: 185px; }
  .brand-cell img { width: 175px; height: auto; display: block; }

  .company-cell { text-align: center; vertical-align: top; }
  .company-cell h1 {
    font-style: italic;
    font-weight: bold;
    font-size: 12pt;
    margin-bottom: 3px;
    text-decoration: underline;
    font-family: 'Times New Roman', Times, serif;
    color: #0033CC;
  }
  .company-cell .address {
    font-weight: bold;
    font-size: 9pt;
    line-height: 1.4;
  }

  .docinfo-cell { width: 155px; text-align: left; }
  .doc-title {
    color: #0033CC;
    font-weight: bold;
    font-size: 11pt;
    margin-bottom: 2px;
  }
  .doc-row { font-size: 9pt; margin-bottom: 1px; }
  .doc-row b { font-weight: bold; margin-right: 4px; }

  .client-header-row {
    display: table;
    width: 100%;
    padding-top: 3px;
    padding-bottom: 2px;
  }
  .client-title {
    display: table-cell;
    color: #0033CC;
    font-weight: bold;
    font-size: 9pt;
    vertical-align: middle;
  }
  .usuario-label {
    display: table-cell;
    width: 155px;
    text-align: left;
    font-size: 9pt;
    font-weight: bold;
    vertical-align: middle;
  }
  .usuario-value { font-weight: normal; }

  .client-box {
    border: 1px solid #000;
    padding: 3px 8px;
    margin-bottom: 3px;
    min-height: 0;
    position: relative;
  }

  .client-code-clean {
    position: absolute;
    top: 4px;
    right: 205px;
    font-weight: bold;
    font-size: 9.5pt;
    color: #000;
  }

  .client-name { font-weight: bold; margin-bottom: 1px; font-size: 9pt; }
  .client-data-table { width: 100%; font-size: 9pt; }
  .client-data-table td { padding: 0; vertical-align: top; }
  .client-data-table b { font-weight: bold; }
  .col-label { width: 70px; }
  .col-value { width: 190px; }
  .col-spacer { width: 20px; }

  .page-num {
    position: absolute;
    bottom: 3px;
    right: 6px;
    font-size: 8pt;
    color: #000;
  }

  table.products {
    width: 100%;
    table-layout: fixed;
    border-collapse: collapse;
    font-size: 8pt;
    border: 1px solid #000;
  }
  table.products thead tr th {
    color: #0033CC;
    font-weight: bold;
    text-align: left;
    padding: 4px;
    border: 1px solid #000;
    font-size: 8pt;
    vertical-align: middle;
    background: #fff;
  }
  table.products thead tr th.num { text-align: right; }
  table.products tbody tr td {
    padding: 6px 4px;
    vertical-align: top;
    border-left: 1px solid #000;
    border-right: 1px solid #000;
    border-bottom: 1px solid #000;
    word-wrap: break-word;
    overflow-wrap: break-word;
  }
  table.products tbody tr:last-child td { border-bottom: 1px solid #000; }
  table.products tbody tr { page-break-inside: avoid; break-inside: avoid; }
  .num { text-align: right; font-variant-numeric: tabular-nums; }
  .cen { text-align: left; }
  .ctr { text-align: center; }

  table.products tbody tr td.img-cell {
    text-align: center;
    vertical-align: middle;
    padding: 6px 4px;
  }
  .prod-img {
    max-width: 80px;
    max-height: 64px;
    width: auto;
    height: auto;
    object-fit: contain;
    display: inline-block;
  }
  .prod-img-empty {
    width: 80px;
    height: 64px;
    display: inline-block;
  }

  .footer-row { margin-top: 10px; page-break-inside: avoid; break-inside: avoid; }
  .footer-table { width: 100%; border-collapse: collapse; }
  .footer-table td { vertical-align: top; padding: 0; border: none; }
  .footer-left { padding-right: 30px; }
  .footer-right { width: 300px; }

  .obs-row { margin-bottom: 10px; }
  .obs-label { font-weight: bold; font-size: 10pt; margin-right: 20px; }
  .qty-articles { font-size: 10pt; }
  .qty-articles b { font-weight: bold; }
  .legal { font-style: italic; font-size: 9pt; line-height: 1.5; margin-top: 3em; }

  table.totals { width: 100%; border-collapse: collapse; font-size: 11pt; }
  table.totals td { border: 1px solid #000; padding: 5px 10px; }
  table.totals .lbl { font-weight: bold; width: 55%; text-align: right; }
  table.totals .val { text-align: right; font-weight: bold; font-variant-numeric: tabular-nums; }

  .signatures { width: 100%; margin-top: 50px; }
  .sig-table { width: 100%; border-collapse: collapse; }
  .sig-table td { width: 50%; padding: 0 40px; }
  .sig {
    text-align: center;
    border-top: 1px solid #000;
    padding-top: 4px;
    font-size: 10pt;
    font-weight: bold;
  }

  .page-footer {
    display: table;
    width: 100%;
    padding-top: 20px;
    border-top: 1.5px solid #555;
    font-size: 7.5pt;
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    padding-left: 3mm;
    padding-right: 3mm;
    padding-bottom: 0;
    background: #fff;
  }
  .footer-col {
    display: table-cell;
    vertical-align: middle;
    padding-left: 10px;
    padding-right: 10px;
  }
  .footer-col-left {
    width: 48%;
    padding-left: 0;
    white-space: nowrap;
  }
  .footer-col-center {
    width: 18%;
    text-align: center;
    white-space: nowrap;
  }
  .footer-col-right {
    width: 20%;
    text-align: right;
  }
  .footer-col-qr {
    width: 8%;
    text-align: right;
    padding-right: 0;
  }

  .footer-col-left svg,
  .footer-col-left img {
    float: left;
    margin-top: 2px;
  }
  .footer-text-block {
    overflow: hidden;
    line-height: 1.6;
    white-space: nowrap;
  }
  .footer-generated {
    font-size: 6.5pt;
    color: #333;
  }
  .footer-brand {
    font-size: 7pt;
    margin-top: 1px;
    white-space: normal;
  }
  .footer-brand b {
    color: #1a3c8a;
  }
  .footer-nebo {
    font-size: 8.5pt;
    margin-top: 1px;
    white-space: normal;
  }
  .footer-nebo b {
    color: #1a3c8a;
  }

  .footer-col-center svg,
  .footer-col-center img {
    display: inline;
    vertical-align: middle;
    margin-right: 5px;
  }
  .footer-registered {
    font-size: 7.5pt;
    color: #333;
    vertical-align: middle;
  }

  .footer-contact-line {
    font-size: 8pt;
    margin-bottom: 5px;
    white-space: nowrap;
    line-height: 20px;
    text-align: right;
  }
  .footer-contact-line span {
    vertical-align: middle;
  }

  .qr-img {
    width: 55px;
    height: 55px;
    display: inline-block;
  }
  .qr-placeholder {
    width: 55px;
    height: 55px;
    border: 1px dashed #999;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 8pt;
    color: #999;
  }
  .qr-caption {
    font-size: 6.5pt;
    margin-top: 2px;
    line-height: 1.2;
    text-align: right;
    color: #333;
  }
"""
