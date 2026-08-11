# PDF Presenter

**Presentaciones simples y poderosas.** Aplicación de escritorio para Windows escrita en **Python + PyQt5 + PyMuPDF** que convierte tus PDFs en presentaciones profesionales con vista moderador, salida NDI y exportación de diapositivas.

> 🌐 Sitio oficial del proyecto: [https://becerrapedro4.github.io/Pdf-Presenter-web/](https://becerrapedro4.github.io/Pdf-Presenter-web/)

## Características Clave

- **Modo Oscuro Inteligente** — Activa el modo oscuro o claro según tu preferencia. La aplicación lo recuerda.
- **Selección y Reordenamiento** — Organiza tus PDFs con vista previa en miniatura y **arrastra para reordenar**.
- **Vista Moderador Avanzada** — Control total de tu presentación con temporizador, vista de diapositiva actual + siguiente, barra de progreso y selector de documento y de monitor.
- **Exportar a Imágenes PNG** — Exporta diapositivas individuales o todas como imágenes de alta calidad.
- **Salida NDI Profesional** — Transmite tu presentación en tiempo real vía NDI a OBS, vMix, Resolume, etc.
- **Drag and Drop** — Carga tus PDFs arrastrando y soltando fácilmente.
- **Unir PDFs** — Combina varios documentos PDF en uno solo rápidamente.

## Extras de la versión 6

- **Impresión** del documento completo o de hojas seleccionadas (especificación tipo `1,3,5-9`).
- **Láser digital** en pantalla para señalar durante la presentación.
- **Páginas ocultas** por documento (no se muestran en la presentación, sí se exportan si las elegís).
- **Renderizado en segundo plano**: la interfaz no se congela con PDFs pesados.
- **Caché LRU** de páginas renderizadas para una navegación fluida.
- **Licencia**: prueba de 15 minutos o activación permanente con clave (persistida en el registro de Windows).

## Requisitos

- Windows (usa `winreg` para la licencia)
- Python 3.9+
- PyQt5, PyMuPDF (fitz), numpy, NDIlib (`Processing.NDI.Lib.x64.dll`)

## Ejecutar desde el código

```bash
pip install PyQt5 PyMuPDF numpy
# NDIlib desde el SDK de NDI: https://ndi.video
python PDFPresenter6.py [archivo.pdf ...]
```

## Compilar a .exe

```bash
pip install pyinstaller
pyinstaller PDFPresenter6.spec --noconfirm
```

El ejecutable queda en `dist\PDFPresenter6.exe` con la DLL de NDI 6 y el ícono incluidos.

## Uso rápido

1. **Cargá** tus PDFs (botón, arrastrar y soltar, o pasándolos como argumento).
2. **Seleccioná y reordená** los documentos en la vista principal.
3. Hacé clic en un documento para abrir la **vista moderador**: preview de la diapositiva actual y siguiente, cronómetro, láser, NDI y selector de monitor.
4. **F5** inicia la presentación fullscreen; navegá con flechas / Espacio / PgUp / PgDn; **ESC** sale.
5. Desde la **Galería** podés ocultar páginas, reordenarlas, exportar a PNG o imprimir.

## Historial de cambios

Ver [CHANGELOG.md](CHANGELOG.md) para el detalle completo de la versión 6.

## Archivos

| Archivo | Descripción |
| --- | --- |
| `PDFPresenter6.py` | Última versión (recomendada) |
| `PDFPresenter6.spec` | Spec de PyInstaller para la v6 |
| `PDFPresenter5.py` | Versión anterior |
| `PDFPresenter5.spec` | Spec de PyInstaller para la v5 |
| `icon.ico` / `icono.ico` | Íconos de la aplicación |
