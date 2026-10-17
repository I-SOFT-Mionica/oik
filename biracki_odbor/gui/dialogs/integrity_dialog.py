"""Shared UI for a `file_integrity.IntegrityMismatchError` — a load-bearing
internal file (Stalni_sastav.xlsx, master.xlsx, nacelnik_sablion.xlsx)
changed outside the application since it was last verified.

One function, reused by every consumption site (Phase1Tab, Phase2Tab,
Phase3Tab, CorrectionsTab, the nacelnik Export/Send buttons) so the
wording and the restore flow can't drift apart between them.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QMessageBox, QWidget

from biracki_odbor.core import file_integrity
from biracki_odbor.gui.widgets.banner import StatusBanner


_CTX = "IntegrityMismatch"


def handle_integrity_mismatch(
    parent: QWidget,
    banner: StatusBanner,
    error: file_integrity.IntegrityMismatchError,
    on_resolved: Callable[[], None],
) -> None:
    """Blocks the affected feature with a clear banner, then offers to
    restore the last verified snapshot (if one exists).

    `on_resolved` is called after a successful restore so the caller
    can re-run whatever preflight/reload check just failed — leaving
    the caller in charge of what "resolved" means for it.
    """
    banner.show_error(
        QCoreApplication.translate(
            _CTX,
            "{name} was changed outside the application since it was last"
            " verified ({when}). Blocked until resolved.",
        ).format(name=error.path.name, when=error.verified_at)
    )

    if not file_integrity.has_verified_copy(error.path):
        QMessageBox.critical(
            parent,
            QCoreApplication.translate(_CTX, "File changed unexpectedly"),
            QCoreApplication.translate(
                _CTX,
                "{name} was changed outside the application and no verified"
                " backup copy exists to restore from. Re-import or"
                " regenerate it to continue.",
            ).format(name=error.path.name),
        )
        return

    answer = QMessageBox.warning(
        parent,
        QCoreApplication.translate(_CTX, "File changed unexpectedly"),
        QCoreApplication.translate(
            _CTX,
            "{name} was changed outside the application since it was last"
            " verified ({when}).\n\n"
            "This can mean accidental editing, disk corruption, or"
            " malicious modification (e.g. ransomware). If you did not make"
            " this change yourself, stop and investigate before continuing"
            " — check for other unusual activity and that your antivirus is"
            " current.\n\n"
            "Restore the last verified copy?",
        ).format(name=error.path.name, when=error.verified_at),
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    if answer != QMessageBox.StandardButton.Yes:
        return

    if file_integrity.restore_verified(error.path):
        banner.show_ok(
            QCoreApplication.translate(_CTX, "Restored the last verified copy.")
        )
        on_resolved()
    else:
        QMessageBox.critical(
            parent,
            QCoreApplication.translate(_CTX, "Restore failed"),
            QCoreApplication.translate(
                _CTX, "Could not restore {name}.",
            ).format(name=error.path.name),
        )
