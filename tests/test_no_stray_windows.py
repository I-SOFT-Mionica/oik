"""Starting the app must open exactly one window.

A child widget given setVisible(True) before it has a parent becomes a
top-level window for a moment -- on a real screen, dozens of those read
as windows flashing at startup ("like tests running"). Only hiding is
safe before parenting; children show with their window anyway.
"""

from __future__ import annotations

from unittest.mock import patch

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QWidget


class _WindowSpy(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.windows: list[str] = []

    def eventFilter(self, obj, ev):  # noqa: N802
        if ev.type() == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow():
            self.windows.append(f"{type(obj).__name__} {obj.objectName()!r}")
        return False


def test_main_window_construction_opens_no_other_window(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path / "home"))
    from biracki_odbor import _release_info
    from biracki_odbor.gui.main_window import MainWindow
    from biracki_odbor.gui.style import apply_global_style

    app = QApplication.instance() or QApplication([])
    apply_global_style(app)
    spy = _WindowSpy()
    app.installEventFilter(spy)
    try:
        with patch.object(_release_info, "GITHUB_REPO", ""):
            w = MainWindow()
        app.processEvents()
        assert spy.windows == [], f"widgets shown as their own window: {spy.windows}"
    finally:
        app.removeEventFilter(spy)
        w.deleteLater()
