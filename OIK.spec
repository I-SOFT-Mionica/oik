# PyInstaller spec for the main application.
# Build: pyinstaller --clean OIK.spec

# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

block_cipher = None
ROOT = Path('.').resolve()

a = Analysis(
    [str(ROOT / 'biracki_odbor' / '__main__.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / 'biracki_odbor' / 'resources'), 'biracki_odbor/resources'),
        (str(ROOT / 'biracki_odbor' / 'i18n' / '*.qm'), 'biracki_odbor/i18n'),
        # certifi's cacert.pem. PyInstaller's contrib hook-certifi should
        # collect this already, but that was never verified on a real
        # packaged exe and the failure is silent: the app falls back to
        # the Windows certificate store, which is exactly what breaks the
        # update download on locked-down municipal PCs. ~290 KB to remove
        # the doubt. The About page's Дијагностика card reports which
        # trust store a running build actually ended up with.
        *collect_data_files('certifi'),
    ],
    hiddenimports=[
        'openpyxl',
        'docx',
        'lxml',
        'lxml.etree',
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        # pywin32 family: PyInstaller's stock pywin32 hook misses
        # `win32timezone` because pywintypes imports it dynamically
        # from its C extension during COM datetime marshalling
        # (Outlook ReceivedTime, Excel dates, …). Without these
        # explicit hidden imports the bundled exe crashes the
        # Outlook receive flow with "No module named 'win32timezone'"
        # and the inbox picker shows zero messages.
        'win32timezone',
        'pywintypes',
        'pythoncom',
        'win32com.client',
        'win32api',
        # See the certifi note in datas above.
        'certifi',
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
    name='OIK',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,        # windowed app
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / 'biracki_odbor' / 'resources' / 'icon.ico') if (ROOT / 'biracki_odbor' / 'resources' / 'icon.ico').exists() else None,
)
