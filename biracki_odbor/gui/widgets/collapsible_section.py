from __future__ import annotations

from PySide6.QtCore import Property, QEasingCurve, QPointF, QPropertyAnimation, Qt, Signal
from PySide6.QtGui import QPainter, QPolygonF
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class _RotatingArrow(QWidget):
    """Solid right-pointing triangle that rotates 90° clockwise to point down when expanded."""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._angle = 0.0
        self._anim = QPropertyAnimation(self, b"rotation_angle")
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.setFixedSize(16, 16)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # QWidget's own base QSS rule paints an opaque SURFACE background
        # by default — visible as a stray white square against the
        # header's tinted background otherwise.
        self.setStyleSheet("background: transparent;")

    def _get_angle(self) -> float:
        return self._angle

    def _set_angle(self, v: float) -> None:
        self._angle = v
        self.update()

    rotation_angle = Property(float, _get_angle, _set_angle)

    def set_expanded(self, expanded: bool, *, animate: bool = True) -> None:
        target = 90.0 if expanded else 0.0
        if not animate:
            self._anim.stop()
            self._angle = target
            self.update()
            return
        self._anim.stop()
        self._anim.setStartValue(self._angle)
        self._anim.setEndValue(target)
        self._anim.start()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.clicked.emit()
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self.width() / 2.0, self.height() / 2.0)
        painter.rotate(self._angle)
        # Right-pointing triangle: apex at right, base on left
        s = 4.5
        poly = QPolygonF([
            QPointF(-s, -s * 1.15),
            QPointF(s,   0.0),
            QPointF(-s,  s * 1.15),
        ])
        painter.setPen(Qt.PenStyle.NoPen)
        color = self.palette().color(self.foregroundRole())
        color.setAlpha(160)
        painter.setBrush(color)
        painter.drawPolygon(poly)


class CollapsibleSection(QWidget):
    """
    Card-style section with a collapsible body.

    Header row (always visible):
        ▶→▼  Title  [count]  description  ──────  [quick_actions]  [Hide/Show]

    The arrow rotates 90° clockwise (▶ → ▼) when expanded and is clickable.
    Quick-action widgets (added via `add_quick_action`) are surfaced in the
    header only when the section is **collapsed**.
    """

    toggled = Signal(bool)  # True = expanded, False = collapsed

    def __init__(
        self,
        title: str,
        description: str = "",
        *,
        initially_expanded: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._expanded = initially_expanded
        self._locked = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Outer card frame ─────────────────────────────────────────
        card = QFrame()
        card.setObjectName("CollapsibleCard")
        card_vbox = QVBoxLayout(card)
        card_vbox.setContentsMargins(0, 0, 0, 0)
        card_vbox.setSpacing(0)
        root.addWidget(card)

        # ── Header ───────────────────────────────────────────────────
        hdr = QFrame()
        hdr.setObjectName("CollapsibleCardHeader")
        hbox = QHBoxLayout(hdr)
        hbox.setContentsMargins(18, 10, 14, 10)
        hbox.setSpacing(6)

        self._arrow = _RotatingArrow()
        self._arrow.clicked.connect(self.toggle)
        hbox.addWidget(self._arrow)

        self._title_lbl = QLabel(title)
        self._title_lbl.setObjectName("CollapsibleTitle")
        hbox.addWidget(self._title_lbl)

        self._count_lbl = QLabel()
        self._count_lbl.setObjectName("CollapsibleCount")
        self._count_lbl.setVisible(False)
        hbox.addWidget(self._count_lbl)

        # Extra gap (beyond the layout's uniform 6px) so title+count read
        # as one visual unit, clearly separated from the subtitle.
        hbox.addSpacing(6)

        self._desc_lbl = QLabel(description)
        self._desc_lbl.setObjectName("CollapsibleDesc")
        if not description:  # never setVisible(True) before parenting: it pops a window
            self._desc_lbl.hide()
        hbox.addWidget(self._desc_lbl)

        hbox.addStretch()

        # Quick-action container — visible only when collapsed
        self._qa = QWidget()
        qa_row = QHBoxLayout(self._qa)
        qa_row.setContentsMargins(0, 0, 0, 0)
        qa_row.setSpacing(4)
        self._qa_row = qa_row
        hbox.addWidget(self._qa)

        self._btn_toggle = QPushButton()
        self._btn_toggle.clicked.connect(self.toggle)
        hbox.addWidget(self._btn_toggle)

        card_vbox.addWidget(hdr)

        # ── Separator ────────────────────────────────────────────────
        self._sep = QFrame()
        self._sep.setFrameShape(QFrame.Shape.HLine)
        self._sep.setObjectName("CollapsibleSep")
        card_vbox.addWidget(self._sep)

        # ── Body ─────────────────────────────────────────────────────
        self._body = QWidget()
        body_vbox = QVBoxLayout(self._body)
        body_vbox.setContentsMargins(18, 10, 18, 14)
        body_vbox.setSpacing(8)
        self._body_layout = body_vbox
        card_vbox.addWidget(self._body)

        self._sync(animate=False)

    # ── Public API ────────────────────────────────────────────────────

    def set_count(self, n: int | None) -> None:
        if n is None:
            self._count_lbl.setVisible(False)
        else:
            # Bare "2" sitting between the title and subtitle read as a
            # typo/stray digit inside the subtitle sentence -- parens make
            # it unambiguous as a standalone count badge.
            self._count_lbl.setText(f"({n})")
            self._count_lbl.setVisible(True)

    def set_description(self, text: str) -> None:
        self._desc_lbl.setText(text)
        self._desc_lbl.setVisible(bool(text))

    def add_quick_action(self, widget: QWidget) -> None:
        """Add a button shown in the header only when the section is collapsed."""
        self._qa_row.addWidget(widget)

    def set_content(self, widget: QWidget) -> None:
        self._body_layout.addWidget(widget)

    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, value: bool) -> None:
        """Programmatic expand/collapse — works even while locked, so
        callers can still force-collapse a locked section."""
        if value == self._expanded:
            return
        self._expanded = value
        self._sync()
        self.toggled.emit(value)

    def set_locked(self, locked: bool) -> None:
        """Disable user-triggered expand/collapse (arrow click, Hide/Show
        button) until some precondition is met. Does not affect
        `set_expanded()`, which callers can still use directly."""
        self._locked = locked
        self._arrow.setEnabled(not locked)
        self._btn_toggle.setEnabled(not locked)

    def is_locked(self) -> bool:
        return self._locked

    def toggle(self) -> None:
        if self._locked:
            return
        self.set_expanded(not self._expanded)

    # ── Internal ──────────────────────────────────────────────────────

    def _sync(self, animate: bool = True) -> None:
        self._arrow.set_expanded(self._expanded, animate=animate)
        if self._expanded:
            self._btn_toggle.setText(self.tr("Hide"))
            self._qa.setVisible(False)
            self._sep.setVisible(True)
            self._body.setVisible(True)
            self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        else:
            self._btn_toggle.setText(self.tr("Show"))
            self._qa.setVisible(True)
            self._sep.setVisible(False)
            self._body.setVisible(False)
            self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
