"""Shared "confirm with an explicit acknowledgement toggle" dialog.

Hard-to-reverse actions (nacelnik takeover, RIK submission) must not be a
single accidental click — the operator has to explicitly acknowledge
before Confirm becomes clickable. `QMessageBox.setCheckBox()` only
accepts a plain `QCheckBox`, whose border renders almost invisibly
against the dialog's background (same class of contrast bug fixed for
CollapsibleCard in style.py). Uses `ToggleSwitch` instead — the red/blue
widget already adopted elsewhere in the app to solve exactly this.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QWidget

from biracki_odbor.gui.widgets.toggle_switch import ToggleSwitch


def confirm_with_toggle(
    parent: QWidget | None,
    *,
    title: str,
    text: str,
    toggle_text: str,
    confirm_text: str,
    cancel_text: str,
) -> bool:
    """Modal confirmation gated on an explicit toggle. Returns True iff
    the operator toggled it on AND clicked Confirm."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setMinimumWidth(480)
    dlg.setWindowFlags(dlg.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

    layout = QVBoxLayout(dlg)
    layout.setSpacing(14)
    layout.setContentsMargins(20, 16, 20, 16)

    lbl = QLabel(text)
    lbl.setWordWrap(True)
    layout.addWidget(lbl)

    toggle = ToggleSwitch(toggle_text)
    layout.addWidget(toggle)

    btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
    confirm_btn = btns.addButton(confirm_text, QDialogButtonBox.ButtonRole.AcceptRole)
    confirm_btn.setObjectName("DestructiveButton")
    # Disabled until the toggle is on — Confirm must never be a silent
    # no-op just because the acknowledgement wasn't given; making it
    # unclickable until then is self-explanatory (also means it can
    # never fire via a stray Enter keypress while still disabled).
    confirm_btn.setEnabled(False)
    toggle.toggled.connect(confirm_btn.setEnabled)
    cancel_btn = btns.button(QDialogButtonBox.StandardButton.Cancel)
    if cancel_btn is not None:
        cancel_btn.setText(cancel_text)
        cancel_btn.setDefault(True)
    btns.accepted.connect(dlg.accept)
    btns.rejected.connect(dlg.reject)
    layout.addWidget(btns)

    return dlg.exec() == QDialog.DialogCode.Accepted
