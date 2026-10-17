# Third-party software

ОИК — Бирачки одбор is licensed under GPL-3.0 (see LICENSE). The official
installer bundles the following libraries under their own licences:

| Library | Licence |
|---|---|
| Qt for Python (PySide6) and Qt | LGPL-3.0 — https://www.qt.io/licensing/ |
| openpyxl | MIT |
| python-docx | MIT |
| pdfplumber / pdfminer.six | MIT |
| pypdfium2 (and PDFium) | Apache-2.0 or BSD-3-Clause |
| Pillow | MIT-CMU (HPND) |
| reportlab | BSD |
| pypdf | BSD-3-Clause |
| httpx | BSD-3-Clause |
| cryptography | Apache-2.0 or BSD-3-Clause |
| certifi | MPL-2.0 |
| pywin32 | PSF |
| PyInstaller bootloader | GPL-2.0 with bootloader exception |

Qt is used as a dynamically linked library; you may replace the bundled Qt
libraries in an installation with your own build of the same version.
