"""Send a filled declaration PDF to a real printer.

Printing goes through Qt directly: `QPdfDocument` renders each page and
`QPainter` draws it onto a `QPrinter` bound to an explicitly named
printer. Nothing about this depends on what the machine has registered
as its PDF handler, which is the whole point.

The two earlier approaches both failed in the field, and the reasons are
worth keeping written down:

  * `os.startfile(path, "print")` hands the file to whatever the default
    PDF handler is and silently follows Windows' own default printer.
    On a real machine that default is very often a *virtual* printer
    ("Microsoft Print to PDF", "Microsoft XPS Document Writer", a
    PDF-creator utility, a remote-desktop printer driver...) rather than
    the physical one in the room — confirmed directly, more than once:
    it "succeeds" with no error at all, just a new PDF file on disk
    instead of a page coming out of the printer.
  * `ShellExecute(0, "printto", ...)` names the printer explicitly and
    fixes that — but it fails two different ways, both seen in the field
    on the same build:

      - **Edge and Chrome do not register the verb at all**, so nothing
        happens. That is the stock-laptop case, where Edge is the PDF
        handler *and* "Microsoft Print to PDF" is the out-of-the-box
        default printer — the precise combination routed into this
        branch. Nitro and Acrobat do register it, which is why this
        looked fine on a developer machine.
      - **Acrobat registers it and still fails**, because its command
        line is `/t "%1" "%2" "%3" "%4"` — file, printer, driver, port —
        and passing only the printer leaves Acrobat opening an empty
        window and printing nothing.

    The verb is gone for good; nothing here names a printer through the
    shell any more.

Rendering in-process removes the whole class of problem: no handler, no
verb registration, no spooler hand-off to another process. The page is
rasterised at `_RENDER_DPI` and scaled into the printer's printable
area with its aspect ratio preserved, so the tuned layout is reproduced
faithfully — it is a photograph of the finished page, not a re-flow.

`_resolve_target_printer` (the virtual-default detection) is unchanged
and still correct; only the mechanism that acts on its answer changed.
The shell path is kept as a last-resort fallback so a machine where Qt
printing fails for some unforeseen reason is no worse off than before.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from pypdf import PdfReader, PdfWriter

log = logging.getLogger(__name__)

# Rasterisation resolution for the page image. High enough that the
# form's fine print (the НАПОМЕНА legal notes) stays crisp, low enough
# that an A4 page stays a ~35 MB image rather than a ~140 MB one.
_RENDER_DPI = 300
_POINTS_PER_INCH = 72

# Name fragments (case-insensitive) of Windows printer "drivers" that
# don't put ink on paper. Not exhaustive by construction — anything
# genuinely unrecognised is treated as real rather than silently
# filtered, since the failure mode of missing a real printer here
# (nothing prints) is far worse than the failure mode of missing a
# virtual one (an extra PDF file appears alongside the print job).
_VIRTUAL_PRINTER_MARKERS = (
    "microsoft print to pdf",
    "microsoft xps document writer",
    "onenote",
    "adobe pdf",
    "nitro pdf",
    "fax",
    "anydesk",
    "pdf creator",
    "pdfcreator",
    "cutepdf",
    "bullzip",
    "novapdf",
    "dopdf",
)


class PrintUnavailable(Exception):
    """Raised when printing is attempted on a non-Windows platform, or
    when no real (non-virtual) printer can be resolved."""


# Sentinel `printer_name` meaning "keep this as a PDF, don't print it" —
# a deliberate, visible choice offered in the session setup screen's
# printer picker, not the automatic virtual-printer path above.
#
# The two must stay separate. _resolve_target_printer()'s refusal to
# fall back onto a virtual printer when no real one exists is correct
# and stays exactly as strict: that path exists because a virtual
# printer being the OS default is usually an *accident* the operator
# hasn't noticed (see the module docstring — that used to be a silent
# "prints" a PDF file instead of paper, with no error at all). Reported
# from the field once that fix shipped: on a machine with no real
# printer at all, there was then no way to get a PDF either, even
# though sometimes that IS what's wanted — testing the app, an office
# that emails declarations instead of printing them, or simply no
# printer being physically present at a collection point. This
# constant is that explicit escape hatch, chosen on purpose rather than
# landed on by default.
SAVE_AS_PDF = "__save_as_pdf__"


def _is_virtual_printer(name: str) -> bool:
    lowered = name.lower()
    return any(marker in lowered for marker in _VIRTUAL_PRINTER_MARKERS)


def list_real_printers() -> list[str]:
    """Every installed printer that isn't a known virtual/PDF/fax
    driver, in whatever order Windows reports them."""
    import win32print

    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    names = [p[2] for p in win32print.EnumPrinters(flags)]
    return [n for n in names if not _is_virtual_printer(n)]


def _resolve_target_printer() -> str | None:
    """The printer to actually print to.

    None means "use the OS default as-is" — it is already a real
    printer. A resolved name means the default was unusable (virtual, or
    absent) and exactly one real alternative was found. Anything more
    ambiguous than that — no real printer at all, or several, so which
    one is genuinely a question — is an error the operator has to
    resolve, not a guess this function should make for them.

    `GetDefaultPrinter()` *raises* when no default is set, which is not
    an exotic state: removing "Microsoft Print to PDF" from a machine
    that had nothing else set can leave exactly that. Treated here as
    its own case rather than allowed to escape, because a machine with
    one perfectly good printer and no default must still print."""
    import win32print

    try:
        default = win32print.GetDefaultPrinter()
    except Exception:  # noqa: BLE001 — "no default printer set" arrives as pywintypes.error
        default = ""

    if default and not _is_virtual_printer(default):
        return None

    real = list_real_printers()
    if len(real) == 1:
        return real[0]
    if not real:
        raise PrintUnavailable(
            "Није пронађен ниједан штампач на овом рачунару.\n\n"
            "Прикључите штампач и инсталирајте његов драјвер, па покушајте"
            " поново. Унос бирача је сачуван — ништа није изгубљено."
            if not default else
            f"Подразумевани штампач у Windows-у је виртуелни ({default}), "
            "а није пронађен ниједан прави штампач. Прикључите штампач или "
            "промените подразумевани штампач у Windows подешавањима."
        )
    if not default:
        raise PrintUnavailable(
            "У Windows-у није постављен подразумевани штампач, а пронађено"
            f" је више штампача ({', '.join(real)}).\n\n"
            "Поставите жељени штампач као подразумевани (Подешавања →"
            " Штампачи и скенери) па покушајте поново."
        )
    raise PrintUnavailable(
        f"Подразумевани штампач у Windows-у је виртуелни ({default}), а "
        f"пронађено је више правих штампача ({', '.join(real)}). "
        "Поставите жељени штампач као подразумевани у Windows подешавањима "
        "(Подешавања → Штампачи и скенери)."
    )


def _draw_page(painter, doc, page_index: int) -> None:
    """One PDF page, rasterised and fitted into the printable area.

    Aspect ratio is preserved and the result centred: a form whose
    layout was tuned by hand must not be stretched to fill a page whose
    printable area has slightly different proportions."""
    from PySide6.QtCore import QRectF, QSize

    point_size = doc.pagePointSize(page_index)
    image = doc.render(page_index, QSize(
        round(point_size.width() / _POINTS_PER_INCH * _RENDER_DPI),
        round(point_size.height() / _POINTS_PER_INCH * _RENDER_DPI),
    ))
    if image.isNull():
        raise RuntimeError(f"page {page_index} rendered empty")

    viewport = painter.viewport()
    scale = min(viewport.width() / image.width(), viewport.height() / image.height())
    width, height = image.width() * scale, image.height() * scale
    painter.drawImage(
        QRectF((viewport.width() - width) / 2, (viewport.height() - height) / 2, width, height),
        image,
    )


def _qt_printer_info(printer_name: str | None):
    """Find Qt's record for a printer named by win32print.

    The two APIs do not always spell a printer identically — a network
    queue in particular can differ in case or in surrounding whitespace
    between what `EnumPrinters` reports and what Qt exposes. An exact
    lookup that misses returns a null QPrinterInfo, which would abandon
    Qt printing for a machine that has the printer perfectly well, so
    the exact match is backed by a case-insensitive sweep of the list
    Qt itself provides."""
    from PySide6.QtPrintSupport import QPrinterInfo

    if printer_name is None:
        return QPrinterInfo.defaultPrinter()

    info = QPrinterInfo.printerInfo(printer_name)
    if not info.isNull():
        return info

    wanted = printer_name.strip().casefold()
    for candidate in QPrinterInfo.availablePrinters():
        if candidate.printerName().strip().casefold() == wanted:
            return candidate
    return QPrinterInfo()  # null — the caller decides what that means


def _print_via_qt(path: Path, printer_name: str | None, copies: int) -> None:
    """Render and print in-process. Raises on any failure so the caller
    can fall back."""
    from PySide6.QtGui import QPageSize, QPainter
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtPrintSupport import QPrinter, QPrinterInfo
    from PySide6.QtWidgets import QApplication

    if QApplication.instance() is None:
        # QPainter-on-QPrinter needs a running Qt application; without
        # one this would abort the process rather than raise.
        raise RuntimeError("no QApplication instance")

    doc = QPdfDocument()
    doc.load(str(path))
    if doc.pageCount() < 1:
        raise RuntimeError(f"could not load PDF: {path}")

    info = _qt_printer_info(printer_name)
    if info.isNull():
        raise RuntimeError(f"printer not found: {printer_name or '(default)'}")

    printer = QPrinter(info, QPrinter.HighResolution)
    printer.setPageSize(QPageSize(doc.pagePointSize(0), QPageSize.Point))

    # Prefer the driver's own copy handling — it collates properly and
    # sends one job. Not every driver reports support for it, in which
    # case the pages are simply drawn again per copy.
    passes = 1
    if copies > 1:
        if printer.supportsMultipleCopies():
            printer.setCopyCount(copies)
        else:
            passes = copies

    painter = QPainter()
    if not painter.begin(printer):
        raise RuntimeError(f"could not start print job on {info.printerName()}")
    try:
        started = False
        for _ in range(passes):
            for page_index in range(doc.pageCount()):
                if started:
                    printer.newPage()
                started = True
                _draw_page(painter, doc, page_index)
    finally:
        painter.end()


def _pdf_with_repeated_pages(path: Path, copies: int) -> Path:
    """`copies` identical copies as a single document, for the shell
    fallback — which has no way to ask for a copy count, and where
    invoking the OS "print" verb N times would spin up N handler
    processes racing each other through the spooler. Every copy is
    identical, so this is just the same page(s) repeated."""
    reader = PdfReader(str(path))
    writer = PdfWriter()
    for _ in range(copies):
        for page in reader.pages:
            writer.add_page(page)
    out_path = path.with_name(f"{path.stem}_x{copies}{path.suffix}")
    with open(out_path, "wb") as f:
        writer.write(f)
    return out_path


def _print_via_shell(path: Path, copies: int) -> None:
    """Last resort: hand the file to the registered PDF handler and let
    it follow the OS default printer.

    Only ever reached when that default is already a *real* printer —
    see `print_pdf`. The "printto" verb that used to live here is gone
    for good: it is a silent no-op on any machine whose PDF handler does
    not register it (Edge, Chrome), and on Acrobat, which does register
    it, the verb's command line is `/t "%1" "%2" "%3" "%4"` — file,
    printer, driver, port — so passing only the printer made Acrobat
    open an empty window and print nothing. Both failures were seen in
    the field, on two different laptops, from the same build."""
    if copies > 1:
        path = _pdf_with_repeated_pages(path, copies)
    os.startfile(str(path), "print")  # noqa: S606 — user-supplied printable file, not arbitrary code


def print_pdf(path: Path | str, copies: int = 1, printer_name: str = "") -> None:
    """Print `path`.

    `printer_name` is the operator's explicit choice for this session
    and wins over everything this module can infer. That matters most on
    a domain-managed machine, where the default printer is set by Group
    Policy and reapplied behind the operator's back, so "just change the
    default" is not a fix that survives. Empty means follow Windows' own
    default, with the virtual-printer rescue applied on top."""
    if sys.platform != "win32":
        raise PrintUnavailable("Printing is only supported on Windows.")
    path = Path(path)
    copies = max(1, copies)

    chosen = (printer_name or "").strip()
    if chosen:
        target = chosen
    else:
        try:
            target = _resolve_target_printer()
        except PrintUnavailable:
            raise
        except Exception:  # noqa: BLE001 — win32print unavailable/erroring: fail open, not silent
            target = None

    try:
        _print_via_qt(path, target, copies)
        return
    except PrintUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 — decide below whether a fallback is even safe
        log.warning("Qt printing failed: %s", exc)

    # An explicitly chosen printer is never quietly substituted. If it
    # cannot be printed to, the operator needs to know that the printer
    # they named is the problem — falling through to the OS default here
    # would print somewhere they did not ask for, which on a shared
    # office machine means the pages come out in another room.
    if chosen:
        raise PrintUnavailable(
            f"Штампач „{chosen}” тренутно није доступан.\n\n"
            "Проверите да ли је укључен и повезан, или изаберите други"
            " штампач на почетном екрану сесије. Унос бирача је сачуван."
        )

    # The shell verb always follows the OS default printer, which is the
    # one thing it cannot be told. So it is only a safe fallback when
    # that default is already real. When `target` is set the default is
    # virtual — printing there would quietly produce a PDF file instead
    # of paper, which is the original silent failure this whole module
    # exists to prevent. Refuse, loudly, rather than appear to succeed.
    if target is not None:
        raise PrintUnavailable(
            f"Штампање преко Windows-а није успело за штампач „{target}”, "
            "а подразумевани штампач је виртуелни, па би документ био "
            "сачуван као PDF уместо одштампан.\n\n"
            f"Поставите „{target}” као подразумевани штампач у Windows "
            "подешавањима (Подешавања → Штампачи и скенери) и покушајте поново."
        )

    _print_via_shell(path, copies)
