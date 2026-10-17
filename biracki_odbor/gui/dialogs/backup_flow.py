"""Backup orchestration — packages HOME, asks where to send it, sends it.

Lives separately from `backup_dialog.py` (which is just the destination
picker) so the same flow can be invoked from anywhere in the GUI.
Currently triggered from the sidebar's „Сачувај резервну копију…"
action; previously lived inline on Phase 3 but moved out so the
operator can hit "backup" any time, not only after Phase 3 finishes.

Returns a short status string the caller can drop into the status bar,
or None if the operator cancelled. Errors are surfaced as QMessageBox
inline; the caller doesn't need to wrap.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QDialog, QMessageBox, QWidget,
)

from biracki_odbor import app_paths
from biracki_odbor.core import backup as backup_mod
from biracki_odbor.core.backup import BackupTarget


log = logging.getLogger(__name__)


def _delete_later(path: Path, delay_seconds: int = 180) -> None:
    """Delete *path* on a daemon thread after *delay_seconds*.

    Used for email targets where the client (Thunderbird in particular)
    reads the attachment asynchronously after create_drafts returns.
    The delay gives the client time to open and attach the file before
    we remove it from %TEMP%.  unlink(missing_ok=True) means the call
    is harmless if the OS has already swept the file or another code
    path removed it first.
    """
    def _delete() -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    t = threading.Timer(delay_seconds, _delete)
    t.daemon = True
    t.start()


def run_backup_flow(parent: QWidget) -> str | None:
    """Build → pick destination → ship. Returns a status string or None.

    None means the user cancelled or an error was surfaced via dialog.
    On success returns a short Cyrillic sentence suitable for
    statusBar().showMessage().
    """
    # Local imports keep cold start fast — backup is rarely the first
    # thing an operator clicks.
    from biracki_odbor.gui.dialogs.backup_dialog import BackupDialog

    # Build the zip with the wait cursor on so the operator knows we're
    # working. Synchronous because the dialog needs the actual size to
    # render the size-based recommendation.
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        zip_path = backup_mod.build_backup_zip(app_paths.home())
    except OSError as e:
        QApplication.restoreOverrideCursor()
        QMessageBox.critical(
            parent, "Резервна копија",
            f"Не могу да направим .zip: {e}",
        )
        return None
    finally:
        QApplication.restoreOverrideCursor()

    # Initialise target to None so the finally clause below can safely
    # reference it even when the operator cancels the dialog before
    # target = dlg.selected_target() is reached.
    target = None
    try:
        zip_size = zip_path.stat().st_size
        targets = backup_mod.detect_targets()
        dlg = BackupDialog(zip_path, zip_size, targets, parent=parent)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        target = dlg.selected_target()
        payload = dlg.selected_payload()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            final_path = _execute(zip_path, target, payload)
        finally:
            QApplication.restoreOverrideCursor()
        return _status_message(target, final_path)
    finally:
        if target == BackupTarget.OUTLOOK_EMAIL:
            # Email clients read the attachment asynchronously (Thunderbird
            # via a detached subprocess; Outlook COM ingests synchronously
            # but the deferred delete is harmless).  Give the client 3
            # minutes before cleaning up the temp zip.
            _delete_later(zip_path, delay_seconds=180)
        else:
            # Folder-copy targets: file already copied to destination (or
            # dialog was cancelled — zip is no longer needed either way).
            try:
                zip_path.unlink(missing_ok=True)
            except OSError:
                pass


def _execute(zip_path, target, payload):
    """Run the per-destination side-effect. Returns final path or None."""
    if target in (
        BackupTarget.USB, BackupTarget.ONEDRIVE,
        BackupTarget.GOOGLE_DRIVE, BackupTarget.CUSTOM_FOLDER,
    ):
        return backup_mod.copy_to_folder(zip_path, payload)
    if target == BackupTarget.OUTLOOK_EMAIL:
        # Despite the enum name (`OUTLOOK_EMAIL`, kept for backwards
        # compat with cached AppSettings on disk), this now routes
        # through the e-mail-client dispatcher so Thunderbird users
        # get the same flow. The dispatcher reads the operator's
        # preference from AppSettings at call time.
        from biracki_odbor.integrations import email_client as ec_mod
        from biracki_odbor import app_paths
        from biracki_odbor.config import settings as settings_mod
        subject, body = backup_mod.email_subject_body()
        # No `to:` populated — operator fills in the recipient when the
        # draft opens. Safer than guessing; OIK archive addresses vary
        # per municipality.
        pref = settings_mod.load(app_paths.app_settings_path()).email_client
        ec_mod.create_drafts(
            [ec_mod.DraftSpec(
                to="", subject=subject, body=body, attachment=zip_path,
            )],
            preference=pref,
            display_first=True,
        )
        return None
    return None


def _status_message(target, final_path) -> str:
    if target == BackupTarget.OUTLOOK_EMAIL:
        return (
            "Резервна копија — Outlook драфт је креиран и отворен за"
            " попуну адресе и слање."
        )
    if final_path is not None:
        return f"Резервна копија је сачувана у: {final_path}"
    return "Резервна копија је завршена, али нема путање."
