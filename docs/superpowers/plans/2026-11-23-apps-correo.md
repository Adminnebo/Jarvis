# Apps — Correo (Gmail): plan de implementación

> Spec: `docs/superpowers/specs/2026-11-23-apps-correo-design.md`. Rama `feat/apps-correo`.
> Pruebas: `.venv/Scripts/python.exe -m pytest -q`. TDD en cada tarea; commit al terminar cada una.

1. **`gmail.py`: permisos y lectura de la bandeja.** `MODIFICAR` en `PERMISOS`; `permisos(refresh)` con el
   `scope` del canje/refresco; `etiquetas`, `hilos`, `hilo_completo`, `adjunto`, `cambios`.
   Pruebas `tests/test_gmail_bandeja.py` con MockTransport.
2. **`gmail.py`: escritura.** `modificar_hilos`, `papelera`, borradores (crear/actualizar/borrar/enviar),
   `enviar_mime`. Mismas pruebas.
3. **`apps_correo.py`.** `resumen_de_hilo`, `mensaje_para_ver` (HTML, texto→HTML, `cid:` → `data:`,
   adjuntos), `armar_mime` (multipart, respuesta en hilo), `hilos_para_lista` en paralelo, acciones →
   etiquetas. Pruebas `tests/test_apps_correo.py`.
4. **Rutas** `backend/rutas_apps_correo.py` (tabla del spec) + página. Pruebas `tests/test_apps_correo_api.py`:
   409 sin Gmail, 403 sin `gmail.modify`, lista, hilo, adjunto, acciones, borrador, enviar, cambios.
5. **Interfaz** `web/apps-correo.html`, `web/apps/correo.js`, `web/apps/correo.css`; pestañas
   WhatsApp | Correo en las dos vistas; botón "Correo" en el menú. Gmail falso + capturas 1366 / 400 px.
6. **Despliegue y prueba real** (Jorge agrega `gmail.modify` en Google Cloud; OK antes de `main`).
