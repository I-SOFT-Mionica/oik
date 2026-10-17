"""Big drag-and-drop zone with click-to-browse fallback.

Optimised for older users: huge visible target, clear instructional copy
in Cyrillic, single primary action ("Изабери фајл") when drag-drop feels
unfamiliar.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)


class FileDropZone(QFrame):
    file_selected = Signal(str)

    def __init__(
        self,
        prompt: str = "Превуците фајл овде или кликните",
        file_filter: str = "Excel фајлови (*.xlsx)",
        parent=None,
        *,
        initial_dir: str = "",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self._filter = file_filter
        self._path: Path | None = None
        self._initial_dir = initial_dir

        # Cap width so the zone reads as a focused target on wide monitors
        # instead of stretching into a full-width banner.
        self.setMaximumWidth(640)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 28, 20, 28)
        layout.setSpacing(10)

        self.prompt_label = QLabel(prompt)
        self.prompt_label.setAlignment(Qt.AlignCenter)
        self.prompt_label.setObjectName("HeadLabel")
        layout.addWidget(self.prompt_label)

        self.path_label = QLabel("")
        self.path_label.setObjectName("MutedLabel")
        self.path_label.setAlignment(Qt.AlignCenter)
        self.path_label.setWordWrap(True)
        layout.addWidget(self.path_label)

        btn_row = QHBoxLayout()
        btn_row.setAlignment(Qt.AlignCenter)
        self.browse_btn = QPushButton("Изабери фајл…")
        self.browse_btn.clicked.connect(self._on_browse)
        btn_row.addWidget(self.browse_btn)
        layout.addLayout(btn_row)

    @property
    def path(self) -> Path | None:
        return self._path

    def set_path(self, path: str | Path) -> None:
        """Display-only path update — does NOT emit `file_selected`.

        `file_selected` is reserved for genuine user actions (drag,
        drop, file-picker). When a caller wants to reflect persisted
        state in the zone's display (e.g. the template drop zone
        restoring the currently-imported template path), emitting on every refresh
        triggers the listener again → which re-saves → which fires
        template_changed → which calls set_path again. That was an
        infinite signal loop in v0.9.x (~100 reps per launch in the
        wild, before Python's recursion limit broke it).
        """
        p = Path(path)
        self._path = p
        self.path_label.setText(str(p))

    def clear(self) -> None:
        self._path = None
        self.path_label.setText("")

    # ── Drag and drop ──

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setProperty("active", True)
            self.style().unpolish(self)
            self.style().polish(self)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self.setProperty("active", False)
        self.style().unpolish(self)
        self.style().polish(self)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if path:
                self.set_path(path)
                self.file_selected.emit(path)
        self.setProperty("active", False)
        self.style().unpolish(self)
        self.style().polish(self)
        event.acceptProposedAction()

    def _on_browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Изабери фајл", self._initial_dir, self._filter,
        )
        if path:
            self.set_path(path)
            self.file_selected.emit(path)
