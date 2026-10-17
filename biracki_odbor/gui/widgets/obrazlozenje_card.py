"""Reusable образложење paragraph card widget.

Used in Phase3Tab and IzmeneTab for inline paragraph editing.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout,
)

from PySide6.QtCore import QCoreApplication

from biracki_odbor.gui.widgets.toggle_switch import ToggleSwitch


_COMPACT_BTN = "padding: 3px 8px; font-size: 11pt;"
_COMPACT_BTN_DANGER = _COMPACT_BTN + " color: #9B0000; border-color: #F0B0B0;"


class _AutoResizingPlainTextEdit(QPlainTextEdit):
    """QPlainTextEdit that grows/shrinks its height to fit its content.

    Clamped to [min_height, max_height] — below the min it still reserves
    breathing room for an empty/short paragraph; above the max it stops
    growing and falls back to its own internal scrollbar (default policy)
    instead of consuming unbounded vertical space in the card stack.
    """

    def __init__(self, min_height: int, max_height: int, parent=None) -> None:
        super().__init__(parent)
        self._min_height = min_height
        self._max_height = max_height
        self.textChanged.connect(self.fit_to_content)

    def fit_to_content(self) -> None:
        # document().size().height() does NOT report pixel height for
        # QPlainTextEdit — it uses QPlainTextDocumentLayout internally,
        # which behaves differently from QTextEdit's QTextDocumentLayout.
        # The reliable technique: sum each block's WRAPPED line count
        # (blockCount() alone undercounts — it's paragraphs, not display
        # lines) and multiply by the font's line spacing.
        total_lines = 0
        block = self.document().begin()
        while block.isValid():
            layout = block.layout()
            total_lines += layout.lineCount() if layout else 1
            block = block.next()
        total_lines = max(total_lines, 1)

        line_height = self.fontMetrics().lineSpacing()
        doc_margin = self.document().documentMargin()
        frame = 2 * self.frameWidth()
        ideal = int(total_lines * line_height + 2 * doc_margin + frame + 8)
        clamped = max(self._min_height, min(ideal, self._max_height))
        if self.height() != clamped:
            self.setFixedHeight(clamped)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        # Width changes re-wrap the text, changing the wrapped line count —
        # recompute on the next event-loop turn (document size isn't final
        # until Qt finishes processing this resize).
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self.fit_to_content)


class ObrazlozenjeCard(QFrame):
    """One inline-editable образложење paragraph card. Autosaves on focus-out."""

    # Editor height auto-fits its content between these bounds. Above the
    # max, the QPlainTextEdit's own internal scrollbar (default policy)
    # takes over rather than growing the card indefinitely — these cards
    # sit in a scrollable stack, so one very long paragraph must not push
    # every other card far down the page.
    _MIN_EDITOR_HEIGHT = 90
    _MAX_EDITOR_HEIGHT = 460

    def __init__(
        self,
        paragraph,
        *,
        on_changed,
        on_remove,
        on_move_up,
        on_move_down,
        parent=None,
    ) -> None:
        super().__init__(parent)
        from biracki_odbor.config import obrazlozenje as obr_mod

        self.setObjectName("Card")
        self.paragraph_id = paragraph.id
        self._apply_style(False)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(4)

        # Header row: id label + optional checkbox + reorder/delete buttons
        top = QHBoxLayout()
        id_lbl = QLabel(f'<small style="color:#888"><code>{paragraph.id}</code></small>')
        id_lbl.setTextFormat(Qt.TextFormat.RichText)
        top.addWidget(id_lbl)
        top.addStretch()
        self.cb_show = ToggleSwitch(QCoreApplication.translate("ObrazlozenjeFeature", "Show"))
        self.cb_show.setChecked(not paragraph.optional)
        self.cb_show.setToolTip(QCoreApplication.translate(
            "ObrazlozenjeFeature",
            "Include paragraph in the rationale. Disabled paragraphs are"
            " not shown in the preview or the final decision.",
        ))

        def _on_show_toggled(checked: bool) -> None:
            self.editor.setVisible(checked)
            on_changed()

        self.cb_show.toggled.connect(_on_show_toggled)
        top.addWidget(self.cb_show)
        btn_up = QPushButton(QCoreApplication.translate("ObrazlozenjeFeature", "Up"))
        btn_up.setStyleSheet(_COMPACT_BTN)
        btn_up.setToolTip(QCoreApplication.translate("ObrazlozenjeFeature", "Move up"))
        btn_up.clicked.connect(lambda: on_move_up(self))
        top.addWidget(btn_up)
        btn_down = QPushButton(QCoreApplication.translate("ObrazlozenjeFeature", "Down"))
        btn_down.setStyleSheet(_COMPACT_BTN)
        btn_down.setToolTip(QCoreApplication.translate("ObrazlozenjeFeature", "Move down"))
        btn_down.clicked.connect(lambda: on_move_down(self))
        top.addWidget(btn_down)
        btn_del = QPushButton(QCoreApplication.translate("ObrazlozenjeFeature", "Remove"))
        btn_del.setStyleSheet(_COMPACT_BTN_DANGER)
        btn_del.setToolTip(QCoreApplication.translate("ObrazlozenjeFeature", "Remove paragraph"))
        btn_del.clicked.connect(lambda: on_remove(self))
        top.addWidget(btn_del)
        root.addLayout(top)

        self.editor = _AutoResizingPlainTextEdit(
            self._MIN_EDITOR_HEIGHT, self._MAX_EDITOR_HEIGHT,
        )
        self.editor.setVisible(not paragraph.optional)
        self.editor.setPlaceholderText(QCoreApplication.translate(
            "ObrazlozenjeFeature",
            "Paragraph text. **Bold** for bold text. "
            "Codes: {auth_ref}, {auth_name}, {auth_role}, {opstina}…",
        ))
        self.editor.setPlainText(obr_mod.render_paragraph_markdown(paragraph.segments))
        self.editor.fit_to_content()

        orig_focus_out = self.editor.focusOutEvent

        def _focus_out(ev):
            orig_focus_out(ev)
            on_changed()

        self.editor.focusOutEvent = _focus_out
        root.addWidget(self.editor)

    def _apply_style(self, active: bool) -> None:
        border_color = "#2F5496" if active else "#AAAAAA"
        border_width = "2px" if active else "1px"
        self.setStyleSheet(
            f"QFrame#Card {{ background-color: #F8F8F8;"
            f" border: {border_width} solid {border_color}; border-radius: 4px; }}"
        )

    def set_active(self, active: bool) -> None:
        self._apply_style(active)

    def to_paragraph(self):
        from biracki_odbor.config import obrazlozenje as obr_mod
        return obr_mod.Paragraph(
            id=self.paragraph_id,
            segments=obr_mod.parse_markdown_paragraph(self.editor.toPlainText()),
            optional=not self.cb_show.isChecked(),
        )
