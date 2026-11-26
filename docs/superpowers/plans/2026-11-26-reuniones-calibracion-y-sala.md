# Calibración de voces y sala presencial — plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use `- [ ]`.

**Goal:** nombres en las reuniones presenciales: muestras de voz antes de grabar (A) y una sala
donde cada teléfono dice cuándo habla su dueño (B).

**Architecture:** A suma muestras como voces conocidas de `reuniones_voces` y transcribe por
grupos de 4. B suma participantes sin cuenta con token propio, niveles por segundo y una `linea`
de quién habla que usa el `con_nombres` de siempre. Spec:
`docs/superpowers/specs/2026-11-26-reuniones-calibracion-y-sala-design.md`.

**Tech:** FastAPI/SQLite, ffmpeg, `segno` (QR), JS sin framework.

Pruebas: `../jarvis/.venv/Scripts/python -m pytest -q` desde el worktree
`C:\Users\Jorge\jarvis-bot-nombres`. PR 1 = `feat/reuniones-calibracion`, PR 2 = `feat/reuniones-sala`.
Pedir OK antes de cada merge.

---

## PR 1 — Calibración

### Task 1: voces conocidas con cualquier nombre + muestras
- Modify `backend/reuniones_voces.py`: conocidas = `voces.json["nombres"]`; `unificar` respeta
  cualquier nombre conocido y numera «Hablante N» por la cantidad de «Hablante» ya usados;
  `guardar_muestra(reunion_id, nombre, datos, formato)` (ffmpeg → wav ≤ 10 s; valida nombre,
  repetidos y máximo 10); `grupos(voces)` reparte en grupos de ≤ 4 parejos.
- Test `tests/test_reuniones_voces.py`: nombre calibrado se respeta; «Hablante» sigue la cuenta
  aunque haya calibrados; `guardar_muestra` rechaza vacío/repetido/11.ª; grupos 7 → [4, 3], 4 → [4].
- [ ] prueba que falla → implementar → suite → commit.

### Task 2: transcribir por grupos y unir
- Modify `backend/reuniones_trabajo.py`: con > 4 voces, una llamada por grupo y
  `reuniones_voces.unir(llamadas, conocidas)`: segmentos de la primera; si su hablante no es
  conocido, el nombre conocido del segmento con más cruce en el tiempo de las otras.
- Test `tests/test_reuniones_trabajo.py` y `tests/test_reuniones_voces.py::test_unir`.
- [ ] prueba → implementar → suite → commit.

### Task 3: ruta de muestras
- Modify `backend/rutas_reuniones.py` (`POST /api/reuniones/{id}/voces?nombre=`, token, 415/400),
  `backend/acceso.py` (`voces` en `LIBRES_PATRON`).
- Test `tests/test_reuniones_presencial.py::test_muestras_de_voz`.
- [ ] prueba → implementar → suite → commit.

### Task 4: pantalla de calibración
- Modify `web/apps/grabadora.js`: `empezar(titulo, {muestras})` sube las muestras antes de grabar;
  `grabarMuestra(segundos)` devuelve un Blob con el micrófono ya abierto; `abrirMicrofono()`;
  en el APK suelta el micrófono antes del servicio.
- Modify `web/apps-reuniones.html`, `web/apps/reuniones.js`, `web/apps/reuniones.css`: diálogo
  `#calibrar` (cuántas personas → por persona nombre + frase + Grabar/Repetir/Siguiente → Empezar);
  chips de voces para todas las de una presencial.
- [ ] navegador local con micrófono falso: 2 muestras + grabación → `voces/<nombre>.wav` en datos
  (sin ffmpeg local la muestra se guarda cruda y el test de backend cubre la conversión).
- [ ] suite, push, PR 1.

## PR 2 — Sala

### Task 5: datos y lógica (`backend/salas.py`, nuevo)
- `basedatos.py`: columna `reuniones.sala`; tablas `reunion_participantes`, `reunion_niveles`.
- `salas.py`: `crear(reunion_id, organizador)`, `por_codigo`, `unirse(codigo, nombre, usuario)`,
  `token_valido`, `guardar_niveles(codigo, participante, token, desde_ms, niveles)` (máximo por
  segundo, upsert), `participantes`, `linea(reunion)` (umbral 0,02 y margen 1,5×), `borrar(reunion)`,
  `equipo(usuario)`, `invitar(organizador, reunion, ids)`.
- `reuniones.crear_presencial(..., sala=False)` crea la sala y al organizador como participante.
- `reuniones_trabajo.cerrar`: con sala, `linea` = `salas.linea(r)` y borra niveles.
- Tests `tests/test_salas.py`.
- [ ] prueba → implementar → suite → commit.

### Task 6: rutas
- `backend/rutas_salas.py` (nuevo, incluido en `main.py`): las de la spec; libres en `acceso.py`
  (`/sala/<codigo>`, `/api/salas/<codigo>/...`, `/apps/sala.js`, `/apps/sala.css`).
  QR con `segno` (agregar a `requirements.txt`).
- Tests `tests/test_salas_api.py` (con y sin sesión, token malo 401, `seguir` false al terminar,
  invitar crea aviso, QR es SVG).
- [ ] prueba → implementar → suite → commit.

### Task 7: pantallas
- `web/sala.html`, `web/apps/sala.js`, `web/apps/sala.css` (participante).
- Reuniones: botón **Crear sala**, tarjeta con QR, link, Copiar, Invitar del equipo (diálogo con
  casillas) y quién está; `grabadora.js` manda los niveles del organizador.
- [ ] navegador local: sala + 2 participantes (pestañas con micrófono falso), niveles llegan,
  terminar → `linea` armada.
- [ ] suite, push, PR 2, README y memoria.
