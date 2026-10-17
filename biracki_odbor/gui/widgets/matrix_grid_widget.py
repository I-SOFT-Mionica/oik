"""In-app editable БМ × функција Raspodela grid (TODO.md §20).

Embedded (not a popup) in the Шаблон за расподелу section's open body —
eliminates the Excel round-trip's whole class of header-parsing bugs
(RIK's party-quota preamble pushing the header down, header-wording
variants like "БМ #") by having the operator fill the grid directly:
rows come from OIK Settings' configured polling stations, columns are
always the fixed 6 `core.models.FUNCTIONS`, and cells are dropdown-
constrained to declared party short names — no free text, no header to
misparse, no nacelnik/`_default` offered as a slot.

Also enforces RIK-declared seat quotas (`PartyQuota`) as a hard limit:
a party cannot be assigned past its declared Председник/Заменик/
Чл.+Зам.чл. count.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QHeaderView, QMessageBox, QTableWidget, QVBoxLayout, QWidget,
)

from biracki_odbor.core.models import FUNCTIONS, Allocation, PartyQuota, PollingStation

_UNASSIGNED = "—"
_STALE_TOOLTIP = "Ова вредност није на листи посланичких група."

# One combined bucket for the 4 "member" roles — RIK's own quota table
# doesn't split Члан 1 from Члан 2, only Председник/Заменик get their
# own column (see PartyQuota docstring in core/models.py).
_FUNCTION_TO_BUCKET = {
    "Председник": "predsednik",
    "Заменик председника": "zamenik",
    "Члан 1": "clan_i_zamenik",
    "Заменик члана 1": "clan_i_zamenik",
    "Члан 2": "clan_i_zamenik",
    "Заменик члана 2": "clan_i_zamenik",
}

# Single-line display labels for the grid's column headers — QHeaderView
# doesn't support multi-line text, so long FUNCTIONS strings are shown
# abbreviated here (same "Зам."/"Чл." convention as the quota table).
# FUNCTIONS itself stays exact for Excel round-tripping.
_HEADER_LABELS = {
    "Председник": "Председник",
    "Заменик председника": "Зам. председника",
    "Члан 1": "Члан 1",
    "Заменик члана 1": "Зам. члана 1",
    "Члан 2": "Члан 2",
    "Заменик члана 2": "Зам. члана 2",
}

_BUCKET_LABELS = {
    "predsednik": "Председник",
    "zamenik": "Заменик",
    "clan_i_zamenik": "Чл. + Зам. чл.",
}


class _NoWheelComboBox(QComboBox):
    """A mouse-wheel scroll over a focused/hovered combo box normally
    changes its selection — in a scrollable grid that silently swaps a
    party assignment just because the operator scrolled the page past
    it, introducing false data without any deliberate click. Ignore
    wheel events entirely; only an explicit dropdown pick should change
    a cell's value.
    """

    def wheelEvent(self, event) -> None:  # noqa: N802
        event.ignore()


class MatrixGridWidget(QWidget):
    def __init__(
        self,
        stations: list[PollingStation],
        party_abbrevs: list[str],
        existing: list[Allocation],
        quotas: dict[str, PartyQuota] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)

        self._stations = sorted(stations, key=lambda s: s.bm_number)
        self._quotas = quotas or {}
        declared = [_UNASSIGNED] + sorted(party_abbrevs)
        existing_lookup = {(a.bm_number, a.function): a.party for a in existing}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.table = QTableWidget(len(self._stations), len(FUNCTIONS))
        # QHeaderView does not do multi-line text layout — embedded "\n"
        # characters draw overlapping on the same baseline instead of
        # stacking, which is illegible (each column showed only its LAST
        # word). Use single-line official abbreviations instead — same
        # ones already used in the seat-quota table ("Зам." / "Чл.").
        # FUNCTIONS itself (the legally exact strings used for Excel
        # headers) stays untouched; this is a display-only relabeling.
        self.table.setHorizontalHeaderLabels([_HEADER_LABELS[f] for f in FUNCTIONS])
        self.table.setVerticalHeaderLabels([f"БМ {s.bm_number}" for s in self._stations])
        header = self.table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        # Fixed, not Interactive — a draggable column here could be
        # stretched wide enough to push other БМ columns out of the
        # visible box, same class of bug as the quota table.
        header.setSectionResizeMode(QHeaderView.Fixed)
        header.setDefaultSectionSize(150)
        # Default row height leaves QComboBox's 8px top+bottom QSS padding
        # no room to breathe — text was rendering clipped/invisible.
        self.table.verticalHeader().setDefaultSectionSize(40)
        for row, station in enumerate(self._stations):
            header_item = self.table.verticalHeaderItem(row)
            if header_item is not None and station.name:
                header_item.setToolTip(station.name)

        self._combos: dict[tuple[int, str], QComboBox] = {}
        for row, station in enumerate(self._stations):
            for col, func in enumerate(FUNCTIONS):
                combo = _NoWheelComboBox()
                combo.setEditable(False)
                combo.setMinimumWidth(130)
                items = list(declared)
                value = existing_lookup.get((station.bm_number, func), "")
                stale = bool(value) and value not in items
                if stale:
                    items.append(value)
                combo.addItems(items)
                initial = value if value else _UNASSIGNED
                combo.setCurrentText(initial)
                combo._last_value = initial  # type: ignore[attr-defined]
                if stale:
                    combo.setStyleSheet("QComboBox { color: #9B0000; }")
                    combo.setToolTip(_STALE_TOOLTIP)
                    combo.currentIndexChanged.connect(
                        lambda _idx, c=combo: (c.setStyleSheet(""), c.setToolTip(""))
                    )
                # `activated` fires only on genuine user interaction — never
                # on the programmatic setCurrentText above — so prefilling
                # existing data is never subject to the quota check below.
                combo.activated.connect(
                    lambda _idx, c=combo, bm=station.bm_number, fn=func: self._on_activated(c, bm, fn)
                )
                self.table.setCellWidget(row, col, combo)
                self._combos[(station.bm_number, func)] = combo

        layout.addWidget(self.table)

    # ── Quota hard-limit enforcement ────────────────────────────────

    def _on_activated(self, combo: QComboBox, bm_number: int, function: str) -> None:
        new_value = combo.currentText()
        last_value = getattr(combo, "_last_value", _UNASSIGNED)
        if new_value == last_value:
            return
        if new_value == _UNASSIGNED:
            combo._last_value = new_value  # type: ignore[attr-defined]
            return

        quota = self._quotas.get(new_value)
        if quota is not None:
            bucket = _FUNCTION_TO_BUCKET[function]
            limit = getattr(quota, bucket)
            used = sum(
                1
                for (bm, fn), c in self._combos.items()
                if (bm, fn) != (bm_number, function)
                and _FUNCTION_TO_BUCKET[fn] == bucket
                and c.currentText() == new_value
            )
            if used >= limit:
                combo.blockSignals(True)
                combo.setCurrentText(last_value)
                combo.blockSignals(False)
                QMessageBox.warning(
                    self, "Квота достигнута",
                    f"{new_value} већ достигла квоту за {_BUCKET_LABELS[bucket]}"
                    f" ({used}/{limit}).",
                )
                return

        combo._last_value = new_value  # type: ignore[attr-defined]

    # ── Result extraction ────────────────────────────────────────────

    def result_allocations(self) -> list[Allocation]:
        out: list[Allocation] = []
        for (bm_number, function), combo in self._combos.items():
            value = combo.currentText()
            if value and value != _UNASSIGNED:
                out.append(Allocation(bm_number=bm_number, function=function, party=value))
        return out
