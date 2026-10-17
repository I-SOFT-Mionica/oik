"""Read-only viewer for the three election-law markdown files.

Three tabs — Председник / Посланици / Локални. Each tab is a split view:
  Left  — search box + scrollable index of all section (##) and article
           (###) headings; clicking a heading scrolls the right pane.
  Right — rendered law text (HTML with anchor IDs on every heading).
"""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QKeySequence, QShortcut, QTextCharFormat
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QSplitter, QTabWidget, QTextBrowser, QTextEdit, QVBoxLayout, QWidget,
)

_RESOURCES = Path(__file__).resolve().parent.parent.parent / "resources"

# ── Serbian Latin → Cyrillic transliteration ─────────────────────────────────
# Digraphs must come before their component letters so they are matched first.
# dj is NOT in the digraph list — in official legal text it is always the
# separate letters д + ј, never the phoneme ђ.  Only the explicit đ (U+0111)
# character maps to ђ.
_LAT_CYR: tuple[tuple[str, str], ...] = (
    ("DŽ", "Џ"), ("Dž", "Џ"), ("dž", "џ"),
    ("LJ", "Љ"), ("Lj", "Љ"), ("lj", "љ"),
    ("NJ", "Њ"), ("Nj", "Њ"), ("nj", "њ"),
    ("A", "А"), ("B", "Б"), ("C", "Ц"), ("Č", "Ч"), ("Ć", "Ћ"),
    ("D", "Д"), ("Đ", "Ђ"), ("E", "Е"), ("F", "Ф"), ("G", "Г"),
    ("H", "Х"), ("I", "И"), ("J", "Ј"), ("K", "К"), ("L", "Л"),
    ("M", "М"), ("N", "Н"), ("O", "О"), ("P", "П"), ("R", "Р"),
    ("S", "С"), ("Š", "Ш"), ("T", "Т"), ("U", "У"), ("V", "В"),
    ("Z", "З"), ("Ž", "Ж"),
    ("a", "а"), ("b", "б"), ("c", "ц"), ("č", "ч"), ("ć", "ћ"),
    ("d", "д"), ("đ", "ђ"), ("e", "е"), ("f", "ф"), ("g", "г"),
    ("h", "х"), ("i", "и"), ("j", "ј"), ("k", "к"), ("l", "л"),
    ("m", "м"), ("n", "н"), ("o", "о"), ("p", "п"), ("r", "р"),
    ("s", "с"), ("š", "ш"), ("t", "т"), ("u", "у"), ("v", "в"),
    ("z", "з"), ("ž", "ж"),
)

# Matches standalone uppercase Roman numeral sequences (word-bounded).
# These must be protected before transliteration because I/V/X/L/C/D/M
# all have Cyrillic equivalents.
_ROMAN_RE = re.compile(r"\b[IVXLCDM]+\b")


def _lat_to_cyr(text: str) -> str:
    """Transliterate Serbian Latin to Serbian Cyrillic, preserving Roman numerals."""
    slots: list[str] = []

    def _stash(m: re.Match) -> str:
        slots.append(m.group())
        return f"\x00{len(slots) - 1}\x00"

    text = _ROMAN_RE.sub(_stash, text)
    for lat, cyr in _LAT_CYR:
        text = text.replace(lat, cyr)
    for i, val in enumerate(slots):
        text = text.replace(f"\x00{i}\x00", val)
    return text


# ── Markdown → HTML conversion ────────────────────────────────────────────────

def _md_to_html(text: str) -> tuple[str, list[tuple[int, str, str]]]:
    """Convert a law markdown file to HTML with anchor IDs on headings.

    Returns (html_string, [(level, display_text, anchor_id), ...]).
    Only ## (level 2) and ### (level 3) headings are added to the index.
    """
    seen: dict[str, int] = {}
    index: list[tuple[int, str, str]] = []

    def make_id(raw: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-") or "h"
        n = seen.get(slug, 0)
        seen[slug] = n + 1
        return slug if n == 0 else f"{slug}-{n}"

    def inline(t: str) -> str:
        t = _lat_to_cyr(t)
        return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)

    parts = [
        "<html><body style='"
        "margin:16px 20px;font-family:sans-serif;"
        "font-size:13px;line-height:1.6;max-width:900px'>"
    ]

    for block in re.split(r"\n{2,}", text):
        block = block.strip()
        if not block:
            continue
        m = re.match(r"^(#{1,3})\s+(.*)", block)
        if m:
            level = len(m.group(1))
            raw = m.group(2).strip()          # Latin — used for the anchor ID
            htxt = _lat_to_cyr(raw)           # Cyrillic — displayed text
            tag = f"h{level}"
            if level >= 2:
                aid = make_id(raw)            # anchor stays Latin for stability
                index.append((level, htxt, aid))
                parts.append(f'<{tag} id="{aid}">{htxt}</{tag}>')
            else:
                parts.append(f"<{tag}>{htxt}</{tag}>")
        else:
            lines = [inline(ln) for ln in block.splitlines()]
            parts.append(f'<p>{"<br>".join(lines)}</p>')

    parts.append("</body></html>")
    return "\n".join(parts), index


# ── Per-tab widget ─────────────────────────────────────────────────────────────

class _LawTab(QWidget):
    """Split view: left = search + index, right = rendered law text."""

    def __init__(self, path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        if path.exists():
            html, index_entries = _md_to_html(path.read_text(encoding="utf-8"))
        else:
            html = f"<p>File not found:<br>{path}</p>"
            index_entries = []

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.setChildrenCollapsible(False)

        # ── Left panel: search + index ─────────────────────────
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(4, 6, 4, 4)
        left_layout.setSpacing(4)

        self._search = QLineEdit()
        self._search.setPlaceholderText(self.tr("Search… (Enter / Shift+Enter)"))
        self._search.setClearButtonEnabled(True)
        left_layout.addWidget(self._search)

        self._match_label = QLabel("")
        self._match_label.setObjectName("MutedLabel")
        left_layout.addWidget(self._match_label)

        self._index_list = QListWidget()
        self._index_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._index_list.setWordWrap(True)
        bold_font = QFont()
        bold_font.setBold(True)

        for level, display, aid in index_entries:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, aid)
            if level == 2:
                item.setText(display)
                item.setFont(bold_font)
            else:
                item.setText(f"  {display}")
            self._index_list.addItem(item)

        left_layout.addWidget(self._index_list, stretch=1)
        splitter.addWidget(left)

        # ── Right panel: law text ──────────────────────────────
        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(False)
        self._browser.setHtml(html)
        splitter.addWidget(self._browser)

        splitter.setSizes([230, 700])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

        self._all_matches: list[int] = []   # selectionStart of each match
        self._current_idx: int = 0

        # ── Shortcuts ──────────────────────────────────────────
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self._focus_search)
        QShortcut(QKeySequence("Shift+Return"), self._search, activated=self._find_prev)

        # ── Connections ────────────────────────────────────────
        self._index_list.itemClicked.connect(self._on_index_clicked)
        self._search.returnPressed.connect(self._find_next)
        self._search.textChanged.connect(self._on_search_changed)

    # ── Slots ──────────────────────────────────────────────────

    def _focus_search(self) -> None:
        self._search.setFocus()
        self._search.selectAll()

    def _on_index_clicked(self, item: QListWidgetItem) -> None:
        aid = item.data(Qt.UserRole)
        if aid:
            self._browser.scrollToAnchor(aid)

    # ── Search helpers ─────────────────────────────────────────
    # All highlighting goes through ExtraSelections so it is always
    # visible regardless of which widget has keyboard focus.
    # QTextBrowser.find() is NOT used — its native selection rendering
    # goes invisible (grey) when the browser doesn't have focus.

    _FMT_ALL = QTextCharFormat()
    _FMT_ALL.setBackground(QColor("#FF9999"))   # light red — other matches
    _FMT_ALL.setForeground(QColor("#000000"))

    _FMT_CUR = QTextCharFormat()
    _FMT_CUR.setBackground(QColor("#CC0000"))   # dark red — current match
    _FMT_CUR.setForeground(QColor("#FFFFFF"))

    def _collect_matches(self, text: str) -> list[int]:
        """Return selectionStart position of every occurrence of text."""
        doc = self._browser.document()
        positions: list[int] = []
        cur = doc.find(text)
        while not cur.isNull():
            positions.append(cur.selectionStart())
            cur = doc.find(text, cur)
        return positions

    def _repaint(self, text: str) -> None:
        """Rebuild ExtraSelections and update the N/total label."""
        if not text or not self._all_matches:
            self._browser.setExtraSelections([])
            lbl = self.tr("Not found") if text else ""
            self._match_label.setText(lbl)
            return

        doc = self._browser.document()
        n = len(text)
        selections: list[QTextEdit.ExtraSelection] = []
        for i, pos in enumerate(self._all_matches):
            cur = doc.find(text, pos)
            if cur.isNull():
                continue
            sel = QTextEdit.ExtraSelection()
            sel.cursor = cur
            sel.format = self._FMT_CUR if i == self._current_idx else self._FMT_ALL
            selections.append(sel)
        self._browser.setExtraSelections(selections)
        self._match_label.setText(
            f"{self._current_idx + 1}/{len(self._all_matches)}"
        )

    def _scroll_to_current(self) -> None:
        """Scroll browser to show the current match without using find()."""
        if not self._all_matches:
            return
        pos = self._all_matches[self._current_idx]
        cur = self._browser.textCursor()
        cur.setPosition(pos)
        self._browser.setTextCursor(cur)
        self._browser.ensureCursorVisible()

    def _on_search_changed(self, text: str) -> None:
        if not text:
            self._all_matches = []
            self._current_idx = 0
            self._browser.setExtraSelections([])
            self._match_label.setText("")
            return
        self._all_matches = self._collect_matches(text)
        self._current_idx = 0
        self._scroll_to_current()
        self._repaint(text)

    def _find_next(self) -> None:
        text = self._search.text()
        if not text or not self._all_matches:
            return
        self._current_idx = (self._current_idx + 1) % len(self._all_matches)
        self._scroll_to_current()
        self._repaint(text)

    def _find_prev(self) -> None:
        text = self._search.text()
        if not text or not self._all_matches:
            return
        self._current_idx = (self._current_idx - 1) % len(self._all_matches)
        self._scroll_to_current()
        self._repaint(text)


# ── Top-level page ─────────────────────────────────────────────────────────────

class ZakoniPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.addTab(
            _LawTab(_RESOURCES / "zakon o izboru predsednika republike.md"),
            self.tr("President"),
        )
        self._tabs.addTab(
            _LawTab(_RESOURCES / "zakon o izboru narodnih poslanika.md"),
            self.tr("Parliament"),
        )
        self._tabs.addTab(
            _LawTab(_RESOURCES / "zakon o lokalnim izborima.md"),
            self.tr("Local"),
        )

        layout.addWidget(self._tabs)
