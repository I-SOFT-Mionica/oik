"""Измене — builder for amendment decisions.

`IzmenaPanel` is the reusable per-slug builder widget. It is used by:
  * `IzmeneTab`          — stalni workflow, step 5 in the main tab strip
  * `ProsireniWorkspace` — prošireni workflow, step 5 in its own tab strip

Changes are sourced read-only from corrections.log; clicking a row
selects the BM and auto-derives the original broj, session date, and
amendment index. CorrectionsTab is the single authority for changes.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QCoreApplication, QDate, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QFormLayout, QFrame,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QSplitter,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from biracki_odbor import app_paths
from biracki_odbor.config.commission import commission_terms, terms_for, vrsta_for
from biracki_odbor.config.declension import (
    format_serbian_date, parse_serbian_date, to_genitive,
)
from biracki_odbor.core.izmene_docx import (
    CHAIRMAN_LAPSE_REASONS, IzmenaRecord, IzmenaSpec, _CHAIRMAN_FUNCTION_FULL,
    _CHAIRMAN_FUNCTIONS, format_amendment_broj, generate_izmena,
    group_records_by_variant, load_all_post_rik_changes,
    load_izmena_obrazlozenje, record_variant, render_izmena_obrazlozenje,
)
from biracki_odbor.gui.tabs.prestanak_panel import PrestanakPanel
from biracki_odbor.core.phase3_docx import format_broj
from biracki_odbor.core.workflow import STALNI_SPEC, WorkflowSpec, bm_offset
from biracki_odbor.gui.app_state import AppState
from biracki_odbor.gui.widgets.banner import StatusBanner
from biracki_odbor.gui.widgets.collapsible_section import CollapsibleSection
from biracki_odbor.gui.widgets.date_picker import make_date_picker
from biracki_odbor.gui.widgets.obrazlozenje_card import ObrazlozenjeCard
from biracki_odbor.gui.widgets.paginated_preview import (
    PaginatedPreview, anchor_marker, pt_margin_css,
)
from biracki_odbor.gui.widgets.spacing_bar import DocumentSpacingBar
from biracki_odbor.gui.widgets.toggle_switch import ToggleSwitch
from biracki_odbor.logging_setup import log_timing

from datetime import datetime as _dt_cls


# ── Module-level helpers ──────────────────────────────────────────────────────

# 2026 cycle: the Law's own amendment chain collapsed to a single
# consolidated citation (14/22 и 47/26) — confirmed against the official
# RIK-distributed forms under biracki_odbor/new forms/ (1 2, 2 2). Those
# forms also cite a second, brand-new source alongside the Law itself —
# члана 7. Упутства за предлагање лица у бирачке одборе — that didn't
# exist in any earlier cycle's citation at all.
_DEFAULT_LEGAL_BASIS: dict[str, str] = {
    "stalni": (
        'На основу члана 32. тачка 2) и чл. 35. и 41. Закона о избору'
        ' народних посланика ("Службени гласник РС", бр. 14/22 и 47/26) и'
        ' члана 7. Упутства за предлагање лица у бирачке одборе за'
        ' спровођење гласања на изборима за народне посланике'
        ' ("Службени гласник РС", број 79/26 – пречишћен текст),'
    ),
    "prosireni": (
        'На основу члана 32. тачка 2), члана 39. став 1. и члана 41.'
        ' Закона о избору народних посланика ("Службени гласник РС", бр.'
        ' 14/22 и 47/26) и члана 7. Упутства за предлагање лица у'
        ' бирачке одборе за спровођење гласања на изборима за народне'
        ' посланике ("Службени гласник РС", број 79/26 – пречишћен'
        ' текст),'
    ),
}


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("SectionLabel")
    return lbl


def _div() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Sunken)
    return line


def _evs_to_records(evs: list[dict]) -> list[IzmenaRecord]:
    """Convert one BM's post-RIK change events into IzmenaRecords.

    `evs` is expected pre-filtered to a single BM (both call sites do
    this). Multiple events for the SAME function (e.g. "Очисти место"
    followed by a nacelnik appointment — appointing requires clearing
    first, so these land as two separate audit events for one semantic
    correction) are merged into a single record: old_name from the
    EARLIEST event, new_name/mesto/party/appointed_by_nacelnik from the
    LATEST — same reasoning as events_to_izmena_records() in
    core/izmene_docx.py. Without this, a clear-then-appoint pair
    produced two incoherent half-records instead of one correct
    "уместо X именује Y" line, and the two entries visually crowded out
    other genuinely-different slots that also changed on the same BM.
    """
    by_function: dict[str, list[dict]] = {}
    for ev in evs:
        by_function.setdefault(ev.get("function", ""), []).append(ev)

    records = []
    for func, func_evs in by_function.items():
        first_ev, last_ev = func_evs[0], func_evs[-1]
        old_name = first_ev.get("old_name", "")
        new_name = last_ev.get("new_name", "")
        if not old_name and not new_name:
            continue
        old_place = first_ev.get("old_mesto", "")
        new_place = last_ev.get("mesto", "")
        before_jmbg = (first_ev.get("before_jmbg") or "").strip()
        after_jmbg = (last_ev.get("after_jmbg") or "").strip()
        is_correction = bool(before_jmbg) and before_jmbg == after_jmbg
        if is_correction and old_name == new_name and old_place == new_place:
            continue
        reason = (last_ev.get("note") or "").strip()
        is_chairman_lapse = (
            not is_correction
            and func in _CHAIRMAN_FUNCTIONS
            and reason in CHAIRMAN_LAPSE_REASONS
        )
        function = _CHAIRMAN_FUNCTION_FULL[func] if is_chairman_lapse else (func.upper() if func else "")
        records.append(IzmenaRecord(
            old_name=old_name,
            function=function,
            new_name=new_name,
            new_place=new_place,
            party=last_ev.get("party", ""),
            appointed_by_nacelnik=bool(last_ev.get("appointed_by_nacelnik", False)),
            is_correction=is_correction,
            old_place=old_place,
            is_chairman_lapse=is_chairman_lapse,
        ))
    return records


def _izmena_item_html(i: int, r: IzmenaRecord) -> str:
    """Preview line for one disposition item — mirrors the phrasing
    choice in core.izmene_docx's document renderer (same person
    correction vs. actual membership substitution) so the preview never
    shows text the generated .docx won't actually contain."""
    if r.is_chairman_lapse:
        # The actual document for this record is a wholly different,
        # single-item решење (чл. 41. ст. 2.: own title, legal basis,
        # образложење) — this merged multi-item preview can't represent
        # its shape, so it must say so rather than imply it's just
        # another numbered item in THIS document.
        return (
            f"{i}) <i>[посебно решење по чл. 41. ст. 2 — биће генерисано"
            f" као засебан документ]</i> уместо <b>{r.old_name or '…'}</b>,"
            f" за <b>{r.function or '…'}</b> именује:"
            f" <b>{r.new_name or '…'}</b> из {r.new_place or '…'}"
        )
    if r.is_correction:
        name_changed = r.old_name != r.new_name
        place_changed = r.old_place != r.new_place
        identifier = r.new_name or r.old_name
        if name_changed and place_changed:
            return (
                f"{i}) исправљају се подаци за <b>{r.function or '…'}</b>"
                f" {identifier}: уместо „<b>{r.old_name}</b>” уписује се:"
                f" „<b>{r.new_name}</b>”; уместо „<b>{r.old_place}</b>”"
                f" уписује се: „<b>{r.new_place}</b>”;"
            )
        if place_changed:
            return (
                f"{i}) исправља се податак о пребивалишту за"
                f" <b>{r.function or '…'}</b> {identifier}: уместо"
                f" „<b>{r.old_place}</b>” уписује се: „<b>{r.new_place}</b>”;"
            )
        return (
            f"{i}) исправља се податак о имену и презимену за"
            f" <b>{r.function or '…'}</b>: уместо „<b>{r.old_name}</b>”"
            f" уписује се: „<b>{r.new_name}</b>”;"
        )
    return (
        f"{i}) уместо <b>{r.old_name or '…'}</b>,"
        f" за <b>{r.function or '…'}</b> именује:"
        f" <b>{r.new_name or '…'}</b> из {r.new_place or '…'};"
    )


# The three corrections-log-driven legal tracks this step groups changes
# into (чл. 15 Престанак — see PrestanakPanel — isn't here: it's manual
# entry, not derived from the log). Order here is display order.
_VARIANTS = ("replacement", "correction", "chairman_lapse")

_VARIANT_SECTION_TITLES = {
    "replacement": lambda: QCoreApplication.translate(
        "IzmeneFeature", "Replacement (member/chairman, чл. 41 ст. 1)",
    ),
    "correction": lambda: QCoreApplication.translate(
        "IzmeneFeature", "Data correction (same person)",
    ),
    "chairman_lapse": lambda: QCoreApplication.translate(
        "IzmeneFeature", "Chairman cessation (чл. 41 ст. 2)",
    ),
}


def _group_all_records_by_variant(
    changes_data: list[dict],
) -> dict[str, list[tuple[int, list[IzmenaRecord]]]]:
    """All logged changes, grouped first by legal track then by BM.

    Each (bm, records) pair is exactly one document's worth of content —
    the replacement, correction, and chairman-lapse tracks have different
    legal basis/образложење and can never share a document, so the
    grouped UI (one CollapsibleSection per track) shows that split before
    the operator ever clicks a row, instead of hiding it inside one flat
    table of mixed change types.
    """
    by_bm: dict[int, list[dict]] = {}
    for ev in changes_data:
        by_bm.setdefault(ev.get("bm", 0), []).append(ev)

    result: dict[str, list[tuple[int, list[IzmenaRecord]]]] = {
        variant: [] for variant in _VARIANTS
    }
    for bm_number in sorted(by_bm):
        records = _evs_to_records(by_bm[bm_number])
        for group in group_records_by_variant(records):
            variant = record_variant(group[0])
            result.setdefault(variant, []).append((bm_number, group))
    return result


def _group_prestanak_drafts(changes_data: list[dict]) -> list[dict]:
    """Slots flagged with Напомена = "по члану 14. став 1. тачка 8)" —
    the чл. 15 cross-municipality double-appointment track. Unlike the
    three IzmenaRecord-based tracks above, a flagging edit often changes
    nothing else about the slot (the operator just adds the note to an
    already-correct entry), so this reads straight from the raw events —
    `_evs_to_records`'s "nothing material changed" skip would otherwise
    silently drop exactly this case.

    Groups ALL events per slot first, THEN checks for the flag — not
    the other way around. A later, unrelated edit on an already-flagged
    slot (e.g. a name typo fix) may not re-select the Напомена reason,
    so checking only the slot's LAST event would silently "unflag" it.
    Person name comes from the slot's overall latest event either way;
    the flag and the other BM/municipality/decision number come from the
    latest event that actually carried them.
    """
    from biracki_odbor.gui.tabs.corrections import NOTE_REASON_CL_14_1_8

    by_slot: dict[tuple[int, str], list[dict]] = {}
    for ev in changes_data:
        by_slot.setdefault((ev.get("bm", 0), ev.get("function", "")), []).append(ev)

    drafts = []
    for (bm, function), evs in sorted(by_slot.items()):
        flagged = [e for e in evs if (e.get("note") or "").startswith(NOTE_REASON_CL_14_1_8)]
        if not flagged:
            continue
        last_overall = evs[-1]
        last_flagged = flagged[-1]
        drafts.append({
            "bm": bm,
            "function": function,
            "person_name": last_overall.get("new_name") or last_overall.get("old_name", ""),
            "other_bm": last_flagged.get("other_bm"),
            "other_municipality": last_flagged.get("other_municipality", ""),
            "other_decision_broj": last_flagged.get("other_decision_broj", ""),
        })
    return drafts


def _qdate_to_genitive(qdate: QDate) -> str:
    return to_genitive(format_serbian_date(qdate.year(), qdate.month(), qdate.day()))


class _SlugProxy:
    """Minimal duck-type for corrections_log_path_for()."""
    def __init__(self, slug: str) -> None:
        self.slug = slug


# ── Reusable amendment builder panel ─────────────────────────────────────────


class IzmenaPanel(QWidget):
    """Full amendment builder for one composition type (stalni or prosireni).

    Used in the stalni workflow (via IzmeneTab) and in ProsireniWorkspace.
    `navigate_callback` is called with the replaced person's JMBG when the
    operator clicks '→ Corrections tab' — the caller decides where to navigate.
    """

    def __init__(
        self,
        spec: WorkflowSpec,
        state: AppState,
        navigate_callback: Callable[[str], None],
    ) -> None:
        super().__init__()
        self._spec = spec
        self.state = state
        self._navigate = navigate_callback
        self._loading = False
        self._changes_data: list[dict] = []
        self._selected_bm: int | None = None
        self._selected_variant: str | None = None
        self._selected_records: list[IzmenaRecord] | None = None
        self._selected_draft: dict | None = None
        self._selected_before_jmbg: str = ""
        self._derived_original_broj: str = ""
        self._derived_original_date: str = ""
        self._derived_amendment_idx: int = 1

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.banner = StatusBanner()
        outer.addWidget(self.banner)

        self.lbl_locked = QLabel()
        self.lbl_locked.setObjectName("WarnLabel")
        self.lbl_locked.setWordWrap(True)
        self.lbl_locked.setContentsMargins(16, 8, 16, 8)
        self.lbl_locked.setVisible(False)
        outer.addWidget(self.lbl_locked)

        # CollapsibleSection ignores its own contentsMargins (its internal
        # root layout is hardcoded to 0,0,0,0 — see collapsible_section.py),
        # unlike a QGroupBox/QLabel which would respect it directly. Wrap it
        # so it gets the same 16px horizontal gap from the sidebar that
        # every other widget in this panel (lbl_locked, title) has.
        changes_wrap = QWidget()
        changes_wrap_layout = QVBoxLayout(changes_wrap)
        changes_wrap_layout.setContentsMargins(16, 8, 16, 8)
        changes_wrap_layout.setSpacing(8)
        for variant in _VARIANTS:
            changes_wrap_layout.addWidget(self._build_variant_section(variant))
        changes_wrap_layout.addWidget(self._build_prestanak_section())
        changes_wrap_layout.addLayout(self._build_changes_controls_row())
        outer.addWidget(changes_wrap)

        # Title above the splitter (visible over both left and right panes)
        title = QLabel(QCoreApplication.translate("IzmeneFeature","5. Amendment decisions"))
        title.setObjectName("TitleLabel")
        title.setContentsMargins(16, 8, 16, 4)
        outer.addWidget(title)

        # Spans the full tab width, above the splitter (always visible
        # regardless of izmena/Престанак mode -- both share the same
        # underlying DocumentFormat). Confining a 5-control row to the
        # splitter's right pane forced that pane's minimum width up,
        # squeezing the left (editing) pane below its own content's width.
        self.spacing_bar = DocumentSpacingBar(self.state)
        spacing_row = QHBoxLayout()
        spacing_row.setContentsMargins(16, 0, 16, 0)
        spacing_row.addWidget(self.spacing_bar)
        outer.addLayout(spacing_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        outer.addWidget(splitter, stretch=1)

        self._left_scroll = QScrollArea()
        self._left_scroll.setWidgetResizable(True)
        self._left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_container = QWidget()
        self._left_scroll.setWidget(left_container)
        self._left_layout = QVBoxLayout(left_container)
        self._left_layout.setContentsMargins(16, 8, 16, 16)
        self._left_layout.setSpacing(10)

        # Two swappable editors share this one column + the one preview
        # pane/Генериши button below — only one is visible at a time,
        # toggled by _set_mode() whenever the selected track changes.
        self._izmena_editor = QWidget()
        izmena_layout = QVBoxLayout(self._izmena_editor)
        izmena_layout.setContentsMargins(0, 0, 0, 0)
        izmena_layout.setSpacing(10)
        self._build_editor_panel(izmena_layout)
        self._left_layout.addWidget(self._izmena_editor)

        self._prestanak_editor = PrestanakPanel(state)
        self._left_layout.addWidget(self._prestanak_editor)
        self._prestanak_editor.fields_changed.connect(self._refresh_preview)

        self._mode = "izmena"
        self._prestanak_editor.setVisible(False)

        splitter.addWidget(self._left_scroll)

        right_host = QWidget()
        right_vbox = QVBoxLayout(right_host)
        right_vbox.setContentsMargins(0, 0, 0, 0)
        right_vbox.setSpacing(6)

        self._preview = PaginatedPreview()
        self._preview.setObjectName("PreviewPane")
        right_vbox.addWidget(self._preview, stretch=1)

        splitter.addWidget(right_host)
        splitter.setSizes([520, 460])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        # Jumps the paginated preview to whichever real page an образложење
        # card's paragraph landed on when that card gets focus -- same
        # anchor-based mechanism as Phase3Tab (no percentage scroll sync,
        # since the right side renders discrete pages with blank gaps).
        _app = QApplication.instance()
        if isinstance(_app, QApplication):
            _app.focusChanged.connect(self._on_focus_changed)

        outer.addWidget(self._build_generate_row())

        state.election_changed.connect(self._on_election_changed)
        state.resenja_fields_changed.connect(self._on_election_changed)
        state.document_format_changed.connect(self._refresh_preview)
        state.oik_changed.connect(self._on_election_changed)
        state.generation_log_changed.connect(self._refresh_lock_state)
        state.generation_log_changed.connect(self._refresh_changes_table)

        self._refresh_lock_state()
        self._load_legal_basis()
        self._load_auth_fields()
        self.spacing_bar.reload()
        self._load_obrazlozenje_cards()
        self._refresh_changes_table()
        self._refresh_preview()

    # ── Changes tables (grouped by legal track) ─────────────────────────────────

    def _build_grouped_table(self) -> QTableWidget:
        """One small table, shared column setup — used once per track
        section below. Rows are merged IzmenaRecords (what will actually
        appear in the generated document), not raw audit-log events, so
        a clear-then-appoint pair already shows as the one line it will
        become."""
        party_col_header = (
            QCoreApplication.translate("IzmeneFeature", "List") if self._spec.slug == "prosireni"
            else QCoreApplication.translate("IzmeneFeature", "Party")
        )
        headers = [
            QCoreApplication.translate("IzmeneFeature","BM"), QCoreApplication.translate("IzmeneFeature","Function"), QCoreApplication.translate("IzmeneFeature","Old"),
            QCoreApplication.translate("IzmeneFeature","New"), QCoreApplication.translate("IzmeneFeature","Place"), party_col_header,
            QCoreApplication.translate("IzmeneFeature","Generated"),
        ]
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        hdr = table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.Interactive)
        hdr.setStretchLastSection(True)
        hdr.resizeSection(0, 40)
        hdr.resizeSection(1, 140)
        hdr.resizeSection(2, 140)
        hdr.resizeSection(3, 140)
        hdr.resizeSection(4, 100)
        hdr.resizeSection(5, 80)
        table.setMaximumHeight(160)
        return table

    def _build_variant_section(self, variant: str) -> CollapsibleSection:
        section = CollapsibleSection(_VARIANT_SECTION_TITLES[variant]())
        table = self._build_grouped_table()
        table.itemSelectionChanged.connect(lambda v=variant: self._on_row_selected(v))
        setattr(self, f"_section_{variant}", section)
        setattr(self, f"table_{variant}", table)

        body = QWidget()
        vlay = QVBoxLayout(body)
        vlay.setContentsMargins(0, 0, 0, 0)
        vlay.addWidget(table)
        section.set_content(body)
        return section

    def _build_prestanak_section(self) -> CollapsibleSection:
        """чл. 15 cessation of function — cross-municipality double
        appointment. Log-driven exactly like the three tracks above: the
        operator flags it in Corrections with Напомена = "по члану 14.
        став 1. тачка 8)" (see core.prestanak_docx for the legal
        background); this table lists those flagged slots. What it
        CAN'T do is fully auto-derive the document — the other seat is
        in a different municipality, so only its BM/municipality (what
        the operator typed into that Напомена dialog) is known here;
        selecting a row pre-fills that much into the shared left form
        via PrestanakPanel.load_draft(), the rest needs the operator's
        judgment or RIK's notice. Available from step 5 in BOTH
        workflows since either composition's seat can be the one that
        lapses."""
        section = CollapsibleSection(
            QCoreApplication.translate("IzmeneFeature", "Cessation of function (чл. 15, cross-municipality)"),
        )
        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels([
            QCoreApplication.translate("IzmeneFeature", "Name"),
            QCoreApplication.translate("IzmeneFeature", "BM"),
            QCoreApplication.translate("IzmeneFeature", "Other appointment"),
            QCoreApplication.translate("IzmeneFeature", "Generated"),
        ])
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        hdr = table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.Interactive)
        hdr.setStretchLastSection(True)
        hdr.resizeSection(0, 160)
        hdr.resizeSection(1, 40)
        hdr.resizeSection(2, 180)
        table.setMaximumHeight(160)
        table.itemSelectionChanged.connect(lambda: self._on_row_selected("prestanak"))
        self.table_prestanak = table

        body = QWidget()
        vlay = QVBoxLayout(body)
        vlay.setContentsMargins(0, 0, 0, 0)
        vlay.addWidget(table)
        section.set_content(body)
        self._section_prestanak = section
        return section

    def _build_changes_controls_row(self) -> QHBoxLayout:
        btn_row = QHBoxLayout()
        self.btn_nav_correction = QPushButton(QCoreApplication.translate("IzmeneFeature","→ Corrections tab"))
        self.btn_nav_correction.setEnabled(False)
        self.btn_nav_correction.setToolTip(QCoreApplication.translate("IzmeneFeature",
            "Open Corrections tab with this person's JMBG pre-filled in the search"
        ))
        self.btn_nav_correction.clicked.connect(self._on_nav_correction)
        btn_row.addWidget(self.btn_nav_correction)
        self.lbl_changes_status = QLabel("")
        self.lbl_changes_status.setObjectName("MutedLabel")
        btn_row.addWidget(self.lbl_changes_status)
        btn_row.addStretch()
        btn_refresh = QPushButton(QCoreApplication.translate("IzmeneFeature","Refresh"))
        btn_refresh.clicked.connect(self._refresh_changes_table)
        btn_row.addWidget(btn_refresh)
        return btn_row

    def _fill_variant_table(
        self, table: QTableWidget, entries: list[tuple[int, list[IzmenaRecord]]],
        events_by_bm: dict[int, list[dict]],
    ) -> None:
        wl = self.state.generation_log.workflow(self._spec.slug)
        table.setRowCount(len(entries))
        for row_idx, (bm_number, records) in enumerate(entries):
            first = records[0]
            before_jmbg = next(
                (e.get("before_jmbg", "") for e in events_by_bm.get(bm_number, []) if e.get("before_jmbg")),
                "",
            )
            count = wl.izmene_per_bm.get(str(bm_number), 0)
            generated = QCoreApplication.translate("IzmeneFeature","#{n}").format(n=count) if count else "—"
            # Multiple records in one group (e.g. two ordinary members
            # replaced on the same BM) share one row — Old/New show the
            # first; the full set still goes into the one document.
            cells = [
                str(bm_number), first.function, first.old_name, first.new_name,
                first.new_place, first.party, generated,
            ]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if col == 0:
                    item.setData(Qt.UserRole, (bm_number, records, before_jmbg))
                table.setItem(row_idx, col, item)

    def _fill_prestanak_table(self, table: QTableWidget, drafts: list[dict]) -> None:
        table.setRowCount(len(drafts))
        for row_idx, draft in enumerate(drafts):
            other = (
                f"БМ {draft['other_bm']} — {draft['other_municipality']}"
                if draft.get("other_bm") and draft.get("other_municipality")
                else "—"
            )
            # Unlike the izmena tracks, there's no persistent per-BM
            # counter for престанак documents — each one is a standalone
            # filing, not numbered amendments against one original
            # решење, so there's nothing meaningful to count here yet.
            cells = [draft["person_name"], str(draft["bm"]), other, "—"]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if col == 0:
                    item.setData(Qt.UserRole, (draft["bm"], draft))
                table.setItem(row_idx, col, item)

    @log_timing("IzmenaPanel._refresh_changes_table")
    def _refresh_changes_table(self) -> None:
        slug = self._spec.slug
        log_path = app_paths.corrections_log_path_for(_SlugProxy(slug))
        wl = self.state.generation_log.workflow(slug)
        self._changes_data = load_all_post_rik_changes(log_path, wl.submitted_to_rik_ts)

        events_by_bm: dict[int, list[dict]] = {}
        for ev in self._changes_data:
            events_by_bm.setdefault(ev.get("bm", 0), []).append(ev)
        grouped = _group_all_records_by_variant(self._changes_data)

        prev_bm, prev_variant = self._selected_bm, self._selected_variant
        found_selection = False
        total = 0
        for variant in _VARIANTS:
            table = getattr(self, f"table_{variant}")
            section = getattr(self, f"_section_{variant}")
            entries = grouped[variant]
            self._fill_variant_table(table, entries, events_by_bm)
            section.set_count(len(entries) if entries else None)
            # Hide a track's whole section when nothing's pending for it —
            # four always-visible accordions (three of them routinely
            # empty) was pure clutter.
            section.setVisible(bool(entries))
            total += len(entries)

            select_row = next(
                (i for i, (bm, _) in enumerate(entries)
                 if variant == prev_variant and bm == prev_bm),
                None,
            )
            table.blockSignals(True)
            if select_row is not None:
                table.selectRow(select_row)
                self._selected_records = entries[select_row][1]
                found_selection = True
            else:
                table.clearSelection()
            table.blockSignals(False)

        prestanak_drafts = _group_prestanak_drafts(self._changes_data)
        self._fill_prestanak_table(self.table_prestanak, prestanak_drafts)
        self._section_prestanak.set_count(len(prestanak_drafts) if prestanak_drafts else None)
        self._section_prestanak.setVisible(bool(prestanak_drafts))
        total += len(prestanak_drafts)
        select_row = next(
            (i for i, d in enumerate(prestanak_drafts)
             if prev_variant == "prestanak" and d["bm"] == prev_bm),
            None,
        )
        self.table_prestanak.blockSignals(True)
        if select_row is not None:
            self.table_prestanak.selectRow(select_row)
            self._selected_draft = prestanak_drafts[select_row]
            found_selection = True
        else:
            self.table_prestanak.clearSelection()
        self.table_prestanak.blockSignals(False)

        if not found_selection:
            self._selected_bm = None
            self._selected_variant = None
            self._selected_records = None
            self._selected_draft = None
            self._selected_before_jmbg = ""
            self.btn_nav_correction.setEnabled(False)
            self._set_mode("izmena")

        self.lbl_changes_status.setText(
            QCoreApplication.translate("IzmeneFeature","{n} change(s) since RIK cut-off.").format(n=total) if total
            else QCoreApplication.translate("IzmeneFeature","No post-RIK changes recorded.")
        )

        # Repopulating the tables in place does NOT fire itemSelectionChanged
        # when the selected ROW INDEX is unchanged (the common case: the
        # operator is looking at BM 1, clicks Освежи, and the tables refresh
        # without moving the selection) — so the preview must be refreshed
        # here explicitly, not left to piggyback on that signal. Without
        # this, newly-logged changes show up in the tables but the preview
        # (and the document an operator then generates) stays stale.
        if self._selected_bm is not None:
            self._refresh_bm_info()
        self._refresh_preview()

    def _set_mode(self, mode: str) -> None:
        """Switch which editor the shared left column (and, in
        _refresh_preview/_on_generate, the shared preview + Генериши
        button) act on. "prestanak" is a different document TYPE
        entirely (core.prestanak_docx, not core.izmene_docx) — not just
        another izmena variant — so it gets its own editor widget rather
        than reusing the izmena one's fields."""
        self._mode = mode
        self._izmena_editor.setVisible(mode == "izmena")
        self._prestanak_editor.setVisible(mode == "prestanak")

    def _on_row_selected(self, variant: str) -> None:
        table = getattr(self, f"table_{variant}")
        rows = table.selectionModel().selectedRows()
        if not rows:
            # Only clear the shared selection if THIS table owned it —
            # otherwise this fires (with an empty selection) as a side
            # effect of the mutual-exclusivity clearSelection() calls
            # below, right after a DIFFERENT table's row was legitimately
            # selected, which would immediately wipe out that selection.
            if self._selected_variant == variant:
                self._selected_bm = None
                self._selected_variant = None
                self._selected_records = None
                self._selected_draft = None
                self._selected_before_jmbg = ""
                self.btn_nav_correction.setEnabled(False)
                self._refresh_bm_info()
                self._refresh_preview()
            return

        row = rows[0].row()
        item = table.item(row, 0)
        payload = item.data(Qt.UserRole) if item else None
        if not payload:
            return

        if variant == "prestanak":
            bm_number, draft = payload
            self._selected_bm = bm_number
            self._selected_variant = variant
            self._selected_records = None
            self._selected_draft = draft
            self._selected_before_jmbg = ""
            self.btn_nav_correction.setEnabled(False)
            self._set_mode("prestanak")
            self._prestanak_editor.load_draft(draft)
        else:
            bm_number, records, before_jmbg = payload
            self._selected_bm = bm_number
            self._selected_variant = variant
            self._selected_records = records
            self._selected_draft = None
            self._selected_before_jmbg = before_jmbg
            self.btn_nav_correction.setEnabled(bool(before_jmbg))
            self._set_mode("izmena")

        # Exactly one group can be selected at a time across all four
        # tables — clicking a row in one clears whatever was selected in
        # the others (blockSignals so that clearing doesn't re-enter
        # this method and clobber the selection we just made above).
        for other in (*_VARIANTS, "prestanak"):
            if other == variant:
                continue
            other_table = getattr(self, f"table_{other}")
            if other_table.selectionModel().hasSelection():
                other_table.blockSignals(True)
                other_table.clearSelection()
                other_table.blockSignals(False)

        self._refresh_bm_info()
        self._refresh_preview()

    def _on_nav_correction(self) -> None:
        if self._selected_before_jmbg:
            self._navigate(self._selected_before_jmbg)

    def _refresh_bm_info(self) -> None:
        bm_num = self._selected_bm
        if bm_num is None:
            self.lbl_bm.setText(QCoreApplication.translate("IzmeneFeature","— click a row above to select a BM —"))
            self.lbl_original_broj.setText("—")
            self.lbl_original_date.setText("—")
            self.lbl_amendment_idx.setText("—")
            self._derived_original_broj = ""
            self._derived_original_date = ""
            self._derived_amendment_idx = 1
            return

        oik = self.state.oik
        election = self.state.election

        station = oik.station_by_bm(bm_num)
        bm_name = ""
        if station:
            bm_name = getattr(station, "full_name", None) or station.name
        self.lbl_bm.setText(f"{bm_num} — {bm_name}" if bm_name else str(bm_num))
        self.lbl_bm.setWordWrap(True)

        offset = bm_offset(oik, bm_num)
        broj = format_broj(election, bm_num, offset, self._spec)
        self._derived_original_broj = broj.removeprefix("Број: ")
        self.lbl_original_broj.setText(broj)

        original_date = (
            getattr(election.election.dates, self._spec.session_date_field, "") or "—"
        )
        self._derived_original_date = original_date
        self.lbl_original_date.setText(original_date)

        wl = self.state.generation_log.workflow(self._spec.slug)
        idx = wl.next_amendment_index(bm_num)
        self._derived_amendment_idx = idx
        self.lbl_amendment_idx.setText(str(idx))

    # ── Editor panel ──────────────────────────────────────────────────────────

    def _build_editor_panel(self, left: QVBoxLayout) -> None:
        hint = QLabel(QCoreApplication.translate("IzmeneFeature",
            "Select a row in the changes table to choose a BM."
            " Original decision number and date are derived automatically."
        ))
        hint.setObjectName("MutedLabel")
        hint.setWordWrap(True)
        left.addWidget(hint)

        self._build_details_section(left)
        self._build_legal_basis_section(left)
        self._build_auth_section(left)
        self._build_obrazlozenje_section(left)
        left.addStretch(1)

    def _build_details_section(self, left: QVBoxLayout) -> None:
        left.addWidget(_section_label(QCoreApplication.translate("IzmeneFeature","Resolution details")))

        info_form = QFormLayout()
        info_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.lbl_bm = QLabel(QCoreApplication.translate("IzmeneFeature","— click a row above to select a BM —"))
        self.lbl_bm.setWordWrap(True)
        info_form.addRow(QCoreApplication.translate("IzmeneFeature","Polling station:"), self.lbl_bm)

        self.lbl_original_broj = QLabel("—")
        info_form.addRow(QCoreApplication.translate("IzmeneFeature","Original decision number:"), self.lbl_original_broj)

        self.lbl_original_date = QLabel("—")
        info_form.addRow(QCoreApplication.translate("IzmeneFeature","Original decision date:"), self.lbl_original_date)

        self.lbl_amendment_idx = QLabel("—")
        info_form.addRow(QCoreApplication.translate("IzmeneFeature","Amendment sequence:"), self.lbl_amendment_idx)

        left.addLayout(info_form)

        issue_form = QFormLayout()
        issue_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.dt_issue_date = make_date_picker()
        self.dt_issue_date.setToolTip(QCoreApplication.translate("IzmeneFeature","Date of the amendment decision"))
        self.dt_issue_date.dateChanged.connect(lambda _: self._refresh_preview())
        issue_form.addRow(QCoreApplication.translate("IzmeneFeature","Amendment date:"), self.dt_issue_date)
        left.addLayout(issue_form)

    def _build_legal_basis_section(self, left: QVBoxLayout) -> None:
        left.addWidget(_div())
        left.addWidget(_section_label(QCoreApplication.translate("IzmeneFeature","Legal basis (Правни основ)")))

        self.ed_legal_basis = QPlainTextEdit()
        self.ed_legal_basis.setMinimumHeight(80)
        self.ed_legal_basis.setMaximumHeight(160)

        orig_lb_focus_out = self.ed_legal_basis.focusOutEvent

        def _lb_focus_out(ev):
            orig_lb_focus_out(ev)
            self._save_legal_basis()

        self.ed_legal_basis.focusOutEvent = _lb_focus_out
        self.ed_legal_basis.textChanged.connect(self._refresh_preview)
        left.addWidget(self.ed_legal_basis)

        hint = QLabel(QCoreApplication.translate("IzmeneFeature",
            "Replaces the 'На основу…' paragraph when non-empty."
            " Saved per composition type."
        ))
        hint.setObjectName("MutedLabel")
        hint.setWordWrap(True)
        left.addWidget(hint)

        btn_row = QHBoxLayout()
        btn_reset_lb = QPushButton(QCoreApplication.translate("IzmeneFeature","Reset to default"))
        btn_reset_lb.clicked.connect(self._on_reset_legal_basis)
        btn_row.addWidget(btn_reset_lb)
        btn_row.addStretch()
        left.addLayout(btn_row)

    def _build_auth_section(self, left: QVBoxLayout) -> None:
        section = CollapsibleSection(
            QCoreApplication.translate("IzmeneFeature", "Овлашћење"),
            QCoreApplication.translate(
                "IzmeneFeature",
                "ко потписује сва решења — стална, проширена, измене и престанак функције",
            ),
        )
        left.addWidget(section)

        body = QWidget()
        body_vbox = QVBoxLayout(body)
        body_vbox.setContentsMargins(0, 0, 0, 0)
        body_vbox.setSpacing(8)

        self.sw_delegated = ToggleSwitch(
            QCoreApplication.translate("IzmeneFeature", "Делегирано — овлашћено лице")
        )
        self.sw_delegated.setChecked(True)
        self.sw_delegated.setToolTip(QCoreApplication.translate("IzmeneFeature",
            "Off = Непосредно — председник ОИК signs directly, no authorized-person"
            " details needed below."
        ))
        body_vbox.addWidget(self.sw_delegated)
        off_hint = QLabel(QCoreApplication.translate("IzmeneFeature",
            "Off: Непосредно — председник ОИК"
        ))
        off_hint.setObjectName("MutedLabel")
        body_vbox.addWidget(off_hint)

        self._auth_frame = QFrame()
        auth_form = QFormLayout(self._auth_frame)
        auth_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.ed_auth_number = QLineEdit()
        self.ed_auth_number.setPlaceholderText("013-5-32/2023-01")
        self.ed_auth_number.setToolTip(QCoreApplication.translate("IzmeneFeature","Number of the authorization decision"))
        self.ed_auth_number.editingFinished.connect(self._save_auth_fields)
        auth_form.addRow(QCoreApplication.translate("IzmeneFeature","Authorization number:"), self.ed_auth_number)

        self.ed_auth_date = make_date_picker()
        self.ed_auth_date.setToolTip(QCoreApplication.translate("IzmeneFeature","Date of authorization"))
        self.ed_auth_date.dateChanged.connect(self._save_auth_fields)
        auth_form.addRow(QCoreApplication.translate("IzmeneFeature","Authorization date:"), self.ed_auth_date)

        self.ed_auth_name = QLineEdit()
        self.ed_auth_name.setPlaceholderText(QCoreApplication.translate("IzmeneFeature","e.g. Ивана Тешић"))
        self.ed_auth_name.setToolTip(QCoreApplication.translate("IzmeneFeature","Full name of the authorized person (nominative)"))
        self.ed_auth_name.editingFinished.connect(self._save_auth_fields)
        auth_form.addRow(QCoreApplication.translate("IzmeneFeature","Authorized person:"), self.ed_auth_name)

        self.ed_auth_role = QLineEdit()
        self.ed_auth_role.setPlaceholderText(QCoreApplication.translate("IzmeneFeature","e.g. заменик председника"))
        self.ed_auth_role.setToolTip(QCoreApplication.translate("IzmeneFeature","Role of the authorized person in OIK (lowercase)"))
        self.ed_auth_role.editingFinished.connect(self._save_auth_fields)
        auth_form.addRow(QCoreApplication.translate("IzmeneFeature","Role in OIK:"), self.ed_auth_role)

        body_vbox.addWidget(self._auth_frame)
        section.set_content(body)

        self.sw_delegated.toggled.connect(self._on_auth_radio_changed)

    def _build_obrazlozenje_section(self, left: QVBoxLayout) -> None:
        left.addWidget(_div())
        left.addWidget(_section_label(QCoreApplication.translate("IzmeneFeature","Образложење paragraphs")))

        self._cards_host = QWidget()
        self._cards_layout = QVBoxLayout(self._cards_host)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(6)
        left.addWidget(self._cards_host)

        btn_row = QHBoxLayout()
        btn_row.addStretch()  # centers the button cluster (Windows 11 taskbar style)
        btn_add = QPushButton(QCoreApplication.translate("IzmeneFeature","+ Add paragraph"))
        btn_add.clicked.connect(self._on_add_card)
        btn_row.addWidget(btn_add)
        btn_reset = QPushButton(QCoreApplication.translate("IzmeneFeature","Reset to default"))
        btn_reset.clicked.connect(self._on_reset_obrazlozenje)
        btn_row.addWidget(btn_reset)
        btn_row.addStretch()
        left.addLayout(btn_row)

    def _build_generate_row(self) -> QWidget:
        """Compact button row matching Phase3Tab's bottom action strip."""
        row = QWidget()
        lay = QVBoxLayout(row)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(4)

        self.lbl_gen_status = QLabel("")
        self.lbl_gen_status.setObjectName("MutedLabel")
        self.lbl_gen_status.setWordWrap(True)
        lay.addWidget(self.lbl_gen_status)

        btns = QHBoxLayout()
        self.btn_open_out = QPushButton(QCoreApplication.translate("IzmeneFeature","Open folder"))
        self.btn_open_out.setVisible(False)
        self.btn_open_out.clicked.connect(self._open_folder)
        btns.addWidget(self.btn_open_out)
        btns.addStretch()
        self.btn_generate = QPushButton(QCoreApplication.translate("IzmeneFeature","Generate amendment decision…"))
        self.btn_generate.setObjectName("PrimaryButton")
        self.btn_generate.clicked.connect(self._on_generate)
        btns.addWidget(self.btn_generate)
        lay.addLayout(btns)

        return row

    # ── Lock state ────────────────────────────────────────────────────────────

    @log_timing("IzmenaPanel._refresh_lock_state")
    def _refresh_lock_state(self) -> None:
        gl = self.state.generation_log
        slug = self._spec.slug
        unlocked = gl.is_izmena_mode(slug)
        self.btn_generate.setEnabled(unlocked)
        if unlocked:
            self.lbl_locked.setVisible(False)
        else:
            wl = gl.workflow(slug)
            if not wl.phase3_done():
                msg = QCoreApplication.translate("IzmeneFeature",
                    "Amendments unavailable — generate decisions first (tab 4. Decisions)."
                )
            else:
                msg = QCoreApplication.translate("IzmeneFeature",
                    "Amendments unavailable — confirm submission to RIK first"
                    " (tab 4. Decisions → 'Submitted to RIK' button)."
                )
            self.lbl_locked.setText(msg)
            self.lbl_locked.setVisible(True)

    # ── Legal basis ───────────────────────────────────────────────────────────

    def _lb_key(self) -> str:
        return (
            "izmena_legal_basis_prosireni"
            if self._spec.slug == "prosireni"
            else "izmena_legal_basis_stalni"
        )

    def _load_legal_basis(self) -> None:
        if self._loading:
            return
        slug = self._spec.slug
        ec = self.state.election
        saved = getattr(ec.document, self._lb_key(), "") or ""
        text = saved or _DEFAULT_LEGAL_BASIS[slug]
        if self.ed_legal_basis.toPlainText() == text:
            return  # setPlainText fires textChanged -> a redundant preview render
        self._loading = True
        try:
            self.ed_legal_basis.setPlainText(text)
        finally:
            self._loading = False

    def _save_legal_basis(self) -> None:
        ec = self.state.election
        new_val = self.ed_legal_basis.toPlainText().strip()
        if getattr(ec.document, self._lb_key(), None) == new_val:
            return
        setattr(ec.document, self._lb_key(), new_val)
        try:
            self.state.save_resenja_fields()
        except OSError as e:
            self.banner.show_error(QCoreApplication.translate("IzmeneFeature","Cannot save: {e}").format(e=e))

    def _on_reset_legal_basis(self) -> None:
        slug = self._spec.slug
        self._loading = True
        try:
            self.ed_legal_basis.setPlainText(_DEFAULT_LEGAL_BASIS[slug])
        finally:
            self._loading = False
        self._save_legal_basis()
        self._refresh_preview()

    # ── Auth ──────────────────────────────────────────────────────────────────

    def _on_auth_radio_changed(self, checked: bool) -> None:
        self._auth_frame.setVisible(self.sw_delegated.isChecked())
        if not self._loading:
            self._save_auth_fields()
            self._refresh_preview()

    def _load_auth_fields(self) -> None:
        if self._loading:
            return
        doc = self.state.election.document
        self._loading = True
        try:
            use_auth = doc.use_authorization
            self.sw_delegated.setChecked(use_auth)
            self._auth_frame.setVisible(use_auth)
            self.ed_auth_number.setText(doc.authorization_number)
            # Stored value is a genitive date PHRASE ("6. децембра 2023.
            # године"), not an ISO date — parse_serbian_date accepts
            # either nominative or genitive form (legacy tolerance).
            # Unparseable/empty (e.g. nothing saved yet) leaves the
            # picker at its own default (today), same as dt_issue_date
            # never round-trips a stored value either.
            parsed_auth_date = parse_serbian_date(doc.authorization_date)
            if parsed_auth_date is not None:
                y, m, d = parsed_auth_date
                self.ed_auth_date.setDate(QDate(y, m, d))
            self.ed_auth_name.setText(doc.authorized_name)
            self.ed_auth_role.setText(doc.authorized_role)
        finally:
            self._loading = False

    def _save_auth_fields(self) -> None:
        if self._loading:
            return
        doc = self.state.election.document
        doc.use_authorization = self.sw_delegated.isChecked()
        doc.authorization_number = self.ed_auth_number.text().strip()
        doc.authorization_date = _qdate_to_genitive(self.ed_auth_date.date())
        doc.authorized_name = self.ed_auth_name.text().strip()
        doc.authorized_role = self.ed_auth_role.text().strip()
        try:
            self.state.save_resenja_fields()
        except OSError as e:
            self.banner.show_error(QCoreApplication.translate("IzmeneFeature","Cannot save: {e}").format(e=e))

    # ── Образложење cards ─────────────────────────────────────────────────────

    def _obraz_path(self) -> Path:
        return app_paths.izmena_obrazlozenje_path_for(self._spec.slug)

    def _load_obrazlozenje_cards(self) -> None:
        for card in self._cards():
            self._cards_layout.removeWidget(card)
            card.deleteLater()
        paragraphs = load_izmena_obrazlozenje(self._spec.slug, self._obraz_path())
        for p in paragraphs:
            self._append_card(p)
        self._refresh_preview()

    def _save_obrazlozenje(self) -> None:
        from biracki_odbor.config import obrazlozenje as obr_mod
        paragraphs = [c.to_paragraph() for c in self._cards()]
        try:
            obr_mod.save(paragraphs, self._obraz_path())
        except OSError as e:
            self.banner.show_error(QCoreApplication.translate("IzmeneFeature","Cannot save образложење: {e}").format(e=e))
        self._refresh_preview()

    def _append_card(self, paragraph) -> None:
        card = ObrazlozenjeCard(
            paragraph,
            on_changed=self._save_obrazlozenje,
            on_remove=self._remove_card,
            on_move_up=self._move_card_up,
            on_move_down=self._move_card_down,
        )
        self._cards_layout.addWidget(card)

    def _cards(self) -> list[ObrazlozenjeCard]:
        result = []
        for i in range(self._cards_layout.count()):
            item = self._cards_layout.itemAt(i)
            if item is None:
                continue
            w = item.widget()
            if isinstance(w, ObrazlozenjeCard):
                result.append(w)
        return result

    def _on_focus_changed(self, _old, new) -> None:
        for card in self._cards():
            is_active = new is not None and (new is card or card.isAncestorOf(new))
            card.set_active(is_active)
            if is_active:
                self._left_scroll.ensureWidgetVisible(card)
                # Anchored by the card's own stable id (matches
                # _refresh_preview's anchor_marker), NOT its position in
                # self._cards() -- render_izmena_obrazlozenje() can drop
                # optional/ovlascenje paragraphs, so a card's position
                # here and its paragraph's position in the rendered
                # output can diverge.
                self._preview.scroll_to_anchor(f"card_{card.paragraph_id}")
        if new is None:
            return

        def _has_focus(widget) -> bool:
            return new is widget or widget.isAncestorOf(new)

        lb_fields = [w for w in (
            getattr(self, "ed_legal_basis", None), getattr(self, "dt_issue_date", None),
        ) if w is not None]
        if any(_has_focus(w) for w in lb_fields):
            self._preview.scroll_to_anchor("legal_basis")

    def _remove_card(self, card: ObrazlozenjeCard) -> None:
        self._cards_layout.removeWidget(card)
        card.deleteLater()
        self._save_obrazlozenje()

    def _move_card_up(self, card: ObrazlozenjeCard) -> None:
        cards = self._cards()
        idx = cards.index(card)
        if idx == 0:
            return
        self._cards_layout.removeWidget(card)
        self._cards_layout.insertWidget(idx - 1, card)
        self._save_obrazlozenje()

    def _move_card_down(self, card: ObrazlozenjeCard) -> None:
        cards = self._cards()
        idx = cards.index(card)
        if idx >= len(cards) - 1:
            return
        self._cards_layout.removeWidget(card)
        self._cards_layout.insertWidget(idx + 1, card)
        self._save_obrazlozenje()

    def _on_add_card(self) -> None:
        from biracki_odbor.config.obrazlozenje import Paragraph, Segment
        new_p = Paragraph(id=f"para-{len(self._cards()) + 1}", segments=[Segment("", False)])
        self._append_card(new_p)
        self._save_obrazlozenje()

    def _on_reset_obrazlozenje(self) -> None:
        reply = QMessageBox.question(
            self, QCoreApplication.translate("IzmeneFeature","Reset образложење"),
            QCoreApplication.translate("IzmeneFeature",
                "Reset all paragraphs to the built-in defaults"
                " for this composition type?"
            ),
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel,
        )
        if reply != QMessageBox.Yes:
            return
        self._obraz_path().unlink(missing_ok=True)
        self._load_obrazlozenje_cards()

    # ── Preview ───────────────────────────────────────────────────────────────

    def _refresh_prestanak_preview(self) -> None:
        from biracki_odbor.core.prestanak_docx import SASTAV_LOCATIVE

        spec = self._prestanak_editor.collect_spec()
        if spec is None:
            missing = self._prestanak_editor.missing_fields()
            html = (
                "<html><body style='font-family:serif;font-size:12px;"
                "color:#888;font-style:italic;margin:16px 24px'>"
                + QCoreApplication.translate(
                    "IzmeneFeature", "Fill in: {fields}",
                ).format(fields=", ".join(missing))
                + "</body></html>"
            )
            self._preview.set_html(html)
            return

        mun_name = spec.municipality or "…"
        own = self.state.oik.municipality
        terms = terms_for(vrsta_for(own.sifra_opstine), mun_name,
                          own.name_genitive if mun_name == own.name else "",
                          own.name_locative if mun_name == own.name else "",
                          own.full_committee_name)
        other = (spec.existing_municipality or "").strip()
        existing_in_unit = f"у општини {other}" if other and other != mun_name else terms.in_unit
        ceasing_loc = SASTAV_LOCATIVE.get(spec.ceasing_sastav, spec.ceasing_sastav)
        existing_loc = SASTAV_LOCATIVE.get(spec.existing_sastav, spec.existing_sastav)
        legal_text = (spec.legal_basis or "").replace("\n", "<br>")
        html = f"""
<html>
<body style="font-family:serif;font-size:12px;line-height:1.6;color:#000;margin:16px 24px">
<p>{legal_text}</p>
<p><b>{terms.preamble_subject}</b>, на седници одржаној {spec.session_date}, доноси</p>
<h2 style="text-align:center;font-size:14px;letter-spacing:2px;margin:12px 0 4px">
Р&nbsp;Е&nbsp;Ш&nbsp;Е&nbsp;Њ&nbsp;Е
</h2>
<p>1. УТВРЂУЈЕ СЕ да <b>{spec.person_name}</b> по сили закона престаје функција
<b>{spec.ceasing_role}</b> бирачког одбора у {ceasing_loc} саставу на бирачком месту број
<b>{spec.ceasing_bm}</b> {terms.in_unit}, јер је именован за <b>{spec.existing_role}</b>
бирачког одбора у {existing_loc} саставу на бирачком месту број <b>{spec.existing_bm}</b>
{existing_in_unit}.</p>
<p>2. Ово решење ступа на снагу даном доношења.</p>
<p>3. Ово решење објавити.</p>
<hr style="margin:8px 0">
<p>{spec.document_broj}</p>
</body>
</html>
"""
        self._preview.set_html(html)

    @log_timing("IzmenaPanel._refresh_preview")
    def _refresh_preview(self) -> None:
        if not hasattr(self, "_preview"):
            return
        if self._mode == "prestanak":
            self._refresh_prestanak_preview()
            return
        oik = self.state.oik
        election = self.state.election
        slug = self._spec.slug
        is_prosireni = slug == "prosireni"
        mun_name = oik.municipality.name or "…"
        terms = commission_terms(oik.municipality)
        # точка 1/2/3 and each item line have no per-paragraph override in
        # the real generator (core.izmene_docx.py) -- they inherit the
        # Normal style default, i.e. fmt.body_before_pt/body_after_pt.
        # Mirrored here so the preview responds to the spacing bar.
        body_margin = pt_margin_css(
            oik.document_format.body_before_pt, oik.document_format.body_after_pt,
        )

        issue_date = ""
        if hasattr(self, "dt_issue_date"):
            issue_date = _qdate_to_genitive(self.dt_issue_date.date())

        original_broj = self._derived_original_broj
        original_date = self._derived_original_date

        use_auth = (
            self.sw_delegated.isChecked() if hasattr(self, "sw_delegated") else True
        )
        auth_number = (
            self.ed_auth_number.text().strip() if hasattr(self, "ed_auth_number") else ""
        )
        auth_date_val = (
            _qdate_to_genitive(self.ed_auth_date.date()) if hasattr(self, "ed_auth_date") else ""
        )
        auth_name = (
            self.ed_auth_name.text().strip() if hasattr(self, "ed_auth_name") else ""
        )
        auth_role = (
            self.ed_auth_role.text().strip() if hasattr(self, "ed_auth_role") else ""
        )
        auth_ref = (
            f"број {auth_number} од {auth_date_val}"
            if (auth_number and use_auth) else ""
        )

        bm_num = self._selected_bm
        amendment_idx = self._derived_amendment_idx

        if is_prosireni:
            subtitle = (
                "О ИЗМЕНАМА РЕШЕЊА О ИМЕНОВАЊУ ЧЛАНОВА"
                " И ЗАМЕНИКА ЧЛАНОВА БИРАЧКОГ ОДБОРА"
            )
            comp_upper = "У ПРОШИРЕНОМ САСТАВУ"
            comp_lower = "проширеном саставу"
        else:
            subtitle = (
                "О ИЗМЕНАМА РЕШЕЊА О ИМЕНОВАЊУ ПРЕДСЕДНИКА И ЧЛАНОВА"
                " БИРАЧКОГ ОДБОРА И ЊИХОВИХ ЗАМЕНИКА"
            )
            comp_upper = "У СТАЛНОМ САСТАВУ"
            comp_lower = "сталном саставу"

        if bm_num is not None:
            amendment_broj = (
                format_amendment_broj(original_broj, amendment_idx, amendment_idx)
                if original_broj else "Број: …"
            )
            records = self._selected_records or []
        else:
            amendment_broj = "Број: …"
            records = []

        original_ref = (
            f"<b>број {original_broj} од {original_date}</b>"
            if original_broj else "<b>…</b>"
        )

        station = oik.station_by_bm(bm_num) if bm_num is not None else None
        bm_name = ""
        if station:
            bm_name = (getattr(station, "full_name", None) or station.name).upper()

        if records:
            items_html = "".join(
                f"<p style='margin:{body_margin}'>{_izmena_item_html(i, r)}</p>"
                for i, r in enumerate(records, 1)
            )
        elif bm_num is not None:
            items_html = (
                "<p style='color:#888;font-style:italic'>"
                "(Нема измена у дневнику за ово бирачко место)</p>"
            )
        else:
            items_html = (
                "<p style='color:#888;font-style:italic'>"
                "(Изаберите бирачко место из табеле измена изнад)</p>"
            )

        date_suffix = f", {issue_date}" if issue_date else ""

        if hasattr(self, "_cards_layout"):
            from biracki_odbor.config import obrazlozenje as obr_mod
            paragraphs = [c.to_paragraph() for c in self._cards()]
            rendered = render_izmena_obrazlozenje(
                paragraphs,
                use_authorization=use_auth,
                auth_ref=auth_ref,
                auth_name=auth_name,
                auth_role=auth_role,
                opstina=mun_name,
                commission=terms,
            )
            # render_izmena_obrazlozenje() silently drops any optional
            # paragraph and (when use_authorization is off) the
            # 'ovlascenje' paragraph -- so its output can be shorter
            # than, and at different positions from, self._cards(). Same
            # fix as Phase3Tab: anchor by the paragraph's own stable id,
            # computed with the identical two-condition filter, not by
            # plain position.
            active_ids = [
                p.id for p in paragraphs
                if not getattr(p, "optional", False)
                and not (not use_auth and getattr(p, "id", "") == "ovlascenje")
            ]
            obraz_html = "".join(
                anchor_marker(f"card_{pid}")
                + f"<p style='margin:{body_margin}'>"
                + "".join(
                    f"<b>{text}</b>" if bold else text
                    for text, bold in segs
                )
                + "</p>"
                for pid, segs in zip(active_ids, rendered)
            ) or "<p style='color:#888;font-style:italic'>(No образложење paragraphs)</p>"
        else:
            obraz_html = "<p style='color:#888;font-style:italic'>[loading…]</p>"

        lb_text = (
            self.ed_legal_basis.toPlainText().strip()
            if hasattr(self, "ed_legal_basis") else ""
        )
        if lb_text:
            lb_html = "".join(
                f"<p style='margin:2px 0'>{line}</p>"
                for line in lb_text.splitlines() if line.strip()
            )
            if use_auth and auth_ref:
                lb_html += (
                    f"<p style='margin:2px 0'>и Решења о давању овлашћења …"
                    f" <b>{auth_ref}</b>,</p>"
                )
            else:
                lb_html += "<p style='margin:2px 0'>,</p>"
        else:
            lb_html = (
                f"<p>На основу члана 32. тачка 2) и"
                f" <b>{'члана 39 став 1.' if is_prosireni else 'члана 35.'}</b>"
                f" и 41. Закона о избору народних посланика"
                f" (&ldquo;Службени гласник РС&rdquo;, бр. 35/00 &hellip; 14/22)"
                + (
                    f",<br>и Решења о давању овлашћења &hellip; <b>{auth_ref}</b>,"
                    if auth_ref else ","
                )
                + "</p>"
            )

        if use_auth:
            signer = auth_name.upper() or "…"
            signer_role = auth_role or "овлашћено лице"
        else:
            signer = (oik.chairman.name or "…").upper()
            signer_role = oik.chairman.title or "председник"

        bm_display = bm_num if bm_num is not None else "…"

        html = f"""
<html>
<body style="font-family:serif;font-size:12px;line-height:1.6;color:#000;margin:16px 24px">
{anchor_marker("legal_basis")}
{lb_html}
<p><b>овлашћено лице {terms.head_gen} {terms.unit_gen}{date_suffix}</b>, доноси</p>

<h2 style="text-align:center;font-size:14px;letter-spacing:2px;margin:12px 0 4px">
Р&nbsp;Е&nbsp;Ш&nbsp;Е&nbsp;Њ&nbsp;Е
</h2>
<p style="text-align:center;margin:2px 0"><b>{subtitle}</b></p>
<p style="text-align:center;margin:2px 0"><b>- {comp_upper} -</b></p>
<p style="text-align:center;margin:8px 0 2px">
  <b>ЗА БИРАЧКО МЕСТО БРОЈ {bm_display}. {terms.in_unit.upper()}</b>
</p>
<p style="text-align:center;margin:2px 0 12px"><b>{bm_name}</b></p>

<hr style="margin:8px 0">

<p style="margin:{body_margin}">1. Мења се Решење о именовању председника и чланова бирачког одбора и
њихових заменика у {comp_lower} за бирачко место број <b>{bm_display}.</b>
{terms.in_unit}, {original_ref}, тако што се у бирачки одбор:</p>

{items_html}

<p style="margin:{body_margin}">2. Ово решење објавити у Службеном гласнику Републике Србије.</p>
<p style="margin:{body_margin}">3. Решење је коначно и примењује се одмах.</p>

<p style="text-align:center;margin-top:16px;page-break-before:always">
  <b>О&nbsp;б&nbsp;р&nbsp;а&nbsp;з&nbsp;л&nbsp;о&nbsp;ж&nbsp;е&nbsp;њ&nbsp;е</b>
</p>
{obraz_html}

<hr style="margin:8px 0">
{anchor_marker("broj")}
<p>{amendment_broj},</p>
<p style="text-align:center">
  <b>{" ".join(terms.signature_lines)}</b>
</p>
<p style="text-align:center">{signer_role}</p>
<p style="text-align:center"><b>{signer}</b></p>
</body>
</html>
"""
        self._preview.set_html(html)

    # ── Election changed ──────────────────────────────────────────────────────

    @log_timing("IzmenaPanel._on_election_changed")
    def _on_election_changed(self) -> None:
        self._load_legal_basis()
        self._load_auth_fields()
        self.spacing_bar.reload()
        if self._selected_bm is not None:
            self._refresh_bm_info()
        self._refresh_preview()

    # ── Generate ──────────────────────────────────────────────────────────────

    def _on_generate_prestanak(self) -> None:
        from biracki_odbor.core.prestanak_docx import generate_prestanak

        spec = self._prestanak_editor.collect_spec()
        if spec is None:
            missing = self._prestanak_editor.missing_fields()
            QMessageBox.warning(
                self, QCoreApplication.translate("IzmeneFeature", "Missing information"),
                QCoreApplication.translate("IzmeneFeature", "Fill in: {fields}").format(
                    fields=", ".join(missing),
                ),
            )
            return
        try:
            out_path = generate_prestanak(
                spec, self.state.oik, self.state.election, app_paths.prestanak_dir(),
            )
        except OSError as exc:
            QMessageBox.critical(
                self, QCoreApplication.translate("IzmeneFeature", "Generation error"), str(exc),
            )
            return
        self.state.export_generated("Решења о престанку функције", [out_path])
        self.lbl_gen_status.setText(
            QCoreApplication.translate("IzmeneFeature","Decision saved: <b>{name}</b>").format(name=out_path.name)
        )
        self.btn_open_out.setVisible(True)
        self.banner.show_info(
            QCoreApplication.translate("IzmeneFeature","Generated: {name}").format(name=out_path.name)
        )

    def _on_generate(self) -> None:
        if self._mode == "prestanak":
            self._on_generate_prestanak()
            return
        if self._selected_bm is None:
            QMessageBox.warning(
                self, QCoreApplication.translate("IzmeneFeature","No BM selected"),
                QCoreApplication.translate("IzmeneFeature",
                    "Click a row in the changes table to select a polling station."
                ),
            )
            return

        bm_num = self._selected_bm
        oik = self.state.oik
        election = self.state.election

        if not oik.municipality.name.strip():
            QMessageBox.warning(
                self, QCoreApplication.translate("IzmeneFeature","Missing configuration"),
                QCoreApplication.translate("IzmeneFeature",
                    "Municipality name is not set."
                    " Fill in OIK Settings before generating."
                ),
            )
            return

        records = self._selected_records

        if not records:
            QMessageBox.warning(
                self, QCoreApplication.translate("IzmeneFeature","No changes"),
                QCoreApplication.translate("IzmeneFeature",
                    "No replacements recorded for BM {bm} in the corrections log."
                    " Make changes in the Corrections tab first."
                ).format(bm=bm_num),
            )
            return

        use_auth = self.sw_delegated.isChecked()
        if use_auth:
            # Authorization date isn't in this list: a QDateEdit always
            # holds a valid date (defaults to today), so "missing" isn't
            # a state it can be in — unlike the free-text field it used
            # to be, which could genuinely be left blank.
            missing = [
                lbl for lbl, val in [
                    (QCoreApplication.translate("IzmeneFeature","Authorization number"), self.ed_auth_number.text().strip()),
                    (QCoreApplication.translate("IzmeneFeature","Authorized person"), self.ed_auth_name.text().strip()),
                    (QCoreApplication.translate("IzmeneFeature","Role in OIK"), self.ed_auth_role.text().strip()),
                ]
                if not val
            ]
            if missing:
                QMessageBox.warning(
                    self, QCoreApplication.translate("IzmeneFeature","Missing authorization fields"),
                    QCoreApplication.translate("IzmeneFeature",
                        "Authorization is enabled but these fields are empty:\n  • {fields}\n\n"
                        "Fill them in or select 'Непосредно' above."
                    ).format(fields="\n  • ".join(missing)),
                )
                return

        station = oik.station_by_bm(bm_num)
        bm_name = ""
        if station:
            bm_name = (getattr(station, "full_name", None) or station.name).upper()

        issue_date = _qdate_to_genitive(self.dt_issue_date.date())

        self._save_auth_fields()
        self._save_legal_basis()

        wl = self.state.generation_log.workflow(self._spec.slug)
        # `records` is already one track's group (the grouped sections
        # guarantee that — see _group_all_records_by_variant) — one
        # selection, one document.
        amendment_index = wl.next_amendment_index(bm_num)
        spec = IzmenaSpec(
            bm_number=bm_num,
            bm_name=bm_name,
            original_broj=self._derived_original_broj,
            original_date=self._derived_original_date,
            amendment_index=amendment_index,
            amendment_counter=amendment_index,
            issue_date=issue_date,
            records=records,
            slug=self._spec.slug,
        )
        try:
            out_path = generate_izmena(
                spec, oik, election,
                app_paths.izmene_dir(),
                obraz_path=self._obraz_path(),
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, QCoreApplication.translate("IzmeneFeature","Generation error"), str(exc))
            return
        wl.record_izmena(bm_num)
        out_paths = [out_path]

        self.state.save_generation_log()
        self.state.export_generated("Измене", out_paths)

        self._refresh_changes_table()
        names = ", ".join(p.name for p in out_paths)
        self.lbl_gen_status.setText(
            QCoreApplication.translate("IzmeneFeature","Decision saved: <b>{name}</b>").format(name=names)
        )
        self.btn_open_out.setVisible(True)
        self.banner.show_info(QCoreApplication.translate("IzmeneFeature","Generated: {name}").format(name=names))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _open_folder(self) -> None:
        # Confirm where, even when it worked — the window can land behind
        # a maximised app or on a second display that is switched off,
        # making a working button look dead.
        purpose = "Решења о престанку функције" if self._mode == "prestanak" else "Измене"
        folder = self.state.files_dir(purpose)
        try:
            subprocess.Popen(["explorer", str(folder)])
        except OSError:
            QMessageBox.information(
                self,
                QCoreApplication.translate("IzmeneFeature","Folder"),
                QCoreApplication.translate("IzmeneFeature","Output folder:\n{folder}").format(folder=folder),
            )
            return
        self.banner.show_info(
            QCoreApplication.translate("IzmeneFeature","Opened folder: {folder}").format(folder=folder)
        )


# ── Stalni workflow tab (step 5) ──────────────────────────────────────────────


class IzmeneTab(QWidget):
    """Stalni workflow step 5 — amendment builder.

    Thin wrapper around IzmenaPanel(STALNI_SPEC) that exposes the
    navigate_to_corrections signal so MainWindow can wire it up.
    """

    navigate_to_corrections = Signal(str)  # carries before_jmbg

    def __init__(self, state: AppState) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        panel = IzmenaPanel(STALNI_SPEC, state, self.navigate_to_corrections.emit)
        outer.addWidget(panel)
