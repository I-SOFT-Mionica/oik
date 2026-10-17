"""Regression test: the startup splash screen must build without error.

Field report: with nothing shown while MainWindow's ~15 tabs/pages
construct synchronously, startup reads as a blank/flashing white
window. _build_splash() gives the operator a branded screen to look
at during that gap.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_build_splash_returns_nonempty_pixmap(app) -> None:
    from biracki_odbor.__main__ import _build_splash
    splash = _build_splash()
    pix = splash.pixmap()
    assert not pix.isNull()
    assert pix.width() > 0 and pix.height() > 0


def test_build_splash_works_without_icon_file(app, monkeypatch) -> None:
    """Missing icon.ico (e.g. a broken bundle) must not crash the splash."""
    import biracki_odbor.__main__ as main_mod
    from pathlib import Path

    real_exists = Path.exists

    def _fake_exists(self):
        if self.name == "icon.ico":
            return False
        return real_exists(self)

    monkeypatch.setattr(Path, "exists", _fake_exists)
    splash = main_mod._build_splash()
    assert not splash.pixmap().isNull()
