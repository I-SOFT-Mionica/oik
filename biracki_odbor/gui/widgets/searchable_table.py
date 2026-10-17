"""Shared widget pair for editable reference tables.

`SearchableTable` and `RowEditDialog` together replace the per-tab
boilerplate of "QTableWidget with inline editing + add/remove buttons"
that grew up around the parties + polling-station settings tables.

Pattern (matches the Phase 2.5 Сви чланови tab):
  1. Search bar above the table — typing filters rows live.
  2. Cells are read-only — `NoEditTriggers`. All edits go through
     `RowEditDialog`, which gives the operator a proper form with
     labels and validation room instead of a barely-visible inline
     QLineEdit that inherits standalone-field padding.
  3. Double-click (or Enter, or an explicit "Измени…" button) opens
     the edit dialog for the selected row.
  4. The widget does NOT own the data — the parent does. The parent
     keeps its own `list[tuple[str, ...]]` and calls `set_rows()` on
     every change. SearchableTable just renders + filters + tells
     the parent which row was activated (by its index in the
     unfiltered list, so the filter doesn't confuse the parent).

Why parent-owned data: the existing Excel import/export, save flow,
and validation all already iterate over a list of records — making
the widget own that list would duplicate state and force every
table-mutation through the widget API. Parent-owned keeps the
widget pure view and the parent's mental model unchanged.
"""

from __future__ import annotations

from typing import Iterable, Sequence

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QKeyEvent, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPlainTextEdit,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)


class SearchableTable(QWidget):
    """Search bar + non-editable QTableWidget + double-click activation.

    Signals:
      row_activated(int): emitted on double-click or on a programmatic
        call to `activate_selected()`. Carries the index into the
        UNFILTERED row list (the one most recently passed to
        `set_rows()`), so filtering never confuses the parent.
      selection_changed(): emitted whenever the selected row changes.

    The underlying QTableWidget is exposed as `self.table` so callers
    can do column-specific tweaks (resize modes, item alignment, …)
    without the widget API having to grow knobs for every variation.
    """

    row_activated = Signal(int)
    selection_changed = Signal()

    def __init__(
        self,
        column_labels: Sequence[str],
        *,
        placeholder: str = "Куцајте за претрагу…",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._rows: list[tuple[str, ...]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        # ── Search row ────────────────────────────────────────
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Претрага:"))
        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText(placeholder)
        self.ed_search.textChanged.connect(self._apply_filter)
        search_row.addWidget(self.ed_search, stretch=1)
        root.addLayout(search_row)

        # ── Table ─────────────────────────────────────────────
        self.table = QTableWidget(0, len(column_labels))
        self.table.setHorizontalHeaderLabels(list(column_labels))
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.Interactive)
        h.setStretchLastSection(True)
        self.table.doubleClicked.connect(self._on_double_click)
        self.table.itemSelectionChanged.connect(self.selection_changed.emit)
        root.addWidget(self.table, stretch=1)

    # ── Public API ────────────────────────────────────────────

    def set_rows(self, rows: Sequence[Sequence[str]]) -> None:
        """Replace the row set + re-render through the current filter."""
        self._rows = [tuple(str(c) for c in row) for row in rows]
        self._apply_filter()

    def selected_original_index(self) -> int | None:
        """Index into the unfiltered row list, or None if no selection."""
        items = self.table.selectedItems()
        if not items:
            return None
        visible_row = items[0].row()
        marker = self.table.item(visible_row, 0)
        if marker is None:
            return None
        val = marker.data(Qt.UserRole)
        return int(val) if val is not None else None

    def activate_selected(self) -> None:
        """Programmatic equivalent of a double-click — for an Edit button."""
        idx = self.selected_original_index()
        if idx is not None:
            self.row_activated.emit(idx)

    def clear_search(self) -> None:
        self.ed_search.clear()

    # ── Internal ─────────────────────────────────────────────

    def _apply_filter(self) -> None:
        needle = self.ed_search.text().strip().lower()

        visible: list[tuple[int, tuple[str, ...]]] = []
        for orig_idx, row in enumerate(self._rows):
            if needle and needle not in " ".join(row).lower():
                continue
            visible.append((orig_idx, row))

        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(0)
            self.table.setRowCount(len(visible))
            for visible_row, (orig_idx, row) in enumerate(visible):
                for col, val in enumerate(row):
                    self.table.setItem(visible_row, col, QTableWidgetItem(val))
                # Stash the original-list index on column 0 so we can
                # map back even when the filter has reordered things.
                self.table.item(visible_row, 0).setData(Qt.UserRole, orig_idx)
        finally:
            self.table.blockSignals(False)
            self.table.setUpdatesEnabled(True)

    def _on_double_click(self) -> None:
        idx = self.selected_original_index()
        if idx is not None:
            self.row_activated.emit(idx)


class SingleLineEdit(QPlainTextEdit):
    """Single-value text editor — horizontal-scroll by default, or
    wrapped multi-line for fields that are routinely long (rule of
    thumb: names/addresses/free text → `wrap=True`; codes, abbreviations,
    JMBG, phone, email → leave as the horizontal-scroll default).

    `QLineEdit` scrolls internally when content overflows, but never
    shows a scrollbar — the operator has to know to use arrow keys /
    End to navigate, and there's no visual cue that more text exists.
    For fields expected to usually be short but occasionally long, a
    horizontal scrollbar (this class's non-wrap mode) is the right
    fallback. But for fields that are LONG by nature (e.g. "Пун назив
    посланичке групе", which routinely runs 60+ chars, or a coalition's
    full listed name) forcing the operator to scroll sideways to read
    their own input is worse than just showing 2-3 wrapped lines
    up front — `wrap=True` switches to that instead.

    In `wrap` mode (and the plain non-wrap default), Enter/Return is
    blocked and pasted newlines are collapsed to spaces, so the stored
    value (`toPlainText()`) stays one continuous string — appropriate
    for fields that are semantically a single value, just a long one.

    Pass `multiline=True` instead for fields where an embedded line
    break is meaningful content the operator is deliberately entering
    (e.g. a long election-list name copied verbatim from an official
    multi-line layout) — Enter and pasted newlines both work normally,
    and the box is taller with its own vertical scrollbar for overflow
    (still no horizontal scroll — word-wrap always stays on). Mutually
    exclusive with `wrap` in effect; `multiline=True` implies wrapped
    layout regardless of `wrap`'s value.

    Drop-in for callers expecting `QLineEdit.text()` /
    `setText()` / `setPlaceholderText()`. Inherits the base
    `QPlainTextEdit` QSS so it visually matches the rest of the
    settings tabs (same border, padding, focus colour).
    """

    # style.py's shared QLineEdit/QPlainTextEdit rule: "padding: 8px
    # 12px" (top+bottom) + "border: 1px solid ...". Duplicated here
    # since CSS values aren't queryable back from the applied
    # stylesheet — both height formulas below need the same numbers.
    _QSS_VERTICAL_PADDING = 16
    _QSS_BORDER = 2
    _WRAP_LINES = 3  # enough for any real full-name/address value
    _MULTILINE_LINES = 6  # more headroom — real paragraph breaks, not just wrap

    def __init__(
        self,
        text: str = "",
        parent: QWidget | None = None,
        *,
        check: "Callable[[str], bool] | None" = None,
        wrap: bool = False,
        multiline: bool = False,
    ) -> None:
        super().__init__(text, parent)
        # QTextDocument reserves its own margin (4px top+bottom by
        # default) INSIDE the QSS padding box, on top of the border and
        # padding below — neither height formula below originally
        # accounted for it, so the widget was consistently a few px
        # short: in non-wrap mode the horizontal scrollbar rendered
        # overlapping the last line of text instead of sitting cleanly
        # under it. Zeroing it here removes the one factor that isn't
        # visible/knowable from this class, so the math only has to
        # account for values actually defined in CSS.
        self.document().setDocumentMargin(0)
        fm = self.fontMetrics()
        self._multiline = multiline
        if wrap or multiline:
            self.setLineWrapMode(QPlainTextEdit.WidgetWidth)
            self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            # Vertical scrollbar is a rare-case safety net in wrap mode
            # (real values should fit in _WRAP_LINES) but the normal,
            # expected overflow path in multiline mode — several real
            # paragraph breaks routinely exceed _MULTILINE_LINES.
            self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            lines = self._MULTILINE_LINES if multiline else self._WRAP_LINES
            self.setFixedHeight(
                fm.height() * lines
                + self._QSS_VERTICAL_PADDING + self._QSS_BORDER
            )
        else:
            self.setLineWrapMode(QPlainTextEdit.NoWrap)
            self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            # Height = one line of text + room for the horizontal
            # scrollbar + the QSS box, so the scrollbar (which only
            # appears once text overflows) never overlaps the
            # text/caret. Querying the scrollbar's sizeHint avoids
            # hardcoding a number that's wrong on high-DPI displays.
            sb_h = self.horizontalScrollBar().sizeHint().height()
            self.setFixedHeight(
                fm.height() + sb_h
                + self._QSS_VERTICAL_PADDING + self._QSS_BORDER
            )
        # Disable the tab-eats-tab behavior — Tab should move focus to
        # the next form field, not insert a tab character. Multiline
        # fields keep Tab as a real character (there's no next field
        # ambiguity in the common case of it being the only/last field,
        # and an operator entering real multi-paragraph text is more
        # likely to want indentation than focus navigation from Tab).
        self.setTabChangesFocus(not multiline)
        # Optional submit-time validator. We can't use Qt's
        # `setValidator` because QPlainTextEdit doesn't expose one —
        # so we recolour the border on change instead. `is_valid()`
        # exposes the result for caller-side OK-button gating.
        self._check: Callable[[str], bool] | None = check
        if check is not None:
            self.textChanged.connect(self._refresh_validity_border)
            # Apply once so initial value lands with the right border.
            self._refresh_validity_border()

    # ── Validator hook ───────────────────────────────────────

    def is_valid(self) -> bool:
        """True iff no validator is set OR the validator accepts the text."""
        if self._check is None:
            return True
        return bool(self._check(self.toPlainText()))

    def _refresh_validity_border(self) -> None:
        """Style the field with a red border when invalid; default when valid.

        Uses dynamic property + style polish so the QSS-rule stays in
        `style.py` (search for `[invalid="true"]`) and we don't fight
        Qt's stylesheet inheritance.
        """
        invalid = not self.is_valid()
        self.setProperty("invalid", bool(invalid))
        # Force re-polish so the property change actually re-applies QSS.
        self.style().unpolish(self)
        self.style().polish(self)

    # ── Single-line enforcement (skipped entirely in multiline mode) ─

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        # Block Enter/Return so the field can never grow vertically —
        # except in multiline mode, where a real line break is exactly
        # what the operator is asking for.
        if not self._multiline and event.key() in (Qt.Key_Return, Qt.Key_Enter):
            event.ignore()
            return
        super().keyPressEvent(event)

    def insertFromMimeData(self, source: QMimeData) -> None:  # noqa: N802
        # Pasted text often contains newlines (especially from Excel
        # cells); collapse them so we don't accidentally end up with a
        # multi-line value in a field that's semantically single-line.
        # Multiline fields want the opposite — a pasted newline (e.g.
        # copied verbatim from an official multi-line document layout)
        # is meaningful content, not noise to strip.
        if not self._multiline and source.hasText():
            cleaned = source.text().replace("\r\n", " ").replace("\n", " ")
            mime = QMimeData()
            mime.setText(cleaned)
            super().insertFromMimeData(mime)
            return
        super().insertFromMimeData(source)

    # ── QLineEdit-shaped API ─────────────────────────────────

    def text(self) -> str:
        return self.toPlainText()

    def setText(self, text: str) -> None:  # noqa: N802
        self.setPlainText(text)


class RowEditDialog(QDialog):
    """Simple form dialog for editing one row's fields.

    Constructed with a list of `(label, key, current_value)` tuples.
    `values()` returns the new values keyed by `key` after Accept.
    No validation is performed inside the dialog — callers should
    validate after `exec()` returns Accepted and reopen if the input
    is bad.

    Optional `placeholders` maps `key → placeholder text` so callers
    can hint at expected format (e.g. "сњс@example.rs" for emails).

    Each field uses `SingleLineEdit`. By default that's a horizontal
    scrollbar when content exceeds the visible width; pass a field's
    key in `wrap_keys` to switch it to wrapped multi-line instead —
    use that for fields that are long by nature (full names, addresses,
    free text), keep the scrolling default for genuinely short fields
    (codes, abbreviations, JMBG, phone, email) that only occasionally
    run long.
    """

    def __init__(
        self,
        title: str,
        fields: Sequence[tuple[str, str, str]],
        *,
        parent: QWidget | None = None,
        placeholders: dict[str, str] | None = None,
        wrap_keys: Iterable[str] = (),
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        # Wider than QLineEdit dialogs would be — even with the
        # horizontal scrollbar, having more room means it rarely has
        # to appear. The dialog is still resizable if the operator
        # wants more breathing room for a specific edit.
        self.setMinimumWidth(560)
        placeholders = placeholders or {}
        wrap_keys = set(wrap_keys)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(8)
        # `FieldsStayAtSizeHint` would clamp the editor at a small
        # default; `AllNonFixedFieldsGrow` lets editors expand to fill
        # the dialog width so long text has more room before scrolling.
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self._edits: dict[str, SingleLineEdit] = {}
        for label, key, value in fields:
            ed = SingleLineEdit(value, wrap=key in wrap_keys)
            if key in placeholders:
                ed.setPlaceholderText(placeholders[key])
            self._edits[key] = ed
            form.addRow(label, ed)
        layout.addLayout(form)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Прихвати")
        bb.button(QDialogButtonBox.Cancel).setText("Откажи")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

        # Focus the first field on open so the operator can start
        # typing immediately. With three fields this saves a click;
        # with eight (the Phase 2.5 person dialog) it saves a lot.
        if self._edits:
            first_key = next(iter(self._edits))
            ed = self._edits[first_key]
            ed.setFocus()
            # Put the caret at the end of pre-filled text so the
            # operator sees the LAST chars first (most important for
            # long content like the full name that motivated this).
            cursor = ed.textCursor()
            cursor.movePosition(QTextCursor.End)
            ed.setTextCursor(cursor)

    def values(self) -> dict[str, str]:
        return {key: ed.text().strip() for key, ed in self._edits.items()}
