# PyInstaller spec for the Formalizator uninstaller.
# Build: pyinstaller --clean Formalizator_Uninstaller.spec
# Built BEFORE Formalizator_Setup.spec so the setup can bundle it and
# drop it into the install folder alongside the app.

# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

block_cipher = None
ROOT = Path('.').resolve()

a = Analysis(
    [str(ROOT / 'formalizator' / 'installer' / 'uninstaller_main.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / 'biracki_odbor' / 'resources'), 'biracki_odbor/resources'),
    ],
    hiddenimports=[
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter'],
    noarchive=False,
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Formalizator_Uninstaller',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / 'biracki_odbor' / 'resources' / 'icon.ico') if (ROOT / 'biracki_odbor' / 'resources' / 'icon.ico').exists() else None,
)
