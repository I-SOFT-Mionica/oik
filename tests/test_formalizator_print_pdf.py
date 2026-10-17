"""Tests for formalizator.core.print_pdf — sending a filled declaration to
the default printer, including the multi-copy path."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


def _FakeWin32Print(default: str, installed: list[str]):  # noqa: N802 — stands in for a module
    """Stands in for the real win32print, whose answers depend entirely
    on which printers happen to be installed on the machine running the
    tests."""
    mod = types.ModuleType("win32print")
    mod.PRINTER_ENUM_LOCAL = 2
    mod.PRINTER_ENUM_CONNECTIONS = 4
    mod.GetDefaultPrinter = lambda: default
    # Real EnumPrinters returns tuples; only index 2 (the name) is read.
    mod.EnumPrinters = lambda flags: [(0, "", name, "") for name in installed]
    return mod


def _disable_qt_printing(monkeypatch, mod) -> None:
    """Force the shell fallback.

    Without this the tests below would reach `_print_via_qt` for real —
    and if any earlier test in the session left a QApplication alive,
    that is a genuine print job sent to the machine's printer from a
    unit test run."""
    def _fail(*_args, **_kwargs):
        raise RuntimeError("Qt printing disabled for this test")

    monkeypatch.setattr(mod, "_print_via_qt", _fail)


def _make_pdf(path: Path, n_pages: int = 1) -> Path:
    c = canvas.Canvas(str(path), pagesize=A4)
    for _ in range(n_pages):
        c.drawString(100, 700, "test page")
        c.showPage()
    c.save()
    return path


def test_print_pdf_raises_on_non_windows(monkeypatch, tmp_path: Path) -> None:
    import formalizator.core.print_pdf as mod

    monkeypatch.setattr(mod.sys, "platform", "linux")
    with pytest.raises(mod.PrintUnavailable):
        mod.print_pdf(tmp_path / "doesnt_matter.pdf")


def test_print_pdf_with_one_copy_prints_the_original_file_once(monkeypatch, tmp_path: Path) -> None:
    import formalizator.core.print_pdf as mod

    monkeypatch.setattr(mod.sys, "platform", "win32")
    monkeypatch.setattr(mod, "_resolve_target_printer", lambda: None)
    _disable_qt_printing(monkeypatch, mod)
    calls = []
    monkeypatch.setattr(mod.os, "startfile", lambda path, verb: calls.append((path, verb)))

    src = _make_pdf(tmp_path / "declaration.pdf")
    mod.print_pdf(src, copies=1)

    assert calls == [(str(src), "print")]


def test_virtual_printers_are_recognised_by_name() -> None:
    """A default of "Microsoft Print to PDF" silently writes a file
    instead of putting ink on paper — the failure that started this."""
    import formalizator.core.print_pdf as mod

    for virtual in (
        "Microsoft Print to PDF", "Microsoft XPS Document Writer",
        "OneNote (Desktop)", "Adobe PDF", "Nitro PDF Creator", "Fax",
        "AnyDesk v4 Printer Driver",
    ):
        assert mod._is_virtual_printer(virtual), virtual  # noqa: SLF001

    for real in ("Podrska Printer", "HP LaserJet 1020", "Canon MF3010"):
        assert not mod._is_virtual_printer(real), real  # noqa: SLF001


def test_a_real_default_printer_is_left_alone(monkeypatch) -> None:
    """No second-guessing when the OS default is already a real
    printer — that path worked and stays untouched."""
    import formalizator.core.print_pdf as mod

    monkeypatch.setitem(sys.modules, "win32print", _FakeWin32Print("HP LaserJet 1020", ["HP LaserJet 1020"]))

    assert mod._resolve_target_printer() is None  # noqa: SLF001


def test_virtual_default_with_one_real_printer_resolves_to_it(monkeypatch) -> None:
    import formalizator.core.print_pdf as mod

    monkeypatch.setitem(sys.modules, "win32print", _FakeWin32Print(
        "Microsoft Print to PDF", ["Microsoft Print to PDF", "Fax", "HP LaserJet 1020"],
    ))

    assert mod._resolve_target_printer() == "HP LaserJet 1020"  # noqa: SLF001


def test_virtual_default_with_no_real_printer_is_a_clear_error(monkeypatch) -> None:
    """Refusing loudly beats "printing" into a PDF file nobody notices."""
    import formalizator.core.print_pdf as mod

    monkeypatch.setitem(sys.modules, "win32print", _FakeWin32Print(
        "Microsoft Print to PDF", ["Microsoft Print to PDF", "Fax"],
    ))

    with pytest.raises(mod.PrintUnavailable) as excinfo:
        mod._resolve_target_printer()  # noqa: SLF001
    assert "Microsoft Print to PDF" in str(excinfo.value)


def test_virtual_default_with_several_real_printers_asks_the_operator(monkeypatch) -> None:
    """Which of two real printers the operator wants isn't something to
    guess at — name them and let the operator set the default."""
    import formalizator.core.print_pdf as mod

    monkeypatch.setitem(sys.modules, "win32print", _FakeWin32Print(
        "Microsoft Print to PDF", ["Microsoft Print to PDF", "HP LaserJet 1020", "Canon MF3010"],
    ))

    with pytest.raises(mod.PrintUnavailable) as excinfo:
        mod._resolve_target_printer()  # noqa: SLF001
    assert "HP LaserJet 1020" in str(excinfo.value)
    assert "Canon MF3010" in str(excinfo.value)


def test_print_pdf_with_multiple_copies_prints_once_with_a_repeated_page_file(
    monkeypatch, tmp_path: Path,
) -> None:
    """The whole point: N copies is one print job with N identical
    pages, not N separate OS "print" verb invocations racing each
    other — each of those spins up its own handler process with no
    guarantee of completing before the next one starts."""
    import formalizator.core.print_pdf as mod

    monkeypatch.setattr(mod.sys, "platform", "win32")
    monkeypatch.setattr(mod, "_resolve_target_printer", lambda: None)
    _disable_qt_printing(monkeypatch, mod)
    calls = []
    monkeypatch.setattr(mod.os, "startfile", lambda path, verb: calls.append((path, verb)))

    src = _make_pdf(tmp_path / "declaration.pdf")
    mod.print_pdf(src, copies=3)

    assert len(calls) == 1  # exactly one print job, not three
    printed_path, verb = calls[0]
    assert verb == "print"
    assert printed_path != str(src)  # a distinct, expanded file

    reader = PdfReader(printed_path)
    assert len(reader.pages) == 3


def test_pdf_with_repeated_pages_preserves_page_count_per_copy(tmp_path: Path) -> None:
    """A multi-page source (e.g. a two-page declaration) repeats all
    of its pages per copy, not just the first."""
    import formalizator.core.print_pdf as mod

    src = _make_pdf(tmp_path / "declaration.pdf", n_pages=2)

    out = mod._pdf_with_repeated_pages(src, copies=2)  # noqa: SLF001

    reader = PdfReader(out)
    assert len(reader.pages) == 4


def test_printing_goes_through_qt_and_never_touches_the_shell(monkeypatch, tmp_path: Path) -> None:
    """The regression this replaced: `ShellExecute(0, "printto", ...)`
    is a silent no-op unless the machine's PDF handler registers a
    printto verb, and Edge — the handler on a stock laptop — does not.
    Nothing in the normal path may depend on the shell any more."""
    import formalizator.core.print_pdf as mod

    monkeypatch.setattr(mod.sys, "platform", "win32")
    monkeypatch.setattr(mod, "_resolve_target_printer", lambda: "HP LaserJet 1020")
    qt_calls = []
    monkeypatch.setattr(mod, "_print_via_qt", lambda p, n, c: qt_calls.append((p, n, c)))
    shell_calls = []
    monkeypatch.setattr(mod.os, "startfile", lambda path, verb: shell_calls.append((path, verb)))

    src = _make_pdf(tmp_path / "declaration.pdf")
    mod.print_pdf(src, copies=2)

    assert qt_calls == [(src, "HP LaserJet 1020", 2)]
    assert shell_calls == []


def test_a_qt_failure_still_falls_back_to_the_shell(monkeypatch, tmp_path: Path) -> None:
    """Qt printing is the fix, not a new single point of failure — a
    machine where it breaks is left no worse off than before."""
    import formalizator.core.print_pdf as mod

    monkeypatch.setattr(mod.sys, "platform", "win32")
    monkeypatch.setattr(mod, "_resolve_target_printer", lambda: None)
    _disable_qt_printing(monkeypatch, mod)
    shell_calls = []
    monkeypatch.setattr(mod.os, "startfile", lambda path, verb: shell_calls.append((path, verb)))

    src = _make_pdf(tmp_path / "declaration.pdf")
    mod.print_pdf(src, copies=1)

    assert shell_calls == [(str(src), "print")]


def test_an_unresolvable_printer_is_raised_not_quietly_printed_anyway(monkeypatch, tmp_path: Path) -> None:
    """A PrintUnavailable from printer resolution must reach the
    operator, never be swallowed by the fallback."""
    import formalizator.core.print_pdf as mod

    monkeypatch.setattr(mod.sys, "platform", "win32")

    def _no_printer():
        raise mod.PrintUnavailable("нема штампача")

    monkeypatch.setattr(mod, "_resolve_target_printer", _no_printer)
    monkeypatch.setattr(mod.os, "startfile", lambda path, verb: pytest.fail("must not print"))

    with pytest.raises(mod.PrintUnavailable):
        mod.print_pdf(_make_pdf(tmp_path / "declaration.pdf"))


def test_the_rendered_page_is_actually_drawn_onto_the_print_device(tmp_path: Path) -> None:
    """Exercises the real render-and-draw path end to end against a
    PDF-format QPrinter, which is the same QPaintDevice a physical
    printer presents — no printer hardware, but every step in between
    is the production one."""
    from PySide6.QtGui import QPageSize, QPainter
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtPrintSupport import QPrinter
    from PySide6.QtWidgets import QApplication

    import formalizator.core.print_pdf as mod

    QApplication.instance() or QApplication([])

    src = _make_pdf(tmp_path / "declaration.pdf", n_pages=2)
    doc = QPdfDocument()
    doc.load(str(src))
    assert doc.pageCount() == 2

    out = tmp_path / "printed.pdf"
    printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(str(out))
    printer.setPageSize(QPageSize(doc.pagePointSize(0), QPageSize.Point))

    painter = QPainter()
    assert painter.begin(printer)
    try:
        for page_index in range(doc.pageCount()):
            if page_index:
                printer.newPage()
            mod._draw_page(painter, doc, page_index)  # noqa: SLF001
    finally:
        painter.end()

    assert out.exists() and out.stat().st_size > 0
    assert len(PdfReader(str(out)).pages) == 2


def test_pdf_with_repeated_pages_does_not_touch_the_original_file(tmp_path: Path) -> None:
    import formalizator.core.print_pdf as mod

    src = _make_pdf(tmp_path / "declaration.pdf")
    original_bytes = src.read_bytes()

    mod._pdf_with_repeated_pages(src, copies=3)  # noqa: SLF001

    assert src.read_bytes() == original_bytes


# ── Fallback safety ──────────────────────────────────────────────────
#
# Two laptops, same build, two different failures: one printed nothing
# at all, the other opened Adobe Acrobat on an empty window. Both are
# the "printto" verb — absent on Edge/Chrome, and on Acrobat invoked
# with only the printer when its command line wants file, printer,
# driver and port. The verb is gone; these pin down what replaced it.


def test_the_shell_fallback_never_uses_printto(monkeypatch, tmp_path: Path) -> None:
    import formalizator.core.print_pdf as mod

    monkeypatch.setattr(mod.sys, "platform", "win32")
    monkeypatch.setattr(mod, "_resolve_target_printer", lambda: None)
    _disable_qt_printing(monkeypatch, mod)
    monkeypatch.setattr(mod.os, "startfile", lambda path, verb: None)

    def _explode(*a, **kw):
        raise AssertionError("printto must never be invoked again")

    import sys as _sys
    fake = types.ModuleType("win32api")
    fake.ShellExecute = _explode
    monkeypatch.setitem(_sys.modules, "win32api", fake)

    mod.print_pdf(_make_pdf(tmp_path / "declaration.pdf"))


def test_a_qt_failure_on_a_virtual_default_refuses_instead_of_saving_a_pdf(
    monkeypatch, tmp_path: Path,
) -> None:
    """The shell verb can only follow the OS default. If that default is
    virtual, falling back to it writes a PDF file and reports success —
    exactly the silent failure this module exists to prevent."""
    import formalizator.core.print_pdf as mod

    monkeypatch.setattr(mod.sys, "platform", "win32")
    monkeypatch.setattr(mod, "_resolve_target_printer", lambda: "HP LaserJet 1020")
    _disable_qt_printing(monkeypatch, mod)
    monkeypatch.setattr(mod.os, "startfile", lambda path, verb: pytest.fail("must not print to a virtual default"))

    with pytest.raises(mod.PrintUnavailable) as excinfo:
        mod.print_pdf(_make_pdf(tmp_path / "declaration.pdf"))

    assert "HP LaserJet 1020" in str(excinfo.value)


def test_a_printer_name_qt_spells_differently_is_still_found(monkeypatch) -> None:
    """win32print and Qt do not always agree on a printer's exact
    spelling — case and stray whitespace differ on network queues. An
    exact-match miss would abandon Qt printing on a machine that has the
    printer perfectly well."""
    import formalizator.core.print_pdf as mod

    class _Info:
        def __init__(self, name: str) -> None:
            self._name = name
        def printerName(self) -> str:  # noqa: N802 — mirrors the Qt API
            return self._name
        def isNull(self) -> bool:  # noqa: N802
            return self._name == ""

    fake = types.ModuleType("PySide6.QtPrintSupport")
    fake.QPrinterInfo = type("QPrinterInfo", (), {
        "__init__": lambda self: setattr(self, "_name", ""),
        "printerName": lambda self: "",
        "isNull": lambda self: True,
        "printerInfo": staticmethod(lambda name: _Info("")),
        "availablePrinters": staticmethod(lambda: [_Info("  HP LaserJet 1020  ")]),
        "defaultPrinter": staticmethod(lambda: _Info("Microsoft Print to PDF")),
    })
    monkeypatch.setitem(sys.modules, "PySide6.QtPrintSupport", fake)

    found = mod._qt_printer_info("hp laserjet 1020")  # noqa: SLF001

    assert found.printerName().strip() == "HP LaserJet 1020"


# ── The locked-down machine ──────────────────────────────────────────
#
# No Edge, no Chrome, no Acrobat, and "Microsoft Print to PDF" removed.
# Nothing in the Qt path needs a PDF handler — Qt renders and talks to
# the printer driver itself — so the only question that matters is
# whether a real printer can be resolved.


def _win32_without_default(installed: list[str]):
    """GetDefaultPrinter raises when no default is set — which is what
    removing Microsoft Print to PDF can leave behind."""
    mod = types.ModuleType("win32print")
    mod.PRINTER_ENUM_LOCAL = 2
    mod.PRINTER_ENUM_CONNECTIONS = 4

    def _raise():
        raise RuntimeError("The specified printer handle is not valid")

    mod.GetDefaultPrinter = _raise
    mod.EnumPrinters = lambda flags: [(0, "", name, "") for name in installed]
    return mod


def test_no_default_printer_but_one_real_one_still_prints(monkeypatch) -> None:
    """A machine with one working printer and no default set must still
    print. The "one real printer" rescue previously only ran on the
    virtual-default branch, so this case failed despite being trivially
    resolvable."""
    import formalizator.core.print_pdf as mod

    monkeypatch.setitem(sys.modules, "win32print", _win32_without_default(["HP LaserJet 1020"]))

    assert mod._resolve_target_printer() == "HP LaserJet 1020"  # noqa: SLF001


def test_no_printers_at_all_says_so_plainly(monkeypatch) -> None:
    """The end of the line: nothing installed, virtual or otherwise.
    The operator gets a sentence they can act on, not a Windows error
    code — and is told the entry survived."""
    import formalizator.core.print_pdf as mod

    monkeypatch.setitem(sys.modules, "win32print", _win32_without_default([]))

    with pytest.raises(mod.PrintUnavailable) as excinfo:
        mod._resolve_target_printer()  # noqa: SLF001

    message = str(excinfo.value)
    assert "ниједан штампач" in message
    assert "сачуван" in message  # the entry is not lost


def test_no_default_and_several_real_printers_asks_the_operator(monkeypatch) -> None:
    import formalizator.core.print_pdf as mod

    monkeypatch.setitem(sys.modules, "win32print", _win32_without_default(
        ["HP LaserJet 1020", "Canon MF3010"],
    ))

    with pytest.raises(mod.PrintUnavailable) as excinfo:
        mod._resolve_target_printer()  # noqa: SLF001

    assert "HP LaserJet 1020" in str(excinfo.value)
    assert "Canon MF3010" in str(excinfo.value)


def test_printing_needs_no_pdf_handler_at_all(monkeypatch, tmp_path: Path) -> None:
    """The whole point of rendering in-process: with a real printer
    resolved, os.startfile is never reached, so a machine with no PDF
    software whatsoever prints perfectly well."""
    import formalizator.core.print_pdf as mod

    monkeypatch.setattr(mod.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "win32print", _win32_without_default(["HP LaserJet 1020"]))
    printed = []
    monkeypatch.setattr(mod, "_print_via_qt", lambda p, n, c: printed.append(n))
    monkeypatch.setattr(mod.os, "startfile", lambda path, verb: pytest.fail("no PDF handler needed"))

    mod.print_pdf(_make_pdf(tmp_path / "declaration.pdf"))

    assert printed == ["HP LaserJet 1020"]


# ── Operator-chosen printer ──────────────────────────────────────────
#
# Inference cannot win on a domain-managed machine: Group Policy sets
# the default printer and reapplies it, so changing it locally does not
# stick. Naming the printer for the session is the only reliable answer.


def test_an_explicitly_chosen_printer_wins_over_the_windows_default(
    monkeypatch, tmp_path: Path,
) -> None:
    import formalizator.core.print_pdf as mod

    monkeypatch.setattr(mod.sys, "platform", "win32")
    monkeypatch.setattr(mod, "_resolve_target_printer", lambda: pytest.fail("must not infer"))
    used = []
    monkeypatch.setattr(mod, "_print_via_qt", lambda p, n, c: used.append(n))

    mod.print_pdf(_make_pdf(tmp_path / "declaration.pdf"), printer_name="Podrska Printer")

    assert used == ["Podrska Printer"]


def test_a_chosen_printer_that_is_gone_is_never_silently_swapped(
    monkeypatch, tmp_path: Path,
) -> None:
    """Falling through to the OS default would print in another room on
    a shared office machine, and look like success from here."""
    import formalizator.core.print_pdf as mod

    monkeypatch.setattr(mod.sys, "platform", "win32")
    _disable_qt_printing(monkeypatch, mod)
    monkeypatch.setattr(mod.os, "startfile", lambda path, verb: pytest.fail("must not fall back"))

    with pytest.raises(mod.PrintUnavailable) as excinfo:
        mod.print_pdf(_make_pdf(tmp_path / "d.pdf"), printer_name="Odsutni Stampac")

    assert "Odsutni Stampac" in str(excinfo.value)
    assert "сачуван" in str(excinfo.value)  # the entry survived


def test_an_empty_choice_still_follows_the_windows_default(monkeypatch, tmp_path: Path) -> None:
    """The picker defaults to "" — existing behaviour must be unchanged
    for everyone who never touches it."""
    import formalizator.core.print_pdf as mod

    monkeypatch.setattr(mod.sys, "platform", "win32")
    monkeypatch.setattr(mod, "_resolve_target_printer", lambda: None)
    used = []
    monkeypatch.setattr(mod, "_print_via_qt", lambda p, n, c: used.append(n))

    mod.print_pdf(_make_pdf(tmp_path / "d.pdf"), printer_name="")

    assert used == [None]
