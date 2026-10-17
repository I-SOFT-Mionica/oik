"""Visual baseline for the GUI — OIK V1 Theming.

Tokens, typography, and global QSS align with the design document
[OIK V1 Theming Guide.md](../../OIK%20V1%20Theming%20Guide.md). The
guide is normative for visual rules; sections + functionality are
defined by main_window + the tab modules and are intentionally NOT
restructured here.

Audience: 60+ Serbian lawyers/bureaucrats. Priorities:
  - Readable at default zoom (14 pt body, 18 pt headings).
  - Ample padding so misclicks are rare.
  - Single accent color (deep blue, matches Office defaults).
  - Red reserved exclusively for validation + destructive — never decoration.
  - No flashy animations, no decorative gradients.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication


# ── Colors (OIK V1 § 1.1) ──────────────────────────────────────────────

# Primary / brand
ACCENT = "#2F5496"            # primary
ACCENT_HOVER = "#3A66B0"      # primary hover
ACCENT_PRESSED = "#264478"    # primary pressed
ACCENT_SOFT = "#E8EEF8"       # primary-soft — selected row, active-tab subtle bg

# Surfaces
SURFACE = "#FFFFFF"           # workspace
SURFACE_ALT = "#F5F6FA"       # secondary-bg — sidebar, footer, table alt header
WINDOW_CHROME = "#EDEFF4"     # title/status bar fill

# Borders
BORDER = "#C8CFE0"            # primary borders
BORDER_SOFT = "#E2E6EF"       # row dividers, card internal dividers

# Text tiers
TEXT_PRIMARY = "#1F2A44"      # body, input values
TEXT_SECONDARY = "#4A5468"    # form labels, helper text
TEXT_MUTED = "#8A92A6"        # hints, placeholders, metadata
TEXT_DISABLED = "#B0B6C5"     # disabled sidebar items, disabled inputs

# Status / validation
ERROR_BG = "#FFE3E3"
ERROR_TEXT = "#9B0000"
ERROR_BORDER = "#F0B0B0"
WARN_BG = "#FFF3D6"
WARN_TEXT = "#8A5A00"
WARN_BORDER = "#E0CB7A"
OK_BG = "#E4F5E6"
OK_TEXT = "#1F6F2F"
OK_BORDER = "#B6D9BD"
INFO_BG = ACCENT_SOFT
INFO_TEXT = ACCENT
INFO_BORDER = "#BFD0EE"

# Serbian flag red — used exclusively for high-impact / destructive /
# irreversible actions (e.g. "Нови изборни циклус"). Never decorative.
SERBIAN_RED = "#C6363C"
SERBIAN_RED_HOVER = "#A82D32"
SERBIAN_RED_PRESSED = "#8C2429"

# Scroll
SCROLL_HANDLE = "#A0AABF"
SCROLL_HANDLE_HOVER = "#8893AB"


# ── Type scale (Qt font sizes in points) (OIK V1 § 1.2) ────────────────

BODY_PT = 14        # body / inputs / sidebar items
SUBHEAD_PT = 15     # card titles / section labels
HEAD_PT = 18        # view headings (H1)
TITLE_PT = 18       # alias for H1 callers; keeps legacy name working
TAB_PT = 12         # tab labels / table headers
SMALL_PT = 11       # hint / helper / status bar / paths


# ── Spacing tokens (pixels) (OIK V1 § 1.3) ─────────────────────────────

GAP_TIGHT = 8
GAP = 14            # form row vertical gap
GAP_LARGE = 18      # section vertical gap, card inner padding
PAD = 16


# ── Workspace padding (V1 § 1.3) ───────────────────────────────────────

WORKSPACE_PAD_TOP = 24
WORKSPACE_PAD_SIDE = 32


def apply_global_style(app: QApplication) -> None:
    """Install the baseline font, Qt stylesheet, and window icon on the app."""
    font = QFont("Segoe UI", BODY_PT)
    app.setFont(font)
    app.setStyleSheet(_QSS)

    # Window icon for taskbar / title bar while the app is running. Works in
    # both dev mode and PyInstaller bundle — biracki_odbor/resources/ is
    # alongside this module in both layouts.
    icon_path = Path(__file__).resolve().parent.parent / "resources" / "icon.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))


# ── Global QSS (OIK V1 § 2) ────────────────────────────────────────────
#
# This stylesheet is the source of truth for the V1 visual baseline. The
# guide says: "Every measurement, color, and rule below is normative —
# if a screen disagrees with this document, fix the screen." So we keep
# this file aligned to the guide; per-widget tweaks live elsewhere or
# as objectName-targeted overrides below.

_ARROW_SVG = str(
    (Path(__file__).resolve().parent.parent / "resources" / "arrow_down.svg")
).replace("\\", "/")

_QSS = f"""
/* ===== Application base ===== */
QWidget {{
    background-color: {SURFACE};
    color: {TEXT_PRIMARY};
}}

/* ===== Typography helpers ===== */
QLabel#TitleLabel {{
    font-size: {HEAD_PT}pt;
    font-weight: 600;
    color: {ACCENT};
}}
QLabel#HeadLabel {{
    font-size: {SUBHEAD_PT}pt;
    font-weight: 600;
}}
QLabel#SubHeadLabel {{
    font-size: {SUBHEAD_PT}pt;
    color: {TEXT_SECONDARY};
}}
QLabel#MutedLabel {{
    color: {TEXT_MUTED};
    font-size: {SMALL_PT}pt;
}}
QLabel#ErrorLabel {{
    color: {ERROR_TEXT};
    font-weight: 600;
}}
QLabel#WarnLabel {{
    color: {WARN_TEXT};
}}
QLabel#OkLabel {{
    color: {OK_TEXT};
    font-weight: 600;
}}

/* ===== Scrollbars — THICK (20 px) per V1 § 2 ===== */
QScrollBar:vertical {{
    background: {SURFACE_ALT};
    width: 20px;
    margin: 0;
    border: none;
}}
QScrollBar::handle:vertical {{
    background: {SCROLL_HANDLE};
    min-height: 40px;
    border: 4px solid {SURFACE_ALT};
    border-radius: 10px;
}}
QScrollBar::handle:vertical:hover {{
    background: {SCROLL_HANDLE_HOVER};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
    background: none;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none;
}}
QScrollBar:horizontal {{
    background: {SURFACE_ALT};
    height: 20px;
    margin: 0;
    border: none;
}}
QScrollBar::handle:horizontal {{
    background: {SCROLL_HANDLE};
    min-width: 40px;
    border: 4px solid {SURFACE_ALT};
    border-radius: 10px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {SCROLL_HANDLE_HOVER};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
    background: none;
}}

/* ===== Tabs — underline-only active style (V1 § 5) ===== */
/* Pane has a 1 px #A0AABF top divider as a permanent separator
   between the tab strip and the workspace. The active tab's 3 px
   accent bottom-border still paints over that line — the accent
   pops above the neutral separator without it being suppressed. */
QTabWidget::pane {{
    border: none;
    border-top: 1px solid {SCROLL_HANDLE};
    background: {SURFACE};
}}
QTabBar {{
    background: {SURFACE};
}}
/* Tab labels at {BODY_PT}pt to match the sidebar items — visual
   consistency between the two navigation surfaces. Previously the tabs
   sat at TAB_PT (12 pt) while the sidebar was 14 pt; that mismatch
   read as one being "secondary" when both are top-level navigation. */
QTabBar::tab {{
    background: transparent;
    color: {TEXT_SECONDARY};
    padding: 10px 18px;
    font-size: {BODY_PT}pt;
    font-weight: 500;
    border: none;
    margin-right: 0;
    min-width: 0;
}}
QTabBar::tab:hover:!selected {{
    color: {TEXT_PRIMARY};
}}
QTabBar::tab:selected {{
    color: {ACCENT};
    font-weight: 600;
    border-bottom: 3px solid {ACCENT};
    /* Overlap the pane's top border so the active tab "joins" the pane. */
    margin-bottom: -1px;
}}
QTabBar::tab:disabled {{
    color: {TEXT_DISABLED};
}}

/* ===== Buttons (V1 § 2) ===== */
/* Default = secondary */
QPushButton {{
    background-color: {SURFACE};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 3px;
    padding: 10px 22px;
    font-size: {BODY_PT}pt;
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: {SURFACE_ALT};
}}
QPushButton:pressed {{
    background-color: {ACCENT_SOFT};
}}
QPushButton:disabled {{
    color: {TEXT_DISABLED};
    background-color: {SURFACE};
    border-color: {BORDER_SOFT};
}}

/* Primary — accent fill */
QPushButton#PrimaryButton {{
    background-color: {ACCENT};
    color: white;
    border: 1px solid {ACCENT};
    font-weight: 600;
}}
QPushButton#PrimaryButton:hover {{
    background-color: {ACCENT_HOVER};
    border-color: {ACCENT_HOVER};
}}
QPushButton#PrimaryButton:pressed {{
    background-color: {ACCENT_PRESSED};
    border-color: {ACCENT_PRESSED};
}}
QPushButton#PrimaryButton:disabled {{
    background-color: #A8B5D0;
    border-color: #A8B5D0;
    color: white;
}}

/* Destructive — bordered red, never filled */
QPushButton#DangerButton {{
    background-color: {SURFACE};
    color: {ERROR_TEXT};
    border: 1px solid {ERROR_TEXT};
}}
QPushButton#DangerButton:hover {{
    background-color: {ERROR_BG};
}}

/* DestructiveButton — Serbian-flag red fill. Use ONLY for high-impact,
   irreversible actions (e.g. "Нови изборни циклус"). Never decorative. */
QPushButton#DestructiveButton {{
    background-color: {SERBIAN_RED};
    color: white;
    border: 1px solid {SERBIAN_RED};
    font-weight: 600;
}}
QPushButton#DestructiveButton:hover {{
    background-color: {SERBIAN_RED_HOVER};
    border-color: {SERBIAN_RED_HOVER};
}}
QPushButton#DestructiveButton:pressed {{
    background-color: {SERBIAN_RED_PRESSED};
    border-color: {SERBIAN_RED_PRESSED};
}}
QPushButton#DestructiveButton:disabled {{
    background-color: #D89093;
    border-color: #D89093;
    color: white;
}}

/* ===== Inputs (V1 § 2) ===== */
/* QAbstractSpinBox catches QSpinBox, QDoubleSpinBox, QDateEdit,
   QTimeEdit, and QDateTimeEdit in one selector — they're all spinbox
   subclasses and previously a `QSpinBox` selector missed the date /
   time variants, so date pickers fell back to Qt defaults. */
QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox, QComboBox {{
    background: {SURFACE};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 3px;
    padding: 8px 12px;
    font-size: {BODY_PT}pt;
    selection-background-color: {ACCENT_SOFT};
    selection-color: {TEXT_PRIMARY};
}}
/* Spin boxes take their horizontal inset from lineEdit().setTextMargins
   (widgets/spinbox.py inset_spinbox_text), not QSS padding: PySide6 6.12
   ignores this padding for the inner QLineEdit while 6.11 honours it, so
   QSS padding would render differently per version. */
QAbstractSpinBox {{
    padding: 8px 0px;
}}
/* Replaces setButtonSymbols(NoButtons), which collapses the edit field
   to 1 px in PySide6 6.12 -- see widgets/spinbox.py. */
QAbstractSpinBox[noButtons="true"]::up-button,
QAbstractSpinBox[noButtons="true"]::down-button {{
    width: 0px;
    border: none;
    image: none;
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QAbstractSpinBox:focus, QComboBox:focus {{
    border-color: {ACCENT};
}}
/* Validator-driven invalid border — set as a dynamic property by
   SingleLineEdit (and any other widget that wants to mark itself
   bad). Red-ish so it reads as "fix this" without being aggressive.
   Higher specificity than the focus rule above so a focused invalid
   field still reads as invalid. */
QLineEdit[invalid="true"], QPlainTextEdit[invalid="true"] {{
    border: 1px solid #c0392b;
}}
QLineEdit[invalid="true"]:focus, QPlainTextEdit[invalid="true"]:focus {{
    border: 1px solid #c0392b;
}}
QLineEdit:read-only, QPlainTextEdit:read-only, QTextEdit:read-only {{
    background: {SURFACE_ALT};
    color: {TEXT_SECONDARY};
}}
QLineEdit:disabled, QPlainTextEdit:disabled, QTextEdit:disabled,
QAbstractSpinBox:disabled, QComboBox:disabled {{
    color: {TEXT_DISABLED};
    background: {SURFACE_ALT};
}}
QComboBox::drop-down {{
    width: 26px;
    border-left: 1px solid {BORDER};
    background: {SURFACE_ALT};
    border-radius: 0 3px 3px 0;
}}
QComboBox::down-arrow {{
    image: url({_ARROW_SVG});
    width: 10px;
    height: 6px;
}}
/* QDateEdit's calendar-popup button is a QDateTimeEdit::drop-down
   sub-control (QDateEdit IS-A QDateTimeEdit) -- without an explicit
   rule here it renders invisible once the base QAbstractSpinBox rule
   above applies a custom border/padding (switches Qt to the "styled"
   rendering path, which drops native sub-controls that aren't
   explicitly styled). Without this, setCalendarPopup(True) still
   works on click, but the field LOOKS like a plain text box with no
   calendar affordance at all. Same chevron as QComboBox for a
   consistent "this opens a picker" visual language. */
QDateTimeEdit::drop-down {{
    width: 26px;
    border-left: 1px solid {BORDER};
    background: {SURFACE_ALT};
    border-radius: 0 3px 3px 0;
}}
QDateTimeEdit::down-arrow {{
    image: url({_ARROW_SVG});
    width: 10px;
    height: 6px;
}}

/* Plain bordered list at body size (setup wizard's polling stations).
   Without a rule a QListWidget renders borderless, white on white, in
   Qt's small default item font. */
QListWidget#BorderedList {{
    border: 1px solid {BORDER};
    border-radius: 3px;
    background: {SURFACE};
    font-size: {BODY_PT}pt;
}}
QListWidget#BorderedList::item {{
    padding: 4px 8px;
}}

/* ===== Splitter handle (Phase3Tab/IzmenaPanel editing-pane/preview) =====
   Default Qt handle is a near-invisible 1-pixel seam -- easy to miss
   that the boundary is a live, draggable UI control rather than a
   static divider. A visible width + track color + hover/pressed
   feedback signals "grab me" the way the rest of this app's
   interactive elements already do. */
QSplitter::handle:horizontal {{
    width: 6px;
    background: {SURFACE_ALT};
    border-left: 1px solid {BORDER};
    border-right: 1px solid {BORDER};
}}
QSplitter::handle:horizontal:hover {{
    background: {ACCENT_SOFT};
    border-left: 1px solid {ACCENT};
    border-right: 1px solid {ACCENT};
}}
QSplitter::handle:horizontal:pressed {{
    background: {ACCENT_SOFT};
    border-left: 1px solid {ACCENT_PRESSED};
    border-right: 1px solid {ACCENT_PRESSED};
}}

/* ===== Calendar popup (QDateEdit drop-down) ===== */
/* Themed to match the V1 accent palette so the popup doesn't look
   like a stock Qt widget grafted onto the rest of the screen.
   QCalendarWidget's internals are partially QSS-targetable via
   well-known child object names (Qt convention). */
QCalendarWidget QWidget#qt_calendar_navigationbar {{
    background-color: {ACCENT};
}}
QCalendarWidget QToolButton {{
    color: white;
    background-color: transparent;
    font-size: {BODY_PT}pt;
    font-weight: 600;
    padding: 4px 12px;
    border: none;
    border-radius: 3px;
    margin: 4px;
}}
QCalendarWidget QToolButton:hover {{
    background-color: {ACCENT_HOVER};
}}
QCalendarWidget QToolButton:pressed {{
    background-color: {ACCENT_PRESSED};
}}
QCalendarWidget QToolButton::menu-indicator {{
    image: none;
}}
QCalendarWidget QSpinBox {{
    /* Year spinner inside the navbar — invert to fit on accent bg. */
    background: {ACCENT};
    color: white;
    border: 1px solid white;
    padding: 2px 6px;
    selection-background-color: white;
    selection-color: {ACCENT};
}}
QCalendarWidget QAbstractItemView {{
    background-color: {SURFACE};
    selection-background-color: {ACCENT};
    selection-color: white;
    font-size: {BODY_PT}pt;
    outline: 0;
}}
QCalendarWidget QAbstractItemView:disabled {{
    color: {TEXT_DISABLED};
}}
/* "Today" footer button injected by make_date_picker() — see
   widgets/date_picker.py. Styled like a primary action so it pops. */
QCalendarWidget QPushButton#CalendarTodayButton {{
    background-color: {SURFACE_ALT};
    color: {ACCENT};
    border: none;
    border-top: 1px solid {BORDER_SOFT};
    border-radius: 0;
    padding: 10px 14px;
    font-size: {BODY_PT}pt;
    font-weight: 600;
}}
QCalendarWidget QPushButton#CalendarTodayButton:hover {{
    background-color: {ACCENT_SOFT};
}}
QCalendarWidget QPushButton#CalendarTodayButton:pressed {{
    background-color: {BORDER_SOFT};
}}

/* ===== Tables ===== */
/* font-size uses TAB_PT so it follows the type scale and stays
   legible at every Windows display scaling level (100 / 125 / 150 %).
   px padding values are logical pixels — Qt scales them with DPI. */
QTableView, QTableWidget {{
    background: {SURFACE};
    alternate-background-color: {SURFACE};
    gridline-color: {BORDER_SOFT};
    border: 1px solid {BORDER};
    border-radius: 3px;
    font-size: {TAB_PT}pt;
    selection-background-color: {ACCENT_SOFT};
    selection-color: {TEXT_PRIMARY};
}}
/* Generous vertical padding; horizontal kept tight (6 px) so narrow
   columns like "Кратки назив" (≈95 px wide at 12 pt) are not
   clipped. At 125 % / 150 % scaling Qt adjusts logical → physical
   automatically, so explicit DPI branches are not needed here. */
QHeaderView::section {{
    background: {ACCENT};
    color: white;
    padding: 6px 6px;
    min-height: 2em;
    font-weight: 600;
    font-size: {TAB_PT}pt;
    border: none;
}}
/* Explicit cell padding prevents the default 2 px Qt value from
   looking cramped at larger display-scaling factors. */
QTableView::item, QTableWidget::item {{
    padding: 4px 8px;
}}
QTableView::item:selected, QTableWidget::item:selected {{
    background: {ACCENT_SOFT};
    color: {TEXT_PRIMARY};
}}
/* In-cell editor — without this override the table-cell QLineEdit
   inherits the base 8px/12px padding meant for standalone fields,
   which inside a ~26 px row pushes the text vertically out of view
   ("barely visible" — reported on the Странке + Бирачка места
   tables). Tight padding + accent border so the editing cell is
   visually distinct from the neighbours. */
QTableView QLineEdit, QTableWidget QLineEdit {{
    padding: 0px 4px;
    border: 1px solid {ACCENT};
    background: {SURFACE};
    color: {TEXT_PRIMARY};
    font-size: {TAB_PT}pt;
}}
/* Same class of bug, same fix, for QComboBox cell widgets (e.g. the
   matrix builder's per-BM party dropdowns): the base QComboBox rule's
   8px/12px padding is sized for standalone fields, and inside a short
   table row it pushes the current-item text out of the visible area —
   reads as "invisible" even though a value is genuinely selected. */
QTableView QComboBox, QTableWidget QComboBox {{
    padding: 0px 4px;
    background: {SURFACE};
    color: {TEXT_PRIMARY};
    font-size: {TAB_PT}pt;
}}
/* Same fix, for QSpinBox cell widgets (e.g. the seat-quota table's
   per-group numeric fields) — QAbstractSpinBox shares the same
   oversized standalone-field padding as QLineEdit/QComboBox above. */
QTableView QAbstractSpinBox, QTableWidget QAbstractSpinBox {{
    padding: 0px;
    background: {SURFACE};
    color: {TEXT_PRIMARY};
    font-size: {TAB_PT}pt;
}}
/* Same fix, for QPushButton cell widgets (e.g. Čelik's template-wizard
   per-field "place by click" button): the base QPushButton rule's
   10px/22px padding meant for standalone buttons leaves almost no
   room for the label inside a narrow table column, so it renders
   clipped/illegible ("no idea what's the text on that button"). */
QTableView QPushButton, QTableWidget QPushButton {{
    padding: 2px 4px;
    font-size: {TAB_PT}pt;
}}

/* ===== Cards (V1 § 2 + § 6.1) ===== */
/* Plain QFrame#Card — white surface, soft border. Pair with a child
   QLabel#CardTitle if you want the title-bar look. */
QFrame#Card {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 4px;
}}
QLabel#CardTitle {{
    background: {SURFACE};
    padding: 12px 18px 10px 18px;
    border-bottom: 1px solid {BORDER_SOFT};
    font-size: {SUBHEAD_PT}pt;
    font-weight: 600;
    color: {TEXT_PRIMARY};
}}
/* QGroupBox styled as a V1 card so existing tabs that already use
   QGroupBox pick up the new look without a structural refactor.
   Title sits in the box's top margin with enough breathing room to
   clear the box border underneath — previously margin-top was 28 px
   while the title rendered at ~32 px (15 pt text + 14 px padding),
   so the title text overlapped the card's top border on screen. */
QGroupBox {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 4px;
    margin-top: 40px;          /* > title height (~32 px) + a little air */
    padding: 14px 18px 18px 18px;
    font-size: {SUBHEAD_PT}pt;
    font-weight: 600;
    color: {TEXT_PRIMARY};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 8px 14px 12px 14px;
    color: {TEXT_PRIMARY};
    background: transparent;
}}

/* ===== CollapsibleSection (V1 § 8.4) =====
   Card bg (SURFACE) + a 1px BORDER on a globally-white page (QWidget's
   own default background is also SURFACE, see line ~126) gave almost no
   contrast — collapsed sections in particular (just a thin header row)
   were easy to miss entirely. Fix: 2px border + a tinted header so a
   collapsed section is still clearly visible as its own card. */
QFrame#CollapsibleCard {{
    background-color: {SURFACE};
    border: 2px solid {BORDER};
    border-radius: 4px;
}}
QFrame#CollapsibleCardHeader {{
    background-color: {SURFACE_ALT};
    border-radius: 4px;
}}
/* QWidget's own base rule (line ~126) paints every QLabel an opaque
   SURFACE (white) rectangle by default. That's invisible on a plain
   SURFACE page, but against this header's SURFACE_ALT tint each label
   (title, count badge, description) shows up as its own separate white
   patch — the "broken up boxes" look. Force them transparent so the
   header's tint reads as one continuous background. */
QFrame#CollapsibleCardHeader QLabel {{
    background: transparent;
}}
QLabel#CollapsibleTitle {{
    font-size: {SUBHEAD_PT}pt;
    font-weight: 600;
    color: {TEXT_PRIMARY};
}}
QLabel#CollapsibleDesc {{
    color: {TEXT_MUTED};
    font-size: {SMALL_PT}pt;
    /* Bold/larger title vs. regular/smaller subtitle, centered by full
       bounding box, leaves the subtitle's x-height sitting visibly above
       the title's cap-height baseline -- nudge it down to compensate. */
    padding-top: 3px;
}}
QLabel#CollapsibleCount {{
    /* Same color as the title (not the muted subtitle) so "(2)" reads
       as part of the title -- a row count -- rather than stray text
       glued onto the start of the subtitle sentence. */
    color: {TEXT_PRIMARY};
    font-size: {SUBHEAD_PT}pt;
}}
QFrame#CollapsibleSep {{
    color: {BORDER};
    background: {BORDER};
    max-height: 1px;
    border: none;
}}

/* ===== Drop zone (V1 § 8.3) ===== */
QFrame#DropZone {{
    border: 2px dashed {BORDER};
    border-radius: 4px;
    background-color: {SURFACE_ALT};
    padding: 24px;
}}
QFrame#DropZone[active="true"], QFrame#DropZone[hover="true"] {{
    border-color: {ACCENT};
    background-color: {ACCENT_SOFT};
}}

/* ===== Banners (V1 § 10) ===== */
QFrame#OkBanner {{
    background-color: {OK_BG};
    color: {OK_TEXT};
    border: 1px solid {OK_BORDER};
    border-radius: 4px;
}}
QFrame#OkBanner QLabel {{
    background: transparent;
    color: {OK_TEXT};
}}
QFrame#WarnBanner {{
    background-color: {WARN_BG};
    color: {WARN_TEXT};
    border: 1px solid {WARN_BORDER};
    border-radius: 4px;
}}
QFrame#WarnBanner QLabel {{
    background: transparent;
    color: {WARN_TEXT};
}}
QFrame#ErrorBanner {{
    background-color: {ERROR_BG};
    color: {ERROR_TEXT};
    border: 1px solid {ERROR_BORDER};
    border-radius: 4px;
}}
QFrame#ErrorBanner QLabel {{
    background: transparent;
    color: {ERROR_TEXT};
}}

/* ===== Sticky bottom dock (settings tabs) ===== */
QFrame#StickyDock {{
    background-color: {SURFACE_ALT};
    border-top: 1px solid {BORDER};
}}

/* ===== Progress bar ===== */
QProgressBar {{
    border: 1px solid {BORDER};
    border-radius: 3px;
    text-align: center;
    /* Both the empty and filled regions are dark blue (ACCENT_PRESSED /
       ACCENT) — QSS gives a progress bar's label one text color for its
       whole area, so a light background (readable against dark text
       only on the EMPTY side) made the label illegible wherever the
       chunk had already filled in. White reads cleanly against both. */
    background-color: {ACCENT_PRESSED};
    min-height: 22px;
    color: #FFFFFF;
    font-weight: 600;
}}
QProgressBar::chunk {{
    background-color: {ACCENT};
}}

/* ===== Status bar (V1 § 9) ===== */
QStatusBar {{
    background: {WINDOW_CHROME};
    color: {TEXT_SECONDARY};
    border-top: 1px solid {BORDER};
    font-size: {SMALL_PT}pt;
}}
QStatusBar QLabel {{
    background: transparent;
    color: {TEXT_SECONDARY};
}}

/* ===== Sidebar (V1 § 4) ===== */
/* No right border on the sidebar itself — the inactive items provide
   the divider via their own right edge, and the active item visually
   merges with the workspace pane because it doesn't draw that edge.
   That's the "inset" feeling: the active item appears to punch
   through to the white workspace on its right. */
QWidget#Sidebar {{
    background-color: {SURFACE_ALT};
    border-right: none;
}}
/* 96 px logo strip at the top of the sidebar — bottom border separates
   it from the first menu item so the title bar's chrome doesn't blur
   into the menu (V1 § 4.2). The right border continues the
   per-inactive-item edge so the logo zone visually aligns with the
   rest of the sidebar. */
QFrame#SidebarLogoZone {{
    background-color: {SURFACE_ALT};
    border: none;
    border-right: 1px solid {BORDER};
    border-bottom: 1px solid {BORDER};
}}
QFrame#SidebarLogoZone QLabel {{
    background: transparent;
}}
QFrame#SidebarSeparator {{
    background-color: {BORDER};
    border: none;
}}
QToolButton#SidebarItem {{
    text-align: left;
    padding: 14px 16px 14px 12px;
    /* Per-item right border gives the sidebar/workspace divider
       except where the active item carves through it. Same colour as
       the old sidebar border-right so the column looks identical when
       no item is active. */
    border: none;
    border-right: 1px solid {BORDER};
    border-left: 4px solid transparent;   /* reserves active-state space */
    border-radius: 0;
    background-color: transparent;
    color: {TEXT_PRIMARY};
    font-size: {BODY_PT}pt;
    font-weight: 500;
}}
QToolButton#SidebarItem:hover:!checked:enabled {{
    background-color: {SURFACE};
}}
QToolButton#SidebarItem:checked {{
    background-color: {SURFACE};
    color: {ACCENT};
    font-weight: 700;
    border-left: 4px solid {ACCENT};
    /* Drop the right border on the active item so its white bg flows
       seamlessly into the workspace — the "inset" effect. */
    border-right: none;
}}
QToolButton#SidebarItem:disabled {{
    color: {TEXT_DISABLED};
}}
/* Muted variant — Поставке ОИК + О апликацији in the bottom block.
   Smaller font + secondary text colour signals "rare / setup-only"
   per the V1 spec § 4.3. */
QToolButton#SidebarItem[muted="true"] {{
    color: {TEXT_SECONDARY};
    font-size: 13pt;
    padding: 12px 16px 12px 12px;
    font-weight: 500;
}}
QToolButton#SidebarItem[muted="true"]:checked {{
    color: {ACCENT};
    font-weight: 700;
}}
"""
