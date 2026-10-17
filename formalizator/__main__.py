from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from biracki_odbor.gui.style import apply_global_style
from formalizator.gui.main_window import APP_NAME, MainWindow


def _icon_path() -> Path:
    """The shared product icon. Formalizator is a companion to the OIK
    app rather than a separate product line, so it wears the same one —
    inside a PyInstaller bundle it arrives under `sys._MEIPASS`."""
    meipass = getattr(sys, "_MEIPASS", None)
    root = Path(meipass) if meipass else Path(__file__).resolve().parent.parent
    return root / "biracki_odbor" / "resources" / "icon.ico"


def _run_headless_conversion() -> int:
    """The frozen build re-enters itself to convert a Word document to
    a PDF background, because a PyInstaller exe has no `-m` to spawn a
    module with. Handled before anything Qt is touched, so this process
    stays a plain console-less worker instead of a second GUI."""
    from formalizator.core.pdf_template import export_to_pdf

    try:
        export_to_pdf(sys.argv[2], sys.argv[3])
    except Exception as e:  # noqa: BLE001 — surface it to the parent's stderr
        sys.stderr.write(str(e))
        return 1
    return 0


def _install_error_dialog_hook() -> None:
    """Show uncaught exceptions instead of losing them.

    This is a windowed build (console=False), so an uncaught exception
    inside a Qt slot writes its traceback to a stderr that goes
    nowhere — the button simply appears to do nothing. That cost real
    field time once already: an OSError from the print path made
    Штампај silently no-op, with no dialog to explain it and no way to
    tell it apart from a dead button. Anything unhandled now says so
    on screen."""
    import traceback

    from PySide6.QtWidgets import QMessageBox

    def _hook(exc_type, exc_value, exc_tb) -> None:
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        sys.stderr.write(text)
        try:
            QMessageBox.critical(
                None, "Неочекивана грешка",
                f"{exc_type.__name__}: {exc_value}\n\n"
                "Апликација наставља да ради, али ова радња није успела.",
            )
        except Exception:  # noqa: BLE001 — never let the reporter itself crash the app
            pass

    sys.excepthook = _hook


def main() -> None:
    from formalizator.core.pdf_template import CONVERT_FLAG

    if len(sys.argv) >= 4 and sys.argv[1] == CONVERT_FLAG:
        sys.exit(_run_headless_conversion())

    app = QApplication.instance() or QApplication(sys.argv)
    _install_error_dialog_hook()
    app.setApplicationName(APP_NAME)
    icon = _icon_path()
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    apply_global_style(app)
    window = MainWindow()
    # Not plain show(): the window's initial resize(1500, 950) in
    # main_window.py can exceed the usable screen area on an ordinary
    # 1920x1080 laptop at 125% scaling (logical resolution 1536x864,
    # already shorter than 950 before the taskbar even takes its cut),
    # pushing bottom-anchored buttons under/behind the taskbar —
    # confirmed directly on real hardware. showMaximized() sidesteps
    # this by sizing against the screen's actual available geometry
    # (taskbar excluded), same as biracki_odbor's own entry point.
    window.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
