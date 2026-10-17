# PyInstaller spec for the Formalizator installer wizard.
# Build AFTER Formalizator.spec AND Formalizator_Uninstaller.spec so both
# .exes can be bundled inside:
#   pyinstaller --clean Formalizator.spec
#   pyinstaller Formalizator_Uninstaller.spec
#   pyinstaller Formalizator_Setup.spec
# (no --clean after the first — it wipes dist/, taking the exes with it)
# The resulting Formalizator_Setup.exe is self-contained: it carries the
# application, the shared icon and the pre-calibrated starter forms, so
# the end user picks a folder, clicks Next, and gets a desktop shortcut.

# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

block_cipher = None
ROOT = Path('.').resolve()

# Bundle the app + uninstaller exes if already built, so Setup.exe needs
# nothing else alongside it.
extra_datas = []
for name in ('Formalizator.exe', 'Formalizator_Uninstaller.exe'):
    built = ROOT / 'dist' / name
    if built.exists():
        extra_datas.append((str(built), '.'))

a = Analysis(
    [str(ROOT / 'formalizator' / 'installer' / 'installer_main.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / 'formalizator' / 'resources'), 'formalizator/resources'),
        (str(ROOT / 'biracki_odbor' / 'resources'), 'biracki_odbor/resources'),
    ] + extra_datas,
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
    name='Formalizator_Setup',
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
