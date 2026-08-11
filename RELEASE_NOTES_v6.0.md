# PDF Presenter 6.0

Ejecutable compilado con PyInstaller (onefile, 64-bit). Incluye la DLL de NDI 6 y el ícono.

## Qué hay en este release

- **PDFPresenter6.exe** — aplicación completa lista para usar, sin instalar.

## Cambios principales desde v5

- **Impresión**: documento completo o hojas seleccionadas (`1,3,5-9`), con barra de progreso y centrado a resolución de impresora.
- **Reordenado por arrastre** de documentos funcional.
- **Render en segundo plano**: la interfaz no se congela con PDFs pesados.
- **Páginas ocultas por documento** (ya no se mezclan entre PDFs).
- **Miniaturas de galería correctas** para cada página.
- **NDI con pacing** (~30 fps) para evitar frames congelados en vMix/OBS/Resolume.
- **Navegación corregida**: volver al moderador, ESC al gestor y selección de documento en la vista principal.
- **Corrección de crash y hoja en blanco al imprimir**.

## Uso

```
PDFPresenter6.exe [archivo.pdf ...]
```

Cargá PDFs (botón, arrastrar y soltar o argumentos), seleccioná y reordená, hacé clic en un documento para el moderador, y **F5** inicia la presentación fullscreen (**ESC** sale).

## Nota de firma

Este ejecutable **no está firmado digitalmente**, por lo que Windows SmartScreen puede mostrar "Editor desconocido" y algunos antivirus pueden marcarlo como sospechoso. Se recomienda firmarlo con un certificado de firma de código (ver README) para eliminar esas advertencias.
