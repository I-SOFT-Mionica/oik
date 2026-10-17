"""Small status banner shown above each phase tab.

`show_ok` / `show_info` auto-hide after a short delay (success
messages are acks, not state — they don't need to linger). Warnings
and errors stay until the next banner action so the operator can't
miss them.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel


# Success messages auto-dismiss after this many milliseconds. 5 s is
# enough to read a short ack without becoming visual clutter that
# distracts from the next action.
_OK_AUTOHIDE_MS = 5000


class StatusBanner(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._label = QLabel("")
        self._label.setWordWrap(True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.addWidget(self._label)

        # Single-shot timer reused across calls. Created with self as
        # parent so it gets cleaned up when the banner is destroyed
        # (avoids the QTimer-outlives-widget warning at shutdown).
        self._autohide = QTimer(self)
        self._autohide.setSingleShot(True)
        self._autohide.timeout.connect(self.clear)

        self.hide()

    def show_ok(self, text: str) -> None:
        self._set("OkBanner", text)
        self._autohide.start(_OK_AUTOHIDE_MS)

    def show_warn(self, text: str) -> None:
        self._set("WarnBanner", text)
        # Warnings stay until the next action — they often flag
        # something the operator should fix before moving on.
        self._autohide.stop()

    def show_error(self, text: str) -> None:
        self._set("ErrorBanner", text)
        # Errors stay until explicitly cleared. Auto-hiding an error
        # the operator might have missed could mask a real problem.
        self._autohide.stop()

    def show_info(self, text: str) -> None:
        self._set("OkBanner", text)
        self._autohide.start(_OK_AUTOHIDE_MS)

    def clear(self) -> None:
        self._autohide.stop()
        self.hide()
        self._label.setText("")

    def _set(self, object_name: str, text: str) -> None:
        self.setObjectName(object_name)
        self.style().unpolish(self)
        self.style().polish(self)
        self._label.setText(text)
        self.show()
