"""Backup destination picker dialog.

Shown after the operator clicks „Сачувај резервну копију…" in the
sidebar. We've already packaged the backup .zip in a background thread
by the time this dialog opens (so the user sees the actual size, not
a forecast).

The dialog lets the operator pick a destination from those actually
available on this machine, with a recommended default driven by the
.zip's size (`core/backup.recommend_target`). Empty / N/A targets are
hidden — no greyed-out radio buttons that don't do anything.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QRadioButton, QVBoxLayout, QWidget,
)

from biracki_odbor.core import backup as backup_mod
from biracki_odbor.core.backup import AvailableTargets, BackupTarget


log = logging.getLogger(__name__)


def _human_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes / (1024 * 1024):.1f} MB"


class BackupDialog(QDialog):
    """Returns (selected_target, selected_payload) on accept.

    `selected_payload`:
      - USB / CUSTOM_FOLDER → `Path` of the chosen folder.
      - ONEDRIVE / GOOGLE_DRIVE → `Path` of the detected sync folder.
      - OUTLOOK_EMAIL → empty string (no extra payload; default
        subject/body comes from `backup.email_subject_body`).
    """

    def __init__(
        self,
        zip_path: Path,
        zip_size: int,
        targets: AvailableTargets,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Резервна копија")
        self.resize(560, 480)

        self._zip_path = zip_path
        self._zip_size = zip_size
        self._targets = targets
        self._selected_target: BackupTarget | None = None
        self._selected_payload: object = None

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        header = QLabel(
            f"Резервна копија је припремљена. Величина пакета: <b>{_human_size(zip_size)}</b>."
        )
        header.setWordWrap(True)
        root.addWidget(header)

        recommended = backup_mod.recommend_target(
            zip_size, targets.as_target_list(),
        )
        why = _recommendation_reason(zip_size, recommended)
        rec_label = QLabel(f"Препоручено: <b>{_target_label(recommended)}</b> — {why}")
        rec_label.setObjectName("MutedLabel")
        rec_label.setWordWrap(True)
        root.addWidget(rec_label)

        # Radio group — one button per available target.
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._radios: dict[BackupTarget, QRadioButton] = {}
        self._usb_combo: QComboBox | None = None
        self._custom_label: QLabel | None = None
        self._custom_path: Path | None = None

        form = QFormLayout()
        form.setSpacing(8)

        if targets.usb_drives:
            row = QHBoxLayout()
            rb = QRadioButton("USB диск")
            self._radios[BackupTarget.USB] = rb
            self._group.addButton(rb)
            row.addWidget(rb)
            combo = QComboBox()
            for p in targets.usb_drives:
                combo.addItem(f"{p} ", str(p))
            row.addWidget(combo, stretch=1)
            self._usb_combo = combo
            wrap = QWidget()
            wrap.setLayout(row)
            form.addRow(wrap)

        if targets.onedrive is not None:
            rb = QRadioButton(f"OneDrive — {targets.onedrive}")
            self._radios[BackupTarget.ONEDRIVE] = rb
            self._group.addButton(rb)
            form.addRow(rb)

        if targets.google_drive is not None:
            rb = QRadioButton(f"Google Drive — {targets.google_drive}")
            self._radios[BackupTarget.GOOGLE_DRIVE] = rb
            self._group.addButton(rb)
            form.addRow(rb)

        if targets.outlook:
            # Despite the `targets.outlook` field name (kept for
            # backwards compat with on-disk AppSettings), this option
            # actually routes through the e-mail-client dispatcher and
            # will use Thunderbird when that's the configured backend.
            label = "Драфт мејл"
            if zip_size > backup_mod.EMAIL_MAX_BYTES:
                label += "  (упозорење: прилог већи од 10 МБ)"
            rb = QRadioButton(label)
            self._radios[BackupTarget.OUTLOOK_EMAIL] = rb
            self._group.addButton(rb)
            form.addRow(rb)

        # Custom folder always available.
        custom_row = QHBoxLayout()
        rb = QRadioButton("Друга фасцикла…")
        self._radios[BackupTarget.CUSTOM_FOLDER] = rb
        self._group.addButton(rb)
        custom_row.addWidget(rb)
        custom_label = QLabel("(није изабрана)")
        custom_label.setObjectName("MutedLabel")
        self._custom_label = custom_label
        custom_row.addWidget(custom_label, stretch=1)
        custom_btn = QRadioButton()
        # use a plain button instead — the radio gets the click intent
        from PySide6.QtWidgets import QPushButton
        pick_btn = QPushButton("Изабери…")
        pick_btn.clicked.connect(self._pick_custom_folder)
        custom_row.addWidget(pick_btn)
        wrap = QWidget()
        wrap.setLayout(custom_row)
        form.addRow(wrap)

        root.addLayout(form)
        root.addStretch(1)

        # Pre-select the recommended target so OK with no clicks just works.
        if recommended in self._radios:
            self._radios[recommended].setChecked(True)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Сачувај резервну копију")
        bb.button(QDialogButtonBox.Cancel).setText("Откажи")
        bb.accepted.connect(self._on_accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

    def _pick_custom_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Изабери фасциклу за резервну копију", str(Path.home()),
        )
        if not path:
            return
        self._custom_path = Path(path)
        if self._custom_label is not None:
            self._custom_label.setText(str(self._custom_path))
        # Auto-select the custom-folder radio when the operator picks
        # a path — saves them an extra click.
        self._radios[BackupTarget.CUSTOM_FOLDER].setChecked(True)

    def _on_accept(self) -> None:
        for target, rb in self._radios.items():
            if rb.isChecked():
                self._selected_target = target
                break
        if self._selected_target is None:
            # Shouldn't happen given the pre-selection above, but
            # nothing checked = nothing to do.
            self.reject()
            return
        if self._selected_target == BackupTarget.USB:
            if self._usb_combo is None or self._usb_combo.count() == 0:
                self.reject()
                return
            self._selected_payload = Path(self._usb_combo.currentData())
        elif self._selected_target == BackupTarget.ONEDRIVE:
            self._selected_payload = self._targets.onedrive
        elif self._selected_target == BackupTarget.GOOGLE_DRIVE:
            self._selected_payload = self._targets.google_drive
        elif self._selected_target == BackupTarget.CUSTOM_FOLDER:
            if self._custom_path is None:
                # No folder picked — keep the dialog open with a hint.
                if self._custom_label is not None:
                    self._custom_label.setText(
                        "<b>Изаберите фасциклу пре него што наставите</b>"
                    )
                return
            self._selected_payload = self._custom_path
        # OUTLOOK_EMAIL: no payload needed; the runner generates the draft.
        self.accept()

    def selected_target(self) -> BackupTarget | None:
        return self._selected_target

    def selected_payload(self) -> object:
        return self._selected_payload


def _target_label(t: BackupTarget) -> str:
    return {
        BackupTarget.USB: "USB",
        BackupTarget.ONEDRIVE: "OneDrive",
        BackupTarget.GOOGLE_DRIVE: "Google Drive",
        BackupTarget.OUTLOOK_EMAIL: "Драфт мејл",
        BackupTarget.CUSTOM_FOLDER: "Друга фасцикла",
    }.get(t, str(t))


def _recommendation_reason(zip_size: int, target: BackupTarget) -> str:
    """One-line rationale for the recommended default."""
    if target == BackupTarget.OUTLOOK_EMAIL:
        return "пакет је мали — мејл је најбржи"
    if target in (BackupTarget.ONEDRIVE, BackupTarget.GOOGLE_DRIVE):
        return "пакет премашује типичну границу мејл прилога"
    if target == BackupTarget.USB:
        return "пакет је превелик за поуздан upload — USB је сигурнији офлајн"
    return "нема доступних аутоматских циљева; изабери фасциклу ручно"
