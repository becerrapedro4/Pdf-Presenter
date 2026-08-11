# -*- mode: python ; coding: utf-8 -*-

import sys
import os

# --- Ruta base del proyecto (compatible con PyInstaller) ---
try:
    project_root = os.path.dirname(os.path.abspath(__file__))
except NameError:
    project_root = os.getcwd()

print(f"Project root directory: {project_root}")

# --- DLL de NDI 6 ---
NDI_SDK_DIR = r"C:\Program Files\NDI\NDI 6 SDK"
NDI_BIN_DIR = os.path.join(NDI_SDK_DIR, "Bin", "x64")


def _find_ndi_dll():
    """Ubica la DLL de NDI en: el SDK instalado, el repo, o el paquete
    ndi-python (permite compilar en CI sin el SDK de NDI instalado)."""
    import importlib.util

    candidates = [
        os.path.join(NDI_BIN_DIR, "Processing.NDI.Lib.x64.dll"),
        os.path.join(project_root, "Processing.NDI.Lib.x64.dll"),
    ]
    try:
        spec = importlib.util.find_spec("NDIlib")
        if spec and spec.submodule_search_locations:
            pkg_dir = list(spec.submodule_search_locations)[0]
            for f in os.listdir(pkg_dir):
                if f.lower().endswith(".dll") and "ndi" in f.lower():
                    candidates.append(os.path.join(pkg_dir, f))
    except Exception:
        pass
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


NDI_DLL = _find_ndi_dll()
if NDI_DLL is None:
    raise SystemExit(
        "No se encontró la DLL de NDI (Processing.NDI.Lib.x64.dll). "
        "Instalá el SDK de NDI o el paquete ndi-python (pip install ndi-python)."
    )
print(f"NDI DLL: {NDI_DLL}")

# --- Paquete NDIlib ---
# NDIlib es un módulo compilado (.pyd) que al importarse crashea el subproceso
# aislado de análisis de PyInstaller en algunas versiones de Python. Por eso se
# EXCLUYE del análisis y se incluye manualmente (pyd + DLL + __init__.py).

def _ndilib_package_dir():
    import importlib.util
    spec = importlib.util.find_spec("NDIlib")
    if spec and spec.submodule_search_locations:
        return list(spec.submodule_search_locations)[0]
    return None


NDILIB_DIR = _ndilib_package_dir()
ndilib_binaries = []
ndilib_datas = []
if NDILIB_DIR:
    for f in os.listdir(NDILIB_DIR):
        p = os.path.join(NDILIB_DIR, f)
        if f.endswith((".pyd", ".dll")):
            ndilib_binaries.append((p, "NDIlib"))
        elif f.endswith((".py", ".txt", ".json", ".md")):
            ndilib_datas.append((p, "NDIlib"))
    print(f"NDIlib empaquetado desde: {NDILIB_DIR} ({len(ndilib_binaries)} binarios, {len(ndilib_datas)} datos)")
else:
    print("Advertencia: no se encontró el paquete NDIlib; NDI no funcionará en el exe.")

# --- Configuración del Análisis ---
a = Analysis(
    ['PDFPresenter6.py'],
    pathex=[project_root],
    binaries=[
        # Incluir la DLL de NDI 6 dentro del ejecutable
        (NDI_DLL, '.'),
    ] + ndilib_binaries,
    datas=[
        ('icon.ico', '.'),
    ] + ndilib_datas,
    # --- Forzar la inclusión de TODOS los módulos problemáticos ---
    hiddenimports=[
        # Numpy completo
        'numpy',
        'numpy.core',
        'numpy.core.multiarray',
        'numpy.core._multiarray_umath',
        'numpy.core._dtype_ctypes',
        'numpy.core._exceptions',
        'numpy.core._internal',
        'numpy.core._methods',
        'numpy.core.arrayprint',
        'numpy.core.fromnumeric',
        'numpy.core.function_base',
        'numpy.core.numeric',
        'numpy.core.numerictypes',
        'numpy.core.shape_base',
        'numpy.compat',
        'numpy.linalg',
        'numpy.linalg.lapack_lite',
        'numpy.random',
        'numpy.random.bit_generator',
        'numpy.random._bounded_integers',
        'numpy.random._common',
        'numpy.random._generator',
        'numpy.random._mt19937',
        'numpy.random._pcg64',
        'numpy.random._philox',
        'numpy.random._sfc64',
        'numpy.random.mtrand',
        'numpy.fft',

        # PyMuPDF
        'fitz',
        'fitz.fitz',
        'fitz.utils',

        # Registro de Windows
        'winreg',

        # PyQt5 (incluye QtPrintSupport para la impresión)
        'PyQt5',
        'PyQt5.QtCore',
        'PyQt5.QtGui',
        'PyQt5.QtWidgets',
        'PyQt5.QtPrintSupport',
        'PyQt5.sip',
    ],
    # --- Excluir módulos innecesarios ---
    excludes=[
        'tkinter',
        'matplotlib',
        'scipy',
        'PyQt5.QtWebEngine',
        'PyQt5.QtWebEngineWidgets',
        'PyQt5.QtNetwork',
        'PyQt5.QtSql',
        'PyQt5.QtTest',
        # NDIlib se incluye manualmente (ver arriba); excluirlo evita que
        # PyInstaller lo importe en el subproceso aislado de análisis.
        'NDIlib',
        'NDIlib.ndi',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

# --- Configuración del PYZ ---
pyz = PYZ(a.pure, a.zipped_data, cipher=None)

# --- Configuración del Ejecutable ---
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='PDFPresenter6',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # Desactivar UPX para evitar conflictos con numpy
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Cambiar a True solo para debug
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',
)
