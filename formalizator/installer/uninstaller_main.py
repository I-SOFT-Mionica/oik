"""Uninstaller wizard for Formalizator.

Deliberately a single screen, not a multi-page wizard: uninstalling is
one decision, and the only real question is whether the operator's own
calibrated templates and collected session data go with the program.
That answer is gated behind a typed confirmation, because a calibrated
template is hand-tuned work that cannot be recovered and the session
database holds real citizens' personal data.

Packaged as its own PyInstaller one-file build
(`Formalizator_Uninstaller.exe`), dropped into the install folder by the
installer so "Uninstall" is always to hand.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QVBoxLayout,
)

from biracki_odbor.gui.style import apply_global_style
from formalizator.installer.scaffold import shared_icon
from formalizator.installer.uninstall import describe_install, perform_uninstall

_CONFIRM_WORD = "БРИШИ"


class Uninstaller(QDialog):
    def __init__(self, base_dir: Path) -> None:
        super().__init__()
        self._base_dir = base_dir
        self.setWindowTitle("Formalizator — деинсталација")
        self.setMinimumSize(640, 480)
        icon = shared_icon()
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))

        info = describe_install(base_dir)
        root = QVBoxLayout(self)

        header = QLabel(f"Деинсталација из фасцикле:\n{base_dir}")
        header.setWordWrap(True)
        root.addWidget(header)

        warning = QLabel(
            "Биће обрисано СВЕ — програм и сви подаци:\n\n"
            "  • апликација, икона и пречица\n"
            f"  • калибрисани обрасци (пронађено: {info['templates']}) и извозни шаблони\n"
            "  • база сесија са подацима бирача\n"
            "  • радна фасцикла, укључујући и ону из раније верзије\n"
            "  • привремене PDF изјаве (садрже име, ЈМБГ и адресу бирача)\n\n"
            "Ово је намерно потпуно брисање: апликација чува личне податке"
            " грађана, па се ништа не сме оставити на рачунару. Радња је"
            " неповратна — калибрацију образаца ће бити потребно урадити изнова."
        )
        warning.setWordWrap(True)
        root.addWidget(warning)

        confirm_row = QHBoxLayout()
        self.lbl_confirm = QLabel(f"Упишите „{_CONFIRM_WORD}” за потврду:")
        confirm_row.addWidget(self.lbl_confirm)
        self.ed_confirm = QLineEdit()
        self.ed_confirm.textChanged.connect(self._refresh_confirm)
        confirm_row.addWidget(self.ed_confirm, stretch=1)
        root.addLayout(confirm_row)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        root.addWidget(self.log, stretch=1)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Деинсталирај")
        self.buttons.button(QDialogButtonBox.Cancel).setText("Откажи")
        self.buttons.accepted.connect(self._on_uninstall)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)

        self._refresh_confirm()

    def _refresh_confirm(self) -> None:
        """Uninstalling is always destructive here, so the typed
        confirmation always gates it."""
        ok = self.buttons.button(QDialogButtonBox.Ok)
        ok.setEnabled(self.ed_confirm.text().strip() == _CONFIRM_WORD)

    def _on_uninstall(self) -> None:
        result = perform_uninstall(self._base_dir)
        for path in result.removed_files:
            self.log.appendPlainText(f"  - {path.name}")
        for path in result.removed_dirs:
            self.log.appendPlainText(f"  - {path.name}/")

        if result.errors:
            self.log.appendPlainText("\nНије обрисано:")
            for error in result.errors:
                self.log.appendPlainText(f"  ! {error}")

        if result.base_removed:
            self.log.appendPlainText("\nФасцикла је уклоњена.")
        elif result.self_delete_scheduled:
            self.log.appendPlainText(
                "\nФасцикла и сам деинсталер бришу се одмах по затварању"
                " овог прозора."
            )
        elif self._base_dir.exists():
            self.log.appendPlainText(
                "\nФасцикла није уклоњена (садржи датотеке које нису наше)."
            )

        self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)
        if result.errors:
            QMessageBox.warning(
                self, "Завршено уз грешке",
                "Деинсталација је завршена, али неке ставке нису обрисане."
                " Списак је приказан у прозору испод.",
            )
        else:
            QMessageBox.information(
                self, "Готово",
                "Деинсталација је завршена. Ништа није остало на рачунару.",
            )
        # The deferred cleanup waits for this process to exit before it
        # can remove the running .exe, so closing is part of the
        # operation rather than something to leave to the operator.
        self.accept()


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    icon = shared_icon()
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    apply_global_style(app)
    # The uninstaller lives inside the install folder it is tearing down.
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()
    dialog = Uninstaller(base)
    dialog.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
