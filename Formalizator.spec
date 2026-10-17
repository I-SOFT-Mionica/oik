# PyInstaller spec for Formalizator (voter-support signature collection).
# Build: pyinstaller --clean Formalizator.spec
#
# Mirrors OIK.spec. Formalizator is a companion to the main app and
# imports from it (the shared Qt style, the JMBG MOD-11 module), so
# biracki_odbor ships inside this bundle too — including its resources,
# which is where the shared product icon lives.

# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

block_cipher = None
ROOT = Path('.').resolve()

a = Analysis(
    [str(ROOT / 'formalizator' / '__main__.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        # Starter forms + the bundled CelikApi.dll live here.
        (str(ROOT / 'formalizator' / 'resources'), 'formalizator/resources'),
        # Shared icon and whatever else the reused GUI code reads.
        (str(ROOT / 'biracki_odbor' / 'resources'), 'biracki_odbor/resources'),
    ],
    hiddenimports=[
        'openpyxl',
        'reportlab',
        'pypdf',
        'pdfplumber',
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        # The document preview and the calibration wizard's page render —
        # and, since printing moved in-process, the render half of the
        # print path too (see core.print_pdf).
        'PySide6.QtPdf',
        'PySide6.QtPdfWidgets',
        # QPrinter/QPrinterInfo: printing draws the rendered page onto an
        # explicitly named printer rather than handing the file to
        # whatever PDF handler is registered. Without this in the bundle
        # the frozen build silently falls back to the shell verbs, which
        # is the failure this replaced.
        'PySide6.QtPrintSupport',
        # Word COM, used only for the one-time .doc/.docx -> PDF export
        # when a template is calibrated from a Word file. Same missing
        # `win32timezone` hook problem OIK.spec documents.
        'win32timezone',
        'pywintypes',
        'pythoncom',
        'win32com.client',
        'win32api',
        # Printer enumeration, so printing doesn't silently follow a
        # virtual default printer (Microsoft Print to PDF, etc.) — see
        # core.print_pdf.
        'win32print',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # openpyxl imports numpy and lxml opportunistically (for pandas
    # interop and a faster XML backend) and both are optional — the
    # export was verified to produce identical output with all three
    # blocked. They are pure weight in a bundle the operator has to
    # download, so they are left out deliberately rather than by
    # oversight. reportlab's Pillow dependency is NOT excluded: it is
    # imported unconditionally.
    excludes=['tkinter', 'numpy', 'pandas', 'lxml', 'matplotlib', 'scipy'],
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
    name='Formalizator',
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
