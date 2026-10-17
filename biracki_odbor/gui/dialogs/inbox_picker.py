"""Inbox picker — lets the operator select which messages to import.

Backend-agnostic: takes a list of `InboxMessage` objects (produced by
either Outlook COM or Thunderbird MBox parsing) and presents one row
per attachment. The operator ticks the rows to import; on Accept,
`picked()` returns the chosen attachments together with each parent
message's received_time — that's the canonical "submitted at" stamp
Phase 2 then bakes into the file's name and cache entry.

Surrounding Phase 2 logic gates on
`email_client.any_inbox_available()` so the dialog never opens when
neither backend can read mail. The empty-list case (backend works but
the inbox has nothing matching) shows a friendly hint inside the
dialog rather than refusing to open.
"""

from __future__ import annotations

import datetime
import subprocess
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHeaderView, QHBoxLayout,
    QLabel, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from biracki_odbor.integrations.email_client import (
    InboxAttachment, InboxMessage, PickedAttachment,
)
from biracki_odbor.integrations.thunderbird import ImapOfflineGap


def _parse_cutoff(cutoff_date: str) -> datetime.date | None:
    """Return a date object from an ISO string, or None if blank/invalid."""
    if not cutoff_date:
        return None
    try:
        parts = cutoff_date.split("-")
        if len(parts) == 3:
            return datetime.date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, TypeError):
        pass
    return None


class InboxPickerDialog(QDialog):
    """Modal dialog listing Inbox messages + their .xlsx attachments.

    On `accept()`, `picked()` returns the list of attachments the
    operator checked. Empty list = nothing selected (or fetch returned
    nothing in the first place).

    When `cutoff_date` (ISO date string) is provided, messages received
    after midnight at the end of that date are visually greyed and
    pre-unchecked. The operator can still manually re-check them; doing
    so triggers a confirmation prompt on Accept.
    """

    HEADERS = ["", "Примљено", "Пошиљалац", "Тема", "Прилог"]

    def __init__(
        self,
        messages: list[InboxMessage],
        parent: QWidget | None = None,
        cutoff_date: str = "",
        imap_gaps: list[ImapOfflineGap] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Увоз из мејла")
        self.resize(900, 520)

        self._cutoff = _parse_cutoff(cutoff_date)

        # Flatten: one row per attachment so the operator can pick
        # individual files when one email carries several .xlsx
        # attachments. Each row knows its parent message's metadata.
        self._rows: list[tuple[InboxMessage, InboxAttachment]] = []
        for msg in messages:
            for att in msg.attachments:
                self._rows.append((msg, att))

        # Track which row indices are post-cutoff so `accept()` can
        # ask for confirmation when the operator overrides them.
        self._post_cutoff_rows: set[int] = set()

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        hint = QLabel(
            "Изаберите пријаве које желите да увезете. Време пријема из"
            " мејла се користи као званични тренутак пријаве —"
            " приликом избора најновије верзије по странци, узима се"
            " највећи 'Примљено' међу свим пријавама исте странке."
        )
        hint.setObjectName("MutedLabel")
        hint.setWordWrap(True)
        root.addWidget(hint)

        if self._cutoff:
            cutoff_lbl = QLabel(
                f"Рок за пријаву сталног састава: <b>{cutoff_date}</b>."
                " Пријаве примљене после тог датума су означене сивом бојом"
                " и подразумевано нису изабране. Можете их ручно означити"
                " ако постоји оправдан разлог."
            )
            cutoff_lbl.setObjectName("WarnLabel")
            cutoff_lbl.setWordWrap(True)
            root.addWidget(cutoff_lbl)

        if not self._rows:
            if imap_gaps:
                names = ", ".join(
                    f"{g.email} ({g.hostname})" for g in imap_gaps
                )
                gap_lbl = QLabel(
                    f"Thunderbird је конфигурисан са IMAP налогом(а): <b>{names}</b>,"
                    " али поруке нису доступне локално — вероватно није укључено"
                    " чување на рачунару. Идите на:"
                    " <b>Поставке налога → Синхронизација и чување →"
                    " Чувај поруке на рачунару</b>."
                )
                gap_lbl.setObjectName("WarnLabel")
                gap_lbl.setWordWrap(True)
                root.addWidget(gap_lbl)

                open_row = QHBoxLayout()
                open_btn = QPushButton("Отвори Thunderbird")
                open_btn.clicked.connect(_open_thunderbird)
                open_row.addWidget(open_btn)
                open_row.addStretch()
                root.addLayout(open_row)
            else:
                empty = QLabel(
                    "У Inbox-у нема ниједне поруке са .xlsx прилогом у задњих"
                    " 14 дана. Затворите овај дијалог и користите 'Увези фајлове…'"
                    " за ручни увоз."
                )
                empty.setObjectName("WarnLabel")
                empty.setWordWrap(True)
                root.addWidget(empty)

        self.table = QTableWidget(len(self._rows), len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.Interactive)
        h.resizeSection(0, 32)
        h.resizeSection(1, 140)
        h.resizeSection(2, 180)
        h.resizeSection(3, 320)
        h.setStretchLastSection(True)

        dim_fg = QColor(160, 160, 160)
        italic_font = QFont()
        italic_font.setItalic(True)

        for row, (msg, att) in enumerate(self._rows):
            # Determine whether this message is past the cutoff deadline.
            # Cutoff means: received_time.date() > cutoff_date. Messages
            # received on the cutoff date itself (before midnight) are
            # still valid — they arrived on the last allowed day.
            is_late = bool(
                self._cutoff
                and msg.received_time.astimezone().date() > self._cutoff
            )
            if is_late:
                self._post_cutoff_rows.add(row)

            # Column 0 — checkbox; post-cutoff rows start unchecked.
            cb_item = QTableWidgetItem()
            cb_item.setFlags(cb_item.flags() | Qt.ItemIsUserCheckable)
            cb_item.setCheckState(Qt.Unchecked if is_late else Qt.Checked)
            if is_late:
                cb_item.setToolTip(
                    f"Пријава примљена после рока ({cutoff_date})."
                    " Означите ручно ако постоји оправдан разлог за увоз."
                )
            self.table.setItem(row, 0, cb_item)

            received_str = msg.received_time.astimezone().strftime("%Y-%m-%d %H:%M")
            if is_late:
                received_str += " — после рока"

            values = [
                received_str,
                msg.sender_name or msg.sender_email,
                msg.subject,
                att.name,
            ]
            for col, val in enumerate(values, start=1):
                item = QTableWidgetItem(val)
                if is_late:
                    item.setForeground(dim_fg)
                    item.setFont(italic_font)
                    item.setToolTip(
                        f"Пријава примљена после рока ({cutoff_date})."
                    )
                self.table.setItem(row, col, item)

        root.addWidget(self.table, stretch=1)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._on_accept)
        bb.rejected.connect(self.reject)
        bb.button(QDialogButtonBox.Ok).setText("Увези изабране")
        bb.button(QDialogButtonBox.Cancel).setText("Откажи")
        root.addWidget(bb)

    def _on_accept(self) -> None:
        """Confirm before importing any manually-overridden post-cutoff rows."""
        if not self._post_cutoff_rows:
            self.accept()
            return
        overridden = [
            row for row in self._post_cutoff_rows
            if (item := self.table.item(row, 0)) is not None
            and item.checkState() == Qt.Checked
        ]
        if not overridden:
            self.accept()
            return
        reply = QMessageBox.question(
            self,
            "Увоз после рока",
            f"Означили сте {len(overridden)} пријав(а) примљен(их) после"
            " рока за предају. Ове пријаве неће бити дио редовног"
            " поступка именовања — странка је прекасно предала.\n\n"
            "Да ли заиста желите да увезете ове пријаве?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.accept()

    def picked(self) -> list[PickedAttachment]:
        """Return the attachments whose checkbox is ticked.

        Safe to call before `exec()` returns Accepted — but only the
        Accepted path is interesting in practice.
        """
        out: list[PickedAttachment] = []
        for row, (msg, att) in enumerate(self._rows):
            item = self.table.item(row, 0)
            if item is None or item.checkState() != Qt.Checked:
                continue
            out.append(PickedAttachment(
                attachment=att,
                received_time=msg.received_time,
                subject=msg.subject,
                sender_name=msg.sender_name or msg.sender_email,
            ))
        return out


def _open_thunderbird() -> None:
    """Launch Thunderbird so the operator can adjust account settings."""
    from biracki_odbor.integrations.thunderbird import find_thunderbird_exe
    exe = find_thunderbird_exe()
    if exe:
        subprocess.Popen([str(exe)])
    elif sys.platform == "win32":
        subprocess.Popen(["explorer", "thunderbird:"])  # URL handler fallback
