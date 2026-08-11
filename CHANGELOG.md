# Changelog

## v6 (actual) — PDF Presenter 6

Versión basada en `PDFPresenter5.py` con correcciones de robustez, nuevas funcionalidades y mejoras de rendimiento. Es la versión recomendada.

### Nuevas funcionalidades

- **Impresión**: botón en el moderador y en la galería. Permite imprimir el **documento completo** o **hojas seleccionadas** (especificación tipo `1,3,5-9`, autocompletada con las páginas marcadas como "Exp." en la galería). Usa el diálogo estándar de Windows, con barra de progreso y centrado en la hoja a resolución de impresora.

### Correcciones de bugs

- **Reordenado por arrastre de documentos funcionando**: las tarjetas distinguen clic de arrastre (señal propia `clicked`) y la grilla acepta drops internos con un MIME propio; al reordenar se remapean las páginas ocultas y el combo del moderador.
- **`current_page` se re-mapea** al mover páginas ▲▼ en la galería (también el estado oculto de las dos posiciones intercambiadas).
- **`hidden_pages` por documento**: ahora es un diccionario `{doc_index: set}`; ocultar una página de un PDF ya no afecta a los demás.
- **Galería sin duplicación de código**: el grid se construye en un único método reutilizado por abrir y refrescar.
- **Sin `except:` desnudos**: todos registran el error en `pdf_presenter_error.log`.
- **Ícono corregido**: la v5 referenciaba `icono.ico` que no existía; ahora usa `icon.ico` con `resource_path`, que funciona también dentro del .exe.
- **Miniaturas de galería**: se renderiza correctamente cada página (antes se mostraba siempre la página 0 del documento equivocado y varias quedaban en blanco).
- **Navegación entre vistas**: los índices del `QStackedWidget` se calculan dinámicamente, por lo que "Volver al moderador" desde la galería y el flujo tras recargar PDFs funcionan siempre.
- **Tecla ESC**: ahora vuelve del moderador al gestor de documentos y de la galería al moderador.
- **Selección de documento en la vista principal**: corregido el clic para que seleccione el PDF correcto (el combo del moderador ahora bloquea señales al armarse).
- **Crash y hoja en blanco al imprimir**: `QPrinter.pageRect()` devuelve `QRectF` (flotante); se convierte a enteros antes de escalar/dibujar, y cada página se protege para que un fallo puntual no corte el trabajo.

### Mejoras de rendimiento y robustez

- **Renderizado en segundo plano**: un `RenderWorker(QThread)` con cola FIFO + lock serializa el acceso a fitz. Las previews (actual/siguiente), la presentación y las miniaturas se renderizan asíncronamente con invalidación por versión (los renders obsoletos se descartan).
- **Sin doble conversión PNG**: el `QImage` se construye directo desde `pix.samples` (RGB888) con copia segura de píxeles.
- **NDI con pacing**: timer de ~30 fps que mantiene el flujo constante aunque la diapositiva no cambie (evita frames congelados en vMix/OBS).
- **Licencia ligada a la máquina**: `_machine_id` ahora se usa en la validación de claves (se mantiene el hash legado para claves existentes).

## v5 — PDF Presenter 5

Versión anterior sin las correcciones de la v6. Se conserva en el repositorio como referencia histórica.
