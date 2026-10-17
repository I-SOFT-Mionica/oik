"""„Пошаљи странкама…" / „Пошаљи листама…" — Outlook draft per
recipient from Phase 1 output. Shared by both composition workflows
(see `gui/tabs/phase1.py`'s `BasePhase1Tab._on_send`): стали, one
recipient per RIK-allocated party, and прошиени, one per registered
list. `workflow_slug` selects the matching window title, table column
label, and subject/body boilerplate so the wording always says the
right thing for whichever composition is actually being sent.

After Фаза 1 generates one .xlsx per recipient, the operator clicks
this dialog to fan out N drafts in Outlook — one per recipient, each
with the matching file attached. Drafts go to the operator's Outlook
Drafts folder; the first one opens for review. Operator stays in
control of the actual send.

Address book — two separate ones, never mixed, passed in by the caller:
  - стали: `ElectionConfig.party_contacts[abbrev].email` (filled in via
    Election Settings → Странке), keyed by RIK party abbreviation.
  - прошиени: `Entity.email`, keyed by entity_id (filled in via
    Election Settings → Кандидати). A list's entity_id and a RIK
    party's abbreviation are different identity systems that can
    coincidentally collide, so `BasePhase1Tab._send_recipients()` (see
    `ProsireniPhase1Tab`'s override) is the only place that decides
    which address book a given send actually reads from — this dialog
    itself is address-book-agnostic, it just renders whatever mapping
    it's given.
  - Either way: empty addresses can be entered inline in the dialog
    table, and rows with empty email after the operator's pass are
    skipped on OK (with a banner note) — we never create an Outlook
    draft to nowhere.

Subject + body templates use simple {placeholders} so the operator
can tweak the wording in the dialog without editing code.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHeaderView,
    QLabel, QLineEdit, QPlainTextEdit, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)


log = logging.getLogger(__name__)


# {token} is the per-election subject rider — the same string for
# every party in a given election. Phase 2's Outlook fetch filters the
# inbox with `[Subject] ci_phrasematch '<token>'`, so any reply that
# preserves the subject (i.e. virtually all mail clients on Reply) is
# automatically picked up. New mails from parties that drop the subject
# get caught via the body footer below, which instructs the recipient
# to either reply directly or paste the token into a new subject.
_DEFAULT_SUBJECT = {
    "stalni": "Стални састав бирачких одбора — фајл за попуну ({party}) {token}",
    "prosireni": "Проширени састав бирачких одбора — фајл за попуну ({party}) {token}",
}
_DEFAULT_BODY = {
    "stalni": (
        "Поштовани,\n\n"
        "У прилогу се налази фајл за попуну предлога чланова и заменика\n"
        "чланова бирачких одбора у сталном саставу за вашу странку.\n\n"
        "Молимо вас да попуните фајл и пошаљете назад одговором на овај\n"
        "мејл, без преименовања фајла.\n\n"
        "Хвала,\n"
        "ОИК\n\n"
        "─────────────────────────────────────\n"
        "ОИК идентификатор: {token}\n\n"
        "Да би ваш одговор био препознат при увозу:\n"
        "  • најједноставније: одговорите директно на овај мејл\n"
        "    (тема почиње са „Re:“ — то је довољно),\n"
        "  • или: ако шаљете нов мејл, обавезно укључите ознаку\n"
        "    {token} у наслову поруке.\n\n"
        "Поруке без ове ознаке у наслову могу бити прескочене при увозу.\n"
        "─────────────────────────────────────"
    ),
    "prosireni": (
        "Поштовани,\n\n"
        "У прилогу се налази фајл за попуну предлога чланова и заменика\n"
        "чланова бирачких одбора у проширеном саставу за вашу листу.\n\n"
        "Молимо вас да попуните фајл и пошаљете назад одговором на овај\n"
        "мејл, без преименовања фајла.\n\n"
        "Хвала,\n"
        "ОИК\n\n"
        "─────────────────────────────────────\n"
        "ОИК идентификатор: {token}\n\n"
        "Да би ваш одговор био препознат при увозу:\n"
        "  • најједноставније: одговорите директно на овај мејл\n"
        "    (тема почиње са „Re:“ — то је довољно),\n"
        "  • или: ако шаљете нов мејл, обавезно укључите ознаку\n"
        "    {token} у наслову поруке.\n\n"
        "Поруке без ове ознаке у наслову могу бити прескочене при увозу.\n"
        "─────────────────────────────────────"
    ),
}


_WINDOW_TITLE = {
    "stalni": "Пошаљи странкама",
    "prosireni": "Пошаљи листама",
}
# The table's 2nd column label — "Странка" (Party) reads wrong when the
# rows are actually прошиени lists, not RIK-allocated parties.
_RECIPIENT_COLUMN_LABEL = {
    "stalni": "Странка",
    "prosireni": "Листа",
}
_HINT = {
    "stalni": (
        "Прави Outlook драфтове — по један за сваку странку, са одговарајућим .xlsx-ом"
        " као прилогом. Драфтови иду у Outlook → Drafts; први се отвара ради провере."
        " Е-пошта се чита из Изборне конфигурације → Странке; могуће је уредити овде."
    ),
    "prosireni": (
        "Прави Outlook драфтове — по један за сваку листу, са одговарајућим .xlsx-ом"
        " као прилогом. Драфтови иду у Outlook → Drafts; први се отвара ради провере."
        " Е-пошта се чита из Избори → Кандидати; могуће је уредити овде."
    ),
}


@dataclass
class _Row:
    party: str
    full_name: str
    file_path: Path
    email: str
    include: bool = True


class SendToPartiesDialog(QDialog):
    """Returns prepared DraftSpec rows on accept; empty list on reject."""

    def __init__(
        self,
        files: list[Path],
        party_full_names: dict[str, str],
        party_emails: dict[str, str],
        parent: QWidget | None = None,
        *,
        subject_token: str = "",
        workflow_slug: str = "stalni",
    ) -> None:
        super().__init__(parent)
        self.resize(900, 540)
        # Per-election subject rider, same for every recipient. Empty
        # string ⇒ no rider (election date unset/unparseable) and the
        # {token} placeholder renders to "" in both subject and body.
        self._subject_token = subject_token
        # Selects which boilerplate ("...у сталном саставу..." vs
        # "...у проширеном саставу...") seeds the subject/body fields,
        # window title and table header — stalni and prosireni both use
        # this same Send dialog (see BasePhase1Tab._on_send /
        # ProsireniPhase1Tab._send_recipients, which keep the two
        # address books separate), but every piece of on-screen wording
        # must still match whichever composition is actually being sent.
        self._workflow_slug = workflow_slug if workflow_slug in _DEFAULT_SUBJECT else "stalni"
        self.setWindowTitle(_WINDOW_TITLE[self._workflow_slug])
        self.HEADERS = ["Шаљи", _RECIPIENT_COLUMN_LABEL[self._workflow_slug], "Е-пошта", "Прилог"]

        # Match each generated file to its recipient by filename. Phase 1
        # writes files as `<safe_key_name>.xlsx` (RIK party abbreviation
        # for stalni, entity_id for prosireni) — safe-filename mangling
        # is reversible enough that we just compare against the key set.
        self._rows: list[_Row] = []
        for f in files:
            party_key = _match_party(f, party_full_names)
            self._rows.append(_Row(
                party=party_key or f.stem,
                full_name=party_full_names.get(party_key or "", ""),
                file_path=f,
                email=party_emails.get(party_key or "", ""),
            ))

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        hint = QLabel(_HINT[self._workflow_slug])
        hint.setObjectName("MutedLabel")
        hint.setWordWrap(True)
        root.addWidget(hint)

        # Subject + body templates. {party} placeholder gets the
        # party's abbreviation, {full_name} the full Cyrillic name.
        # Both default to the boilerplate above; operator can change
        # them and every draft picks up the change.
        root.addWidget(QLabel("Тема:"))
        self.ed_subject = QLineEdit(_DEFAULT_SUBJECT[self._workflow_slug])
        root.addWidget(self.ed_subject)
        root.addWidget(QLabel(
            "Тело поруке (плейн текст; {party}, {full_name} и {token}"
            " се замењују):"
        ))
        self.ed_body = QPlainTextEdit(_DEFAULT_BODY[self._workflow_slug])
        self.ed_body.setMinimumHeight(120)
        root.addWidget(self.ed_body)

        self.table = QTableWidget(len(self._rows), len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Interactive)
        h.resizeSection(0, 50)
        h.setSectionResizeMode(1, QHeaderView.Interactive)
        h.resizeSection(1, 140)
        h.setSectionResizeMode(2, QHeaderView.Interactive)
        h.resizeSection(2, 240)
        h.setSectionResizeMode(3, QHeaderView.Stretch)
        for r, row in enumerate(self._rows):
            cb = QTableWidgetItem()
            cb.setFlags(cb.flags() | Qt.ItemIsUserCheckable)
            cb.setCheckState(Qt.Checked if row.email else Qt.Unchecked)
            self.table.setItem(r, 0, cb)
            party_item = QTableWidgetItem(row.party)
            party_item.setFlags(party_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(r, 1, party_item)
            self.table.setItem(r, 2, QTableWidgetItem(row.email))
            file_item = QTableWidgetItem(row.file_path.name)
            file_item.setFlags(file_item.flags() & ~Qt.ItemIsEditable)
            file_item.setToolTip(str(row.file_path))
            self.table.setItem(r, 3, file_item)
        root.addWidget(self.table, stretch=1)

        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("MutedLabel")
        root.addWidget(self.lbl_status)
        self._refresh_status()
        self.table.itemChanged.connect(lambda _: self._refresh_status())

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Креирај драфтове")
        bb.button(QDialogButtonBox.Cancel).setText("Откажи")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

    def _refresh_status(self) -> None:
        sel = self._selected_count()
        no_email = sum(
            1 for r in range(self.table.rowCount())
            if self.table.item(r, 0) is not None
            and self.table.item(r, 0).checkState() == Qt.Checked
            and not (self.table.item(r, 2) or QTableWidgetItem("")).text().strip()
        )
        msg = f"Изабрано: {sel}"
        if no_email:
            msg += (
                f"  ·  {no_email} ред(ова) без е-поште — биће прескочени"
            )
        self.lbl_status.setText(msg)

    def _selected_count(self) -> int:
        n = 0
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            if item is not None and item.checkState() == Qt.Checked:
                n += 1
        return n

    def prepared_drafts(self) -> list:
        """Return DraftSpec rows for parties the operator selected with
        non-empty email. Subject + body templates are rendered per row.

        Returns `list[outlook.DraftSpec]` typed at runtime — we don't
        import outlook at module top so the dialog can be smoke-tested
        on Linux CI without pywin32.
        """
        from biracki_odbor.integrations.outlook import DraftSpec
        subject_tpl = self.ed_subject.text() or _DEFAULT_SUBJECT[self._workflow_slug]
        body_tpl = self.ed_body.toPlainText() or _DEFAULT_BODY[self._workflow_slug]
        out: list = []
        for r in range(self.table.rowCount()):
            cb = self.table.item(r, 0)
            if cb is None or cb.checkState() != Qt.Checked:
                continue
            email = (self.table.item(r, 2) or QTableWidgetItem("")).text().strip()
            if not email:
                continue
            row = self._rows[r]
            ctx = {
                "party": row.party,
                "full_name": row.full_name or row.party,
                "token": self._subject_token,
            }
            try:
                subject = subject_tpl.format(**ctx)
            except (KeyError, IndexError):
                subject = subject_tpl
            try:
                body = body_tpl.format(**ctx)
            except (KeyError, IndexError):
                body = body_tpl
            out.append(DraftSpec(
                to=email, subject=subject, body=body,
                attachment=row.file_path,
            ))
        return out


def _match_party(file_path: Path, party_full_names: dict[str, str]) -> str | None:
    """Phase 1 writes `<_safe_filename(party)>.xlsx`. Try to find the
    matching party abbreviation; fall back to None for unknown files."""
    from biracki_odbor.core.phase1_generate import _safe_filename
    stem = file_path.stem
    for abbrev in party_full_names.keys():
        if _safe_filename(abbrev) == stem:
            return abbrev
    return None
