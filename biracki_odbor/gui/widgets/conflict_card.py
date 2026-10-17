"""Side-by-side card for resolving a duplicate-JMBG conflict.

Layout: header (JMBG + name) + a contextual subtitle + a row of
submission panels. Each submission panel carries its own two action
buttons (Keep this slot / Remove this slot) so the operator never has
to map a button at the bottom back to a card above it — important
when the same party submits the same JMBG twice (e.g. БМ 1 Председник
and БМ 3 Члан 1 both as СНС) and the per-party label alone is
ambiguous.

Signals carry `slot_key = (bm_number, function)` rather than party
name. Slot keys are globally unique within a master spreadsheet; party
names are not (same-party dupes share a name). See
`tests/test_corrections.py::test_resolve_conflict_same_party_keeps_by_slot`
for the regression this prevents.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QMessageBox,
    QPushButton, QVBoxLayout, QWidget,
)

from biracki_odbor.core.models import Conflict, Person


class ConflictCard(QFrame):
    # Each signal carries the conflict + the slot it targets + an
    # operator note. Slot keys are (bm_number, function) tuples — see
    # Person.slot_key.
    resolved = Signal(object, object, str)        # conflict, keep_slot_key, note
    slot_removed = Signal(object, object, str)    # conflict, slot_key, note
    removed_both = Signal(object, str)            # conflict, note

    def __init__(self, conflict: Conflict, parent=None) -> None:
        super().__init__(parent)
        self.conflict = conflict
        self.setObjectName("Card")

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        header = QLabel(f"ЈМБГ: {conflict.jmbg}   ·   Име: {conflict.name}")
        header.setObjectName("HeadLabel")
        root.addWidget(header)

        # Subtitle distinguishes cross-party from same-party-duplicate.
        # Same-party-duplicate is the "person listed twice in one
        # party's file" case — the v0.5.0 field report.
        unique_parties = {(s.party or "").strip() for s in conflict.submissions}
        n_subs = len(conflict.submissions)
        if len(unique_parties) <= 1:
            party_name = next(iter(unique_parties)) or "—"
            sub_text = (
                f"Иста особа се појављује {n_subs} пута у странци '{party_name}'."
                " Изаберите који слот задржати — остали постају празни."
            )
        else:
            sub_text = (
                f"Особа је пријављена од стране {len(unique_parties)} странака"
                f" ({n_subs} пријава)."
                " Изаберите коју пријаву задржати — остале постају празне."
            )
        sub = QLabel(sub_text)
        sub.setObjectName("MutedLabel")
        sub.setWordWrap(True)
        root.addWidget(sub)

        # Side-by-side panels, each carrying its own Keep + Remove buttons.
        cards_row = QHBoxLayout()
        cards_row.setSpacing(10)
        for sub_person in conflict.submissions:
            cards_row.addWidget(self._build_submission_panel(sub_person))
        root.addLayout(cards_row)

        # Cross-workflow matches (стални vs проширени): informational
        # only, no Keep/Remove -- resolving these means editing the
        # OTHER workflow's own data, which this tab has no business
        # doing. Shown as a visually distinct, labeled row underneath
        # rather than mixed into cards_row, so the "these are editable,
        # that one isn't" split reads immediately rather than only
        # being discoverable by noticing missing buttons.
        if conflict.cross_workflow:
            other_name = conflict.other_workflow_label or "другом саставу"
            cross_label = QLabel(
                f"Иста особа има попуњен слот и у: {other_name} "
                "(погледајте тамо да бисте то решили):"
            )
            cross_label.setObjectName("MutedLabel")
            cross_label.setWordWrap(True)
            root.addWidget(cross_label)
            cross_row = QHBoxLayout()
            cross_row.setSpacing(10)
            for cross_person in conflict.cross_workflow:
                cross_row.addWidget(
                    self._build_submission_panel(cross_person, editable=False)
                )
            root.addLayout(cross_row)

        # Global action (only one): nuke from all parties at once. Per-slot
        # remove lives inside each panel so it's clear which row dies.
        global_row = QHBoxLayout()
        global_row.addStretch()
        rm_all = QPushButton("Уклони из свих")
        rm_all.setObjectName("DangerButton")
        rm_all.setToolTip(
            "Брише ову особу из свих странака које су је пријавиле."
        )
        rm_all.clicked.connect(self._on_remove_both)
        global_row.addWidget(rm_all)
        root.addLayout(global_row)

    def _build_submission_panel(self, p: Person, *, editable: bool = True) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Card")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(10, 8, 10, 8)
        panel_layout.setSpacing(6)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(2)

        title = QLabel(f"Странка: {p.party or '—'}")
        title.setObjectName("HeadLabel")
        title.setAlignment(Qt.AlignCenter)
        grid.addWidget(title, 0, 0, 1, 2)

        fields = [
            ("БМ:", str(p.bm_number)),
            ("Функција:", p.function),
            ("Место:", p.mesto or "—"),
            ("Адреса:", p.adresa or "—"),
            ("Телефон:", p.telefon or "—"),
            ("Пријава примљена:", self._format_submission_time(p)),
        ]
        for i, (label, value) in enumerate(fields, start=1):
            lbl = QLabel(label)
            lbl.setObjectName("MutedLabel")
            val = QLabel(value)
            val.setWordWrap(True)
            grid.addWidget(lbl, i, 0)
            grid.addWidget(val, i, 1)
        panel_layout.addLayout(grid)

        if not editable:
            return panel

        # Per-slot action buttons attached to THIS panel so the operator
        # never has to map a bottom-row button back up to a card.
        # Cross-workflow panels (editable=False) skip these entirely --
        # resolving them means editing the OTHER workflow's own data.
        btn_row = QHBoxLayout()
        btn_keep = QPushButton("Задржи овај слот")
        btn_keep.setObjectName("PrimaryButton")
        btn_keep.setToolTip(
            f"Задржи слот БМ {p.bm_number}, {p.function} — остали слотови"
            " конфликта постају празни."
        )
        btn_keep.clicked.connect(
            lambda _checked, key=p.slot_key: self._on_keep(key)
        )
        btn_row.addWidget(btn_keep)

        btn_remove = QPushButton("Уклони овај слот")
        btn_remove.setObjectName("DangerButton")
        btn_remove.setToolTip(
            f"Испразни само овај слот (БМ {p.bm_number}, {p.function})."
            " Остале пријаве остају нетакнуте."
        )
        btn_remove.clicked.connect(
            lambda _checked, key=p.slot_key: self._on_remove_slot(key)
        )
        btn_row.addWidget(btn_remove)
        panel_layout.addLayout(btn_row)

        return panel

    def _format_submission_time(self, p: Person) -> str:
        """Human-readable submission timestamp for this panel, or '—'
        when unknown (party field blank, no cache entry, or the caller
        didn't pass an election_uuid to detect_conflicts at all)."""
        iso = self.conflict.submission_times.get(id(p), "")
        if not iso:
            return "—"
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(iso)
            return dt.strftime("%d.%m.%Y. %H:%M")
        except ValueError:
            return iso

    def _on_keep(self, slot_key: tuple[int, str]) -> None:
        bm, func = slot_key
        while True:
            note, ok = QInputDialog.getText(
                self, "Напомена (обавезна)",
                f"Разлог за задржавање слота БМ {bm}, {func}:",
            )
            if not ok:
                return
            if note.strip():
                break
            QMessageBox.warning(
                self, "Обавезна напомена",
                "Напомена не сме бити празна — потребна је за ревизорски траг.",
            )
        self.resolved.emit(self.conflict, slot_key, note.strip())

    def _on_remove_slot(self, slot_key: tuple[int, str]) -> None:
        bm, func = slot_key
        while True:
            note, ok = QInputDialog.getText(
                self, "Напомена (обавезна)",
                f"Разлог уклањања слота БМ {bm}, {func}:",
            )
            if not ok:
                return
            if note.strip():
                break
            QMessageBox.warning(
                self, "Обавезна напомена",
                "Напомена не сме бити празна — потребна је за ревизорски траг.",
            )
        self.slot_removed.emit(self.conflict, slot_key, note.strip())

    def _on_remove_both(self) -> None:
        while True:
            note, ok = QInputDialog.getText(
                self, "Напомена (обавезна)",
                "Разлог уклањања из свих странака:",
            )
            if not ok:
                return
            if note.strip():
                break
            QMessageBox.warning(
                self, "Обавезна напомена",
                "Напомена не сме бити празна — потребна је за ревизорски траг.",
            )
        self.removed_both.emit(self.conflict, note.strip())
