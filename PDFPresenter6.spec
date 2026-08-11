# -*- mode: python ; coding: utf-8 -*-

import sys
import os

# --- Ruta base del proyecto (compatible con PyInstaller) ---
try:
    project_root = os.path.dirname(os.path.abspath(__file__))
except NameError:
    project_root = os.getcwd()

print(f"Project root directory: {project_root}")

# --- Librería nativa de NDI (Windows: SDK o ndi-python; macOS/Linux: ndi-python) ---
NDI_SDK_DIR = r"C:\Program Files\NDI\NDI 6 SDK"
NDI_BIN_DIR = os.path.join(NDI_SDK_DIR, "Bin", "x64")

_IS_WINDOWS = sys.platform.startswith("win")
_IS_MACOS = sys.platform == "darwin"


def _find_ndi_lib():
    """Ubica la librería nativa de NDI (Processing.NDI.Lib.*) en el SDK de
    Windows, en el repo, o en el paquete ndi-python (para CI sin SDK)."""
    import importlib.util

    candidates = []
    if _IS_WINDOWS:
        candidates.append(os.path.join(NDI_BIN_DIR, "Processing.NDI.Lib.x64.dll"))
        candidates.append(os.path.join(project_root, "Processing.NDI.Lib.x64.dll"))
    try:
        spec = importlib.util.find_spec("NDIlib")
        if spec and spec.submodule_search_locations:
            pkg_dir = list(spec.submodule_search_locations)[0]
            for f in os.listdir(pkg_dir):
                low = f.lower()
                if "ndi" in low and low.endswith((".dll", ".dylib", ".so")):
                    candidates.append(os.path.join(pkg_dir, f))
    except Exception:
        pass
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


NDI_DLL = _find_ndi_lib()
if NDI_DLL is None:
    print("Advertencia: no se encontró la librería nativa de NDI; el build saldrá SIN NDI.")
else:
    print(f"NDI nativo: {NDI_DLL}")

# --- Paquete NDIlib ---
# NDIlib es un módulo compilado (pyd/so) que al importarse crashea el subproceso
# aislado de análisis de PyInstaller en algunas versiones de Python. Por eso se
# EXCLUYE del análisis y se incluye manualmente (módulo + librería + __init__.py).

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
        if f.endswith((".pyd", ".so", ".dylib", ".dll")):
            ndilib_binaries.append((p, "NDIlib"))
        elif f.endswith((".py", ".txt", ".json", ".md")):
            ndilib_datas.append((p, "NDIlib"))
    print(f"NDIlib empaquetado desde: {NDILIB_DIR} ({len(ndilib_binaries)} binarios, {len(ndilib_datas)} datos)")
else:
    print("Advertencia: no se encontró el paquete NDIlib; NDI no funcionará en el build.")

# --- Configuración del Análisis ---
a = Analysis(
    ['PDFPresenter6.py'],
    pathex=[project_root],
    binaries=([(NDI_DLL, '.')] if NDI_DLL else []) + ndilib_binaries,
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

# --- Runtime de VC ---
# El wheel de PyQt5 trae MSVCP140.dll/vcruntime140*.dll en Qt5/bin; al
# empaquetarlas junto con las del sistema se mezclan versiones y la app
# crashea con 0xc0000005. Se quitan del bundle: Windows usa las instaladas
# en el sistema (presentes en cualquier equipo con apps modernas).
if _IS_WINDOWS:
    _VC_RUNTIME_DLLS = {
        "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll",
        "msvcp140_atomic_wait.dll", "vcruntime140.dll", "vcruntime140_1.dll",
        "concrt140.dll",
    }
    a.binaries = [
        b for b in a.binaries
        if os.path.basename(b[0]).lower() not in _VC_RUNTIME_DLLS
    ]
    print("Runtime de VC quitado del bundle (usa el del sistema)")

# --- Configuración del PYZ ---
pyz = PYZ(a.pure, a.zipped_data, cipher=None)

# --- Configuración del Ejecutable ---
if _IS_MACOS:
    # macOS: one-dir + BUNDLE para generar el .app (luego el workflow arma el .dmg)
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name='PDFPresenter6',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        name='PDFPresenter6',
    )
    app = BUNDLE(
        coll,
        name='PDFPresenter6.app',
        icon=None,
        bundle_identifier='com.becerra.pdfpresenter',
        info_plist={
            'NSHighResolutionCapable': True,
            'CFBundleDisplayName': 'PDF Presenter',
            'CFBundleShortVersionString': '6.1',
            'CFBundleVersion': '6.1',
        },
    )
else:
    # Windows y Linux: one-file (un solo ejecutable)
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
        icon='icon.ico' if _IS_WINDOWS else None,
    )
