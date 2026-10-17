"""Restore-from-backup dialog.

Flow:
  1. Operator picks a .zip via QFileDialog.
  2. ``inspect_zip`` runs (no writes) and returns a ZipInfo summary.
  3. Dialog shows a pre-flight panel:
       - zip filename + date of newest entry
       - file count
       - list of files that already exist on disk (будуће преписивање)
       - staleness warning if the zip is older than current local files
  4. "Backup current state first" checkbox (default checked).
  5. OK → ``restore_from_zip`` → success panel with count + safety-backup
     path; operator is told to restart the app.
  6. Cancel at any point is safe — nothing is written until OK is confirmed.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QLabel,
    QMessageBox, QPlainTextEdit, QVBoxLayout, QWidget,
)

from biracki_odbor.gui.widgets.toggle_switch import ToggleSwitch

from biracki_odbor import app_paths
from biracki_odbor.core.backup import RestoreResult, ZipInfo, inspect_zip, restore_from_zip


def run_restore_flow(parent: QWidget | None = None) -> str:
    """Open the full restore flow. Returns a status message or empty string."""
    zip_path_str, _ = QFileDialog.getOpenFileName(
        parent,
        "Изабери резервну копију (.zip)",
        str(app_paths.home()),
        "ZIP архива (*.zip)",
    )
    if not zip_path_str:
        return ""

    zip_path = Path(zip_path_str)
    home = app_paths.home()

    try:
        info = inspect_zip(zip_path, home)
    except Exception as e:  # noqa: BLE001
        QMessageBox.critical(
            parent, "Грешка при читању архиве",
            f"Не могу да отворим '{zip_path.name}':\n{e}",
        )
        return ""

    dlg = _RestorePreflightDialog(info, parent)
    if dlg.exec() != QDialog.Accepted:
        return ""

    make_backup = dlg.make_backup_checked()

    try:
        result: RestoreResult = restore_from_zip(
            zip_path, home, make_pre_restore_backup=make_backup,
        )
    except Exception as e:  # noqa: BLE001
        QMessageBox.critical(
            parent, "Грешка при враћању",
            f"Враћање није успело:\n{e}",
        )
        return ""

    _show_success(parent, result)
    return f"Враћено {len(result.restored_files)} фајлова. Поново покрените апликацију."


class _RestorePreflightDialog(QDialog):
    """Pre-flight review before any writes happen."""

    def __init__(self, info: ZipInfo, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Врати из резервне копије")
        self.setMinimumWidth(520)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowContextHelpButtonHint
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 16, 20, 16)

        # ── Summary ──────────────────────────────────────────
        date_str = (
            info.newest_entry_mtime.strftime("%Y-%m-%d %H:%M UTC")
            if info.newest_entry_mtime
            else "непознат датум"
        )
        summary = QLabel(
            f"<b>{info.path.name}</b><br>"
            f"Датум копије: {date_str}<br>"
            f"Број фајлова: {info.file_count}"
        )
        summary.setTextFormat(Qt.RichText)
        layout.addWidget(summary)

        # ── Staleness warning ─────────────────────────────────
        if info.has_stale_entries:
            warn = QLabel(
                "Неки фајлови на диску су <b>новији</b> од ове резервне копије. "
                "Враћање ће преписати тренутне податке старијим верзијама. "
                "Наставите само ако сте сигурни."
            )
            warn.setTextFormat(Qt.RichText)
            warn.setWordWrap(True)
            warn.setObjectName("MutedLabel")
            layout.addWidget(warn)

        # ── Overwrite list ────────────────────────────────────
        if info.would_overwrite:
            lbl = QLabel("Фајлови који ће бити замењени:")
            layout.addWidget(lbl)
            txt = QPlainTextEdit()
            txt.setReadOnly(True)
            txt.setMaximumHeight(120)
            txt.setPlainText("\n".join(sorted(info.would_overwrite)))
            layout.addWidget(txt)
        else:
            layout.addWidget(QLabel("Нема постојећих фајлова — чиста инсталација."))

        # ── Safety backup checkbox ────────────────────────────
        self._cb_backup = ToggleSwitch(
            "Аутоматски архивира тренутно стање пре враћања"
        )
        self._cb_backup.setChecked(True)
        layout.addWidget(self._cb_backup)
        _backup_hint = QLabel("(у backups/pre-restore-<датум>.zip)")
        _backup_hint.setObjectName("MutedLabel")
        layout.addWidget(_backup_hint)

        # ── Restart notice ────────────────────────────────────
        notice = QLabel(
            "Апликација мора бити поново покренута после враћања."
        )
        notice.setObjectName("MutedLabel")
        layout.addWidget(notice)

        # ── Buttons ───────────────────────────────────────────
        ok_text = "Замени и настави" if info.has_stale_entries else "Врати"
        btns = QDialogButtonBox(QDialogButtonBox.Cancel)
        ok_btn = btns.addButton(ok_text, QDialogButtonBox.AcceptRole)
        if info.has_stale_entries:
            ok_btn.setObjectName("DangerButton")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def make_backup_checked(self) -> bool:
        return self._cb_backup.isChecked()


def _show_success(parent: QWidget | None, result: RestoreResult) -> None:
    msg = QMessageBox(parent)
    msg.setWindowTitle("Враћање успешно")
    msg.setIcon(QMessageBox.Information)
    lines = [f"Враћено {len(result.restored_files)} фајлова."]
    if result.pre_restore_backup:
        lines.append(
            f"Претходно стање архивирано у:\n{result.pre_restore_backup}"
        )
    lines.append("\nПоново покрените апликацију да би измене ступиле на снагу.")
    msg.setText("\n".join(lines))
    msg.exec()
