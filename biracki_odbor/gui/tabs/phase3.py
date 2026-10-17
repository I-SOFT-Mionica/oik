"""Фаза 3 — генерисање Word решења по бирачким местима."""

from __future__ import annotations

import logging
from pathlib import Path
import subprocess

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QApplication, QFormLayout, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QScrollArea, QSplitter, QVBoxLayout, QWidget,
)

from biracki_odbor.gui.widgets.toggle_switch import ToggleSwitch
from biracki_odbor.gui.widgets.obrazlozenje_card import ObrazlozenjeCard
from biracki_odbor.gui.widgets.paginated_preview import (
    PaginatedPreview, anchor_marker, pt_margin_css,
)
from biracki_odbor.gui.widgets.spacing_bar import DocumentSpacingBar


log = logging.getLogger(__name__)

from biracki_odbor import app_paths
from biracki_odbor.config.commission import commission_terms
from biracki_odbor.config import declension
from biracki_odbor.core.master_io import read_master
from biracki_odbor.core.phase3_docx import (
    Phase3Result, format_broj, generate_documents,
)
from biracki_odbor.core.workflow import STALNI_SPEC, WorkflowSpec
from biracki_odbor.gui.app_state import AppState
from biracki_odbor.gui.widgets.banner import StatusBanner
from biracki_odbor.gui.widgets.date_picker import make_date_picker
from biracki_odbor.gui.widgets.validators import (
    int_validator, separator_validator,
)
from biracki_odbor.gui.widgets.error_table import ErrorTable
from biracki_odbor.gui.worker import start_worker
from biracki_odbor.logging_setup import log_timing
from biracki_odbor.validation import preflight


# 2026 cycle citation — confirmed against the official RIK-distributed
# forms (biracki_odbor/new forms/1 1, 2 1). Unlike izmene.py's amendment
# citation, the initial appointment decision needs neither "члан 41"
# (that governs CHANGING an already-appointed member, not the first
# appointment) nor the Упутство source (that's specific to changes too).
# Phase 3 had no hardcoded default at all before this — the operator had
# to type the entire legal basis from scratch every cycle; this is a
# pre-fill, same "saved or default" pattern as izmene.py's, not a value
# ever silently forced over what the operator already typed/saved.
_DEFAULT_LEGAL_BASIS: dict[str, str] = {
    "stalni": (
        'На основу члана 32. тачка 2) и члана 35. Закона о избору'
        ' народних посланика ("Службени гласник РС", бр. 14/22 и 47/26),'
    ),
    "prosireni": (
        'На основу члана 32. тачка 2) и члана 39. став 1. Закона о избору'
        ' народних посланика ("Службени гласник РС", бр. 14/22 и 47/26),'
    ),
}


class Phase3Tab(QWidget):
    _master_integrity_error = None  # set by _read_master_safe(), read by callers

    def _read_master_safe(self, master):
        """`read_master(master, verify=True)`, but never raises.

        On a mismatch, stashes the error on `self._master_integrity_error`
        and returns None — CorrectionsTab (same master_changed signal)
        already owns the interactive restore dialog, so this stays
        passive: callers just show a disabled/blocked state.
        """
        from biracki_odbor.core.file_integrity import IntegrityMismatchError
        try:
            self._master_integrity_error = None
            return read_master(master, verify=True, spec=self._spec)
        except IntegrityMismatchError as e:
            self._master_integrity_error = e
            return None

    def __init__(self, state: AppState, *, spec: WorkflowSpec | None = None) -> None:
        super().__init__()
        self.state = state
        self._spec = spec if spec is not None else STALNI_SPEC
        self._export_purpose = "Решења" if self._spec.slug == "stalni" else "Решења (проширени)"
        self._obraz_path = app_paths.obrazlozenje_path_for(self._spec)
        self._loading = False

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel(self.tr("Decision generation"))
        title.setObjectName("TitleLabel")
        root.addWidget(title)

        # Spans the full tab width, above the splitter -- not confined to
        # the splitter's right pane, whose ~60% share of the window was
        # too narrow for a 5-control row and forced the left (editing)
        # pane down below its own content's width, clipping it.
        self.spacing_bar = DocumentSpacingBar(self.state)
        root.addWidget(self.spacing_bar)

        # ── Splitter ─────────────────────────────────────────────────────────
        split_row = QHBoxLayout()
        split_row.setContentsMargins(0, 0, 0, 0)
        split_row.setSpacing(4)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # Left: continuous editor in a hidden-bar scroll area
        self._left_scroll = QScrollArea()
        self._left_scroll.setWidgetResizable(True)
        self._left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._left_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_host = QWidget()
        left = QVBoxLayout(left_host)
        left.setContentsMargins(0, 0, 8, 0)
        left.setSpacing(10)
        self._left_scroll.setWidget(left_host)
        splitter.addWidget(self._left_scroll)

        # Right: preview (scrollable) + permanently-visible helper panel
        right_host = QWidget()
        right_vbox = QVBoxLayout(right_host)
        right_vbox.setContentsMargins(0, 0, 0, 0)
        right_vbox.setSpacing(0)

        self._preview = PaginatedPreview()
        # Cheat-sheet moved to a hover tooltip (was a permanent label
        # above the preview, crowding out the spacing bar's real estate).
        self._preview.setToolTip(self.tr(
            "Each card is 1 paragraph. <b>**text**</b> = bold. Saves automatically. "
            "Codes: <code>{odluka_rik}</code>, <code>{opstina}</code>, "
            "<code>{pod_stalni}</code>, <code>{dana_predlog}</code>, "
            "<code>{dana_imenovanje}</code>, <code>{pod_prosireni}</code>."
        ))

        right_vbox.addWidget(self._preview, stretch=1)

        splitter.addWidget(right_host)

        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 6)
        splitter.setSizes([380, 620])

        split_row.addWidget(splitter, stretch=1)
        root.addLayout(split_row, stretch=1)

        # ── Left panel content ─────────────────────────────────────────────

        # Section: Session
        left.addWidget(self._section_label(self.tr("Session")))
        session_form = QFormLayout()
        session_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.dt_session = make_date_picker()
        self.dt_session.dateChanged.connect(self._on_session_date_changed)
        session_form.addRow(self.tr("Session date:"), self.dt_session)
        self.ed_session_number = QLineEdit()
        self.ed_session_number.setPlaceholderText(self.tr("e.g. 5"))
        self.ed_session_number.setValidator(int_validator(min_value=1, max_value=999))
        self.ed_session_number.editingFinished.connect(self._save_session_fields)
        session_form.addRow(self.tr("Session number:"), self.ed_session_number)
        left.addLayout(session_form)

        # Section: Legal basis
        left.addWidget(self._div())
        left.addWidget(self._section_label(self.tr("Legal basis")))
        self.ed_legal = QPlainTextEdit()
        self.ed_legal.setMinimumHeight(80)
        self.ed_legal.setMaximumHeight(200)
        self.ed_legal.setPlaceholderText(self.tr(
            "Text of the law articles that will appear in the decision header…"
        ))
        self.ed_legal.focusOutEvent = self._wrap_focus_out(
            self.ed_legal.focusOutEvent, self._save_document_fields,
        )
        left.addWidget(self.ed_legal)

        # Section: Rationale — inline paragraph card editor
        left.addWidget(self._div())
        left.addWidget(self._section_label(self.tr("Rationale")))
        self._cards_host = QWidget()
        self._cards_layout = QVBoxLayout(self._cards_host)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(6)
        left.addWidget(self._cards_host)

        obraz_btns = QHBoxLayout()
        obraz_btns.addStretch()  # centers the button cluster (Windows 11 taskbar style)
        btn_add_para = QPushButton(self.tr("+ Add paragraph"))
        btn_add_para.clicked.connect(self._on_add_paragraph)
        obraz_btns.addWidget(btn_add_para)
        btn_reset = QPushButton(self.tr("Reset to default"))
        btn_reset.setToolTip(self.tr(
            "Restores the canonical legal text from the program."
            " All user edits will be lost."
        ))
        btn_reset.clicked.connect(self._on_reset_to_seed)
        obraz_btns.addWidget(btn_reset)
        obraz_btns.addStretch()
        left.addLayout(obraz_btns)

        # Section: Decision number
        left.addWidget(self._div())
        left.addWidget(self._section_label(self.tr("Decision number")))
        broj_form = QFormLayout()
        broj_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        _broj_tip = self.tr(
            "Each decision gets a label: prefix + separator + sub-number / year.\n"
            "The sub-number increments by 1 per polling station."
        )
        self.ed_num_prefix = QLineEdit()
        self.ed_num_prefix.setPlaceholderText(self.tr("e.g. 013-5-30"))
        self.ed_num_prefix.setToolTip(_broj_tip)
        self.ed_num_prefix.editingFinished.connect(self._save_document_fields)
        broj_form.addRow(self.tr("Number prefix:"), self.ed_num_prefix)
        self.ed_subbroj_sep = QLineEdit()
        self.ed_subbroj_sep.setPlaceholderText(self.tr("e.g. - or /"))
        self.ed_subbroj_sep.setMaxLength(1)
        self.ed_subbroj_sep.setValidator(separator_validator())
        self.ed_subbroj_sep.setToolTip(_broj_tip)
        self.ed_subbroj_sep.editingFinished.connect(self._save_document_fields)
        broj_form.addRow(self.tr("Sub-number separator:"), self.ed_subbroj_sep)
        self.ed_subbroj_start = QLineEdit()
        self.ed_subbroj_start.setPlaceholderText(self.tr("e.g. 200"))
        self.ed_subbroj_start.setValidator(int_validator(min_value=0, max_value=999999))
        self.ed_subbroj_start.setToolTip(_broj_tip)
        self.ed_subbroj_start.editingFinished.connect(self._save_document_fields)
        broj_form.addRow(self.tr("Starting sub-number:"), self.ed_subbroj_start)
        left.addLayout(broj_form)

        left.addStretch(1)

        # ── Bottom: generation controls (full-width below splitter) ───────
        gen_box = QWidget()
        gen_layout = QVBoxLayout(gen_box)
        gen_layout.setContentsMargins(0, 4, 0, 0)
        gen_layout.setSpacing(4)
        self.banner = StatusBanner()
        gen_layout.addWidget(self.banner)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        gen_layout.addWidget(self.progress)
        self.errors = ErrorTable()
        gen_layout.addWidget(self.errors, stretch=1)
        self.lbl_email_stat = QLabel()
        self.lbl_email_stat.setObjectName("MutedLabel")
        gen_layout.addWidget(self.lbl_email_stat)
        btns = QHBoxLayout()
        self.btn_open = QPushButton(self.tr("Open decisions folder…"))
        self.btn_open.clicked.connect(self._open_folder)
        self.btn_open.setEnabled(False)
        btns.addWidget(self.btn_open)
        self.btn_send_members = QPushButton(self.tr("Send"))
        self.btn_send_members.setToolTip(self.tr(
            "Send decisions to members. Creates an Outlook/Thunderbird draft"
            " per member with the corresponding decision (.docx) as"
            " attachment. Works only for members with a filled email."
            " Drafts are NOT sent automatically."
        ))
        self.btn_send_members.setEnabled(False)
        self.btn_send_members.setVisible(self._spec.slug == "stalni")
        self.btn_send_members.clicked.connect(self._on_send_resenja_to_members)
        btns.addWidget(self.btn_send_members)
        btns.addStretch()
        self.btn_refresh = QPushButton(self.tr("Refresh checks"))
        self.btn_refresh.clicked.connect(self._refresh_preflight)
        btns.addWidget(self.btn_refresh)
        self.btn_run = QPushButton(self.tr("Run"))
        self.btn_run.setObjectName("PrimaryButton")
        self.btn_run.clicked.connect(self._run)
        btns.addWidget(self.btn_run)
        self.btn_submit_rik = QPushButton(self.tr("Submitted to RIK"))
        self.btn_submit_rik.setObjectName("DangerButton")
        self.btn_submit_rik.setToolTip(self.tr(
            "Marks decisions as submitted to RIK. After this step Phase 3\n"
            "cannot be re-run — corrections go through the Amendments tab."
        ))
        self.btn_submit_rik.setEnabled(False)
        self.btn_submit_rik.clicked.connect(self._on_submit_to_rik)
        btns.addWidget(self.btn_submit_rik)
        self.btn_revert_rik = QPushButton(self.tr("Withdraw submission"))
        self.btn_revert_rik.setToolTip(self.tr(
            "Cancels the 'Submitted to RIK' status. Available only if no"
            " amendment decisions have been issued."
        ))
        self.btn_revert_rik.setVisible(False)
        self.btn_revert_rik.clicked.connect(self._on_revert_rik)
        btns.addWidget(self.btn_revert_rik)
        gen_layout.addLayout(btns)
        root.addWidget(gen_box)

        # ── Focus tracking for active card border + preview anchor jump ─────
        _app = QApplication.instance()
        if isinstance(_app, QApplication):
            _app.focusChanged.connect(self._on_focus_changed)

        # ── State wiring ───────────────────────────────────────────────────
        _master_sig = (
            self.state.master_changed
            if self._spec.slug == "stalni"
            else self.state.prosireni_master_changed
        )
        _master_sig.connect(self._refresh_preflight)
        _master_sig.connect(self._refresh_preview)
        if self._spec.slug == "stalni":
            _master_sig.connect(self._refresh_email_stat)
        self.state.election_changed.connect(self._on_election_changed)
        self.state.resenja_fields_changed.connect(self._on_election_changed)
        self.state.document_format_changed.connect(self._refresh_preview)
        self.state.oik_changed.connect(self._refresh_preflight)
        self.state.oik_changed.connect(self._refresh_preview)
        self.state.generation_log_changed.connect(self._restore_open_btn)
        self.state.generation_log_changed.connect(self._update_rik_gate_ui)

        # ── Initial state ──────────────────────────────────────────────────
        self._reload_session_fields()
        self._reload_document_fields()
        self._load_obrazlozenje_cards()
        self._refresh_preflight()
        self._refresh_preview()
        if self._spec.slug == "stalni":
            self._refresh_email_stat()
        self._restore_open_btn()
        self._update_rik_gate_ui()

    # ── UI helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _section_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("SectionLabel")
        return lbl

    @staticmethod
    def _div() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        return line

    def _wrap_focus_out(self, original, after):
        """Compose a focusOutEvent with a save call after the default handler."""
        def handler(event):
            original(event)
            after()
        return handler

    # ── Focus tracking ───────────────────────────────────────────────────────

    def _on_focus_changed(self, _old, new) -> None:
        for card in self._cards():
            is_active = new is not None and (new is card or card.isAncestorOf(new))
            card.set_active(is_active)
            if is_active:
                self._left_scroll.ensureWidgetVisible(card)
                # Jumps the paginated preview to whichever real page this
                # card's paragraph landed on -- replaces the old percentage
                # scroll sync, which stopped meaning anything once the
                # right side renders discrete pages with blank gaps
                # between them instead of one continuous flow. Anchored
                # by the card's own stable id (matches _refresh_preview's
                # anchor_marker), NOT its position in self._cards() --
                # render() can drop optional paragraphs, so a card's
                # position here and its paragraph's position in the
                # rendered output can diverge.
                self._preview.scroll_to_anchor(f"card_{card.paragraph_id}")
        if new is None:
            return
        # Same anchor-jump mechanism for the other left-column fields that
        # map onto an identifiable spot in the preview -- not just cards.
        def _has_focus(widget) -> bool:
            return new is widget or widget.isAncestorOf(new)

        if any(_has_focus(w) for w in (self.dt_session, self.ed_session_number, self.ed_legal)):
            self._preview.scroll_to_anchor("legal_basis")
        elif any(_has_focus(w) for w in (
            self.ed_num_prefix, self.ed_subbroj_sep, self.ed_subbroj_start,
        )):
            self._preview.scroll_to_anchor("broj")

    # ── Образложење inline card management ────────────────────────────────

    def _load_obrazlozenje_cards(self) -> None:
        from biracki_odbor.config import obrazlozenje as obr_mod
        for card in self._cards():
            self._cards_layout.removeWidget(card)
            card.deleteLater()
        for p in obr_mod.load(path=self._obraz_path):
            self._append_card(p)

    def _append_card(self, paragraph) -> None:
        card = ObrazlozenjeCard(
            paragraph,
            on_changed=self._on_card_changed,
            on_remove=self._remove_card,
            on_move_up=self._move_card_up,
            on_move_down=self._move_card_down,
        )
        self._cards_layout.addWidget(card)

    def _cards(self) -> list[ObrazlozenjeCard]:
        result = []
        for i in range(self._cards_layout.count()):
            item = self._cards_layout.itemAt(i)
            if item is not None:
                w = item.widget()
                if isinstance(w, ObrazlozenjeCard):
                    result.append(w)
        return result

    def _on_card_changed(self) -> None:
        self._save_obrazlozenje()
        self._refresh_preview()

    def _save_obrazlozenje(self) -> None:
        from biracki_odbor.config import obrazlozenje as obr_mod
        paragraphs = [c.to_paragraph() for c in self._cards()]
        paragraphs = [p for p in paragraphs if any(s.text.strip() for s in p.segments)]
        if not paragraphs:
            return
        try:
            obr_mod.save(paragraphs, path=self._obraz_path)
        except OSError as e:
            log.warning("Phase3Tab: failed to save obrazlozenje: %s", e)

    def _remove_card(self, card: ObrazlozenjeCard) -> None:
        self._cards_layout.removeWidget(card)
        card.deleteLater()
        self._save_obrazlozenje()
        self._refresh_preview()

    def _move_card_up(self, card: ObrazlozenjeCard) -> None:
        cards = self._cards()
        idx = cards.index(card)
        if idx == 0:
            return
        self._cards_layout.removeWidget(card)
        self._cards_layout.insertWidget(idx - 1, card)
        self._save_obrazlozenje()
        self._refresh_preview()

    def _move_card_down(self, card: ObrazlozenjeCard) -> None:
        cards = self._cards()
        idx = cards.index(card)
        if idx >= len(cards) - 1:
            return
        self._cards_layout.removeWidget(card)
        self._cards_layout.insertWidget(idx + 1, card)
        self._save_obrazlozenje()
        self._refresh_preview()

    def _on_add_paragraph(self) -> None:
        from biracki_odbor.config import obrazlozenje as obr_mod
        new = obr_mod.Paragraph(
            id=f"custom-{len(self._cards()) + 1}",
            segments=[obr_mod.Segment("", bold=False)],
            optional=False,
        )
        self._append_card(new)
        bar = self._left_scroll.verticalScrollBar()
        if bar:
            bar.setValue(bar.maximum())
        self._save_obrazlozenje()

    def _on_reset_to_seed(self) -> None:
        if QMessageBox.question(
            self,
            self.tr("Reset to default"),
            self.tr("The current rationale text will be replaced with the standard legal text. Continue?"),
        ) != QMessageBox.StandardButton.Yes:
            return
        from biracki_odbor.config import obrazlozenje as obr_mod
        for card in self._cards():
            self._cards_layout.removeWidget(card)
            card.deleteLater()
        # default_paragraphs() picks стални's or прошиени's own seed by
        # inspecting self._obraz_path's filename -- the old
        # obr_mod._SEED_PARAGRAPHS module attribute this used to read was
        # stalni-only and always-stalni, and no longer exists at all since
        # the JSON-backed refactor (this crashed on every click for both
        # workflows; see test coverage for the regression).
        for p in obr_mod.default_paragraphs(path=self._obraz_path):
            self._append_card(p)
        self._save_obrazlozenje()
        self._refresh_preview()

    @log_timing("Phase3Tab._on_election_changed")
    def _on_election_changed(self) -> None:
        self._refresh_preflight()
        self._reload_session_fields()
        self._reload_document_fields()
        self._refresh_preview()

    # ── Session fields ─────────────────────────────────────────────────────

    @log_timing("Phase3Tab._reload_session_fields")
    def _reload_session_fields(self) -> None:
        if self.ed_session_number.hasFocus():
            return
        d = self.state.election.election.dates
        date_val = getattr(d, self._spec.session_date_field, "").strip()
        num_val = getattr(d, self._spec.session_number_field, "").strip()
        parsed = declension.parse_serbian_date(date_val)
        self.dt_session.blockSignals(True)
        if parsed is not None:
            y, m, day = parsed
            self.dt_session.setDate(QDate(y, m, day))
        else:
            self.dt_session.setDate(QDate.currentDate())
        self.dt_session.blockSignals(False)
        self._refresh_session_genitive_label()
        self.ed_session_number.setText(num_val)

    def _on_session_date_changed(self, _qdate: QDate) -> None:
        self._refresh_session_genitive_label()
        self._save_session_fields()

    def _refresh_session_genitive_label(self) -> None:
        d = self.dt_session.date()
        nominative = declension.format_serbian_date(d.year(), d.month(), d.day())
        self.dt_session.setToolTip(f"У решењу: {declension.to_genitive(nominative)}")

    def _save_session_fields(self) -> None:
        if self._loading:
            return
        d = self.state.election.election.dates
        qd = self.dt_session.date()
        nominative = declension.format_serbian_date(qd.year(), qd.month(), qd.day())
        new_date = declension.to_genitive(nominative)
        new_num = self.ed_session_number.text().strip()
        old_date = getattr(d, self._spec.session_date_field, "")
        old_num = getattr(d, self._spec.session_number_field, "")
        if new_date == old_date and new_num == old_num:
            self._refresh_preview()
            return
        setattr(d, self._spec.session_date_field, new_date)
        setattr(d, self._spec.session_number_field, new_num)
        try:
            self.state.save_resenja_fields()  # re-renders via resenja_fields_changed
        except OSError as e:
            QMessageBox.critical(self, self.tr("Error"), self.tr("Cannot save: {error}").format(error=e))
            self._refresh_preview()

    # ── Document / sub-broj fields ─────────────────────────────────────────

    @log_timing("Phase3Tab._reload_document_fields")
    def _reload_document_fields(self) -> None:
        if any(w.hasFocus() for w in (
            self.ed_num_prefix, self.ed_subbroj_sep,
            self.ed_subbroj_start, self.ed_legal,
        )):
            return
        ec = self.state.election
        self._loading = True
        try:
            self.ed_num_prefix.setText(
                getattr(ec.document, self._spec.number_prefix_field, "")
            )
            self.ed_subbroj_sep.setText(ec.election.dates.subbroj_separator or "-")
            self.ed_subbroj_start.setText(
                getattr(ec.election.dates, self._spec.subbroj_field, "")
            )
            saved_legal = getattr(ec.document, self._spec.resenja_legal_basis_key, "")
            self.ed_legal.setPlainText(
                saved_legal or _DEFAULT_LEGAL_BASIS.get(self._spec.slug, "")
            )
            self.spacing_bar.reload()
        finally:
            self._loading = False

    def _save_document_fields(self) -> None:
        if self._loading:
            return
        ec = self.state.election
        new_prefix = self.ed_num_prefix.text().strip()
        new_sep = self.ed_subbroj_sep.text().strip() or "-"
        new_start = self.ed_subbroj_start.text().strip()
        new_legal = self.ed_legal.toPlainText().strip()
        dates = ec.election.dates
        old_prefix = getattr(ec.document, self._spec.number_prefix_field, "")
        old_start = getattr(dates, self._spec.subbroj_field, "")
        old_legal = getattr(ec.document, self._spec.resenja_legal_basis_key, "")
        if (
            new_prefix == old_prefix
            and new_sep == (dates.subbroj_separator or "-")
            and new_start == old_start
            and new_legal == old_legal
        ):
            self._refresh_preview()
            return
        setattr(ec.document, self._spec.number_prefix_field, new_prefix)
        dates.subbroj_separator = new_sep
        setattr(dates, self._spec.subbroj_field, new_start)
        setattr(ec.document, self._spec.resenja_legal_basis_key, new_legal)
        try:
            self.state.save_resenja_fields()  # re-renders via resenja_fields_changed
        except OSError as e:
            QMessageBox.critical(self, self.tr("Error"), self.tr("Cannot save: {error}").format(error=e))
            self._refresh_preview()

    # ── Preview ────────────────────────────────────────────────────────────

    @staticmethod
    def _fmt_cutoff(iso: str) -> str:
        """Format an ISO date string as Serbian genitive for display / shortcode substitution."""
        if not iso:
            return ""
        try:
            y, m, d = (int(x) for x in iso.split("-"))
            nom = declension.format_serbian_date(y, m, d)
            return declension.to_genitive(nom)
        except Exception:  # noqa: BLE001
            return iso

    @staticmethod
    def _days_between_iso(iso_from: str, iso_to: str) -> int | None:
        """Return the "дана пре избора" count from iso_from to iso_to, or
        None if either date is missing/invalid.

        -1 vs. the raw calendar-day span: election day itself isn't
        counted as one of the "days before" -- Oct 9 is "15 dana pre
        izbora" for an Oct 25 election, not 16. Must match
        phase3_docx.py's identical computation for the generated
        decision, since this is only used to preview that same text."""
        if not iso_from or not iso_to:
            return None
        try:
            from datetime import date as _date
            fy, fm, fd = (int(x) for x in iso_from.split("-"))
            ty, tm, td = (int(x) for x in iso_to.split("-"))
            return (_date(ty, tm, td) - _date(fy, fm, fd)).days - 1
        except Exception:  # noqa: BLE001
            return None

    @log_timing("Phase3Tab._refresh_preview")
    def _refresh_preview(self) -> None:
        """Build a single HTML document simulating the first polling station's resolution."""
        ec = self.state.election
        oik = self.state.oik
        fmt = oik.document_format
        mun = oik.municipality
        terms = commission_terms(mun)
        chairman = oik.chairman
        stations = sorted(oik.polling_stations, key=lambda s: s.bm_number)

        # Compute cutoff values passed to obrazlozenje.render()
        dates = ec.election.dates
        cutoff_stalni_fmt = self._fmt_cutoff(dates.cutoff_stalni)
        cutoff_prosireni_fmt = self._fmt_cutoff(dates.cutoff_prosireni)

        # Derive election date ISO from date_full for day-count arithmetic
        election_iso = ""
        parsed_election = declension.parse_serbian_date(dates.date_full)
        if parsed_election:
            ey, em, ed_day = parsed_election
            election_iso = f"{ey:04d}-{em:02d}-{ed_day:02d}"

        days_proposal = self._days_between_iso(dates.cutoff_stalni, election_iso)
        days_appoint = self._days_between_iso(dates.cutoff_prosireni, election_iso)

        def missing(text: str) -> str:
            return f'<span style="color:#999;font-style:italic">{text}</span>'

        blocks: list[str] = []

        # Committee header (centered, bold)
        committee = mun.full_committee_name.strip()
        if committee:
            blocks.append(
                '<p style="text-align:center;font-weight:bold;margin:0 0 4px 0">'
                f'{committee.replace(chr(10), "<br>")}</p>'
            )
        else:
            blocks.append(f'<p>{missing("(нема пуног назива комисије у Поставке ИК)")}</p>')

        # Legal basis + opening sentence — one continuous paragraph in the document
        _dates = ec.election.dates
        session_date = (getattr(_dates, self._spec.session_date_field, "").strip()
                        or _dates.session_date.strip())
        s_num = (getattr(_dates, self._spec.session_number_field, "").strip()
                 or _dates.session_number.strip())
        if not session_date:
            session_clause = missing("(нема датума седнице)")
        elif s_num:
            session_clause = f"на {s_num}. седници одржаној {session_date}"
        else:
            session_clause = f"на седници одржаној {session_date}"
        muni_name = mun.name.strip() or missing("(нема назива општине)")
        preamble = terms.preamble_subject if mun.name.strip() else f"Општинска изборна комисија општине {muni_name}"

        legal = getattr(ec.document, self._spec.resenja_legal_basis_key, "").strip()
        blocks.append(anchor_marker("legal_basis"))
        blocks.append('<p style="font-weight:bold;margin:12px 0 2px 0">Правни основ:</p>')
        if legal:
            legal_inline = " ".join(ln.strip() for ln in legal.split("\n") if ln.strip())
            join = " " if legal_inline.endswith(",") else ", "
            blocks.append(
                f'<p style="margin:2px 0 4px 0;line-height:1.5">'
                f'{legal_inline}{join}'
                f'{preamble},'
                f' {session_clause}, донела је'
                f'</p>'
            )
        else:
            blocks.append(
                f'<p style="margin:2px 0 4px 0">'
                f'{missing("(нема правног основа)")} '
                f'{preamble},'
                f' {session_clause}, донела је'
                f'</p>'
            )

        # Resolution title block -- per-line margins mirror
        # core.phase3_docx._build_document()'s own per-paragraph calls
        # exactly, so the preview actually responds to the spacing bar:
        # subtitle/composition-mark/election-type line/РАСПИСАНИХ ЗА/
        # ЗА БИРАЧКО МЕСТО all use fmt.title_before_pt/title_after_pt.
        # "Р Е Ш Е Њ Е" itself keeps its fixed 12pt/12pt.
        title_margin = pt_margin_css(fmt.title_before_pt, fmt.title_after_pt)
        title_lines_html = [
            '<p style="margin:12pt 0 12pt 0;font-size:14pt;font-weight:bold;'
            'letter-spacing:3px">Р Е Ш Е Њ Е</p>',
            f'<p style="margin:{title_margin}">{self._spec.resenja_title_subtitle}</p>',
            f'<p style="margin:{title_margin};font-weight:bold">'
            f'{self._spec.resenja_composition_mark}</p>',
        ]
        expanded = ec.election.expanded_types(mun.name, terms.local_assembly)
        if expanded:
            multi = len(expanded) > 1
            for i, (_, t_upper) in enumerate(expanded):
                if t_upper.startswith("ИЗБОРА ЗА "):
                    suffix = t_upper[len("ИЗБОРА ЗА "):]
                    if i == 0:
                        # Mirrors core.phase3_docx's real generator — "ЗА
                        # ИЗБОРА ЗА" (missing СПРОВОЂЕЊЕ) isn't
                        # grammatical Serbian.
                        prefix_line = (
                            "ЗА КООРДИНИРАНО СПРОВОЂЕЊЕ ИЗБОРА ЗА" if multi
                            else "ЗА СПРОВОЂЕЊЕ ИЗБОРА ЗА"
                        )
                    else:
                        prefix_line = "И ИЗБОРА ЗА"
                else:
                    suffix = t_upper
                    if i == 0:
                        prefix_line = "ЗА КООРДИНИРАНО СПРОВОЂЕЊЕ" if multi else "ЗА"
                    else:
                        prefix_line = "И"
                # One line, matching the official RIK reference form
                # exactly (was two separate paragraphs — a non-bold
                # prefix glued to a bold type-name line — which didn't
                # match the reference at all).
                title_lines_html.append(
                    f'<p style="margin:{title_margin}">{prefix_line} <b>{suffix}</b></p>'
                )
        else:
            title_lines_html.append(f'<p>{missing("(нема изабраних врста избора)")}</p>')
        date_full = ec.election.dates.date_full.strip()
        date_html = (
            f"<b>{date_full.upper()}</b>" if date_full
            else missing("(нема датума избора)")
        )
        title_lines_html.append(
            f'<p style="margin:{title_margin}">РАСПИСАНИХ ЗА {date_html}</p>'
        )
        mun_upper = mun.name.upper() or missing("(нема назива)")
        bm_num_for_title = stations[0].bm_number if stations else None
        bm_num_html = (
            f"БРОЈ {bm_num_for_title}." if bm_num_for_title is not None
            else missing("(нема бирачких места у Поставке ИК)")
        )
        title_lines_html.append(
            f'<p style="margin:{title_margin}">'
            f'ЗА БИРАЧКО МЕСТО <b>{bm_num_html}</b> {terms.in_unit.upper() if mun.name.strip() else "У ОПШТИНИ " + mun_upper}</p>'
        )
        blocks.append(
            '<div style="text-align:center;margin:16px 0;'
            'border-top:1px solid #ccc;border-bottom:1px solid #ccc;padding:10px 0">'
            + "".join(title_lines_html)
            + '</div>'
        )

        # BM name/address — table-cell "signature line" preview (structural,
        # not covered by the spacing bar, same as the real member table).
        if stations:
            first = stations[0]
            bm_num = first.bm_number
            persons = None
            try:
                # Preview-only best effort — deliberately NOT verify=True:
                # this is a live-typing preview snippet, not a decision to
                # act on, so a tampered file just means the count silently
                # goes blank here (the real block is in _refresh_preflight).
                persons = read_master(app_paths.master_path_for(self._spec), spec=self._spec)
                n_filled = sum(1 for p in persons if p.bm_number == bm_num and p.is_filled)
                n_total = sum(1 for p in persons if p.bm_number == bm_num)
                count_note = (
                    f' <span style="color:#888;font-size:9pt">({n_filled}/{n_total})</span>'
                )
            except Exception:  # noqa: BLE001 — best-effort preview only
                # openpyxl can raise a variety of its own exceptions on a
                # corrupted/tampered file (zipfile.BadZipFile is NOT an
                # OSError subclass, so the narrower catch this used to
                # have let a bad master.xlsx crash tab construction).
                count_note = ""
            blocks.append(
                f'<div style="text-align:center;margin:10px 0">'
                f'<b>{first.full_name or first.name}</b><br>'
                f'<span style="color:#666">{first.address}</span>'
                f'{count_note}</div>'
            )

            # Member table — real appointed names for this BM, mirroring
            # core.phase3_docx._build_document()'s member_table loop
            # (same func_groups/labels/proposal text) so the operator
            # sees actual names instead of just a fill count.
            if persons is not None:
                bm_persons = [p for p in persons if p.bm_number == bm_num]
                member_by_func = {p.function: p for p in bm_persons}
                if self._spec.slug == "prosireni":
                    from biracki_odbor.core.prosireni_allocation import (
                        MEMBER_LABEL, SUBSTITUTE_LABEL, parse_slot_function, slot_function,
                    )
                    slot_indices: set[int] = set()
                    for p in bm_persons:
                        parsed = parse_slot_function(p.function)
                        if parsed is not None:
                            slot_indices.add(parsed[0])
                    func_groups = [
                        (f"{slot_idx})", [
                            (slot_function(MEMBER_LABEL, slot_idx), MEMBER_LABEL),
                            (slot_function(SUBSTITUTE_LABEL, slot_idx), SUBSTITUTE_LABEL),
                        ])
                        for slot_idx in sorted(slot_indices)
                    ]
                else:
                    func_groups = [
                        ("1)", [("Председник", "Председник"), ("Заменик председника", "Заменик председника")]),
                        ("2)", [("Члан 1", "Члан 1"), ("Заменик члана 1", "Заменик члана 1")]),
                        ("3)", [("Члан 2", "Члан 2"), ("Заменик члана 2", "Заменик члана 2")]),
                    ]
                from biracki_odbor.core.phase3_docx import _proposal_text
                rows_html = []
                for group_label, funcs in func_groups:
                    for i, (func_name, display_label) in enumerate(funcs):
                        person = member_by_func.get(func_name)
                        name_html = f"<b>{person.name}</b>" if person and person.name else missing("—")
                        mesto = person.mesto if person else ""
                        proposal_label, proposal_party = (
                            _proposal_text(
                                person.party, ec, oik.nacelnik_proposal_name,
                                appointed_by_nacelnik=person.appointed_by_nacelnik,
                            ) if person else ("", "")
                        )
                        proposal_html = (
                            f"{proposal_label}<br>{proposal_party}" if proposal_party
                            else proposal_label
                        )
                        rows_html.append(
                            "<tr>"
                            f'<td style="width:4%;vertical-align:top;padding:3px 8px 3px 0">'
                            f'{group_label if i == 0 else ""}</td>'
                            f'<td style="width:18%;vertical-align:top;padding:3px 8px">'
                            f'{display_label.lower()}</td>'
                            f'<td style="width:24%;vertical-align:top;padding:3px 8px">'
                            f'{name_html}</td>'
                            f'<td style="width:15%;vertical-align:top;padding:3px 8px">'
                            f'{mesto}</td>'
                            '<td style="width:39%;vertical-align:top;padding:3px 0;'
                            'font-size:9pt;color:#555">'
                            f'{proposal_html}</td>'
                            "</tr>"
                        )
                blocks.append(
                    '<table style="width:100%;border-collapse:collapse;margin:8px 0;font-size:10pt">'
                    + "".join(rows_html)
                    + "</table>"
                )

        # Body-group paragraphs below (RIK provision, points 2-3, legal
        # remedy) have NO explicit per-paragraph override in the real
        # generator — they inherit the Normal style default, i.e.
        # fmt.body_before_pt/body_after_pt. Mirrored here so the preview
        # actually responds to the spacing bar.
        body_margin = pt_margin_css(fmt.body_before_pt, fmt.body_after_pt)

        # RIK transitional provision
        rik_prov = self.state.election.rik_provision
        if rik_prov.active:
            rik_entry = rik_prov.members.get(stations[0].bm_number if stations else -1)
            if rik_entry and not rik_entry.member.is_empty:
                from biracki_odbor.config.election import rik_provision_articles
                articles = rik_provision_articles(ec.election.types)
                m = rik_entry.member
                d_part = ""
                if not rik_entry.deputy.is_empty:
                    dep = rik_entry.deputy
                    d_part = (
                        f'<br>заменик члана: <b>{dep.name}</b>'
                        + (f', {dep.address}' if dep.address else '')
                    )
                blocks.append(
                    f'<p style="text-align:justify;margin:{body_margin}">'
                    f'<i>{articles}, Републичка изборна комисија именовала је у бирачки одбор:</i><br>'
                    f'члан: <b>{m.name}</b>'
                    + (f', {m.address}' if m.address else '')
                    + d_part
                    + f'</p>'
                )

        # Disposition points 2-3 — the real document always has these
        # (phase3_docx.py's _build_document) regardless of what's filled
        # in; the text itself isn't operator-configurable, but the
        # paragraph spacing is (inherited body default, same as above).
        blocks.append(
            f'<p style="text-align:justify;margin:{body_margin}">'
            '<b>2.</b> Ово решење објављује се на веб-презентацији Републичке '
            'изборне комисије.</p>'
        )
        blocks.append(
            f'<p style="text-align:justify;margin:{body_margin}">'
            '<b>3.</b> Ово решење ступа на снагу даном објављивања.</p>'
        )

        # Образложење section -- forced onto its own page in the real
        # generator (paragraph_format.page_break_before = True); Qt's
        # QTextDocument honours the same CSS property under
        # PaginatedPreview's pageSize-based pagination.
        blocks.append(
            '<p style="font-weight:bold;margin:12px 0 4px 0;'
            'page-break-before:always">О б р а з л о ж е њ е</p>'
        )
        try:
            from biracki_odbor.config import obrazlozenje as obr_mod
            _local_elections = "local" in (ec.election.types or [])
            paragraphs = obr_mod.render(
                rik_decision=ec.election.rik_decision or "",
                municipality=mun.name or "",
                cutoff_stalni=cutoff_stalni_fmt,
                cutoff_prosireni=cutoff_prosireni_fmt,
                days_before_proposal=days_proposal if days_proposal is not None else 15,
                days_before_appointment=days_appoint if days_appoint is not None else 10,
                municipality_website=mun.website or "",
                local_elections=_local_elections,
                path=self._obraz_path,
                commission=terms,
            )
            if paragraphs:
                # render() silently drops optional paragraphs whose
                # condition isn't met, so its output can be shorter than
                # (and at different positions from) self._cards() -- a
                # plain positional card_i anchor would then point at the
                # wrong paragraph, or not exist at all, the moment any
                # optional paragraph sits earlier in the file. Anchor by
                # the paragraph's own stable id instead, using the exact
                # same inclusion rule render() just applied.
                active_ids = obr_mod.active_paragraph_ids(
                    path=self._obraz_path, local_elections=_local_elections,
                )
                for pid, segs in zip(active_ids, paragraphs):
                    para_html = "".join(
                        f"<b>{text}</b>" if bold else text
                        for text, bold in segs
                    )
                    blocks.append(
                        f'{anchor_marker(f"card_{pid}")}'
                        f'<p style="text-align:justify;margin:{body_margin};line-height:1.5">'
                        f'{para_html}</p>'
                    )
            else:
                blocks.append(f'<p>{missing("(нема параграфа образложења)")}</p>')
        except Exception:  # noqa: BLE001
            log.exception("phase3 preview: obrazlozenje render failed")
            blocks.append(f'<p>{missing("(грешка при учитавању образложења)")}</p>')

        # УПУТСТВО О ПРАВНОМ СРЕДСТВУ is now the last paragraph in the
        # obrazlozenje template itself (id "uputstvo-pravno-sredstvo"),
        # so it already rendered above as part of the obrazlozenje loop
        # -- no separate hardcoded block needed here anymore.

        # Footer: Број + место + датум
        if stations:
            broj = format_broj(ec, stations[0].bm_number, 0, spec=self._spec)
        else:
            broj = "Број: " + missing("(нема бројчаног префикса)")
        place_locative = mun.name_locative.strip()
        place_html = (
            f"У {place_locative}" if place_locative
            else missing("(нема локатива општине у Поставке ИК)")
        )
        date_footer = session_date if session_date else missing("(нема датума седнице)")
        blocks.append(anchor_marker("broj"))
        blocks.append(f'<p style="margin-top:16px">{broj}</p>')
        blocks.append(f'<p>{place_html}, {date_footer}</p>')

        # Signature block
        ch_title = chairman.title.strip() or "ПРЕДСЕДНИК"
        ch_name = chairman.name.strip()
        committee_footer = (
            committee.replace("\n", "<br>") if committee
            else missing("(нема назива комисије)")
        )
        name_html = ch_name if ch_name else missing("(нема имена председника)")
        blocks.append(
            f'<div style="text-align:center;margin-top:20px">'
            f'<b>{committee_footer}</b><br><br>'
            f'<b>{ch_title}</b><br>'
            f'{name_html}'
            f'</div>'
        )

        blocks.append(
            '<p style="margin-top:24px;color:#888;font-style:italic;font-size:9pt">'
            '↑ Приказ за прво бирачко место. '
            'Стварни документ генерише се за свако БМ засебно.'
            '</p>'
        )

        html = (
            '<html><head><style>'
            'body { font-family: "Times New Roman", Times, serif;'
            '       font-size: 12pt; line-height: 1.5; color: #1a1a1a; }'
            'p { margin: 3px 0; }'
            '</style></head><body>'
            + "\n".join(blocks)
            + "</body></html>"
        )
        self._preview.set_html(html)

    # ── Preflight ──────────────────────────────────────────────────────────

    @log_timing("Phase3Tab._refresh_preflight")
    def _refresh_preflight(self) -> None:
        # RIK submission gate: if already submitted, block Phase 3 re-run entirely.
        if self.state.generation_log.is_izmena_mode(self._spec.slug):
            self.btn_run.setEnabled(False)
            self.banner.show_warn(self.tr(
                "Decisions submitted to RIK. Corrections go through the Amendments tab."
            ))
            return

        master = app_paths.master_path_for(self._spec)
        persons = self._read_master_safe(master)
        if persons is None:
            e = self._master_integrity_error
            self.banner.show_error(
                self.tr(
                    "{name} was changed outside the application since it was"
                    " last verified ({when}). Resolve in Corrections before"
                    " generating decisions."
                ).format(name=e.path.name, when=e.verified_at)
            )
            self.btn_run.setEnabled(False)
            return
        # `master` is a shared committee DB spanning both workflows, so its
        # own existence no longer implies THIS workflow has any rows yet —
        # check the actual result instead (used to check master.exists()).
        if not persons:
            self.banner.show_warn(self.tr("Consolidated table does not exist. Run Phase 2."))
            self.btn_run.setEnabled(False)
            return
        persons = self._demo_scope(persons)
        parties = {p.party for p in persons if p.is_filled and p.party}
        report = preflight.preflight_phase3(
            master, self.state.oik, self.state.election, parties, spec=self._spec,
            persons=persons,
        )
        self.errors.set_report(report)
        if self._spec.require_all_slots_filled:
            empty_slots = [p for p in persons if not p.is_filled]
            if empty_slots and not report.errors:
                count_html = f"<b>{len(empty_slots)}</b>"
                self.banner.show_warn(
                    self.tr("{n} slot(s) not filled. Edit via Phase 2.5 or mark as chief appointment before generating decisions.").format(n=count_html)
                )
                self.btn_run.setEnabled(False)
                return
        # Проширені: empty slots are valid (party may choose not to participate
        # at a given BM) — never block generation for missing entries.
        if report.errors:
            n = len(report.errors)
            error_word = declension.count_word(
                n, self.state.app_settings.ui_language,
                "error", "errors", "грешку", "грешке", "грешака",
            )
            self.banner.show_error(
                self.tr("Pre-flight has {n} {error_word}.").format(n=n, error_word=error_word)
            )
            self.btn_run.setEnabled(False)
        elif report.warnings:
            self.banner.show_warn(
                self.tr("Pre-flight: {n} warning(s). You can run Phase 3.").format(n=len(report.warnings))
            )
            self.btn_run.setEnabled(True)
        else:
            self.banner.show_ok(self.tr("All checks passed. You can run Phase 3."))
            self.btn_run.setEnabled(True)

    def _demo_scope(self, persons: list) -> list:
        """Demo mode covers one polling station (AppState.demo_bm): only
        its slots must be filled and only its decision is generated."""
        bm = self.state.demo_bm
        return persons if bm is None else [p for p in persons if p.bm_number == bm]

    # ── Run ────────────────────────────────────────────────────────────────

    def _run(self) -> None:
        master = app_paths.master_path_for(self._spec)
        persons = self._read_master_safe(master)
        if persons is None:
            # _refresh_preflight() already disabled btn_run and showed the
            # tampered-file banner for this same condition; this is just
            # the defensive backstop in case _run() is reached anyway.
            return
        if not persons:
            self.banner.show_error(self.tr("No data in the consolidated table."))
            return
        persons = self._demo_scope(persons)
        if not self._confirm_hand_edits():
            return
        log.info(
            "Phase 3 start: spec=%s persons=%d session_date=%r session_number=%r",
            self._spec.slug, len(persons),
            self.state.election.election.dates.session_date,
            self.state.election.election.dates.session_number,
        )
        self.btn_run.setEnabled(False)
        self.btn_open.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)

        self._worker, self._thread = start_worker(
            self, generate_documents,
            persons, self.state.oik, self.state.election,
            app_paths.resenja_dir_for(self._spec),
            spec=self._spec,
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)

    def _on_progress(self, label, current: int, total: int) -> None:
        self.progress.setRange(0, total)
        self.progress.setValue(current)
        self.progress.setFormat(f"BM {label}  ({current}/{total})")

    def _confirm_hand_edits(self) -> bool:
        """Ask before regeneration overwrites decisions edited in Word.
        Returns False to cancel; fills self._preserved for "keep"."""
        from biracki_odbor.core.hand_edits import hand_edited
        self._preserved: dict[Path, bytes] = {}
        folder = app_paths.resenja_dir_for(self._spec)
        last = self.state.generation_log.workflow(self._spec.slug).phase3_last
        edited = hand_edited(folder, last)
        if not edited:
            return True
        names = "\n".join(f"  • {p.name}" for p in edited[:12])
        if len(edited) > 12:
            names += "\n  …"
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(self.tr("Decisions edited by hand"))
        box.setText(self.tr(
            "{n} decision(s) were changed after they were generated"
            " (e.g. edited in Word):\n\n{names}\n\n"
            "Overwrite them with freshly generated ones, or keep your edits?"
        ).format(n=len(edited), names=names))
        btn_overwrite = box.addButton(self.tr("Overwrite all"), QMessageBox.ButtonRole.DestructiveRole)
        btn_keep = box.addButton(self.tr("Keep edited"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(btn_keep)
        box.exec()
        clicked = box.clickedButton()
        if clicked is btn_keep:
            self._preserved = {p: p.read_bytes() for p in edited}
            log.info("Phase 3: keeping %d hand-edited decision(s)", len(edited))
            return True
        if clicked is btn_overwrite:
            log.info("Phase 3: overwriting %d hand-edited decision(s)", len(edited))
            return True
        return False

    def _on_finished(self, result: Phase3Result) -> None:
        self.progress.setVisible(False)
        self.btn_run.setEnabled(True)
        self.btn_open.setEnabled(True)
        self.errors.set_report(result.report)
        preserved = getattr(self, "_preserved", {})
        for path, data in preserved.items():
            path.write_bytes(data)
        if result.files_written:
            from biracki_odbor.core.hand_edits import record_generated
            record_generated(
                app_paths.resenja_dir_for(self._spec), result.files_written,
                keep={p.name for p in preserved},
            )
            self.state.generation_log.record_phase(self._spec.slug, "phase3")
            self.state.save_generation_log()
            self.state.export_generated(self._export_purpose, result.files_written)
        log.info(
            "Phase 3 finished: files=%d errors=%d warnings=%d",
            len(result.files_written), len(result.report.errors),
            len(result.report.warnings),
        )
        if result.report.errors:
            n = len(result.report.errors)
            error_word = declension.count_word(
                n, self.state.app_settings.ui_language,
                "error", "errors", "грешку", "грешке", "грешака",
            )
            self.banner.show_error(
                self.tr("Phase 3 completed with {n} {error_word}.").format(n=n, error_word=error_word)
            )
        elif result.report.warnings:
            self.banner.show_warn(
                self.tr("Generated {n} decision(s) with {w} warning(s).").format(n=len(result.files_written), w=len(result.report.warnings))
            )
        else:
            self.banner.show_ok(
                self.tr("Done! Generated {n} decision(s).").format(n=len(result.files_written))
            )

    def _on_failed(self, err: str) -> None:
        self.progress.setVisible(False)
        self.btn_run.setEnabled(True)
        log.exception("Phase 3 failed: %s", err)
        QMessageBox.critical(self, self.tr("Error"), err)
        self.banner.show_error(self.tr("Unexpected error: {error}").format(error=err))

    @log_timing("Phase3Tab._restore_open_btn")
    def _restore_open_btn(self) -> None:
        """Enable «Отвори фасциклу решења» if Phase 3 output exists on disk.

        Must stay a cheap check: it runs on every generation_log_changed.
        It used to also re-copy every решење into the export folder each
        time (export_generated) -- redundant, the generate handler already
        exports right after writing, the only moment the files change.
        """
        resenja = app_paths.resenja_dir_for(self._spec)
        self.btn_open.setEnabled(resenja.exists() and any(resenja.glob("*.docx")))

    def _refresh_email_stat(self) -> None:
        master = app_paths.master_path_for(self._spec)
        persons = self._read_master_safe(master)
        if persons is None:
            self.lbl_email_stat.setText(
                self.tr("File changed outside the application — see Corrections.")
            )
            self.btn_send_members.setEnabled(False)
            return
        filled = [p for p in persons if p.is_filled]
        with_email = [p for p in filled if p.email.strip()]
        without = len(filled) - len(with_email)
        resenja = app_paths.resenja_dir_for(self._spec)
        has_files = resenja.exists() and any(resenja.glob("*.docx"))
        if not filled:
            self.lbl_email_stat.setText("")
            self.btn_send_members.setEnabled(False)
            return
        parts = [self.tr("{n} of {total} members have email").format(n=len(with_email), total=len(filled))]
        if without:
            parts.append(self.tr("{n} without").format(n=without))
        self.lbl_email_stat.setText(" — ".join(parts) + ".")
        self.btn_send_members.setEnabled(bool(with_email) and has_files)

    def _on_send_resenja_to_members(self) -> None:
        """Create one draft per filled member that has an email address."""
        from biracki_odbor.integrations import email_client as ec_mod

        master = app_paths.master_path_for(self._spec)
        all_persons = self._read_master_safe(master)
        if all_persons is None:
            # Must not send decisions built from data we can't currently
            # trust — resolve the mismatch in Corrections first.
            self.banner.show_error(
                self.tr(
                    "{name} was changed outside the application — resolve"
                    " in Corrections before sending."
                ).format(name=self._master_integrity_error.path.name)
            )
            return
        persons = [p for p in all_persons if p.is_filled and p.email.strip()]
        if not persons:
            self.banner.show_warn(self.tr("No members with email."))
            return

        resenja = app_paths.resenja_dir_for(self._spec)
        ec = self.state.election
        oik = self.state.oik
        mun_name = oik.municipality.name
        date_full = ec.election.dates.date_full.strip()
        subject_token = ec.election.dates.subject_token
        token_part = f" [{subject_token}]" if subject_token else ""

        drafts: list[ec_mod.DraftSpec] = []
        missing_files: list[str] = []
        for p in persons:
            docx = resenja / f"БМ_{p.bm_number:02d}_STALNI.docx"
            if not docx.exists():
                missing_files.append(docx.name)
                continue
            subject = (
                f"Решење о именовању — БМ {p.bm_number}"
                f", {mun_name}{token_part}"
            )
            body = (
                f"Поштована/и {p.first_name} {p.last_name},\n\n"
                f"У прилогу се налазе решење о именовању за бирачко место"
                f" бр. {p.bm_number} {commission_terms(oik.municipality).in_unit}"
            )
            if date_full:
                body += f" за изборе {date_full}"
            body += f".\n\n{commission_terms(oik.municipality).subject}"
            drafts.append(ec_mod.DraftSpec(
                to=p.email.strip(),
                subject=subject,
                body=body,
                attachment=docx,
            ))

        if missing_files:
            QMessageBox.warning(
                self, self.tr("Missing files"),
                self.tr("The following decision files were not found:\n{files}\n\nRun Phase 3 first, then send.").format(
                    files="\n".join(f"  {f}" for f in missing_files)
                ),
            )
            if not drafts:
                return

        try:
            results = ec_mod.create_drafts(
                drafts,
                preference=self.state.app_settings.email_client,
                display_first=True,
            )
        except ec_mod.EmailClientUnavailable as e:
            QMessageBox.warning(self, self.tr("Email client unavailable"), str(e))
            return
        except Exception as e:  # noqa: BLE001
            log.exception("send resenja to members failed")
            QMessageBox.critical(self, self.tr("Error"), self.tr("Error creating drafts:\n\n{error}").format(error=e))
            return

        ok = sum(1 for r in results if r.ok)
        failed = [r for r in results if not r.ok]
        if failed:
            details = "\n\n".join(f"• {r.spec.to}\n  {r.error}" for r in failed)
            QMessageBox.warning(
                self, self.tr("Drafts — partial"),
                self.tr("Created {ok} draft(s), {n_failed} failed:\n\n{details}").format(ok=ok, n_failed=len(failed), details=details),
            )
            self.banner.show_warn(self.tr("Created {ok} draft(s); {n_failed} failed.").format(ok=ok, n_failed=len(failed)))
        else:
            self.banner.show_ok(
                self.tr("Created {n} draft(s) for members. Review before sending.").format(n=ok)
            )

    @log_timing("Phase3Tab._update_rik_gate_ui")
    def _update_rik_gate_ui(self) -> None:
        """Sync the Submit / Revert buttons with the current workflow state."""
        gl = self.state.generation_log
        wl = gl.workflow(self._spec.slug)
        submitted = wl.submitted_to_rik()
        self.btn_submit_rik.setVisible(not submitted)
        self.btn_submit_rik.setEnabled(not submitted and wl.phase3_done())
        has_izmene = bool(wl.izmene_per_bm)
        self.btn_revert_rik.setVisible(submitted and not has_izmene)

    def _on_submit_to_rik(self) -> None:
        from biracki_odbor.gui.dialogs.confirm_dialog import confirm_with_toggle
        confirmed = confirm_with_toggle(
            self,
            title=self.tr("Submit decisions to RIK"),
            text=self.tr(
                "By checking this action you confirm that the decisions have been submitted to RIK.\n\n"
                "After this step:\n"
                "  • Re-running Phase 3 will not be possible.\n"
                "  • Corrections will be made through the Amendments tab — the program\n"
                "    automatically generates separate amendment decisions.\n\n"
                "Text errors can be corrected by directly editing the Word files.\n"
                "This action is reversible only if no amendment decisions have been issued."
            ),
            toggle_text=self.tr("I understand — decisions have been submitted to RIK"),
            confirm_text=self.tr("Confirm"),
            cancel_text=self.tr("Cancel"),
        )
        if not confirmed:
            return

        gl = self.state.generation_log
        gl.workflow(self._spec.slug).submit_to_rik()
        self.state.save_generation_log()

        from biracki_odbor.core.corrections import append_rik_submission
        append_rik_submission(
            app_paths.corrections_log_path_for(self._spec),
            self._spec.slug,
        )

    def _on_revert_rik(self) -> None:
        gl = self.state.generation_log
        wl = gl.workflow(self._spec.slug)
        if wl.izmene_per_bm:
            QMessageBox.warning(
                self, self.tr("Cannot withdraw"),
                self.tr("Amendment decisions exist. The submission cannot be withdrawn."),
            )
            return
        if QMessageBox.question(
            self, self.tr("Withdraw RIK submission"),
            self.tr("Do you want to withdraw the 'Submitted to RIK' status?\n\nPhase 3 will become available again."),
        ) != QMessageBox.StandardButton.Yes:
            return
        wl.revert_rik_submission()
        self.state.save_generation_log()
        self._refresh_preflight()
        self.banner.show_ok(self.tr("'Submitted to RIK' status has been withdrawn."))

    def _open_folder(self) -> None:
        # Naming the folder matters even on success: the window can open
        # behind a maximised app or on a switched-off second display, and
        # a silent button is then indistinguishable from a broken one.
        # The failure case used to `pass`, which said nothing at all.
        path = str(self.state.files_dir(self._export_purpose))
        try:
            subprocess.Popen(["explorer", path])
        except OSError:
            self.banner.show_warn(
                self.tr("Could not open the folder. It is at: {path}").format(path=path)
            )
            return
        self.banner.show_info(self.tr("Opened folder: {path}").format(path=path))
