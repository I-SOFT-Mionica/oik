"""Compact one-row решење spacing control — shared by Phase3Tab (step 4)
and IzmenaPanel (step 5), since both edit the same underlying
DocumentFormat. A block dropdown (Наслов/Текст) swaps which pair of
Before/After fields is shown, instead of 4 separate spinboxes; line
spacing and a "RIK defaults" reset live on the same row. One shared
translation context ("DocumentSpacingBar") instead of duplicating these
strings under Phase3Tab/IzmeneFeature.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QMessageBox, QPushButton, QWidget,
)

from biracki_odbor.config.oik import DocumentFormat
from biracki_odbor.gui.app_state import AppState
from biracki_odbor.gui.widgets.spinbox import WheelSafeSpinBox

log = logging.getLogger(__name__)

BLOCK_TITLE = "title"
BLOCK_BODY = "body"

# Debounce window for live Before/After typing. Each keystroke's
# valueChanged used to call _save() synchronously, which -- via
# `changed` -- triggers Phase3Tab/IzmenaPanel's _refresh_preview(),
# which re-renders EVERY page of the paginated preview as a full
# pixmap (paginated_preview.py's _rebuild_pages()). Doing that on every
# single digit typed was the actual cause of a field report of "lag
# when editing Датум седнице etc, much worse on a slower PC" -- and,
# more subtly, of the Before/After fields sometimes painting blank:
# that heavy, synchronous rebuild runs reentrantly inside the
# spinbox's own valueChanged handling, racing its own paint event.
# Debouncing means the expensive refresh only runs once typing pauses.
_SAVE_DEBOUNCE_MS = 300


class DocumentSpacingBar(QWidget):
    """Emitted after a change has been persisted via state.save_document_format()."""
    changed = Signal()

    def __init__(self, state: AppState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state
        self._loading = False
        # Coalesces rapid-fire valueChanged ticks from typing into a
        # single save+refresh once typing pauses. editingFinished (Enter
        # or focus loss) still flushes immediately -- see _on_live_change
        # and _flush_pending_save -- so navigating away mid-edit never
        # loses the last keystroke.
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._save)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        # Full labels on every control, not just Before/After -- the bar
        # spans the full tab width (see Phase3Tab/IzmenaPanel), so there's
        # no reason to lean on tooltip-only discovery for the block/line-
        # spacing combos the way the earlier space-constrained layout did.
        block_tip = self.tr(
            "Choose which block the Before/After fields edit: the"
            " title-block lines (subtitle, election type, РАСПИСАНИХ ЗА…)"
            " or the ordinary body paragraphs (тачка 1/2/3, РИК provision,"
            " образложење, legal remedy)."
        )
        lbl_block = QLabel(self.tr("Block:"))
        lbl_block.setToolTip(block_tip)
        row.addWidget(lbl_block)
        self.cb_block = QComboBox()
        self.cb_block.addItem(self.tr("Title"), BLOCK_TITLE)
        self.cb_block.addItem(self.tr("Body"), BLOCK_BODY)
        self.cb_block.setToolTip(block_tip)
        self.cb_block.currentIndexChanged.connect(self._on_block_switched)
        row.addWidget(self.cb_block)

        _spacing_tip = self.tr(
            "Shrinks or grows the gap around the selected block's"
            " paragraphs. Lower values fit more on one page — useful when"
            " a решење overflows by just a couple of rows onto an extra"
            " page."
        )
        # Label OUTSIDE the field, not as a QDoubleSpinBox prefix -- a
        # prefix renders inside the same editable-looking box as the
        # number, which read as confusing/ambiguous about what's
        # actually editable. Now that the bar spans the full tab width
        # (see Phase3Tab/IzmenaPanel) instead of competing for space
        # inside the splitter's right pane, there's room for real
        # QLabels again.
        lbl_before = QLabel(self.tr("Before:"))
        lbl_before.setToolTip(_spacing_tip)
        row.addWidget(lbl_before)
        self.sb_before = WheelSafeSpinBox()
        self.sb_before.setRange(0, 72)
        self.sb_before.setSingleStep(1)
        self.sb_before.setSuffix(" pt")
        self.sb_before.setToolTip(_spacing_tip)
        self.sb_before.valueChanged.connect(self._on_live_change)
        self.sb_before.editingFinished.connect(self._flush_pending_save)
        row.addWidget(self.sb_before)

        lbl_after = QLabel(self.tr("After:"))
        lbl_after.setToolTip(_spacing_tip)
        row.addWidget(lbl_after)
        self.sb_after = WheelSafeSpinBox()
        self.sb_after.setRange(0, 72)
        self.sb_after.setSingleStep(1)
        self.sb_after.setSuffix(" pt")
        self.sb_after.setToolTip(_spacing_tip)
        self.sb_after.valueChanged.connect(self._on_live_change)
        self.sb_after.editingFinished.connect(self._flush_pending_save)
        row.addWidget(self.sb_after)

        lbl_line_spacing = QLabel(self.tr("Line spacing:"))
        row.addWidget(lbl_line_spacing)
        self.cb_line_spacing = QComboBox()
        # Matches Word's own "Поставити подразумеване вредности" dialog
        # vocabulary, same as Поставке ОИК (which no longer edits this —
        # moved here per the same "edit where you generate" rationale).
        self.cb_line_spacing.addItem(self.tr("Single"), "single")
        self.cb_line_spacing.addItem(self.tr("1.5 lines"), "one_point_five")
        self.cb_line_spacing.addItem(self.tr("Double"), "double")
        self.cb_line_spacing.addItem(self.tr("Multiple (1.15)"), "multiple_1_15")
        self.cb_line_spacing.currentIndexChanged.connect(self._save)
        row.addWidget(self.cb_line_spacing)

        row.addStretch(1)

        self.btn_rik_defaults = QPushButton(self.tr("RIK format"))
        self.btn_rik_defaults.setToolTip(self.tr(
            "Resets title/body spacing and line spacing to the original"
            " RIK-format look. Header/footer margins are unaffected (set"
            " in Поставке ОИК)."
        ))
        self.btn_rik_defaults.clicked.connect(self._on_rik_defaults)
        row.addWidget(self.btn_rik_defaults)

        self.reload()
        # Keeps the Решења and Измене bars (one per workflow) in sync.
        self.state.document_format_changed.connect(self.reload)

    # ── State sync ───────────────────────────────────────────────

    def reload(self) -> None:
        """Re-sync from state.oik.document_format. Skipped while Before/
        After is focused so an external refresh signal firing mid-typing
        doesn't clobber the in-progress edit."""
        if self.sb_before.hasFocus() or self.sb_after.hasFocus():
            log.debug("reload: skipped, Before/After has focus")
            return
        fmt = self.state.oik.document_format
        self._loading = True
        try:
            block = self.cb_block.currentData() or BLOCK_TITLE
            if block == BLOCK_TITLE:
                self.sb_before.setValue(int(fmt.title_before_pt))
                self.sb_after.setValue(int(fmt.title_after_pt))
            else:
                self.sb_before.setValue(int(fmt.body_before_pt))
                self.sb_after.setValue(int(fmt.body_after_pt))
            idx = self.cb_line_spacing.findData(fmt.line_spacing)
            self.cb_line_spacing.setCurrentIndex(max(0, idx))
        finally:
            self._loading = False

    def _on_block_switched(self, _index: int) -> None:
        # Switching the dropdown only changes which fields the same two
        # spinboxes display -- each block's own values were already
        # persisted as they were typed, so this never writes anything.
        self.reload()

    def _on_live_change(self, *_args: object) -> None:
        """valueChanged handler for sb_before/sb_after -- restarts the
        debounce timer instead of saving immediately. Rapid keystrokes
        each push the deadline back further; the real _save() only
        runs once typing actually pauses."""
        if self._loading:
            return
        log.debug(
            "live change: before=%d after=%d -- debounce restarted (%d ms)",
            self.sb_before.value(), self.sb_after.value(), _SAVE_DEBOUNCE_MS,
        )
        self._save_timer.start(_SAVE_DEBOUNCE_MS)

    def _flush_pending_save(self) -> None:
        """editingFinished handler (Enter, or focus lost) -- Пре/После
        losing focus, e.g. by tabbing or clicking elsewhere, must not
        silently drop whatever was typed just because the debounce
        window hadn't elapsed yet."""
        if self._save_timer.isActive():
            log.debug("editingFinished: flushing pending debounced save")
            self._save_timer.stop()
            self._save()

    def _save(self, *_args: object) -> None:
        if self._loading:
            return
        log.debug(
            "saving: before=%d after=%d",
            self.sb_before.value(), self.sb_after.value(),
        )
        old_fmt = self.state.oik.document_format
        block = self.cb_block.currentData() or BLOCK_TITLE
        title_before, title_after = old_fmt.title_before_pt, old_fmt.title_after_pt
        body_before, body_after = old_fmt.body_before_pt, old_fmt.body_after_pt
        if block == BLOCK_TITLE:
            title_before, title_after = float(self.sb_before.value()), float(self.sb_after.value())
        else:
            body_before, body_after = float(self.sb_before.value()), float(self.sb_after.value())
        self.state.oik.document_format = DocumentFormat(
            line_spacing=self.cb_line_spacing.currentData() or "single",
            header_distance_cm=old_fmt.header_distance_cm,
            footer_distance_cm=old_fmt.footer_distance_cm,
            title_before_pt=title_before,
            title_after_pt=title_after,
            body_before_pt=body_before,
            body_after_pt=body_after,
        )
        if not self._persist():
            return
        self.changed.emit()

    def _on_rik_defaults(self) -> None:
        defaults = DocumentFormat()
        old_fmt = self.state.oik.document_format
        self.state.oik.document_format = DocumentFormat(
            line_spacing=defaults.line_spacing,
            header_distance_cm=old_fmt.header_distance_cm,
            footer_distance_cm=old_fmt.footer_distance_cm,
            title_before_pt=defaults.title_before_pt,
            title_after_pt=defaults.title_after_pt,
            body_before_pt=defaults.body_before_pt,
            body_after_pt=defaults.body_after_pt,
        )
        if not self._persist():
            return
        self.reload()
        self.changed.emit()

    def _persist(self) -> bool:
        try:
            self.state.save_document_format()
        except OSError as e:
            QMessageBox.critical(
                self, self.tr("Error"), self.tr("Cannot save: {error}").format(error=e),
            )
            return False
        return True
