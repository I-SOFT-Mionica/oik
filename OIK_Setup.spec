# PyInstaller spec for the installer wizard.
# Build AFTER OIK.spec AND OIK_Uninstaller.spec so we
# can bundle BOTH .exes:
#   pyinstaller --clean OIK.spec
#   pyinstaller --clean OIK_Uninstaller.spec
#   pyinstaller --clean OIK_Setup.spec
# The installer drops the uninstaller into the install dir alongside the
# main exe so the operator can do clean test-cycles (install → use →
# uninstall → reinstall) without leaving residual files behind.

# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

block_cipher = None
ROOT = Path('.').resolve()

# If the prerequisite .exes were already built, bundle them inside the
# installer so the resulting Setup.exe is fully self-contained.
main_exe = ROOT / 'dist' / 'OIK.exe'
uninstaller_exe = ROOT / 'dist' / 'OIK_Uninstaller.exe'
extra_datas = []
if main_exe.exists():
    extra_datas.append((str(main_exe), '.'))
if uninstaller_exe.exists():
    extra_datas.append((str(uninstaller_exe), '.'))

a = Analysis(
    [str(ROOT / 'biracki_odbor' / 'installer' / 'installer_main.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
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
    name='OIK_Setup',
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
