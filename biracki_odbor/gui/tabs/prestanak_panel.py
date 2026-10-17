"""Престанак функције — чл. 15 "automatic lapse" decision builder.

Fields-only widget embedded in IzmenaPanel's step 5 (see izmene.py) —
it shares that panel's one Генериши button and one preview pane rather
than having its own, exactly like the other three (log-driven) tracks.
Unlike those, this one genuinely cannot be auto-derived from a single
BM's data: a cross-municipality double appointment is only visible once
the operator flags it in Corrections (Напомена = "по члану 14. став 1.
тачка 8)"), at which point `load_draft()` pre-fills the person's name
and both known BMs/municipality from that event — the rest (which seat
is ceasing vs existing, both decisions' broj/date) still needs the
operator's judgment or RIK's notice. See core.prestanak_docx's module
docstring for the full legal background.
"""

from __future__ import annotations

from PySide6.QtCore import QDate, Signal
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QLineEdit, QPlainTextEdit,
    QSpinBox, QVBoxLayout, QWidget,
)

from biracki_odbor.config.declension import (
    format_serbian_date, parse_serbian_date, to_genitive,
)
from biracki_odbor.core.phase3_docx import format_broj
from biracki_odbor.core.prestanak_docx import (
    DEFAULT_LEGAL_BASIS, ROLE_CHOICES, PrestanakSpec,
)
from biracki_odbor.core.workflow import PROSIRENI_SPEC, STALNI_SPEC, bm_offset
from biracki_odbor.gui.app_state import AppState
from biracki_odbor.gui.widgets.date_picker import make_date_picker
from biracki_odbor.gui.widgets.spinbox import inset_spinbox_text


def _qdate_to_genitive(qdate: QDate) -> str:
    return to_genitive(format_serbian_date(qdate.year(), qdate.month(), qdate.day()))


def _role_from_function(function: str) -> str:
    """Map a slot's raw function string (e.g. "Заменик члана 2",
    "Председник") onto PrestanakSpec's two generic ROLE_CHOICES — this
    document only distinguishes member vs. deputy member, not which
    specific numbered/named seat."""
    return ROLE_CHOICES[1] if "заменик" in function.lower() else ROLE_CHOICES[0]


class PrestanakPanel(QWidget):
    # Emitted on any field edit — IzmenaPanel connects this to its shared
    # preview refresh, since (unlike the izmena editor) none of this
    # panel's own widgets live in izmene.py for it to wire up directly.
    fields_changed = Signal()

    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        hint = QPlainTextEdit(self.tr(
            "This decision covers чл. 15 of the Law on the Election of"
            " Members of Parliament: the same person cannot be appointed"
            " to two election-administration bodies. Because electoral"
            " lists are submitted at the national level, the same person"
            " can be proposed for the extended composition in several"
            " municipalities at once — something this municipality's own"
            " application cannot detect by itself (each municipality only"
            " sees its own data). Select the flagged person on the left to"
            " pre-fill what's known; fill in the rest from the Republic"
            " Election Commission's notice or the list submitter."
        ))
        hint.setReadOnly(True)
        hint.setMaximumHeight(90)
        hint.setObjectName("MutedLabel")
        root.addWidget(hint)

        form = QFormLayout()
        form.setSpacing(8)

        self.ed_person_name = QLineEdit()
        self.ed_person_name.setPlaceholderText(self.tr("e.g. Петар Петровић"))
        form.addRow(self.tr("First and last name:"), self.ed_person_name)

        root.addLayout(form)

        # ── Ceasing (later, прошиени) appointment ──────────────────
        root.addWidget(_section_label(self.tr(
            "Seat that lapses (the later appointment by decision date —"
            " this is checked by RIK, or simply by comparing the dates of"
            " the two decisions, not by this application)"
        )))
        ceasing_form = QFormLayout()
        ceasing_form.setSpacing(8)

        self.cb_ceasing_role = QComboBox()
        for role in ROLE_CHOICES:
            self.cb_ceasing_role.addItem(role, role)
        ceasing_form.addRow(self.tr("Role:"), self.cb_ceasing_role)

        self.cb_ceasing_sastav = QComboBox()
        for key, label in self._sastav_labels().items():
            self.cb_ceasing_sastav.addItem(label, key)
        self.cb_ceasing_sastav.setCurrentIndex(
            self.cb_ceasing_sastav.findData("prosireni")
        )
        ceasing_form.addRow(self.tr("Composition:"), self.cb_ceasing_sastav)

        self.sb_ceasing_bm = QSpinBox()
        self.sb_ceasing_bm.setRange(1, 9999)
        inset_spinbox_text(self.sb_ceasing_bm)
        ceasing_form.addRow(self.tr("Polling station no.:"), self.sb_ceasing_bm)

        self.ed_ceasing_broj = QLineEdit()
        self.ed_ceasing_broj.setPlaceholderText(self.tr("e.g. 013-5-30-9/2026"))
        ceasing_form.addRow(self.tr("Decision number (seat that lapses):"), self.ed_ceasing_broj)

        self.dt_ceasing_date = make_date_picker()
        ceasing_form.addRow(self.tr("Decision date (seat that lapses):"), self.dt_ceasing_date)

        root.addLayout(ceasing_form)

        # THIS OIK's own original decision for the lapsing seat is fully
        # derivable from the election config — the same inputs Phase 3
        # used to print it in the first place (see format_broj +
        # bm_offset) — so it's recomputed here, not something the
        # operator has to look up or that we need to store separately.
        self.sb_ceasing_bm.valueChanged.connect(lambda _: self._auto_derive_ceasing())
        self.cb_ceasing_sastav.currentIndexChanged.connect(lambda _: self._auto_derive_ceasing())

        # ── Existing (earlier, either composition) appointment ──────
        root.addWidget(_section_label(self.tr(
            "Existing seat (the earlier appointment, stalni or prosireni —"
            " usually in a DIFFERENT municipality, which is exactly why"
            " neither OIK could detect this on its own)"
        )))
        existing_form = QFormLayout()
        existing_form.setSpacing(8)

        self.cb_existing_role = QComboBox()
        for role in ROLE_CHOICES:
            self.cb_existing_role.addItem(role, role)
        existing_form.addRow(self.tr("Role:"), self.cb_existing_role)

        self.cb_existing_sastav = QComboBox()
        for key, label in self._sastav_labels().items():
            self.cb_existing_sastav.addItem(label, key)
        existing_form.addRow(self.tr("Composition:"), self.cb_existing_sastav)

        self.sb_existing_bm = QSpinBox()
        self.sb_existing_bm.setRange(1, 9999)
        inset_spinbox_text(self.sb_existing_bm)
        existing_form.addRow(self.tr("Polling station no.:"), self.sb_existing_bm)

        self.ed_existing_municipality = QLineEdit()
        self.ed_existing_municipality.setPlaceholderText(self.tr("e.g. Ваљево"))
        existing_form.addRow(self.tr("Municipality (other appointment):"), self.ed_existing_municipality)

        self.ed_existing_broj = QLineEdit()
        self.ed_existing_broj.setPlaceholderText(self.tr("e.g. 013-5-30-1/2026"))
        existing_form.addRow(self.tr("Decision number (existing seat):"), self.ed_existing_broj)

        self.dt_existing_date = make_date_picker()
        existing_form.addRow(self.tr("Decision date (existing seat):"), self.dt_existing_date)

        root.addLayout(existing_form)

        # ── This decision's own admin facts ─────────────────────────
        root.addWidget(_section_label(self.tr("This decision's details")))
        own_form = QFormLayout()
        own_form.setSpacing(8)

        self.dt_session_date = make_date_picker()
        own_form.addRow(self.tr("Session date:"), self.dt_session_date)

        self.ed_document_broj = QLineEdit()
        self.ed_document_broj.setPlaceholderText(self.tr("e.g. Број: 013-5-30-15/2026"))
        own_form.addRow(self.tr("Decision number (this decision):"), self.ed_document_broj)

        self.ed_legal_basis = QPlainTextEdit(DEFAULT_LEGAL_BASIS)
        self.ed_legal_basis.setMaximumHeight(100)
        own_form.addRow(self.tr("Legal basis:"), self.ed_legal_basis)

        root.addLayout(own_form)
        root.addStretch()

        # Any edit should refresh IzmenaPanel's shared preview — without
        # this, typing a broj or picking a date left the preview frozen
        # on whatever `missing_fields()` snapshot it last showed.
        _emit = lambda *_: self.fields_changed.emit()
        self.ed_person_name.textChanged.connect(_emit)
        self.cb_ceasing_role.currentIndexChanged.connect(_emit)
        self.cb_ceasing_sastav.currentIndexChanged.connect(_emit)
        self.sb_ceasing_bm.valueChanged.connect(_emit)
        self.ed_ceasing_broj.textChanged.connect(_emit)
        self.dt_ceasing_date.dateChanged.connect(_emit)
        self.cb_existing_role.currentIndexChanged.connect(_emit)
        self.cb_existing_sastav.currentIndexChanged.connect(_emit)
        self.sb_existing_bm.valueChanged.connect(_emit)
        self.ed_existing_municipality.textChanged.connect(_emit)
        self.ed_existing_broj.textChanged.connect(_emit)
        self.dt_existing_date.dateChanged.connect(_emit)
        self.dt_session_date.dateChanged.connect(_emit)
        self.ed_document_broj.textChanged.connect(_emit)
        self.ed_legal_basis.textChanged.connect(_emit)

    def _sastav_labels(self) -> dict[str, str]:
        return {"stalni": self.tr("Stalni"), "prosireni": self.tr("Prosireni")}

    def _auto_derive_ceasing(self) -> None:
        """Recompute (not look up) THIS OIK's own original decision
        number/date for whichever BM+composition is currently selected
        as the lapsing seat — identical inputs to what Phase 3 used to
        print it originally, so it always matches the real document."""
        spec = (
            STALNI_SPEC if self.cb_ceasing_sastav.currentData() == "stalni"
            else PROSIRENI_SPEC
        )
        oik = self.state.oik
        election = self.state.election
        bm_num = self.sb_ceasing_bm.value()
        offset = bm_offset(oik, bm_num)
        broj = format_broj(election, bm_num, offset, spec)
        self.ed_ceasing_broj.setText(broj.removeprefix("Број: "))
        date_text = (
            getattr(election.election.dates, spec.session_date_field, "")
            or election.election.dates.session_date
        )
        parsed = parse_serbian_date(date_text)
        if parsed is not None:
            year, month, day = parsed
            self.dt_ceasing_date.setDate(QDate(year, month, day))

    def load_draft(self, draft: dict) -> None:
        """Pre-fill from one чл. 14(1)(8)-flagged slot — see
        izmene.py's `_group_prestanak_drafts()`. The person's name, the
        BM they're flagged on here, and the other BM/municipality/decision
        number the operator typed into Corrections' Напомена dialog — plus
        THIS OIK's own ceasing-seat decision number/date, which doesn't
        come from the draft at all but is recomputed by
        `_auto_derive_ceasing()`. Which side is "ceasing" vs. "existing"
        and both compositions are still judgment calls the operator (or
        RIK's notice) has to make — never guessed at here. The existing
        seat's own decision DATE also isn't captured in Corrections (only
        its broj) and still needs to be filled in by hand.
        """
        self.ed_person_name.setText(draft.get("person_name", ""))
        self.sb_ceasing_bm.setValue(draft.get("bm", 1) or 1)
        role = _role_from_function(draft.get("function", ""))
        idx = self.cb_ceasing_role.findData(role)
        if idx >= 0:
            self.cb_ceasing_role.setCurrentIndex(idx)
        other_bm = draft.get("other_bm")
        if other_bm:
            self.sb_existing_bm.setValue(other_bm)
        self.ed_existing_municipality.setText(draft.get("other_municipality", ""))
        self.ed_existing_broj.setText(draft.get("other_decision_broj", ""))
        self._auto_derive_ceasing()

    def collect_spec(self) -> PrestanakSpec | None:
        """Returns None (caller shows the warning) when required fields
        are missing — `missing_fields()` names them."""
        name = self.ed_person_name.text().strip()
        ceasing_broj = self.ed_ceasing_broj.text().strip()
        existing_broj = self.ed_existing_broj.text().strip()
        document_broj = self.ed_document_broj.text().strip()
        if not (name and ceasing_broj and existing_broj and document_broj):
            return None
        return PrestanakSpec(
            person_name=name,
            ceasing_role=self.cb_ceasing_role.currentData(),
            ceasing_sastav=self.cb_ceasing_sastav.currentData(),
            ceasing_bm=self.sb_ceasing_bm.value(),
            ceasing_decision_broj=ceasing_broj,
            ceasing_decision_date=_qdate_to_genitive(self.dt_ceasing_date.date()),
            existing_role=self.cb_existing_role.currentData(),
            existing_sastav=self.cb_existing_sastav.currentData(),
            existing_bm=self.sb_existing_bm.value(),
            existing_decision_broj=existing_broj,
            existing_decision_date=_qdate_to_genitive(self.dt_existing_date.date()),
            existing_municipality=self.ed_existing_municipality.text().strip(),
            municipality=self.state.oik.municipality.name,
            session_date=_qdate_to_genitive(self.dt_session_date.date()),
            document_broj=document_broj,
            legal_basis=self.ed_legal_basis.toPlainText().strip(),
        )

    def missing_fields(self) -> list[str]:
        missing = []
        if not self.ed_person_name.text().strip():
            missing.append(self.tr("First and last name"))
        if not self.ed_ceasing_broj.text().strip():
            missing.append(self.tr("Decision number (seat that lapses)"))
        if not self.ed_existing_broj.text().strip():
            missing.append(self.tr("Decision number (existing seat)"))
        if not self.ed_document_broj.text().strip():
            missing.append(self.tr("Decision number (this decision)"))
        return missing


def _section_label(text: str) -> QWidget:
    from PySide6.QtWidgets import QLabel
    lbl = QLabel(text)
    lbl.setObjectName("SectionLabel")
    return lbl
