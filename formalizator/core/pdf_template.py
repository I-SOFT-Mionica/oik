"""One-time conversion of an official Word document to a frozen PDF
background — the only place this app drives Word at all. Every fill
afterward works purely in PDF space (`core.overlay_fill`), never
touching Word again for that template.

Guarded the same way `biracki_odbor.integrations.outlook` guards
pywin32, so this module still imports on non-Windows dev/CI machines.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

WORD_COM_AVAILABLE: bool = False
_IMPORT_ERR: str = ""
try:  # pragma: no cover — covered by a smoke test where reachable
    if sys.platform == "win32":
        import win32com.client  # noqa: F401
        WORD_COM_AVAILABLE = True
except Exception as e:  # noqa: BLE001 — any import error means "no Word COM"
    _IMPORT_ERR = str(e)


class WordUnavailable(Exception):
    """Raised when export_to_pdf is called without Word installed (or
    on a non-Windows platform). Callers should guard with
    WORD_COM_AVAILABLE first."""


# Word's SaveAs2 FileFormat constant for PDF.
_WD_FORMAT_PDF = 17

# argv flag the frozen build uses to re-enter itself as a headless
# converter instead of starting the GUI (see start_conversion_process).
CONVERT_FLAG = "--convert-to-pdf"


def export_to_pdf(doc_path: Path | str, out_pdf_path: Path | str) -> Path:
    """Open `doc_path` (.doc or .docx) in Word and export it as PDF —
    a faithful, pixel-preserving snapshot of however the document is
    currently tuned, used as the fill mechanism's frozen background."""
    if not WORD_COM_AVAILABLE:
        raise WordUnavailable(
            f"Microsoft Word unavailable on this platform: {_IMPORT_ERR or 'not Windows'}"
        )
    import win32com.client

    doc_path = Path(doc_path).resolve()
    out_pdf_path = Path(out_pdf_path).resolve()
    out_pdf_path.parent.mkdir(parents=True, exist_ok=True)

    word = win32com.client.DispatchEx("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0  # wdAlertsNone — never let Word wait on a dialog we can't click
    try:
        doc = word.Documents.Open(str(doc_path), ReadOnly=True, ConfirmConversions=False)
        # A file carrying a Mark-of-the-Web (routine for anything that
        # arrived by email/download — i.e. most real official docs the
        # client will load) makes Word open it in Protected View, a
        # banner window that `Visible = False` cannot suppress. Nothing
        # can click "Enable Editing" in an automated run, so SaveAs2
        # would hang forever waiting for it. Promote it to a normal,
        # editable Document via the documented API for this exact case
        # instead — confirmed reproducible with the real NPRS-3 .doc.
        if word.ProtectedViewWindows.Count > 0:
            doc = word.ProtectedViewWindows(word.ProtectedViewWindows.Count).Edit()
        try:
            doc.SaveAs2(str(out_pdf_path), FileFormat=_WD_FORMAT_PDF)
        finally:
            doc.Close(SaveChanges=False)
    finally:
        word.Quit()
    return out_pdf_path


def start_conversion_process(doc_path: Path | str, out_pdf_path: Path | str) -> subprocess.Popen:
    """Run `export_to_pdf` in its own OS process instead of a thread in
    this one.

    Tried backgrounding it on a plain Python thread first — that was
    wrong. pywin32's blocking COM calls hold the GIL while they wait,
    so a stuck Word instance can freeze this *entire* process's
    interpreter, safety-net timer included (confirmed directly: a
    conversion sat at "converting" for 5+ minutes with no timeout ever
    firing, because the thread meant to detect the stall never got to
    run). A separate process can be polled and killed without touching
    this one at all, however long Word decides to hang for."""
    if getattr(sys, "frozen", False):
        # In a PyInstaller build `sys.executable` is this application's
        # own .exe, and a frozen exe has no `-m` — spawning it that way
        # would relaunch the whole GUI instead of converting anything.
        # The entry point recognises this flag and runs the conversion
        # headlessly before any Qt object exists (see __main__.main).
        command = [sys.executable, CONVERT_FLAG, str(doc_path), str(out_pdf_path)]
    else:
        command = [
            sys.executable, "-m", "formalizator.core.pdf_template",
            str(doc_path), str(out_pdf_path),
        ]
    return subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        # No console window for the child — otherwise every conversion
        # flashes a black box over the operator's screen.
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


if __name__ == "__main__":  # pragma: no cover — exercised as a real subprocess, not imported
    try:
        export_to_pdf(sys.argv[1], sys.argv[2])
    except Exception as e:  # noqa: BLE001 — surface it to the parent process's stderr
        sys.stderr.write(str(e))
        sys.exit(1)
