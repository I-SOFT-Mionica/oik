"""Entry point: launches the PySide6 GUI."""

from __future__ import annotations

import multiprocessing
import sys


def _build_splash():
    """A branded splash screen shown while MainWindow builds.

    MainWindow.__init__ eagerly constructs every section's widgets
    (Phase1-3 tabs, Измене, Проширени's 4 tabs, Посматрачи, both
    settings pages, ...) synchronously before the window is ever shown
    -- several seconds of real work with nothing on screen yet, which
    otherwise reads as a blank/flashing window during startup. A splash
    gives the operator something branded to look at instead.
    """
    from pathlib import Path

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
    from PySide6.QtWidgets import QSplashScreen

    from biracki_odbor import __version__

    if hasattr(sys, "_MEIPASS"):
        resources_root = Path(sys._MEIPASS) / "biracki_odbor" / "resources"
    else:
        resources_root = Path(__file__).parent / "resources"

    width, height = 420, 260
    pix = QPixmap(width, height)
    pix.fill(QColor("#FFFFFF"))

    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    icon_path = resources_root / "icon.ico"
    if icon_path.exists():
        icon_pix = QIcon(str(icon_path)).pixmap(72, 72)
        painter.drawPixmap((width - 72) // 2, 46, icon_pix)
    painter.setPen(QColor("#2F5496"))
    painter.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
    painter.drawText(
        pix.rect().adjusted(0, 132, 0, 0),
        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
        "OIK — Бирачки одбор",
    )
    painter.setPen(QColor("#8A92A6"))
    painter.setFont(QFont("Segoe UI", 9))
    painter.drawText(
        pix.rect().adjusted(0, 162, 0, 0),
        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
        f"верзија {__version__}",
    )
    painter.drawText(
        pix.rect().adjusted(0, -20, 0, 0),
        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
        "Учитавање…",
    )
    painter.end()

    return QSplashScreen(pix)


def main() -> int:
    # MUST be first inside `if __name__ == "__main__"` for PyInstaller-bundled
    # multiprocessing workers — without this, each ProcessPoolExecutor worker
    # would re-launch the .exe and loop infinitely.
    multiprocessing.freeze_support()

    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import QApplication

    from biracki_odbor import __version__, app_paths, logging_setup
    from biracki_odbor.config import settings as settings_mod
    from biracki_odbor.gui.main_window import MainWindow
    from biracki_odbor.gui.style import apply_global_style

    # Configure logging BEFORE any Qt code so import-time errors get captured.
    app_settings = settings_mod.load(app_paths.app_settings_path())
    logging_setup.configure("DEBUG" if app_settings.debug_logging else "INFO")

    # One-time reconciliation on version upgrade — e.g. importing the old
    # per-workflow xlsx masters into the shared SQLite committee.db (see
    # core/master_io.py). Runs before any UI, no progress needed (row
    # counts are small); logs its own outcome.
    if app_settings.last_run_version != __version__:
        from biracki_odbor.core.master_io import reconcile_legacy_xlsx_masters
        if reconcile_legacy_xlsx_masters():
            # Surface a one-off cleanup button in Поставке ОИК → Систем —
            # hidden by default, see core/maintenance.py.
            app_settings.pending_maintenance_action = "cleanup_legacy_migration_files"
        app_settings.last_run_version = __version__
        settings_mod.save(app_settings, app_paths.app_settings_path())

    app = QApplication(sys.argv)
    from biracki_odbor.gui import single_instance
    if single_instance.notify_running_instance():
        return 0  # the running copy comes to the front instead
    instance_server = single_instance.InstanceServer(parent=app)
    splash = _build_splash()
    # Windows animates the transition from a freshly-created window's
    # default geometry to its maximized state (visible as a small
    # top-left frame snapping to full-screen) -- without this hint the
    # splash isn't guaranteed to stay above that transient frame, so
    # the raw MainWindow flashes through underneath it.
    splash.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    splash.show()
    app.processEvents()

    apply_global_style(app)

    from pathlib import Path
    from PySide6.QtCore import QTranslator
    _translator = QTranslator(app)
    # In a PyInstaller onefile bundle the entry-point script's __file__ resolves
    # to the .exe itself, not the package directory. Use sys._MEIPASS (extraction
    # root) when bundled; fall back to the normal package directory in source mode.
    if hasattr(sys, "_MEIPASS"):
        _i18n_dir = Path(sys._MEIPASS) / "biracki_odbor" / "i18n"
    else:
        _i18n_dir = Path(__file__).parent / "i18n"
    _qm = _i18n_dir / f"biracki_{app_settings.ui_language}.qm"
    if _qm.exists() and _translator.load(str(_qm)):
        app.installTranslator(_translator)

    window = MainWindow()
    instance_server.activate_requested.connect(lambda: single_instance.bring_to_front(window))
    window.showMaximized()
    # Don't close the splash in the same tick as showMaximized() -- on
    # Windows the restore-to-maximized transition is a visible animation,
    # not an instant state change, so closing immediately let that
    # transient small frame show through before the splash covered it.
    QTimer.singleShot(200, lambda: splash.finish(window))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
