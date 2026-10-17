"""Setup wizard for Biracki_Odbor.

Five screens via a QWizard:
  1. Добродошли — explain what will be installed where.
  2. Локација — pick install dir; if existing install, offer Upgrade.
  3. Инсталација — progress while we copy + scaffold.
  4. Пречице — desktop / Start Menu shortcut checkboxes.
  5. Завршено — Run / Close.

The wizard runs `scaffold.perform_scaffold` and is meant to be packaged
as a separate PyInstaller --onefile: `Biracki_Odbor_Setup.exe`.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout,
    QLabel, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout,
    QWidget, QWizard, QWizardPage,
)

from biracki_odbor.gui.style import apply_global_style
from biracki_odbor.installer.scaffold import (
    existing_install_info, perform_scaffold,
)


DEFAULT_DIR = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "OIK"


class WelcomePage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Добродошли")
        self.setSubTitle("Инсталација апликације OIK.")
        layout = QVBoxLayout(self)
        body = QLabel(
            "Овај чаробњак ће инсталирати апликацију OIK\n"
            "у изабрану фасциклу и припремити радни директоријум за"
            " управљање сталним саставом бирачких одбора.\n\n"
            "Ништа се не пише ван изабране фасцикле."
            " Постојеће поставке и подаци се чувају при ажурирању.\n\n"
            "Кликните „Даље” за наставак."
        )
        body.setWordWrap(True)
        layout.addWidget(body)
        layout.addStretch()


class LocationPage(QWizardPage):
    _MODES = [
        ("upgrade",      "Ажурирање — сачувај постојеће поставке и податке"),
        ("backup_reset", "Резервна копија и ресет — направи .zip, потом потпуни ресет"),
        ("clean",        "Ресет без резервне копије — обришу се сви подаци"),
    ]

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

        # Dropdown — shown only when an existing install is detected.
        self._mode_label = QLabel("Начин инсталације:")
        self._mode_combo = QComboBox()
        for key, label in self._MODES:
            self._mode_combo.addItem(label, key)
        self._mode_label.setVisible(False)
        self._mode_combo.setVisible(False)
        self._mode_combo.currentIndexChanged.connect(self._refresh_backup_label)
        layout.addWidget(self._mode_label)
        layout.addWidget(self._mode_combo)

        self._backup_dest_label = QLabel("")
        self._backup_dest_label.setObjectName("MutedLabel")
        self._backup_dest_label.setWordWrap(True)
        layout.addWidget(self._backup_dest_label)

        layout.addStretch()

        self.registerField("path*", self.ed_path)
        self.ed_path.textChanged.connect(self.completeChanged)
        self._refresh_status()

    @property
    def install_mode(self) -> str:
        """One of 'new', 'upgrade', 'backup_reset', 'clean'."""
        if not self._mode_combo.isVisible():
            return "new"
        return self._mode_combo.currentData()

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
            self._mode_label.setVisible(False)
            self._mode_combo.setVisible(False)
            self._backup_dest_label.setVisible(False)
        else:
            preserved = info.get("preserved", [])
            preserved_str = ", ".join(preserved) if preserved else "(ништа)"
            self.status.setText(f"Пронађена постојећа инсталација ({preserved_str}).")
            self._mode_label.setVisible(True)
            self._mode_combo.setVisible(True)
            self._backup_dest_label.setVisible(True)
            self._refresh_backup_label()

    def _refresh_backup_label(self) -> None:
        if not self._mode_combo.isVisible() or self._mode_combo.currentData() != "backup_reset":
            self._backup_dest_label.setText("")
            return
        from biracki_odbor.installer.scaffold import _resolve_desktop
        import datetime
        desktop = _resolve_desktop()
        dest_dir = desktop if desktop else Path.home()
        stamp = datetime.date.today().strftime("%Y-%m-%d")
        dest = dest_dir / f"OIK_резервна_{stamp}.zip"
        self._backup_dest_label.setText(f"Резервна копија → {dest}")


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

    def initializePage(self) -> None:
        self.log.clear()
        path = Path(self.field("path"))
        mode = self.wizard().location.install_mode

        if mode == "backup_reset":
            if not self._do_backup(path):
                return
            self._do_remove_user_data(path)
        elif mode == "clean":
            self._do_remove_user_data(path)

        upgrade = (mode == "upgrade")
        try:
            exe_source = _current_exe_source()
            uninstaller_source = _current_uninstaller_source()
            result = perform_scaffold(
                path,
                upgrade=upgrade,
                exe_source=exe_source,
                uninstaller_source=uninstaller_source,
            )
        except Exception as e:
            self._append(f"Грешка: {e}")
            return
        self._append(f"Инсталациона фасцикла: {result.base_dir}")
        if result.created_dirs:
            self._append("\nКреиране фасцикле:")
            for d in result.created_dirs:
                self._append(f"  + {d.name}/")
        if result.copied_files:
            self._append("\nКопирано:")
            for f in result.copied_files:
                self._append(f"  + {f.name}")
        if result.preserved_files:
            self._append("\nСачувано (ажурирање):")
            for f in result.preserved_files:
                self._append(f"  · {Path(f).name}")
        self._append("\nИнсталирање је завршено. Кликните „Даље”.")
        self.setField("install_dir", str(result.base_dir))

    def _do_backup(self, path: Path) -> bool:
        """Create a backup zip. Returns True on success, False on failure (aborts install)."""
        from biracki_odbor.core.backup import build_backup_zip
        from biracki_odbor.installer.scaffold import _resolve_desktop
        import datetime
        desktop = _resolve_desktop()
        dest_dir = desktop if desktop else Path.home()
        stamp = datetime.date.today().strftime("%Y-%m-%d")
        dest = dest_dir / f"OIK_резервна_{stamp}.zip"
        self._append("Правим резервну копију…")
        try:
            build_backup_zip(path, dest)
            self._append(f"Резервна копија: {dest}\n")
            return True
        except Exception as e:
            self._append(f"Грешка при прављењу резервне копије: {e}\nИнсталација прекинута.")
            return False

    def _do_remove_user_data(self, path: Path) -> None:
        from biracki_odbor.installer.uninstall import remove_user_data
        self._append("Уклањам постојеће корисничке податке…")
        result = remove_user_data(path)
        self._append(
            f"Уклоњено {len(result.removed_files)} фајлова,"
            f" {len(result.removed_dirs)} фасцикли.\n"
        )

    def _append(self, text: str) -> None:
        self.log.appendPlainText(text)


class DonePage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Завршено")
        layout = QVBoxLayout(self)
        self.msg = QLabel(
            "Инсталација је успешно завршена.\n\n"
            "Пречицу на радној површини можете направити касније у Поставкама"
            " (Поставке ИК → Систем)."
        )
        self.msg.setWordWrap(True)
        layout.addWidget(self.msg)
        self.cb_launch = QCheckBox("Покрени апликацију одмах")
        self.cb_launch.setChecked(True)
        layout.addWidget(self.cb_launch)
        layout.addStretch()


class RestorePage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Враћање из резервне копије")
        self.setSubTitle("Опционо — учитајте раније сачуване поставке и податке.")
        layout = QVBoxLayout(self)

        intro = QLabel(
            "Уколико имате резервну копију са претходне инсталације, "
            "изаберите .zip фајл и кликните „Врати”.\n\n"
            "Ако немате резервну копију или желите да прескочите, "
            "кликните „Даље →” без избора."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        row = QHBoxLayout()
        self.ed_zip = QLineEdit()
        self.ed_zip.setPlaceholderText("(опционо — .zip резервна копија)")
        self.ed_zip.setReadOnly(True)
        row.addWidget(self.ed_zip, stretch=1)
        self.btn_browse = QPushButton("Изабери .zip…")
        self.btn_browse.clicked.connect(self._on_browse)
        row.addWidget(self.btn_browse)
        self.btn_restore = QPushButton("Врати")
        self.btn_restore.setEnabled(False)
        self.btn_restore.clicked.connect(self._do_restore)
        row.addWidget(self.btn_restore)
        layout.addLayout(row)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(160)
        layout.addWidget(self.log)

        layout.addStretch()

    def isComplete(self) -> bool:  # noqa: N802
        return True

    def _on_browse(self) -> None:
        start = self.field("path") or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self, "Изабери резервну копију (.zip)", start, "ZIP архива (*.zip)",
        )
        if path:
            self.ed_zip.setText(path)
            self.btn_restore.setEnabled(True)
            self.log.clear()

    def _do_restore(self) -> None:
        from biracki_odbor.core.backup import inspect_zip, restore_from_zip
        zip_path = Path(self.ed_zip.text())
        install_dir = Path(self.field("path"))

        self.log.clear()
        self.btn_restore.setEnabled(False)

        try:
            info = inspect_zip(zip_path, install_dir)
        except Exception as e:  # noqa: BLE001
            self.log.appendPlainText(f"Грешка при читању архиве: {e}")
            self.btn_restore.setEnabled(True)
            return

        if info.has_stale_entries:
            self.log.appendPlainText(
                "⚠ Неки фајлови у резервној копији су старији од постојећих.\n"
                "Настављам са враћањем…\n"
            )

        try:
            result = restore_from_zip(zip_path, install_dir, make_pre_restore_backup=False)
        except Exception as e:  # noqa: BLE001
            self.log.appendPlainText(f"Грешка при враћању: {e}")
            self.btn_restore.setEnabled(True)
            return

        self.log.appendPlainText(
            f"Враћено {len(result.restored_files)} фајлова.\n"
            "Кликните „Даље →” за наставак."
        )


class Installer(QWizard):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("OIK — инсталација")
        self.setWizardStyle(QWizard.WizardStyle.ClassicStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)
        self.setOption(QWizard.WizardOption.HaveFinishButtonOnEarlyPages, False)
        self.setMinimumSize(720, 520)
        from biracki_odbor.gui.style import ACCENT, ACCENT_HOVER, SURFACE, BORDER, TEXT_PRIMARY, BODY_PT
        self.setStyleSheet(f"""
            QWizard > QWidget {{
                background: {SURFACE};
            }}
            QWizard QAbstractButton {{
                min-width: 100px;
            }}
        """)

        self.welcome = WelcomePage()
        self.location = LocationPage()
        self.install = InstallPage()
        self.restore_page = RestorePage()
        self.done_page = DonePage()

        self.addPage(self.welcome)
        self.addPage(self.location)
        self.addPage(self.install)
        self.addPage(self.restore_page)
        self.addPage(self.done_page)

        # Translate built-in button text to Cyrillic
        self.setButtonText(QWizard.WizardButton.NextButton, "Даље →")
        self.setButtonText(QWizard.WizardButton.BackButton, "← Назад")
        self.setButtonText(QWizard.WizardButton.CancelButton, "Откажи")
        self.setButtonText(QWizard.WizardButton.FinishButton, "Заврши")
        self.setButtonText(QWizard.WizardButton.CommitButton, "Инсталирај")

        self.finished.connect(self._on_finished)

    def _on_finished(self, _result: int) -> None:
        # Shortcut creation already happened in ShortcutsPage.validatePage so
        # DonePage could surface the result. Here we just optionally launch.
        base = Path(self.location.ed_path.text())
        exe = base / "OIK.exe"
        if self.done_page.cb_launch.isChecked() and exe.exists():
            try:
                subprocess.Popen([str(exe)], cwd=str(base))
            except OSError:
                pass


def _current_exe_source() -> Path | None:
    """When running as a PyInstaller-built setup.exe, the main app .exe is
    bundled alongside it (we'll configure that via PyInstaller --add-binary)
    or extracted to a known location. For now: return the directory of the
    running setup binary so the user can drop both exes side-by-side.
    """
    return _locate_bundled_exe("OIK.exe")


def _current_uninstaller_source() -> Path | None:
    """Same logic as _current_exe_source, but for the uninstaller exe."""
    return _locate_bundled_exe("OIK_Uninstaller.exe")


def _locate_bundled_exe(name: str) -> Path | None:
    """Look for `name` next to the running setup binary, then in _MEIPASS.

    When the setup wizard is itself a PyInstaller bundle, our companion
    .exes are bundled as data. PyInstaller extracts data to _MEIPASS at
    runtime; side-by-side placement is the alt path for development /
    manually-laid-out builds.
    """
    if not getattr(sys, "frozen", False):
        return None
    sibling = Path(sys.executable).parent / name
    if sibling.exists():
        return sibling
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate = Path(meipass) / name
        if candidate.exists():
            return candidate
    return None


def main() -> int:
    app = QApplication(sys.argv)
    apply_global_style(app)
    wiz = Installer()
    wiz.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
