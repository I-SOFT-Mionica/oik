"""Uninstaller wizard for Biracki_Odbor.

Four screens via a QWizard:
  1. Добродошли — explain what's about to happen + show detected install.
  2. Опције — three checkboxes: shortcut / program files / user data.
                Data deletion requires typed confirmation ("БРИШИ").
  3. Деинсталирање — progress while removals run.
  4. Завршено — summary of what was removed.

Mirrors `installer_main.py` so users see a familiar wizard shape. The
heavy lifting is in `uninstall.py` so the destructive paths are testable
without Qt.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QVBoxLayout, QWidget, QWizard, QWizardPage,
)

from biracki_odbor.gui.style import apply_global_style
from biracki_odbor.installer.uninstall import (
    UninstallPlan, describe_install, execute, find_install_dir,
)


CONFIRM_WORD = "БРИШИ"


# Env-var sentinel set when we re-launch ourselves from %TEMP%. Used so
# the relaunched copy doesn't fork again.
_TEMP_RELAUNCH_ENV = "BIRACKI_UNINSTALLER_FROM_TEMP"


def _relaunch_from_temp_if_needed() -> bool:
    """Self-relaunch out of %TEMP% so we can wipe our own exe in the install dir.

    Windows locks any running .exe — if the uninstaller is sitting in
    `%USERPROFILE%\\Biracki_Odbor\\Biracki_Odbor_Uninstaller.exe` and we
    try to delete that directory, the .exe (us) can't be removed and the
    base dir survives with one stray file.

    Fix: on first launch, copy ourselves to a uniquely-named file under
    `%TEMP%`, spawn it, and exit. The relaunched copy is no longer
    holding the install-dir file open, so it can delete everything
    cleanly. The temp copy itself is left behind for Windows to clean
    up at next reboot (Windows reaps %TEMP% on its own schedule) — this
    is simpler and more reliable than self-delete-via-cmd tricks.

    Returns True iff the caller should exit (relaunch was triggered).
    Dev-mode (non-frozen) and already-from-temp invocations are no-ops.
    """
    if not getattr(sys, "frozen", False):
        return False  # `python -m biracki_odbor.installer.uninstaller_main`
    if os.environ.get(_TEMP_RELAUNCH_ENV) == "1":
        return False  # Already running the relaunched copy.
    me = Path(sys.executable).resolve()
    temp_root = Path(tempfile.gettempdir())
    # Unique name so multiple launches don't fight over the same path.
    temp_copy = temp_root / f"OIK_Uninstaller_{os.getpid()}.exe"
    try:
        shutil.copy2(me, temp_copy)
    except OSError:
        # If we can't copy to %TEMP% (disk full, AV blocked it, …),
        # carry on in place — partial uninstall is better than no
        # uninstall, and the only victim is our own .exe.
        return False
    env = os.environ.copy()
    env[_TEMP_RELAUNCH_ENV] = "1"
    # CREATE_NEW_PROCESS_GROUP + DETACHED so closing the parent doesn't
    # cascade. close_fds keeps file handles out of the child.
    creationflags = 0
    if os.name == "nt":
        creationflags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
        )
    try:
        subprocess.Popen(
            [str(temp_copy), *sys.argv[1:]],
            env=env,
            close_fds=True,
            creationflags=creationflags,
        )
    except OSError:
        # Spawn failed — fall back to in-place uninstall.
        return False
    return True


class WelcomePage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Деинсталација")
        self.setSubTitle("Уклањање апликације OIK и/или њених података.")
        layout = QVBoxLayout(self)

        self.body = QLabel("…")
        self.body.setWordWrap(True)
        layout.addWidget(self.body)

        layout.addWidget(QLabel("Инсталациона фасцикла:"))
        row = QHBoxLayout()
        self.ed_path = QLineEdit("")
        row.addWidget(self.ed_path, stretch=1)
        self.btn_browse = QPushButton("Преглед…")
        self.btn_browse.clicked.connect(self._on_browse)
        row.addWidget(self.btn_browse)
        layout.addLayout(row)

        layout.addStretch()
        self.registerField("path*", self.ed_path)
        self.ed_path.textChanged.connect(self.completeChanged)

    def initializePage(self) -> None:
        detected = find_install_dir()
        if detected is not None:
            self.ed_path.setText(str(detected))
            self.body.setText(
                "Пронађена је инсталација у фасцикли испод."
                " На следећем кораку бирате шта тачно желите да уклоните."
                "\n\nКорисничке податке (поставке, збирну табелу,"
                " кориговане странице и историјат) можете задржати."
            )
        else:
            self.body.setText(
                "Аутоматска детекција није пронашла инсталацију."
                " Унесите путању до фасцикле у којој је апликација инсталирана."
            )

    def isComplete(self) -> bool:  # noqa: N802
        return bool(self.ed_path.text().strip())

    def _on_browse(self) -> None:
        start = self.ed_path.text() or os.environ.get("USERPROFILE", str(Path.home()))
        path = QFileDialog.getExistingDirectory(self, "Изабери фасциклу", start)
        if path:
            self.ed_path.setText(path)


class OptionsPage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Опције уклањања")
        self.setSubTitle("Изаберите шта желите да обришете.")
        layout = QVBoxLayout(self)

        self.detected_label = QLabel("…")
        self.detected_label.setWordWrap(True)
        self.detected_label.setObjectName("MutedLabel")
        layout.addWidget(self.detected_label)

        self.cb_shortcut = QCheckBox('Уклони пречицу „OIK" са радне површине')
        self.cb_shortcut.setChecked(True)
        layout.addWidget(self.cb_shortcut)

        self.cb_program = QCheckBox(
            "Уклони инсталационе фајлове (OIK.exe, икона, упутство)"
        )
        self.cb_program.setChecked(True)
        layout.addWidget(self.cb_program)

        self.cb_user_data = QCheckBox(
            "Уклони И корисничке податке — поставке, збирна табела, ИСТОРИЈАТ"
        )
        self.cb_user_data.setObjectName("DangerCheckbox")
        self.cb_user_data.setChecked(False)
        self.cb_user_data.toggled.connect(self._on_data_toggled)
        layout.addWidget(self.cb_user_data)

        warn = QLabel(
            "⚠ Брисање корисничких података је неповратно. Историјат корекција"
            " и сви .xlsx/.docx фајлови ће бити изгубљени. Држите ову опцију"
            " ИСКЉУЧЕНУ ако планирате да реинсталирате касније."
        )
        warn.setWordWrap(True)
        warn.setObjectName("DangerLabel")
        layout.addWidget(warn)

        confirm_row = QHBoxLayout()
        confirm_row.addWidget(QLabel(f'За потврду брисања података укуцајте „{CONFIRM_WORD}":'))
        self.ed_confirm = QLineEdit()
        self.ed_confirm.setEnabled(False)
        self.ed_confirm.textChanged.connect(self.completeChanged)
        confirm_row.addWidget(self.ed_confirm, stretch=1)
        layout.addLayout(confirm_row)

        layout.addStretch()

        self.registerField("remove_shortcut", self.cb_shortcut)
        self.registerField("remove_program", self.cb_program)
        self.registerField("remove_user_data", self.cb_user_data)

        self.cb_shortcut.toggled.connect(self.completeChanged)
        self.cb_program.toggled.connect(self.completeChanged)
        self.cb_user_data.toggled.connect(self.completeChanged)

    def initializePage(self) -> None:
        base = Path(self.field("path"))
        info = describe_install(base)
        if not info["exists"]:
            self.detected_label.setText(
                f"⚠ Не постоји фасцикла {base}. Деинсталација ће бити no-op."
            )
            return
        parts = []
        if info["program_files"]:
            parts.append(
                "Инсталациони фајлови: " + ", ".join(info["program_files"])
            )
        non_empty = [d for d in info["user_data_dirs"] if d["entries"] > 0]
        if info["user_data_files"] or non_empty:
            sub = []
            if info["user_data_files"]:
                sub.append("конфигурације: " + ", ".join(info["user_data_files"]))
            if non_empty:
                sub.append("фасцикле: " + ", ".join(
                    f"{d['name']}/ ({d['entries']})" for d in non_empty
                ))
            parts.append("Корисничке ставке — " + "; ".join(sub))
        self.detected_label.setText(
            "Пронађено у " + str(base) + ":\n  • " + "\n  • ".join(parts)
            if parts else f"Фасцикла {base} је празна."
        )

    def _on_data_toggled(self, checked: bool) -> None:
        self.ed_confirm.setEnabled(checked)
        if not checked:
            self.ed_confirm.clear()

    def isComplete(self) -> bool:  # noqa: N802
        if not (self.cb_shortcut.isChecked()
                or self.cb_program.isChecked()
                or self.cb_user_data.isChecked()):
            return False
        if self.cb_user_data.isChecked() and self.ed_confirm.text().strip() != CONFIRM_WORD:
            return False
        return True


class ExecutePage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Деинсталација")
        self.setSubTitle("Уклањање изабраних ставки.")
        self.setCommitPage(True)
        layout = QVBoxLayout(self)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log)

    def initializePage(self) -> None:
        self.log.clear()
        base = Path(self.field("path"))
        plan = UninstallPlan(
            remove_shortcut=bool(self.field("remove_shortcut")),
            remove_program_files=bool(self.field("remove_program")),
            remove_user_data=bool(self.field("remove_user_data")),
        )
        self._append(f"Циљна фасцикла: {base}")
        self._append(f"Опције: пречица={plan.remove_shortcut}, "
                     f"програм={plan.remove_program_files}, "
                     f"подаци={plan.remove_user_data}")
        self._append("")
        try:
            result = execute(base, plan)
        except Exception as e:  # noqa: BLE001
            self._append(f"Грешка: {e}")
            return
        if result.removed_files:
            self._append("Обрисани фајлови:")
            for p in result.removed_files:
                self._append(f"  − {p}")
        if result.removed_dirs:
            self._append("\nОбрисане фасцикле:")
            for p in result.removed_dirs:
                self._append(f"  − {p}/")
        if result.skipped:
            self._append("\nПрескочено:")
            for s in result.skipped:
                self._append(f"  · {s}")
        if result.errors:
            self._append("\nГрешке:")
            for e in result.errors:
                self._append(f"  ! {e}")
        if not (result.removed_files or result.removed_dirs):
            self._append("\nНичега за уклањање.")
        self._append('\nГотово. Кликните „Заврши".')

    def _append(self, text: str) -> None:
        self.log.appendPlainText(text)


class DonePage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Завршено")
        layout = QVBoxLayout(self)
        msg = QLabel(
            "Деинсталација је завршена.\n\n"
            "Уколико сте оставили корисничке податке, можете их касније"
            " ручно уклонити брисањем фасцикле."
        )
        msg.setWordWrap(True)
        layout.addWidget(msg)
        layout.addStretch()


class Uninstaller(QWizard):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("OIK — деинсталација")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)
        self.setOption(QWizard.WizardOption.HaveFinishButtonOnEarlyPages, False)
        self.setMinimumSize(720, 520)

        self.addPage(WelcomePage())
        self.addPage(OptionsPage())
        self.addPage(ExecutePage())
        self.addPage(DonePage())

        self.setButtonText(QWizard.WizardButton.NextButton, "Даље →")
        self.setButtonText(QWizard.WizardButton.BackButton, "← Назад")
        self.setButtonText(QWizard.WizardButton.CancelButton, "Откажи")
        self.setButtonText(QWizard.WizardButton.FinishButton, "Заврши")
        self.setButtonText(QWizard.WizardButton.CommitButton, "Деинсталирај")


def main() -> int:
    # Self-relaunch from %TEMP% so we don't hold the install-dir exe open
    # while we're trying to delete it. Idempotent: the relaunched copy
    # sees the sentinel env-var and skips the dance.
    if _relaunch_from_temp_if_needed():
        return 0
    app = QApplication(sys.argv)
    apply_global_style(app)
    wiz = Uninstaller()
    wiz.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
