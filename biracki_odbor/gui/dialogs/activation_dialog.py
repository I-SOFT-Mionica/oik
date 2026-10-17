"""License activation dialog.

Shown:
  - automatically at first launch on a machine without a license file,
    when `licensing_server_url` is set
  - manually from About page → „Активирај лиценцу"

Flow: technician enters the license code → app POSTs (code, hid) to
the server → server returns a JWT → we write it to license.dat →
AppState reloads the license → dialog closes.

The local HID is shown read-only so the technician can dictate it
to support if activation fails (e.g. the code was issued for a
different machine and needs the server-side row's HID cleared).
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QFormLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)


log = logging.getLogger(__name__)


# Map server-side `reason_code` → operator-friendly Cyrillic message.
# Anything not in the map falls back to a generic "server returned X".
_REASON_MESSAGES = {
    "machine_mismatch": (
        "Лиценца је већ активирана за други рачунар. Контактирајте"
        " подршку да би се поново регистровала."
    ),
    "unknown_license": (
        "Лиценцни код није препознат. Проверите за грешке у уносу"
        " (велика/мала слова, '-' уместо '_'…)."
    ),
    "revoked": (
        "Лиценца је повучена. Контактирајте I-SOFT подршку."
    ),
    "network_error": (
        "Сервер за лиценце није доступан. Проверите интернет везу"
        " и пробајте поново."
    ),
    "bad_response": (
        "Сервер за лиценце је вратио неочекивани одговор. Контактирајте"
        " I-SOFT подршку."
    ),
}


class ActivationDialog(QDialog):
    """Modal activation dialog.

    Returns Accepted when the server issued a token AND we wrote it
    to disk; Rejected otherwise. Caller (AppState / MainWindow) is
    responsible for reloading the License after Accept.
    """

    def __init__(
        self,
        *,
        server_url: str,
        license_dat_path: Path,
        machine_hid: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Активирај лиценцу")
        self.setMinimumWidth(540)
        self._server_url = server_url
        self._license_dat_path = license_dat_path
        self._machine_hid = machine_hid

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        title = QLabel("Активирај лиценцу")
        title.setObjectName("TitleLabel")
        root.addWidget(title)

        hint = QLabel(
            "Унесите лиценцни код који сте добили од I-SOFT-а. Активација"
            " везује лиценцу за овај рачунар — ако касније мењате рачунар,"
            " биће потребна нова активација."
        )
        hint.setObjectName("MutedLabel")
        hint.setWordWrap(True)
        root.addWidget(hint)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        self.ed_code = QLineEdit()
        self.ed_code.setPlaceholderText("ABCD-EFGH-IJKL-MNOP")
        # Force uppercase for visual consistency; the server lookup
        # should be case-insensitive but we don't depend on that.
        self.ed_code.textChanged.connect(
            lambda _: self.ed_code.setText(self.ed_code.text().upper())
        )
        form.addRow("Лиценцни код:", self.ed_code)

        # Fingerprint shown read-only with a copy button — support
        # often needs this to clear a stale binding on the server.
        hid_row = QLabel()
        hid_row.setText(self._machine_hid)
        hid_row.setObjectName("MutedLabel")
        hid_row.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow("Отисак машине (HID):", hid_row)

        btn_copy_hid = QPushButton("Копирај HID")
        btn_copy_hid.clicked.connect(self._copy_hid)
        form.addRow("", btn_copy_hid)

        root.addLayout(form)

        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setObjectName("ErrorLabel")
        root.addWidget(self.lbl_status)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Активирај")
        bb.button(QDialogButtonBox.Cancel).setText("Касније")
        bb.accepted.connect(self._on_activate)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

    def _copy_hid(self) -> None:
        QApplication.clipboard().setText(self._machine_hid)
        self.lbl_status.setObjectName("OkLabel")
        self.lbl_status.setText("HID је копиран у клипборд.")
        self.lbl_status.style().unpolish(self.lbl_status)
        self.lbl_status.style().polish(self.lbl_status)

    def _on_activate(self) -> None:
        code = self.ed_code.text().strip()
        if not code:
            self._show_error("Унесите лиценцни код.")
            return

        # Local import — keeps the module testable without httpx
        # installed when the dialog is only being smoke-imported.
        from biracki_odbor.licensing import server_client

        try:
            result = server_client.activate(
                self._server_url, code, self._machine_hid,
            )
        except server_client.LicenseError as e:
            msg = _REASON_MESSAGES.get(
                e.reason_code,
                f"Сервер је одбио активацију: {e.reason_code}"
                + (f" — {e.detail}" if e.detail else ""),
            )
            self._show_error(msg)
            return
        except Exception as e:  # noqa: BLE001 — surface unexpected COM/SSL errors
            log.exception("activation failed")
            self._show_error(f"Грешка приликом активације: {e}")
            return

        try:
            self._license_dat_path.parent.mkdir(parents=True, exist_ok=True)
            self._license_dat_path.write_text(result.token, encoding="utf-8")
        except OSError as e:
            self._show_error(
                f"Сервер је послао лиценцу, али не могу да је сачувам:"
                f" {e}"
            )
            return

        QMessageBox.information(
            self, "Активирано",
            "Лиценца је успешно активирана. Апликација ће се ажурирати"
            " тренутно.",
        )
        self.accept()

    def _show_error(self, message: str) -> None:
        self.lbl_status.setObjectName("ErrorLabel")
        self.lbl_status.setText(message)
        self.lbl_status.style().unpolish(self.lbl_status)
        self.lbl_status.style().polish(self.lbl_status)
