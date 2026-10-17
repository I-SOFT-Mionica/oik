"""Formalizator main window — hosts the two-screen flow: setup
(pick/create a template, enter session-fixed data, set copy count) then
fill-out (read-or-type one voter at a time, live preview, print +
record).

Reuses `biracki_odbor.gui.style` so this looks and behaves like the
same product family as the OIK app, per the client's brief ("use the
GUI from our app").
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox, QStackedWidget

from formalizator.core import export_template_catalog, session_store, starter_catalog
from formalizator.core.generic_export import export_roster
from formalizator.core.home_migration import APP_DIR_NAME, DB_NAME, default_home
from formalizator.core.models import CalibratedTemplate, SessionInfo
from formalizator.gui.fillout_screen import FilloutScreen
from formalizator.gui.setup_screen import SetupScreen

log = logging.getLogger(__name__)

APP_NAME = APP_DIR_NAME

_default_home = default_home


class MainWindow(QStackedWidget):
    def __init__(self, home_dir: Path | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Formalizator — прикупљање подршке бирача")
        self.resize(1500, 950)
        # A floor low enough that the window still fits inside the
        # screen on the scaled laptops this actually runs on: a
        # 1920x1080 panel at 125% has 864 logical pixels (816 under the
        # taskbar), and at 150% only 720 (672 under it) — a 700 px
        # minimum does not fit that second case, and a window taller
        # than the screen puts its bottom row of buttons beneath the
        # taskbar. Both screens scroll their content now, so this only
        # needs to be large enough to stay usable, not large enough to
        # hold everything at once.
        self.setMinimumSize(1000, 560)

        self._home = home_dir or _default_home()
        self._db_path = self._home / DB_NAME
        self._catalog_dir = self._home / "templates"
        # Ships with the forms already calibrated for this cycle, so a
        # fresh install isn't an empty catalog the operator has to fill
        # before the app does anything.
        starter_catalog.seed(self._home, self._catalog_dir)
        self._session_id: int | None = None
        self._session_info: SessionInfo | None = None

        self.setup_screen = SetupScreen(self._catalog_dir, self._home)
        self.setup_screen.session_ready.connect(self._on_session_ready)
        self.addWidget(self.setup_screen)

        self.fillout_screen = FilloutScreen()
        self.fillout_screen.entry_printed.connect(self._on_entry_printed)
        self.fillout_screen.back_requested.connect(self._on_back)
        self.fillout_screen.finish_requested.connect(self._on_finish_session)
        self.addWidget(self.fillout_screen)

        self.setCurrentWidget(self.setup_screen)
        self._try_resume_session()

    def _try_resume_session(self) -> None:
        existing = session_store.get_open_session(self._db_path)
        if existing is None:
            return
        session_id, info = existing
        reply = QMessageBox.question(
            self, "Настави сесију",
            f"Постоји незавршена сесија (шаблон „{info.template_name}”,"
            f" покренута {info.started_at}). Наставити је?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return
        self._session_id = session_id
        self._session_info = info
        self.setup_screen.load_from_info(info)

        from formalizator.core import template_catalog
        template = template_catalog.find_by_name(self._catalog_dir, info.template_name)
        if template is not None:
            self._enter_fillout(info, template)

    def _on_session_ready(self, info: SessionInfo, template: CalibratedTemplate) -> None:
        self._session_id = session_store.open_session(self._db_path, info)
        self._session_info = info
        self._enter_fillout(info, template)

    def _enter_fillout(self, info: SessionInfo, template: CalibratedTemplate) -> None:
        self.fillout_screen.set_template(template)
        self.fillout_screen.set_session_info(info)
        self.fillout_screen.set_copies(info.copies)
        count = len(session_store.list_entries(self._db_path, self._session_id))
        self.fillout_screen.set_entry_count(count)
        self.setCurrentWidget(self.fillout_screen)

    def _on_entry_printed(self, entry) -> None:
        if self._session_id is None:
            return
        session_store.add_entry(
            self._db_path, self._session_id, entry,
            datetime.now().isoformat(timespec="seconds"),
        )
        count = len(session_store.list_entries(self._db_path, self._session_id))
        self.fillout_screen.set_entry_count(count)

    def _on_back(self) -> None:
        self.setup_screen.reload_catalog()
        self.setCurrentWidget(self.setup_screen)

    def _on_finish_session(self) -> None:
        if self._session_id is None or self._session_info is None:
            return
        entries = session_store.list_entries(self._db_path, self._session_id)

        # The export template was already chosen (or explicitly skipped
        # via "(без извоза)") as an optional step on the setup screen,
        # right after the template itself — nothing to pick here.
        if self._session_info.export_template_name:
            export_template = export_template_catalog.find_by_name(
                self._home, self._session_info.export_template_name,
            )
            if export_template is None:
                QMessageBox.warning(
                    self, "Извозни шаблон није пронађен",
                    f"Шаблон „{self._session_info.export_template_name}” више не"
                    " постоји. Сесија ће бити завршена без извоза.",
                )
            elif not entries:
                QMessageBox.information(self, "Нема уноса", "Сесија нема унетих бирача — нема шта да се извезе.")
            else:
                default_name = f"{export_template.name}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
                path, _ = QFileDialog.getSaveFileName(
                    self, "Сачувај извоз", str(Path.home() / default_name),
                    "Excel фајлови (*.xlsx)",
                )
                if not path:
                    # Cancelling the save dialog cancels ending the
                    # session too — the operator can try again rather
                    # than losing the export silently.
                    return
                try:
                    export_roster(entries, self._session_info, export_template, path)
                except OSError as e:
                    QMessageBox.critical(self, "Грешка", f"Не могу да сачувам: {e}")
                    return
                QMessageBox.information(self, "Извезено", f"Извоз сачуван: {path}")

        session_store.close_session(
            self._db_path, self._session_id, datetime.now().isoformat(timespec="seconds"),
        )
        self._session_id = None
        self._session_info = None
        self.setup_screen.reload_catalog()
        self.setCurrentWidget(self.setup_screen)

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt override
        if self.fillout_screen._reader is not None:  # noqa: SLF001
            try:
                self.fillout_screen._reader.cleanup()  # noqa: SLF001
            except Exception:  # noqa: BLE001
                log.exception("eID reader cleanup failed")
        # The rendered declarations are personal data, not scratch —
        # they don't outlive the session that produced them.
        self.fillout_screen.cleanup_previews()
        super().closeEvent(event)
