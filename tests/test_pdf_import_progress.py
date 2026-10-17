"""Tests for PdfImportWidget's async extraction + progress feedback.

Field report: converting a multi-page PDF just showed a static
"Учитавање…" label with no actual progress indication while the GUI
thread was blocked inside pdfplumber for several seconds — no way to
tell "working" from "frozen". Fixed by moving extraction into a
start_worker() background thread (same pattern as every other
long-running operation in the app) with a visible QProgressBar.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(h))
    monkeypatch.setattr("biracki_odbor._release_info.GITHUB_REPO", "", raising=False)
    return h


def _make_widget(app, home):
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.dialogs.pdf_import_dialog import PdfImportWidget
    state = AppState()
    return PdfImportWidget(state)


def test_extract_shows_progress_and_dispatches_worker_immediately(app, home, monkeypatch, tmp_path) -> None:
    """The progress bar must appear and the pick button must disable
    the moment extraction starts — synchronously, before any parsing
    happens — not only after the (possibly slow) parse completes."""
    import biracki_odbor.gui.dialogs.pdf_import_dialog as mod

    calls = []

    class _FakeWorker:
        def __init__(self):
            self.finished = _FakeSignal()
            self.failed = _FakeSignal()

    class _FakeSignal:
        def connect(self, slot):
            pass

    def fake_start_worker(parent, fn, *args, **kwargs):
        calls.append((parent, fn, args, kwargs))
        return _FakeWorker(), object()

    monkeypatch.setattr(mod, "start_worker", fake_start_worker)

    w = _make_widget(app, home)
    try:
        assert not w._progress.isVisibleTo(w)  # noqa: SLF001
        w._extract(tmp_path / "fake.pdf")  # noqa: SLF001

        assert w._progress.isVisibleTo(w)  # noqa: SLF001
        assert not w._btn_pick.isEnabled()  # noqa: SLF001
        assert len(calls) == 1
        _, fn, args, _ = calls[0]
        assert fn is mod._extract_fragments  # noqa: SLF001
        assert args == (tmp_path / "fake.pdf",)
    finally:
        w.deleteLater()


def test_on_extract_finished_populates_table_and_hides_progress(app, home) -> None:
    w = _make_widget(app, home)
    try:
        w._progress.setVisible(True)  # noqa: SLF001
        w._btn_pick.setEnabled(False)  # noqa: SLF001

        frags = [(1, 1, [["А", "Б"], ["1", "2"]])]
        w._on_extract_finished(frags)  # noqa: SLF001

        assert not w._progress.isVisibleTo(w)  # noqa: SLF001
        assert w._btn_pick.isEnabled()  # noqa: SLF001
        assert w._combo.count() == 1  # noqa: SLF001
        assert w._btn_save.isEnabled()  # noqa: SLF001
        assert w._preview.rowCount() == 2  # noqa: SLF001 — header row is real data (RIK PDFs have no separate header row)
    finally:
        w.deleteLater()


def test_on_extract_finished_no_tables_found_shows_message(app, home) -> None:
    w = _make_widget(app, home)
    try:
        w._on_extract_finished([])  # noqa: SLF001
        assert not w._progress.isVisibleTo(w)  # noqa: SLF001
        assert not w._btn_save.isEnabled()  # noqa: SLF001
        assert "нису пронађене" in w._status.text()  # noqa: SLF001
    finally:
        w.deleteLater()


def test_on_extract_failed_warns_and_recovers_ui_state(app, home, monkeypatch) -> None:
    import biracki_odbor.gui.dialogs.pdf_import_dialog as mod
    from PySide6.QtWidgets import QMessageBox

    warned = []
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda *a, **kw: warned.append(True),
    )

    w = _make_widget(app, home)
    try:
        w._progress.setVisible(True)  # noqa: SLF001
        w._btn_pick.setEnabled(False)  # noqa: SLF001

        w._on_extract_failed("boom")  # noqa: SLF001

        assert warned
        assert not w._progress.isVisibleTo(w)  # noqa: SLF001
        assert w._btn_pick.isEnabled()  # noqa: SLF001
    finally:
        w.deleteLater()


def test_extract_fragments_is_plain_python_no_qt(tmp_path: Path) -> None:
    """_extract_fragments must be callable without a QApplication — it
    runs inside a worker thread, not the GUI thread."""
    from biracki_odbor.gui.dialogs.pdf_import_dialog import _extract_fragments
    pytest.importorskip("pdfplumber")
    # A file that isn't a real PDF should raise (pdfplumber's own
    # error), not hang or need Qt to fail cleanly.
    bad_pdf = tmp_path / "not_a_pdf.pdf"
    bad_pdf.write_bytes(b"not a pdf")
    with pytest.raises(Exception):
        _extract_fragments(bad_pdf)
