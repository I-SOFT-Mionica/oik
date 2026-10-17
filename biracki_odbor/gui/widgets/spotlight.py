"""Spotlight overlay for the guided tour: dims the whole window and blocks
clicks everywhere except one target widget, with a short callout next
to it.

The hole is cut out of the overlay's mask, so clicks inside it go
straight to the real widget underneath; everything else lands on the
overlay and is swallowed. Modal dialogs and file pickers the target
opens are separate top-level windows, so they stay usable.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QRegion
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from biracki_odbor.gui.style import ACCENT, SURFACE, TEXT_PRIMARY, TEXT_SECONDARY

_PAD = 8
_DIM = QColor(15, 20, 35, 150)


class SpotlightOverlay(QWidget):
    skip_requested = Signal()
    next_requested = Signal()

    def __init__(self, host: QWidget) -> None:
        super().__init__(host)
        self._host = host
        self._target: QWidget | None = None
        self._hole = QRect()
        host.installEventFilter(self)

        self.bubble = QFrame(self)
        self.bubble.setObjectName("SpotlightBubble")
        self.bubble.setStyleSheet(
            f"QFrame#SpotlightBubble {{ background: {SURFACE}; border: 2px solid {ACCENT};"
            f" border-radius: 6px; }}"
        )
        self.bubble.setFixedWidth(380)
        lay = QVBoxLayout(self.bubble)
        lay.setContentsMargins(16, 12, 16, 12)
        self.lbl_step = QLabel()
        self.lbl_step.setStyleSheet(f"color: {TEXT_SECONDARY}; border: none;")
        self.lbl_title = QLabel()
        self.lbl_title.setWordWrap(True)
        self.lbl_title.setStyleSheet(f"color: {ACCENT}; font-weight: 600; border: none;")
        self.lbl_text = QLabel()
        self.lbl_text.setWordWrap(True)
        self.lbl_text.setStyleSheet(f"color: {TEXT_PRIMARY}; border: none;")
        lay.addWidget(self.lbl_step)
        lay.addWidget(self.lbl_title)
        lay.addWidget(self.lbl_text)
        row = QHBoxLayout()
        self.btn_skip = QPushButton(self.tr("End tour"))
        self.btn_skip.clicked.connect(self.skip_requested)
        row.addWidget(self.btn_skip)
        row.addStretch()
        self.btn_next = QPushButton(self.tr("Next →"))
        self.btn_next.setObjectName("PrimaryButton")
        self.btn_next.clicked.connect(self.next_requested)
        row.addWidget(self.btn_next)
        lay.addLayout(row)

        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._sync)
        self.hide()

    # ── public ──────────────────────────────────────────────────────

    def show_step(self, target: QWidget | None, *, step: str, title: str, text: str,
                  next_label: str | None) -> None:
        self._target = target
        self.lbl_step.setText(step)
        self.lbl_title.setText(title)
        self.lbl_text.setText(text)
        self.btn_next.setVisible(next_label is not None)
        if next_label is not None:
            self.btn_next.setText(next_label)
        self.bubble.adjustSize()
        self.setGeometry(self._host.rect())
        self.show()
        self.raise_()
        self._sync()
        self._timer.start()

    def finish(self) -> None:
        self._timer.stop()
        self._target = None
        self.hide()

    @property
    def hole(self) -> QRect:
        return QRect(self._hole)

    # ── internals ───────────────────────────────────────────────────

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self._host and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self.setGeometry(self._host.rect())
            self._sync()
        return False

    def _sync(self) -> None:
        t = self._target
        if t is not None and t.isVisible():
            top_left = t.mapTo(self._host, QPoint(0, 0))
            hole = QRect(top_left, t.size()).adjusted(-_PAD, -_PAD, _PAD, _PAD)
        else:
            hole = QRect()
        if hole != self._hole or self.mask().isEmpty():
            self._hole = hole
            region = QRegion(self.rect())
            if not hole.isNull():
                region = region.subtracted(QRegion(hole))
            self.setMask(region)
            self._place_bubble()
            self.update()

    def _place_bubble(self) -> None:
        b = self.bubble
        b.adjustSize()
        w, h = b.width(), b.height()
        r = self.rect()
        hole = self._hole
        if hole.isNull():
            x, y = (r.width() - w) // 2, (r.height() - h) // 2
        elif hole.bottom() + 16 + h <= r.bottom():
            x, y = hole.left(), hole.bottom() + 16
        elif hole.top() - 16 - h >= 0:
            x, y = hole.left(), hole.top() - 16 - h
        else:
            x, y = hole.right() + 16, hole.top()
            if x + w > r.right():
                x = hole.left() - 16 - w
        x = max(16, min(x, r.width() - w - 16))
        y = max(16, min(y, r.height() - h - 16))
        b.move(x, y)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRect(self.rect())
        if not self._hole.isNull():
            hole_path = QPainterPath()
            hole_path.addRoundedRect(self._hole, 6, 6)
            path = path.subtracted(hole_path)
        p.fillPath(path, _DIM)
        if not self._hole.isNull():
            p.setPen(QPen(QColor(ACCENT), 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            # Just outside the hole: inside it the overlay is masked away.
            p.drawRoundedRect(self._hole.adjusted(-3, -3, 3, 3), 7, 7)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        event.accept()  # swallow clicks outside the hole
