"""Paginated, real-page-break preview — replaces a plain continuously
scrolling QTextEdit with actual A4 pages rendered via Qt's own text
layout engine (QTextDocument.setPageSize + pageCount), stacked
vertically with visible gaps between them, like Word's own continuous
page view. Shared by Phase3Tab and IzmenaPanel since both generate the
same A4 page geometry (core.phase3_docx / izmene_docx / prestanak_docx
all set up an identical section).

Anchors: callers embed `anchor_marker(key)` in the HTML right before
any section they want to allow jumping to. `scroll_to_anchor(key)`
later locates it via QTextDocument.find() and scrolls that section's
real page into view — this replaces the old percentage-based scroll
sync, which stopped making sense once the right side renders discrete
pages with blank gaps between them instead of one continuous flow.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QRectF, QSizeF, Qt, QTimer
from PySide6.QtGui import QFont, QPainter, QPixmap, QTextDocument
from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

from biracki_odbor.logging_setup import log_timing

log = logging.getLogger(__name__)

# Mirrors core.phase3_docx.py / izmene_docx.py / prestanak_docx.py's
# identical section setup (A4, ~2cm side/top margins, ~3cm bottom for
# stamp/signature room) — a presentation-only copy, not imported from
# there, since this widget only approximates layout for preview and
# never writes a real .docx.
_TWIPS_PER_PT = 20.0
PAGE_WIDTH_PT = 11906 / _TWIPS_PER_PT
PAGE_HEIGHT_PT = 16838 / _TWIPS_PER_PT
TOP_MARGIN_PT = 1134 / _TWIPS_PER_PT
RIGHT_MARGIN_PT = 1134 / _TWIPS_PER_PT
BOTTOM_MARGIN_PT = 1701 / _TWIPS_PER_PT
LEFT_MARGIN_PT = 1134 / _TWIPS_PER_PT

PX_PER_PT = 4 / 3  # 96 dpi screen preview
_PAGE_GAP_PX = 18
_ANCHOR_MARK = "⁣"  # invisible separator -- never appears in real text


def pt_margin_css(before_pt: float, after_pt: float) -> str:
    """CSS `margin` value converting pt (as used by python-docx/Word) to
    px at this widget's render scale. Qt's QTextDocument HTML/CSS engine
    does NOT understand `pt` units on `margin` (unlike `font-size`,
    where it works fine) -- a `margin: Npt 0 Mpt 0` string is silently
    ignored, which is why the preview used to show no visible change at
    all when the spacing bar's values changed. Callers building preview
    HTML from a DocumentFormat's *_before_pt/*_after_pt fields must use
    this instead of writing `pt` directly into a margin/padding style."""
    return f"{round(before_pt * PX_PER_PT)}px 0 {round(after_pt * PX_PER_PT)}px 0"


def anchor_marker(key: str) -> str:
    """HTML snippet to embed right before a section so
    scroll_to_anchor(key) can find it later. 1px/white so it can never
    be visible on the rendered page."""
    return f'<span style="font-size:1px;color:#ffffff">{_ANCHOR_MARK}{key}{_ANCHOR_MARK}</span>'


class PaginatedPreview(QScrollArea):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._page_w = round(PAGE_WIDTH_PT * PX_PER_PT)
        self._page_h = round(PAGE_HEIGHT_PT * PX_PER_PT)
        self._margin_left = round(LEFT_MARGIN_PT * PX_PER_PT)
        self._margin_top = round(TOP_MARGIN_PT * PX_PER_PT)
        self._margin_right = round(RIGHT_MARGIN_PT * PX_PER_PT)
        self._margin_bottom = round(BOTTOM_MARGIN_PT * PX_PER_PT)
        self._content_w = self._page_w - self._margin_left - self._margin_right
        self._content_h = self._page_h - self._margin_top - self._margin_bottom

        self._doc = QTextDocument()
        self._doc.setDefaultFont(QFont("Times New Roman", 11))
        self._doc.setDocumentMargin(0)
        self._doc.setTextWidth(self._content_w)
        self._doc.setPageSize(QSizeF(self._content_w, self._content_h))

        self._host = QWidget()
        self._vlayout = QVBoxLayout(self._host)
        self._vlayout.setContentsMargins(0, 8, 0, 8)
        self._vlayout.setSpacing(_PAGE_GAP_PX)
        self._vlayout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.setWidget(self._host)

        self._page_labels: list[QLabel] = []
        self._pages_stale = False

    @property
    def page_count(self) -> int:
        return max(1, self._doc.pageCount())

    def to_plain_text(self) -> str:
        """Plain-text content of the current preview, for assertions in
        tests (and any other caller that needs the text, not the
        rendered pages)."""
        return self._doc.toPlainText()

    @log_timing("PaginatedPreview.set_html")
    def set_html(self, html: str) -> None:
        self._doc.setHtml(html)
        # setHtml() can reset page size on some Qt builds -- reassert it.
        self._doc.setPageSize(QSizeF(self._content_w, self._content_h))
        # Four previews exist (Решења + Измене, per workflow) and every
        # relevant edit refreshes all of them; only the one on screen
        # needs its page pixmaps now. Text and page_count stay current.
        if self.isVisible():
            self._rebuild_pages()
            self._pages_stale = False
        else:
            self._pages_stale = True

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._pages_stale:
            self._rebuild_pages()
            self._pages_stale = False

    @log_timing("PaginatedPreview._rebuild_pages")
    def _rebuild_pages(self) -> None:
        log.debug("_rebuild_pages: page_count=%d", self.page_count)
        for lbl in self._page_labels:
            self._vlayout.removeWidget(lbl)
            lbl.deleteLater()
        self._page_labels = []

        for i in range(self.page_count):
            pix = QPixmap(self._page_w, self._page_h)
            pix.fill(Qt.GlobalColor.white)
            painter = QPainter(pix)
            painter.translate(self._margin_left, self._margin_top)
            painter.setClipRect(QRectF(0, 0, self._content_w, self._content_h))
            painter.translate(0, -i * self._content_h)
            self._doc.drawContents(painter)
            painter.end()

            lbl = QLabel()
            lbl.setPixmap(pix)
            lbl.setStyleSheet("border: 1px solid #bbb;")
            lbl.setFixedSize(pix.size())
            self._vlayout.addWidget(lbl)
            self._page_labels.append(lbl)

    def scroll_to_anchor(self, key: str) -> bool:
        """Jump the scroll area to the real page containing `key`'s
        marker, aligning that page's top edge to the top of the
        viewport. Returns False if the marker wasn't found (e.g. a
        card that no longer exists) so callers can no-op silently.

        Deliberately NOT QScrollArea.ensureWidgetVisible(): that call
        stops scrolling as soon as the target has ANY overlap with the
        viewport, which a page taller than the viewport (the normal
        case -- an A4 page is ~1100px) can already satisfy with just
        its top edge peeking in, or lands it centered-ish within
        whatever margin budget Qt's own heuristic negotiates -- neither
        reads as "jumped to this page" the way an operator expects.
        Setting the scrollbar value directly is exact instead.

        The actual scroll is deferred one event-loop tick: this is
        called from QApplication.focusChanged, i.e. while Qt is still
        in the middle of processing the focus change, and the target
        page label's geometry (`.y()` within the scrolled widget) is
        only guaranteed accurate once any layout work queued by that
        same event has actually run -- reading it synchronously here
        could use a stale pre-layout position. Letting the event loop
        finish first (even a 0 ms timer still waits for the next
        iteration) is the standard fix for "geometry not settled yet".

        The deferred timer is a real QTimer parented to `self`, NOT
        the static QTimer.singleShot(...) class method -- that creates
        an anonymous timer with no connection to this widget's
        lifetime, so if `self` (or the previewed tab) is torn down
        before the next event-loop iteration -- exactly what every
        test in tests/test_phase3*.py and tests/test_izmene.py does,
        constructing and immediately `deleteLater()`-ing a tab per
        test -- the callback still fires afterward and touches an
        already-deleted C++ QWidget. That reliably crashed the whole
        test process (not a caught Python exception, since it's a
        native-level use-after-free) the one time this shipped as a
        plain singleShot: CI showed "1640 passed" followed immediately
        by a bare nonzero exit with no traceback. Parenting the timer
        makes Qt cancel it automatically as part of `self`'s own
        teardown, before the callback can ever run on a dead object."""
        if self._pages_stale:
            self._rebuild_pages()
            self._pages_stale = False
        cursor = self._doc.find(f"{_ANCHOR_MARK}{key}{_ANCHOR_MARK}")
        if cursor.isNull() or not self._page_labels:
            return False
        rect = self._doc.documentLayout().blockBoundingRect(cursor.block())
        page_index = int(rect.top() // self._content_h) if self._content_h else 0
        page_index = max(0, min(page_index, len(self._page_labels) - 1))
        target = self._page_labels[page_index]

        def _do_scroll() -> None:
            try:
                bar = self.verticalScrollBar()
                bar.setValue(min(target.y(), bar.maximum()))
            except RuntimeError:
                pass  # self or target already deleted -- nothing to scroll

        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(_do_scroll)
        timer.start(0)
        return True
