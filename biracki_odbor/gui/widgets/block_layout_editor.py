"""Block layout editor — the builder behind observer cards and envelopes.

A layout is a list of blocks on a 12-column grid (`LegitimacijaBlock`:
type, value, col_span, row_height, alignment). The editor is the same
for every printed thing; what differs is supplied by a subclass:

  - `_palette()`        which block types exist, their labels/colours and
                        what each one shows in the preview
  - `_page_size_mm()`   the paper/card/envelope being designed
  - `_build_setup_box()` the settings above the block list
  - `_stored_layout()` / `_store_layout()` / `_default_layout()`
  - `_save()`           persistence

Shared strings use the explicit "BlockLayout" translation context: with
self.tr() in a base class, the lookup would run under each subclass's
name and miss the translation.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIntValidator, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QSplitter, QVBoxLayout, QWidget,
)

from biracki_odbor.core.observers import (
    BLOCK_DIVIDER, BLOCK_SPACER, BLOCK_STATIC_TEXT, LegitimacijaBlock,
)


# Compact Up/Down/Remove buttons: the global QPushButton padding leaves
# no room for text in a narrow button.
_COMPACT_BTN = "padding: 3px 8px; font-size: 11pt;"
_COMPACT_BTN_DANGER = _COMPACT_BTN + " color: #9B0000; border-color: #F0B0B0;"


@dataclass(frozen=True)
class BlockPalette:
    """What a particular editor offers. `preview_text(block)` returns the
    text the printed result will show for that block."""

    types: list[str]
    labels: dict[str, str]
    colors: dict[str, str]
    preview_text: Callable[[LegitimacijaBlock], str]
    static_hint: str = ""
    static_tooltip: str = ""
    extra: dict = field(default_factory=dict)


class _NoWheelFilter(QObject):
    """Swallows wheel events so combo values don't change on scroll."""

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Wheel:
            event.ignore()
            return True
        return False


_NO_WHEEL: _NoWheelFilter | None = None


def no_wheel() -> _NoWheelFilter:
    global _NO_WHEEL  # noqa: PLW0603
    if _NO_WHEEL is None:
        _NO_WHEEL = _NoWheelFilter()
    return _NO_WHEEL


class BlockPreview(QWidget):
    """Live painted preview: the page scaled to fit, blocks laid out
    row by row on the 12-column grid, as they will print."""

    def __init__(self, palette: BlockPalette, parent=None) -> None:
        super().__init__(parent)
        self._palette = palette
        self._blocks: list[LegitimacijaBlock] = []
        self._w_mm = 90.0
        self._h_mm = 60.0
        self.setMinimumWidth(200)
        self.setMinimumHeight(200)

    def update_preview(self, blocks: list[LegitimacijaBlock], w_mm: float, h_mm: float) -> None:
        self._blocks = list(blocks)
        self._w_mm = max(20.0, w_mm)
        self._h_mm = max(20.0, h_mm)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        margin = 20
        avail_w = self.width() - 2 * margin
        avail_h = self.height() - 2 * margin
        if avail_w <= 0 or avail_h <= 0:
            painter.end()
            return

        scale = min(avail_w / self._w_mm, avail_h / self._h_mm)
        cw = self._w_mm * scale
        ch = self._h_mm * scale
        cx = margin + (avail_w - cw) / 2
        cy = margin + (avail_h - ch) / 2

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#C0C0C0"))
        painter.drawRoundedRect(QRectF(cx + 3, cy + 3, cw, ch), 4, 4)
        painter.setBrush(QColor("#FFFFFF"))
        painter.setPen(QPen(QColor("#2F5496"), 1.5))
        painter.drawRoundedRect(QRectF(cx, cy, cw, ch), 4, 4)
        painter.setClipRect(QRect(int(cx) + 1, int(cy) + 1, int(cw) - 2, int(ch) - 2))

        base_h = max(14.0, ch / 10)
        pad = 3.0
        painter.setFont(QFont("Segoe UI", max(6, int(base_h * 0.45))))

        rows: list[tuple[list, float]] = []
        cur_row: list = []
        cur_col = 0
        cur_row_h = 0.0
        for blk in self._blocks:
            span = max(1, min(12, blk.col_span))
            h = max(1, blk.row_height) * base_h
            if cur_col + span > 12:
                rows.append((list(cur_row), cur_row_h))
                cur_row, cur_col, cur_row_h = [], 0, 0.0
            cur_row.append((blk, span, h))
            cur_col += span
            cur_row_h = max(cur_row_h, h)
        if cur_row:
            rows.append((cur_row, cur_row_h))

        draw_y = cy + pad
        usable_w = cw - 2 * pad
        for row_items, row_h in rows:
            if draw_y + row_h > cy + ch:
                break
            draw_x = cx + pad
            for blk, span, blk_h in row_items:
                bw = (span / 12) * usable_w - 1
                bh = blk_h - 1
                if blk.block_type == BLOCK_DIVIDER:
                    painter.setPen(QPen(QColor("#888888"), 1))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    mid = draw_y + bh / 2
                    painter.drawLine(int(draw_x), int(mid), int(draw_x + bw), int(mid))
                elif blk.block_type != BLOCK_SPACER:
                    painter.setBrush(QColor(self._palette.colors.get(blk.block_type, "#F0F0F0")))
                    painter.setPen(QPen(QColor("#AAAAAA"), 0.5))
                    painter.drawRect(QRectF(draw_x, draw_y, bw, bh))
                    label = self._palette.preview_text(blk)
                    if label:
                        self._draw_label(painter, blk, label, QRectF(draw_x + 2, draw_y, bw - 4, bh))
                draw_x += bw + 1
            draw_y += row_h
        painter.end()

    @staticmethod
    def _draw_label(painter: QPainter, blk: LegitimacijaBlock, label: str, rect: QRectF) -> None:
        h_align = {
            "left": Qt.AlignmentFlag.AlignLeft,
            "center": Qt.AlignmentFlag.AlignHCenter,
            "right": Qt.AlignmentFlag.AlignRight,
        }.get(blk.alignment, Qt.AlignmentFlag.AlignHCenter)
        flags = int(Qt.AlignmentFlag.AlignVCenter | h_align | Qt.TextFlag.TextWordWrap)
        base_font = painter.font()
        fit = QFont(base_font)
        # Shrink until the wrapped text fits vertically.
        while fit.pointSize() > 5:
            br = QFontMetrics(fit).boundingRect(QRect(0, 0, int(rect.width()), 9999), flags, label)
            if br.height() <= rect.height():
                break
            fit.setPointSize(fit.pointSize() - 1)
        painter.setFont(fit)
        painter.setPen(QColor("#1F2A44"))
        painter.drawText(rect, flags, label)
        painter.setFont(base_font)


class BlockCard(QFrame):
    """One block in the editor list: type, width, height, alignment, and
    the text for free-text blocks."""

    def __init__(
        self, block: LegitimacijaBlock, palette: BlockPalette, *,
        on_remove, on_move_up, on_move_down, on_changed, parent=None,
    ) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setObjectName("Card")
        self._block_type = block.block_type
        self._bg = palette.colors.get(block.block_type, "#F5F5F5")
        self._apply_style(active=False)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(4)

        top = QHBoxLayout()
        type_label = QLabel(f"<b>{palette.labels.get(block.block_type, block.block_type)}</b>")
        type_label.setTextFormat(Qt.TextFormat.RichText)
        top.addWidget(type_label, stretch=1)
        for text, tip, style, handler in (
            (QCoreApplication.translate("BlockLayout", "Up"), QCoreApplication.translate("BlockLayout", "Move up"), _COMPACT_BTN, on_move_up),
            (QCoreApplication.translate("BlockLayout", "Down"), QCoreApplication.translate("BlockLayout", "Move down"), _COMPACT_BTN, on_move_down),
            (QCoreApplication.translate("BlockLayout", "Remove"), QCoreApplication.translate("BlockLayout", "Remove block"), _COMPACT_BTN_DANGER, on_remove),
        ):
            btn = QPushButton(text)
            btn.setStyleSheet(style)
            btn.setToolTip(tip)
            btn.clicked.connect(lambda _=False, h=handler: h(self))
            top.addWidget(btn)
        root.addLayout(top)

        props = QHBoxLayout()
        props.addWidget(QLabel(QCoreApplication.translate("BlockLayout", "Width:")))
        self._col_combo = QComboBox()
        self._col_combo.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._col_combo.installEventFilter(no_wheel())
        for c in range(1, 13):
            self._col_combo.addItem(f"{c} / 12", c)
        self._col_combo.setCurrentIndex(max(0, min(11, block.col_span - 1)))
        self._col_combo.setToolTip(QCoreApplication.translate("BlockLayout", 
            "Block width in 12-column grid.\n"
            "12 = full width  |  6 = half  |  4 = third  |  3 = quarter"
        ))
        self._col_combo.currentIndexChanged.connect(on_changed)
        props.addWidget(self._col_combo)

        props.addSpacing(12)
        props.addWidget(QLabel(QCoreApplication.translate("BlockLayout", "Height:")))
        self._row_edit = QLineEdit(str(max(1, block.row_height)))
        self._row_edit.setValidator(QIntValidator(1, 20))
        self._row_edit.setFixedWidth(50)
        self._row_edit.setToolTip(QCoreApplication.translate("BlockLayout", "Relative block height in rows (1 = standard row)."))
        self._row_edit.editingFinished.connect(on_changed)
        props.addWidget(self._row_edit)

        props.addSpacing(12)
        props.addWidget(QLabel(QCoreApplication.translate("BlockLayout", "Alignment:")))
        self._align_combo = QComboBox()
        self._align_combo.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._align_combo.installEventFilter(no_wheel())
        for label, data in ((QCoreApplication.translate("BlockLayout", "Left"), "left"), (QCoreApplication.translate("BlockLayout", "Center"), "center"), (QCoreApplication.translate("BlockLayout", "Right"), "right")):
            self._align_combo.addItem(label, data)
        self._align_combo.setCurrentIndex(max(0, self._align_combo.findData(block.alignment or "center")))
        self._align_combo.currentIndexChanged.connect(on_changed)
        props.addWidget(self._align_combo)
        props.addStretch()
        root.addLayout(props)

        self._text_edit: QLineEdit | None = None
        if block.block_type == BLOCK_STATIC_TEXT:
            self._text_edit = QLineEdit(block.value)
            self._text_edit.setPlaceholderText(palette.static_hint)
            self._text_edit.setToolTip(palette.static_tooltip)
            self._text_edit.editingFinished.connect(on_changed)
            root.addWidget(self._text_edit)

    def _apply_style(self, active: bool) -> None:
        border = "#2F5496" if active else "#AAAAAA"
        width = "2px" if active else "1px"
        self.setStyleSheet(
            f"QFrame#Card {{ background-color: {self._bg};"
            f" border: {width} solid {border}; border-radius: 4px; }}"
        )

    def set_active(self, active: bool) -> None:
        self._apply_style(active)

    def to_block(self) -> LegitimacijaBlock:
        try:
            row_h = max(1, int(self._row_edit.text()))
        except ValueError:
            row_h = 1
        return LegitimacijaBlock(
            block_type=self._block_type,
            value=self._text_edit.text().strip() if self._text_edit else "",
            col_span=self._col_combo.currentData() or 12,
            row_height=row_h,
            alignment=self._align_combo.currentData() or "center",
        )


class BlockLayoutEditor(QWidget):
    """Base class: header with Save, setup box + block list on the left,
    live preview on the right. Every change re-renders and saves."""

    TITLE = ""
    BLOCKS_TITLE = ""
    PREVIEW_TITLE = ""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cards: list[BlockCard] = []
        self._active_card: BlockCard | None = None
        self._loading = False
        palette = self._palette()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QWidget()
        header.setObjectName("TabHeader")
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(16, 8, 16, 8)
        title = QLabel(self.TITLE)
        title.setObjectName("TitleLabel")
        header_row.addWidget(title)
        header_row.addStretch()
        self._build_header_actions(header_row)
        self._btn_save = QPushButton(QCoreApplication.translate("BlockLayout", "Save"))
        self._btn_save.setObjectName("PrimaryButton")
        self._btn_save.clicked.connect(self._manual_save)
        header_row.addWidget(self._btn_save)
        self._save_label = QLabel("")
        self._save_label.setObjectName("MutedLabel")
        header_row.addWidget(self._save_label)
        root.addWidget(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(6)

        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        splitter.addWidget(scroll)
        editor = QWidget()
        editor_root = QVBoxLayout(editor)
        editor_root.setContentsMargins(16, 16, 8, 16)
        editor_root.setSpacing(14)
        scroll.setWidget(editor)

        editor_root.addWidget(self._build_setup_box())

        blocks_box = QGroupBox(self.BLOCKS_TITLE)
        blocks_vbox = QVBoxLayout(blocks_box)
        self._cards_container = QWidget()
        self._cards_layout = QVBoxLayout(self._cards_container)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(8)
        self._cards_layout.addStretch(1)
        self._blocks_scroll = QScrollArea()
        self._blocks_scroll.setWidgetResizable(True)
        self._blocks_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._blocks_scroll.setMinimumHeight(320)
        self._blocks_scroll.setWidget(self._cards_container)
        blocks_vbox.addWidget(self._blocks_scroll)

        add_row = QHBoxLayout()
        self._block_type_combo = QComboBox()
        self._block_type_combo.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._block_type_combo.installEventFilter(no_wheel())
        for i, bt in enumerate(palette.types):
            self._block_type_combo.addItem(palette.labels.get(bt, bt), bt)
            color = palette.colors.get(bt)
            if color:
                self._block_type_combo.setItemData(i, QColor(color), Qt.ItemDataRole.BackgroundRole)
        add_row.addWidget(self._block_type_combo, stretch=1)
        btn_add = QPushButton(QCoreApplication.translate("BlockLayout", "+ Add block"))
        btn_add.clicked.connect(self._add_block)
        add_row.addWidget(btn_add)
        btn_reset = QPushButton(QCoreApplication.translate("BlockLayout", "Reset to default"))
        btn_reset.clicked.connect(self._reset_layout)
        add_row.addWidget(btn_reset)
        blocks_vbox.addLayout(add_row)
        editor_root.addWidget(blocks_box)
        editor_root.addStretch()

        right = QWidget()
        right_vbox = QVBoxLayout(right)
        right_vbox.setContentsMargins(8, 16, 16, 16)
        right_vbox.setSpacing(8)
        heading = QLabel(self.PREVIEW_TITLE)
        heading.setObjectName("HeadLabel")
        right_vbox.addWidget(heading)
        self._preview = BlockPreview(palette)
        right_vbox.addWidget(self._preview, stretch=1)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([500, 500])
        root.addWidget(splitter, stretch=1)

        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.focusChanged.connect(self._on_focus_changed)

    # ── hooks ─────────────────────────────────────────────────────
    def _palette(self) -> BlockPalette:
        raise NotImplementedError

    def _page_size_mm(self) -> tuple[float, float]:
        raise NotImplementedError

    def _build_setup_box(self) -> QWidget:
        raise NotImplementedError

    def _build_header_actions(self, row: QHBoxLayout) -> None:
        """Optional extra buttons left of Save."""

    def _stored_layout(self) -> list[LegitimacijaBlock]:
        raise NotImplementedError

    def _store_layout(self, blocks: list[LegitimacijaBlock]) -> None:
        raise NotImplementedError

    def _default_layout(self) -> list[LegitimacijaBlock]:
        raise NotImplementedError

    def _save(self) -> None:
        raise NotImplementedError

    # ── shared behaviour ──────────────────────────────────────────
    def blocks(self) -> list[LegitimacijaBlock]:
        return [c.to_block() for c in self._cards]

    def _refresh_preview(self) -> None:
        w, h = self._page_size_mm()
        self._preview.update_preview(self.blocks(), w, h)

    def _load_layout(self, blocks: list[LegitimacijaBlock]) -> None:
        while self._cards_layout.count() > 1:
            item = self._cards_layout.takeAt(0)
            if item is not None and item.widget() is not None:
                item.widget().deleteLater()
        self._cards.clear()
        self._active_card = None
        for block in blocks:
            self._insert_card(block)

    def _set_active_card(self, card: BlockCard | None) -> None:
        if card is self._active_card:
            return
        if self._active_card is not None and self._active_card in self._cards:
            self._active_card.set_active(False)
        self._active_card = card
        if card is not None:
            card.set_active(True)

    def _on_focus_changed(self, _old, new) -> None:
        w = new
        while w is not None:
            if isinstance(w, BlockCard) and w in self._cards:
                self._set_active_card(w)
                return
            w = w.parent()

    def _insert_card(self, block: LegitimacijaBlock, after: BlockCard | None = None) -> BlockCard:
        card = BlockCard(
            block, self._palette(),
            on_remove=self._remove_card, on_move_up=self._move_card_up,
            on_move_down=self._move_card_down, on_changed=self._on_layout_changed,
        )
        if after is not None and after in self._cards:
            idx = self._cards.index(after)
            self._cards_layout.insertWidget(idx + 1, card)
            self._cards.insert(idx + 1, card)
        else:
            self._cards_layout.insertWidget(self._cards_layout.count() - 1, card)
            self._cards.append(card)
        return card

    def _remove_card(self, card: BlockCard) -> None:
        if card is self._active_card:
            idx = self._cards.index(card)
            nxt = (self._cards[idx - 1] if idx > 0
                   else self._cards[idx + 1] if idx + 1 < len(self._cards) else None)
            self._set_active_card(nxt)
        if card in self._cards:
            self._cards.remove(card)
        self._cards_layout.removeWidget(card)
        card.deleteLater()
        self._on_layout_changed()

    def _move_card(self, card: BlockCard, delta: int) -> None:
        idx = self._cards.index(card) if card in self._cards else -1
        new = idx + delta
        if idx < 0 or not 0 <= new < len(self._cards):
            return
        self._cards.insert(new, self._cards.pop(idx))
        self._cards_layout.removeWidget(card)
        self._cards_layout.insertWidget(new, card)
        self._on_layout_changed()

    def _move_card_up(self, card: BlockCard) -> None:
        self._move_card(card, -1)

    def _move_card_down(self, card: BlockCard) -> None:
        self._move_card(card, +1)

    def _add_block(self) -> None:
        bt = self._block_type_combo.currentData()
        if not bt:
            return
        card = self._insert_card(LegitimacijaBlock(block_type=bt), after=self._active_card)
        self._set_active_card(card)
        self._blocks_scroll.ensureWidgetVisible(card)
        self._on_layout_changed()

    def _reset_layout(self) -> None:
        self._load_layout(self._default_layout())
        self._on_layout_changed()

    def _on_layout_changed(self) -> None:
        if self._loading:
            return
        self._store_layout(self.blocks())
        self._refresh_preview()
        self._save()

    def _manual_save(self) -> None:
        self._save()
        self._save_label.setText(QCoreApplication.translate("BlockLayout", "Saved ✓"))
        QTimer.singleShot(2000, lambda: self._save_label.setText(""))
