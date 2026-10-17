"""Render biracki_odbor/resources/icon.svg into a multi-size icon.ico.

One-shot regeneration tool — run after editing the SVG. Output is checked
into the repo so end users / CI don't need PySide6 at icon-build time.

Usage:
    python tools/build_icon.py

The .ico embeds PNG images at 16/32/48/64/128/256 — the modern Vista+
format Windows expects for both the .exe icon and the install folder
icon (via desktop.ini → IconResource).
"""

from __future__ import annotations

import io
import struct
import sys
from pathlib import Path


SIZES = (16, 32, 48, 64, 128, 256)


def _render_png(svg_path: Path, size: int) -> bytes:
    """Rasterize SVG to size×size PNG bytes via PySide6's QSvgRenderer."""
    from PySide6.QtCore import Qt, QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    if QGuiApplication.instance() is None:
        QGuiApplication([])  # required for QImage on some platforms

    renderer = QSvgRenderer(str(svg_path))
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    renderer.render(painter)
    painter.end()

    buf = QByteArray()
    qbuf = QBuffer(buf)
    qbuf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(qbuf, "PNG")
    qbuf.close()
    return bytes(buf)


def build_ico(svg_path: Path, ico_path: Path) -> None:
    payloads = [(s, _render_png(svg_path, s)) for s in SIZES]
    n = len(payloads)

    out = io.BytesIO()
    # ICONDIR: reserved=0, type=1 (ICO), count=n
    out.write(struct.pack("<HHH", 0, 1, n))

    # Directory entries (16 bytes each); offsets begin after the header + table.
    offset = 6 + 16 * n
    for size, png in payloads:
        w = 0 if size >= 256 else size   # 0 encodes "256" in ICO directory
        h = 0 if size >= 256 else size
        out.write(struct.pack(
            "<BBBBHHII",
            w, h, 0, 0,   # width, height, colorCount, reserved
            1, 32,         # planes, bitCount
            len(png), offset,
        ))
        offset += len(png)

    for _, png in payloads:
        out.write(png)

    ico_path.write_bytes(out.getvalue())


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    svg = repo_root / "biracki_odbor" / "resources" / "icon.svg"
    ico = repo_root / "biracki_odbor" / "resources" / "icon.ico"

    if not svg.exists():
        print(f"error: SVG not found at {svg}", file=sys.stderr)
        return 1

    build_ico(svg, ico)
    print(f"wrote {ico} ({ico.stat().st_size} bytes) from {svg.name} "
          f"at sizes {', '.join(str(s) for s in SIZES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
