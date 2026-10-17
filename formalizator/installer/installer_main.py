"""Setup wizard for Formalizator.

Four screens via a QWizard, matching the OIK installer's shape and
button wording so both products install the same way:
  1. Добродошли — what gets installed, and where.
  2. Локација — pick the install folder.
  3. Инсталација — progress while files are copied and forms seeded.
  4. Завршено — desktop shortcut + run now.

Packaged as its own PyInstaller one-file build (`Formalizator_Setup.exe`),
which carries `Formalizator.exe` inside it — see Formalizator_Setup.spec.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QVBoxLayout, QWizard, QWizardPage,
)

from biracki_odbor.gui.style import apply_global_style
from formalizator.installer.scaffold import (
    APP_EXE_NAME, UNINSTALLER_EXE_NAME, create_desktop_shortcut,
    existing_install_info, perform_scaffold, shared_icon,
)

# Defaults to the folder the app already keeps its data in, so the
# executable, the calibrated forms and the session database all live in
# one place the operator can find.
DEFAULT_DIR = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Formalizator"


class WelcomePage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Добродошли")
        self.setSubTitle("Инсталација апликације Formalizator.")
        layout = QVBoxLayout(self)
        body = QLabel(
            "Овај чаробњак ће инсталирати Formalizator — апликацију за"
            " прикупљање подршке бирача (штампа изјава и извоз списка).\n\n"
            "Уз апликацију се испоручују и већ калибрисани обрасци"
            " НПРС-3 и НПРС-4, па је могуће одмах почети са радом.\n\n"
            "Ништа се не пише ван изабране фасцикле. Постојећи обрасци"
            " и подаци се чувају при поновној инсталацији.\n\n"
            "Кликните „Даље” за наставак."
        )
        body.setWordWrap(True)
        layout.addWidget(body)
        layout.addStretch()


class LocationPage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Локација")
        self.setSubTitle("Изаберите фасциклу за инсталацију.")
        layout = QVBoxLayout(self)

        row = QHBoxLayout()
        self.ed_path = QLineEdit(str(DEFAULT_DIR))
        self.ed_path.textChanged.connect(self._refresh_status)
        row.addWidget(self.ed_path, stretch=1)
        self.btn_browse = QPushButton("Преглед…")
        self.btn_browse.clicked.connect(self._on_browse)
        row.addWidget(self.btn_browse)
        layout.addLayout(row)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addStretch()

        self.registerField("path*", self.ed_path)
        self.ed_path.textChanged.connect(self.completeChanged)
        self._refresh_status()

    def isComplete(self) -> bool:  # noqa: N802
        return bool(self.ed_path.text().strip())

    def _on_browse(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Изабери фасциклу", self.ed_path.text() or str(DEFAULT_DIR),
        )
        if path:
            self.ed_path.setText(path)

    def _refresh_status(self) -> None:
        info = existing_install_info(self.ed_path.text())
        if not info.get("exists"):
            self.status.setText("Нова инсталација. Фасцикла ће бити креирана.")
            return
        preserved = ", ".join(info.get("preserved", [])) or "(ништа)"
        self.status.setText(
            f"Пронађена постојећа инсталација. Биће сачувано: {preserved}."
        )


class InstallPage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Инсталирање")
        self.setSubTitle("Молимо сачекајте — копирају се потребни фајлови.")
        self.setCommitPage(True)
        layout = QVBoxLayout(self)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log)

    def initializePage(self) -> None:  # noqa: N802
        self.log.clear()
        base = Path(self.field("path"))
        try:
            result = perform_scaffold(
                base,
                exe_source=_bundled(APP_EXE_NAME),
                uninstaller_source=_bundled(UNINSTALLER_EXE_NAME),
            )
        except OSError as e:
            self._append(f"Грешка: {e}")
            return

        self._append(f"Инсталациона фасцикла: {result.base_dir}")
        if result.copied_files:
            self._append("\nКопирано:")
            for f in result.copied_files:
                self._append(f"  + {f.name}")
        if result.seeded_forms:
            self._append("\nИспоручени обрасци:")
            for name in result.seeded_forms:
                self._append(f"  + {name}")
        self._append("\nИнсталирање је завршено. Кликните „Даље”.")

    def _append(self, text: str) -> None:
        self.log.appendPlainText(text)


class DonePage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Завршено")
        layout = QVBoxLayout(self)
        self.msg = QLabel("Инсталација је успешно завршена.")
        self.msg.setWordWrap(True)
        layout.addWidget(self.msg)

        self.cb_shortcut = QCheckBox("Направи пречицу на радној површини")
        self.cb_shortcut.setChecked(True)
        layout.addWidget(self.cb_shortcut)

        self.cb_launch = QCheckBox("Покрени апликацију одмах")
        self.cb_launch.setChecked(True)
        layout.addWidget(self.cb_launch)

        self.result_label = QLabel("")
        self.result_label.setObjectName("MutedLabel")
        self.result_label.setWordWrap(True)
        layout.addWidget(self.result_label)
        layout.addStretch()

    def validatePage(self) -> bool:  # noqa: N802
        """Shortcut creation happens here rather than after the wizard
        closes, so a failure can actually be reported to the operator
        instead of vanishing."""
        if not self.cb_shortcut.isChecked():
            return True
        exe = Path(self.field("path")) / APP_EXE_NAME
        link = create_desktop_shortcut(exe)
        self.result_label.setText(
            f"Пречица: {link}" if link
            else "Пречицу није било могуће направити (апликација ради и без ње)."
        )
        return True


class Installer(QWizard):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Formalizator — инсталација")
        self.setWizardStyle(QWizard.WizardStyle.ClassicStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)
        self.setMinimumSize(720, 520)

        icon = shared_icon()
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))

        from biracki_odbor.gui.style import SURFACE
        self.setStyleSheet(f"""
            QWizard > QWidget {{ background: {SURFACE}; }}
            QWizard QAbstractButton {{ min-width: 100px; }}
        """)

        self.location = LocationPage()
        self.done_page = DonePage()
        self.addPage(WelcomePage())
        self.addPage(self.location)
        self.addPage(InstallPage())
        self.addPage(self.done_page)

        self.setButtonText(QWizard.WizardButton.NextButton, "Даље →")
        self.setButtonText(QWizard.WizardButton.BackButton, "← Назад")
        self.setButtonText(QWizard.WizardButton.CancelButton, "Откажи")
        self.setButtonText(QWizard.WizardButton.FinishButton, "Заврши")
        self.setButtonText(QWizard.WizardButton.CommitButton, "Инсталирај")

        self.finished.connect(self._on_finished)

    def _on_finished(self, _result: int) -> None:
        base = Path(self.location.ed_path.text())
        exe = base / APP_EXE_NAME
        if self.done_page.cb_launch.isChecked() and exe.exists():
            try:
                subprocess.Popen([str(exe)], cwd=str(base))
            except OSError:
                pass


def _bundled(name: str) -> Path | None:
    """The app and uninstaller travel inside this setup binary (see
    Formalizator_Setup.spec), unpacked beside it at run time. Falls
    back to copies sitting next to the setup file or in dist/, which is
    what a dev/CI run has."""
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / name)
    candidates.append(Path(sys.executable).parent / name)
    candidates.append(Path.cwd() / "dist" / name)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    icon = shared_icon()
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    apply_global_style(app)
    wizard = Installer()
    wizard.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
