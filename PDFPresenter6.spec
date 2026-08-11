# -*- mode: python ; coding: utf-8 -*-

import sys
import os

# --- Ruta base del proyecto (compatible con PyInstaller) ---
try:
    project_root = os.path.dirname(os.path.abspath(__file__))
except NameError:
    project_root = os.getcwd()

print(f"Project root directory: {project_root}")

# --- Ruta del SDK de NDI 6 ---
NDI_SDK_DIR = r"C:\Program Files\NDI\NDI 6 SDK"
NDI_BIN_DIR = os.path.join(NDI_SDK_DIR, "Bin", "x64")

# --- Configuración del Análisis ---
a = Analysis(
    ['PDFPresenter6.py'],
    pathex=[project_root],
    binaries=[
        # Incluir la DLL de NDI 6 dentro del ejecutable
        (os.path.join(NDI_BIN_DIR, 'Processing.NDI.Lib.x64.dll'), '.'),
    ],
    datas=[
        ('icon.ico', '.'),
    ],
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

        # NDI
        'NDIlib',
        'NDIlib.ndi',

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
