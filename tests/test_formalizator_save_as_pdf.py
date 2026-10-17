"""Tests for the explicit "Сачувај као PDF" printer choice.

Field report: on a machine with no real printer attached, printing
refused outright — core.print_pdf._resolve_target_printer() correctly
refuses to silently fall back onto a virtual printer (that refusal is
the fix for an earlier, worse bug: a virtual default silently producing
a PDF file when the operator expected paper). But that left no way to
get a PDF *on purpose* either — testing the app, an office that emails
declarations instead of printing them, or simply no printer being
physically present at a collection point all need one.

core.print_pdf.SAVE_AS_PDF is a sentinel `printer_name`, offered as its
own explicit, always-present choice in the session setup screen — not
something the automatic virtual-printer refusal ever falls back to on
its own. These tests pin: it's always offered regardless of what
printers exist, choosing it never touches core.print_pdf at all, and
the file lands somewhere that survives past the session.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from formalizator.core.print_pdf import SAVE_AS_PDF


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path / "home"))


# ── home_migration.saved_pdf_dir ──────────────────────────────────────


def test_saved_pdf_dir_is_created_and_persistent(app) -> None:
    from formalizator.core import home_migration

    d = home_migration.saved_pdf_dir()

    assert d.is_dir()
    # Under the app's own working directory, not the fill-out screen's
    # preview folder (a system-temp directory wiped on exit) — this one
    # must survive an app restart.
    assert d.parent == home_migration.default_home()


# ── Setup screen picker ───────────────────────────────────────────────


def _setup_with_printers(app, tmp_path: Path, monkeypatch, names: list[str]):
    import formalizator.core.print_pdf as print_pdf
    from formalizator.gui.setup_screen import SetupScreen

    monkeypatch.setattr(print_pdf, "list_real_printers", lambda: names)
    return SetupScreen(tmp_path / "templates", tmp_path)


def _printer_data(screen) -> list:
    return [screen.cb_printer.itemData(i) for i in range(screen.cb_printer.count())]


def test_save_as_pdf_is_offered_with_no_real_printers(app, tmp_path, monkeypatch) -> None:
    """The exact machine state that broke: no real printer at all."""
    screen = _setup_with_printers(app, tmp_path, monkeypatch, [])
    try:
        assert SAVE_AS_PDF in _printer_data(screen)
    finally:
        screen.deleteLater()


def test_save_as_pdf_is_offered_alongside_real_printers_too(app, tmp_path, monkeypatch) -> None:
    """Not a fallback that only appears when nothing else works —
    available unconditionally, the same choice every time."""
    screen = _setup_with_printers(app, tmp_path, monkeypatch, ["HP LaserJet 1020", "Canon MF3010"])
    try:
        assert SAVE_AS_PDF in _printer_data(screen)
    finally:
        screen.deleteLater()


def test_save_as_pdf_is_not_the_default_selection(app, tmp_path, monkeypatch) -> None:
    """Opt-in, not opt-out — an operator who never touches the dropdown
    must keep getting today's existing behaviour."""
    screen = _setup_with_printers(app, tmp_path, monkeypatch, [])
    try:
        assert screen.cb_printer.currentData() != SAVE_AS_PDF
    finally:
        screen.deleteLater()


def test_a_resumed_session_with_save_as_pdf_reselects_it(app, tmp_path, monkeypatch) -> None:
    from formalizator.core.models import SessionInfo

    screen = _setup_with_printers(app, tmp_path, monkeypatch, [])
    try:
        screen.load_from_info(SessionInfo(template_name="t", printer_name=SAVE_AS_PDF))

        assert screen.cb_printer.currentData() == SAVE_AS_PDF
        assert "недоступан" not in screen.cb_printer.currentText(), (
            "this choice has no hardware dependency and must never be"
            " flagged unavailable"
        )
    finally:
        screen.deleteLater()


# ── FilloutScreen._process_entry ──────────────────────────────────────


def _armed_screen_for_save(app, monkeypatch, tmp_path):
    """Like test_formalizator_fillout_screen.py's _armed_screen, but
    fill_declaration writes a real file (needed here: save-as-pdf
    copies it) and print_pdf raises if ever reached at all."""
    import formalizator.gui.fillout_screen as mod
    from formalizator.core.models import CalibratedTemplate, FieldPosition, SessionInfo
    from formalizator.gui.fillout_screen import FilloutScreen

    def fake_fill(template, entry, out_path, session_info):
        out_path.write_bytes(b"%PDF-1.4 fake declaration")

    def fail_print_pdf(*a, **kw):
        raise AssertionError("print_pdf must never be called in save-as-pdf mode")

    monkeypatch.setattr(mod, "fill_declaration", fake_fill)
    monkeypatch.setattr(mod, "print_pdf", fail_print_pdf)

    screen = FilloutScreen()
    screen.set_template(CalibratedTemplate(
        name="t", background_pdf_path="",
        positions=[FieldPosition(field_key="full_name", page_index=0, x=1.0, y=1.0)],
    ))
    screen.set_session_info(SessionInfo(template_name="t", printer_name=SAVE_AS_PDF))
    return screen


def test_process_entry_saves_instead_of_printing(app, monkeypatch, tmp_path) -> None:
    from formalizator.core import home_migration
    from formalizator.core.models import VoterEntry

    screen = _armed_screen_for_save(app, monkeypatch, tmp_path)
    try:
        final_entry, error = screen._process_entry(  # noqa: SLF001
            VoterEntry(given_name="Ана", surname="Анић", jmbg="2308985774805"),
        )

        assert error == ""
        saved = home_migration.saved_pdf_dir() / "declaration_2308985774805.pdf"
        assert saved.is_file()
        assert saved.read_bytes() == b"%PDF-1.4 fake declaration"
    finally:
        screen.deleteLater()


def test_process_entry_still_emits_entry_printed(app, monkeypatch, tmp_path) -> None:
    """A saved-not-printed entry must still be recorded into the
    session/roster exactly like a printed one — the export is the
    legally binding artefact either way."""
    from formalizator.core.models import VoterEntry

    screen = _armed_screen_for_save(app, monkeypatch, tmp_path)
    recorded = []
    screen.entry_printed.connect(recorded.append)
    try:
        screen._process_entry(  # noqa: SLF001
            VoterEntry(given_name="Ана", surname="Анић", jmbg="2308985774805"),
        )

        assert len(recorded) == 1
        assert recorded[0].full_name == "Ана Анић"
    finally:
        screen.deleteLater()


def test_a_save_failure_is_reported_not_raised(app, monkeypatch, tmp_path) -> None:
    from formalizator.core.models import VoterEntry

    screen = _armed_screen_for_save(app, monkeypatch, tmp_path)

    def boom(*a, **kw):
        raise OSError("disk full")

    monkeypatch.setattr("formalizator.gui.fillout_screen.shutil.copy2", boom)
    try:
        final_entry, error = screen._process_entry(  # noqa: SLF001
            VoterEntry(given_name="Ана", surname="Анић", jmbg="2308985774805"),
        )

        assert error != ""
        assert "disk full" in error
    finally:
        screen.deleteLater()


# ── _on_print end-to-end ──────────────────────────────────────────────


def test_on_print_in_save_mode_never_reaches_print_pdf(app, monkeypatch, tmp_path) -> None:
    import formalizator.gui.fillout_screen as mod

    screen = _armed_screen_for_save(app, monkeypatch, tmp_path)
    monkeypatch.setattr(mod.FilloutScreen, "_confirm_saved_pdf", lambda self, path: None)
    monkeypatch.setattr(mod.QMessageBox, "warning", lambda *a, **kw: None)
    screen.ed_given_name.setText("Ана")
    screen.ed_surname.setText("Анић")
    screen.ed_jmbg.setText("2308985774805")
    try:
        screen._on_print()  # noqa: SLF001 — the AssertionError in fail_print_pdf would surface here if hit
    finally:
        screen.deleteLater()


def test_on_print_in_save_mode_confirms_the_destination(app, monkeypatch, tmp_path) -> None:
    import formalizator.gui.fillout_screen as mod

    screen = _armed_screen_for_save(app, monkeypatch, tmp_path)
    shown = []
    monkeypatch.setattr(mod.FilloutScreen, "_confirm_saved_pdf", lambda self, path: shown.append(path))
    monkeypatch.setattr(mod.QMessageBox, "warning", lambda *a, **kw: pytest.fail("must not warn on success"))
    screen.ed_given_name.setText("Ана")
    screen.ed_surname.setText("Анић")
    screen.ed_jmbg.setText("2308985774805")
    try:
        screen._on_print()  # noqa: SLF001

        assert shown, "must confirm where the file went — a saved file has no other feedback"
    finally:
        screen.deleteLater()


def test_confirm_saved_pdf_opens_folder_only_if_the_button_is_clicked(app, monkeypatch, tmp_path) -> None:
    """The dialog offers "Отвори фасциклу" (see the discoverability
    report this shipped for: 50+ real files existed exactly where the
    app said, but were still "impossible to find" behind a Cyrillic
    folder name sitting straight under the user profile root) — but it
    must never open Explorer unless the operator actually asks for it,
    since a rapid single-entry workflow would otherwise spawn a new
    Explorer window on every save."""
    import formalizator.gui.fillout_screen as mod
    from PySide6.QtWidgets import QMessageBox as RealQMessageBox

    screen = _armed_screen_for_save(app, monkeypatch, tmp_path)
    opened = []
    monkeypatch.setattr(mod.subprocess, "Popen", lambda args: opened.append(args))

    clicked_ok = {}

    def fake_exec(self):
        clicked_ok["button"] = next(
            b for b in self.buttons() if b.text() == "Отвори фасциклу"
        )

    monkeypatch.setattr(RealQMessageBox, "exec", fake_exec)
    monkeypatch.setattr(RealQMessageBox, "clickedButton", lambda self: clicked_ok.get("button"))
    try:
        screen._confirm_saved_pdf(tmp_path / "declaration_123.pdf")  # noqa: SLF001

        assert opened == [["explorer", str(tmp_path)]]
    finally:
        screen.deleteLater()


def test_confirm_saved_pdf_does_not_open_folder_on_plain_dismiss(app, monkeypatch, tmp_path) -> None:
    import formalizator.gui.fillout_screen as mod
    from PySide6.QtWidgets import QMessageBox as RealQMessageBox

    screen = _armed_screen_for_save(app, monkeypatch, tmp_path)
    opened = []
    monkeypatch.setattr(mod.subprocess, "Popen", lambda args: opened.append(args))
    monkeypatch.setattr(RealQMessageBox, "exec", lambda self: None)
    monkeypatch.setattr(RealQMessageBox, "clickedButton", lambda self: None)
    try:
        screen._confirm_saved_pdf(tmp_path / "declaration_123.pdf")  # noqa: SLF001

        assert opened == []
    finally:
        screen.deleteLater()


def test_on_print_in_save_mode_reports_a_save_failure_distinctly(app, monkeypatch, tmp_path) -> None:
    import formalizator.gui.fillout_screen as mod

    screen = _armed_screen_for_save(app, monkeypatch, tmp_path)

    def boom(*a, **kw):
        raise OSError("disk full")

    monkeypatch.setattr(mod.shutil, "copy2", boom)
    warned = []
    monkeypatch.setattr(mod.QMessageBox, "warning", lambda *a, **kw: warned.append(a))
    monkeypatch.setattr(
        mod.QMessageBox, "information",
        lambda *a, **kw: pytest.fail("must not confirm success on a failure"),
    )
    screen.ed_given_name.setText("Ана")
    screen.ed_surname.setText("Анић")
    screen.ed_jmbg.setText("2308985774805")
    try:
        screen._on_print()  # noqa: SLF001

        assert warned
    finally:
        screen.deleteLater()
