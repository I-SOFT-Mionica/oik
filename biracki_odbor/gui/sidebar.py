"""Left sidebar — V1 layout per OIK Refactor design.

Structure (per `OIK Refactor.html` and chat1.md final agreement):

  ┌────────────────────┐
  │     [LOGO]         │  96 px logo zone, bottom-bordered
  ├────────────────────┤
  │ Изборна конф.      │  TOP block
  │ Стални састав      │
  │ Проширени састав   │  disabled, "(V2)" hint + tooltip
  │ Посматрачи          │  disabled, "(V2)" hint + tooltip
  │   (stretch)        │
  ├────────────────────┤
  │ Поставке ОИК       │  BOTTOM block — muted styling
  ├────────────────────┤
  │ О апликацији       │  Footer link
  └────────────────────┘

Why split Поставке: in v0.5.1 the sidebar had a single "Поставке"
section whose body was a QTabWidget with Изборна+ОИК as inner tabs.
The V1 design promotes Изборна конфигурација to its own top-level
item (it's used every election cycle, not "rarely") and pins
Поставке ОИК to the bottom block (genuinely one-time setup). One
tab strip removed, two clicks → one click.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QLabel, QSizePolicy, QToolButton, QVBoxLayout,
    QWidget,
)


_SIDEBAR_WIDTH = 220        # V1 spec § 4.1 — fits "Проширени састав" on one line
# Logo zone shrunk from V1's 96 px so its bottom edge aligns with the
# bottom of the workspace's inner-tab strip (a QTabBar at 12 pt is
# roughly 48 px tall; 56 px gives the icon a touch of breathing room
# and lands close to the tab-strip baseline).
_LOGO_ZONE_HEIGHT = 56
_LOGO_SIZE = 36
# Bottom-block items get a taller minimum so the bottom-most one (О
# апликацији) aligns its top edge with the StickyDock's top edge in
# the workspace — both 72 px tall, both pinned to the same y at the
# bottom of the central widget.
_BOTTOM_ITEM_MIN_HEIGHT = 72

# Horizontal space the label has inside a sidebar item, after subtracting
# the 4 px active-state border, the 12 px left + 16 px right padding from
# the QSS, and an 8 px safety margin so the wrap isn't pixel-tight.
_LABEL_AVAIL_PX = _SIDEBAR_WIDTH - 4 - 12 - 16 - 8


def _wrap_to_width(text: str, fm: QFontMetrics) -> str:
    """Insert a newline at the last whitespace that lets the label fit.

    QToolButton doesn't word-wrap automatically — passing a long
    label produces an elided "Изборна …гурација" instead of two
    visible lines. We measure with the button's own font metrics so
    the wrap point follows the actual rendered width, not a guess.
    Falls back to the original string if it already fits or if there's
    no whitespace to break on.
    """
    if fm.horizontalAdvance(text) <= _LABEL_AVAIL_PX:
        return text
    parts = text.split()
    if len(parts) < 2:
        return text
    # Find the longest prefix that still fits, then put the rest on a
    # second line. Handles 2-3 word labels — the only kind we have.
    for i in range(len(parts) - 1, 0, -1):
        head = " ".join(parts[:i])
        tail = " ".join(parts[i:])
        if fm.horizontalAdvance(head) <= _LABEL_AVAIL_PX:
            return f"{head}\n{tail}"
    return text


# Section indices — referenced by main_window.py for the stack widget.
# Order matches the V1 sidebar from top to bottom.
SECTION_IZBORNA = 0
SECTION_STALNI = 1
SECTION_PROSIRENI = 2
SECTION_POSMATRACI = 3
SECTION_OIK = 4
SECTION_ABOUT = 5
SECTION_ZAKONI = 6
SECTION_ALATI = 7




class Sidebar(QWidget):
    section_changed = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(_SIDEBAR_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Shared exclusive group so only one item ever looks "active",
        # regardless of which block it lives in.
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._items: dict[int, QToolButton] = {}

        # ── Logo zone (V1 § 4.2) ────────────────────────────
        layout.addWidget(self._build_logo_zone())

        # ── Top block: per-election workflows + V2 placeholders ──
        # Section labels stay left-aligned via the QToolButton's
        # ToolButtonTextOnly style + QSS text-align: left. The active
        # item renders "inset" — its background flips to the workspace
        # white so it visually merges with the workspace pane to its
        # right, anchored by a 4 px accent left border. That alone is
        # enough to distinguish the active item from inactive items
        # sitting on the secondary-bg sidebar surface.
        self._add_section(layout, SECTION_IZBORNA, self.tr("Elections"))
        layout.addWidget(self._build_separator())
        self._add_section(layout, SECTION_STALNI, self.tr("Regular composition"))
        layout.addWidget(self._build_separator())
        self._add_section(layout, SECTION_PROSIRENI, self.tr("Extended composition"))
        layout.addWidget(self._build_separator())
        self._add_section(
            layout, SECTION_POSMATRACI, self.tr("Observers"),
            disabled=True,
            tooltip=self.tr("Planned for V2 — observer registration and accreditation."),
        )
        layout.addWidget(self._build_separator())

        # Stretch pushes the bottom block to the actual bottom of the
        # column even on tall monitors.
        layout.addStretch(1)

        # ── Bottom block: Алати / Закони / Поставке ОИК ────
        layout.addWidget(self._build_separator())
        self._add_section(layout, SECTION_ALATI, self.tr("Tools"), muted=True)
        layout.addWidget(self._build_separator())
        self._add_section(layout, SECTION_ZAKONI, self.tr("Laws"), muted=True)
        layout.addWidget(self._build_separator())
        self._add_section(layout, SECTION_OIK, self.tr("OIK Settings"), muted=True)

        # ── Footer link ────────────────────────────────────
        layout.addWidget(self._build_separator())
        self._add_section(
            layout, SECTION_ABOUT, self.tr("About"), muted=True,
        )
        # Pin the bottom-most item's height so its top edge lines up
        # with the StickyDock's top edge in the workspace. Without this
        # the action bar starts higher than the sidebar's footer link,
        # breaking the bottom-row horizontal alignment the V1 spec
        # cares about.
        self._items[SECTION_ABOUT].setMinimumHeight(_BOTTOM_ITEM_MIN_HEIGHT)

        # Open on Стални састав — the typical entry point during an
        # active election cycle. Изборна конфигурација is touched once
        # per cycle; ОИК even more rarely.
        self._items[SECTION_STALNI].setChecked(True)

    # ── Builders ───────────────────────────────────────────

    def _build_logo_zone(self) -> QWidget:
        """96 px logo strip at the top of the sidebar.

        Bottom-bordered (via QSS on #SidebarLogoZone) so it separates
        from the menu items the same way the V1 design does. Falls back
        to no-image if neither icon.svg nor icon.ico is bundled — the
        zone keeps its height so the spacing below stays correct.
        """
        zone = QFrame()
        zone.setObjectName("SidebarLogoZone")
        zone.setFixedHeight(_LOGO_ZONE_HEIGHT)
        box = QVBoxLayout(zone)
        box.setContentsMargins(12, 16, 12, 16)
        box.setAlignment(Qt.AlignCenter)
        logo = QLabel()
        logo.setAlignment(Qt.AlignCenter)
        # Prefer SVG (sharper at any DPI), fall back to ICO.
        resources = Path(__file__).resolve().parent.parent / "resources"
        for candidate in ("icon.svg", "icon.ico"):
            p = resources / candidate
            if p.exists():
                pm = QPixmap(str(p))
                if not pm.isNull():
                    logo.setPixmap(pm.scaled(
                        QSize(_LOGO_SIZE, _LOGO_SIZE),
                        Qt.KeepAspectRatio, Qt.SmoothTransformation,
                    ))
                    break
        box.addWidget(logo)
        return zone

    def _build_separator(self) -> QFrame:
        sep = QFrame()
        sep.setObjectName("SidebarSeparator")
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Plain)
        sep.setFixedHeight(1)
        return sep

    def _add_section(
        self,
        layout: QVBoxLayout,
        index: int,
        label: str,
        *,
        disabled: bool = False,
        muted: bool = False,
        hint: str = "",
        tooltip: str = "",
    ) -> None:
        """Add a sidebar item button.

        `disabled` greys out + makes unclickable; `muted` is the
        secondary style used for Поставке ОИК + О апликацији in the
        bottom block (smaller font, secondary text colour). `hint`
        appears appended to the label (e.g. "(V2)"); `tooltip`
        surfaces on hover, primarily to explain disabled state.
        """
        btn = QToolButton()
        btn.setObjectName("SidebarItem")
        btn.setCheckable(True)
        # QToolButton renders a single line by default — long Cyrillic
        # labels like "Изборна конфигурација" otherwise truncate to
        # "Изборна ...гурација" at 220 px. Pre-wrap on the last
        # whitespace when the text wouldn't fit so the label always
        # renders fully. The button gets a Preferred vertical policy so
        # the layout grants it enough height for the second line.
        raw = f"{label}  {hint}" if hint else label
        btn.setText(_wrap_to_width(raw, btn.fontMetrics()))
        btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        btn.setToolTip(tooltip or label)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        if disabled:
            btn.setEnabled(False)
            btn.setCursor(Qt.ForbiddenCursor)
        if muted:
            # Property targeted by QSS to apply the secondary style.
            btn.setProperty("muted", True)
        btn.clicked.connect(lambda _=False, i=index: self.section_changed.emit(i))
        self._group.addButton(btn, index)
        layout.addWidget(btn)
        self._items[index] = btn

    # ── Public API ─────────────────────────────────────────

    def set_section(self, index: int) -> None:
        """Programmatically select a section. Also emits section_changed."""
        if index in self._items:
            self._items[index].setChecked(True)
            self.section_changed.emit(index)

    def set_workflow_enabled(
        self,
        enabled: bool,
        local_elections: bool = False,
    ) -> None:
        """Enable or disable workflow sidebar sections.

        `enabled` gates all workflow sections (onboarding complete).
        `local_elections` additionally gates Посматрачи.

        Проширени is deliberately gated on onboarding alone, exactly like
        Стални. It used to additionally require a registered candidacy
        list, which left the operator facing a dead button with only a
        tooltip to explain it — and проширени is genuinely independent of
        стални and of the РИК матрица, so there is no reason it cannot be
        opened and set up before the lists are certified. The "no lists
        yet" notice now lives inside the прошире­ни workspace, and the
        phases themselves still refuse to run (see
        ProsireniPhase1Tab._preflight_check).
        """
        tooltip_off = self.tr(
            "Complete setup first — fill in and save Election Configuration and OIK Settings."
        )
        tooltip_no_local = self.tr("Observers are accredited only for local elections.")

        # Стални and Проширени — both gated only on onboarding
        for section in (SECTION_STALNI, SECTION_PROSIRENI):
            btn = self._items[section]
            btn.setEnabled(enabled)
            btn.setCursor(Qt.ArrowCursor if enabled else Qt.ForbiddenCursor)
            btn.setToolTip("" if enabled else tooltip_off)

        # Посматрачи — additionally requires local elections
        posmatraci_on = enabled and local_elections
        pbtn = self._items[SECTION_POSMATRACI]
        pbtn.setEnabled(posmatraci_on)
        pbtn.setCursor(Qt.ArrowCursor if posmatraci_on else Qt.ForbiddenCursor)
        if posmatraci_on:
            pbtn.setToolTip("")
        elif not enabled:
            pbtn.setToolTip(tooltip_off)
        else:
            pbtn.setToolTip(tooltip_no_local)
