"""Алати — utility section: PDF converter + backup/restore."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QGroupBox, QHBoxLayout, QLabel,
    QMessageBox, QProgressBar, QPushButton, QStackedWidget,
    QTabWidget, QVBoxLayout, QWidget,
)

from biracki_odbor.gui.app_state import AppState
from biracki_odbor.gui.dialogs.pdf_import_dialog import PdfImportWidget
from biracki_odbor.gui.tabs.formalizator_tool import FormalizatorPage
from biracki_odbor.gui.widgets.toggle_switch import ToggleSwitch
from biracki_odbor.gui.worker import start_worker


# ── palette (matches app theme) ───────────────────────────────────────────────
_PRI    = "#2F5496"
_PRI_S  = "#E8EEF8"
_BORDER = "#C8CFE0"
_BDR_S  = "#E2E6EF"
_WHITE  = "#FFFFFF"
_GRAY   = "#F5F6FA"
_TEXT   = "#1F2A44"
_TEXT2  = "#4A5468"
_MUTED  = "#8A92A6"
_OK_BG  = "#E4F5E6"
_OK_FG  = "#1F6F2F"
_OK_BD  = "#B6D9BD"
_WN_BG  = "#FFF3D6"
_WN_FG  = "#8A5A00"
_WN_BD  = "#EAD08A"


# ── worker functions (run in background thread) ───────────────────────────────

def _do_backup(folder_path: Path | None, do_email: bool) -> list[tuple[str, str]]:
    from biracki_odbor.core import backup as bk
    from biracki_odbor import app_paths

    zip_path = bk.build_backup_zip(app_paths.home())
    results: list[tuple[str, str]] = []
    try:
        if folder_path is not None:
            final = bk.copy_to_folder(zip_path, folder_path)
            results.append(("folder", str(final)))
        if do_email:
            from biracki_odbor.integrations import email_client as ec
            from biracki_odbor.config import settings as settings_mod
            subject, body = bk.email_subject_body()
            pref = settings_mod.load(app_paths.app_settings_path()).email_client
            ec.create_drafts(
                [ec.DraftSpec(to="", subject=subject, body=body, attachment=zip_path)],
                preference=pref,
                display_first=True,
            )
            results.append(("email", ""))
    finally:
        if folder_path is None:
            zip_path.unlink(missing_ok=True)
    return results


def _do_restore(zip_path: Path):
    from biracki_odbor.core.backup import restore_from_zip
    from biracki_odbor import app_paths
    return restore_from_zip(zip_path, app_paths.home(), make_pre_restore_backup=True)


# ── shared small helpers ──────────────────────────────────────────────────────

def _section_label(text: str, right_text: str = "") -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"font-size: 11px; font-weight: 700; letter-spacing: 0.5px; color: {_TEXT2};"
    )
    h.addWidget(lbl)
    if right_text:
        r = QLabel(right_text)
        r.setStyleSheet(f"font-size: 12px; color: {_MUTED};")
        h.addWidget(r, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return w


def _check_row(label: str, detail: str = "") -> QWidget:
    """Declares a fixed (non-optional) part of the backup scope.

    Always-on, always-disabled ToggleSwitch — same switch component used
    everywhere else in the app for on/off state, not an ad-hoc checkmark
    badge, so it doesn't read as a clickable checkbox nobody can click.
    setEnabled(False) dims it (see ToggleSwitch.setEnabled) precisely so
    it's visually distinct from the live switches below it ("Где сачувати").
    """
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(10)

    sw = ToggleSwitch()
    sw.setChecked(True)
    sw.setEnabled(False)
    h.addWidget(sw)

    bold = QLabel(label)
    bold.setStyleSheet(f"font-weight: 600; color: {_TEXT};")
    h.addWidget(bold)

    if detail:
        det = QLabel(f"· {detail}")
        det.setStyleSheet(f"font-size: 13px; color: {_MUTED};")
        h.addWidget(det)

    h.addStretch()
    return w


# ── destination tile ──────────────────────────────────────────────────────────

class _DestTile(QWidget):
    """Clickable row: toggle switch + title + description. Tile is the tap target."""

    toggled = Signal(bool)

    def __init__(self, label: str, desc: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("DestTile")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._checked = False

        row = QHBoxLayout(self)
        row.setContentsMargins(13, 11, 13, 11)
        row.setSpacing(14)

        self._sw = ToggleSwitch()
        self._sw.toggled.connect(self._sync)
        row.addWidget(self._sw, alignment=Qt.AlignmentFlag.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(3)
        self._title = QLabel(label)
        self._title.setStyleSheet(f"font-weight: 600; color: {_TEXT};")
        col.addWidget(self._title)
        d = QLabel(desc)
        d.setObjectName("MutedLabel")
        d.setWordWrap(True)
        col.addWidget(d)
        row.addLayout(col, stretch=1)

        self._restyle()

    def _sync(self, v: bool) -> None:
        self._checked = v
        self._restyle()
        self.toggled.emit(v)

    def _restyle(self) -> None:
        bd = _PRI if self._checked else _BORDER
        bg = _PRI_S if self._checked else _WHITE
        self.setStyleSheet(
            f"QWidget#DestTile {{ border: 1px solid {bd}; border-radius: 5px; background: {bg}; }}"
        )
        if hasattr(self, "_title"):
            self._title.setStyleSheet(
                f"font-weight: 600; color: {_PRI if self._checked else _TEXT};"
            )

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, v: bool) -> None:
        self._sw.setChecked(v)

    def setEnabled(self, v: bool) -> None:
        super().setEnabled(v)
        self._sw.setEnabled(v)
        self.setCursor(
            Qt.CursorShape.PointingHandCursor if v else Qt.CursorShape.ArrowCursor
        )

    def mousePressEvent(self, event) -> None:
        if self.isEnabled() and event.button() == Qt.MouseButton.LeftButton:
            self._sw.toggle()
        else:
            super().mousePressEvent(event)


# ── backup panel ──────────────────────────────────────────────────────────────

class _BackupPanel(QGroupBox):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setTitle(self.tr("Backup"))
        self._folder_path: Path = Path.home() / "Documents"
        self._state = "idle"
        self._worker = None
        self._thread = None

        v = QVBoxLayout(self)
        v.setSpacing(14)
        v.setContentsMargins(16, 20, 16, 16)

        # "Шта се чува"
        v.addWidget(_section_label("ШТА СЕ ЧУВА"))
        v.addWidget(_check_row("Поставке", "ОИК, изборна конфигурација, странке"))
        v.addWidget(_check_row("База података", "сви бирачки одбори"))

        # divider
        sep = QWidget(); sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {_BDR_S};")
        v.addWidget(sep)

        # "Где сачувати"
        v.addWidget(_section_label("ГДЕ САЧУВАТИ", "изаберите једно или више"))

        self._tile_folder = _DestTile(
            "Фасцикла на рачунару",
            "USB диск или било која фасцикла на рачунару.",
        )
        v.addWidget(self._tile_folder)

        # Folder path sub-row (indented)
        self._folder_sub = QWidget()
        fh = QHBoxLayout(self._folder_sub)
        fh.setContentsMargins(58, 0, 0, 0)
        fh.setSpacing(8)
        self._path_lbl = QLabel(str(self._folder_path))
        self._path_lbl.setStyleSheet(
            f"font-family: Consolas, monospace; font-size: 12px; color: {_TEXT2}; "
            f"background: {_GRAY}; border: 1px solid {_BORDER}; border-radius: 3px; padding: 6px 10px;"
        )
        self._path_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        fh.addWidget(self._path_lbl, stretch=1)
        btn_pick = QPushButton("Изабери…")
        btn_pick.clicked.connect(self._pick_folder)
        fh.addWidget(btn_pick)
        v.addWidget(self._folder_sub)

        self._tile_email = _DestTile(
            "Прилог мејла",
            "Отвара мејл програм са већ приложеном копијом.",
        )
        v.addWidget(self._tile_email)

        v.addStretch()

        # Status region (idle / working / done)
        self._status = QStackedWidget()
        self._status.addWidget(self._build_idle_widget())    # 0
        self._status.addWidget(self._build_working_widget()) # 1
        self._status.addWidget(self._build_done_widget())    # 2
        v.addWidget(self._status)

        # Action button
        self._btn = QPushButton("Направи резервну копију")
        self._btn.setObjectName("PrimaryButton")
        self._btn.clicked.connect(self._run)
        v.addWidget(self._btn)

        # Wire signals AFTER all widgets exist so callbacks are safe
        self._tile_folder.toggled.connect(self._on_dest_changed)
        self._tile_email.toggled.connect(self._on_dest_changed)
        self._tile_folder.setChecked(True)

    # ── idle ──────────────────────────────────────────────────────────────────

    def _build_idle_widget(self) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 6, 0, 0)
        self._idle_lbl = QLabel()
        self._idle_lbl.setStyleSheet(f"font-size: 13px; color: {_MUTED};")
        h.addWidget(self._idle_lbl)
        h.addStretch()
        self._refresh_idle()
        return w

    def _refresh_idle(self) -> None:
        try:
            from biracki_odbor import app_paths
            backup_dir = app_paths.home() / "backups"
            if backup_dir.exists():
                zips = sorted(
                    backup_dir.glob("*.zip"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                if zips:
                    from datetime import datetime
                    t = datetime.fromtimestamp(zips[0].stat().st_mtime)
                    kb = zips[0].stat().st_size // 1024
                    sz = f"{kb / 1024:.1f} MB" if kb > 1024 else f"{kb} KB"
                    self._idle_lbl.setText(
                        f"Последња копија: {t.strftime('%d.%m.%Y. у %H:%M')} · {sz}"
                    )
                    return
        except Exception:
            pass
        self._idle_lbl.setText("Нема претходних резервних копија.")

    # ── working ───────────────────────────────────────────────────────────────

    def _build_working_widget(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 6, 0, 0)
        v.setSpacing(8)
        lbl = QLabel("Прави се резервна копија…")
        lbl.setStyleSheet(f"font-weight: 500; color: {_TEXT};")
        v.addWidget(lbl)
        self._backup_bar = QProgressBar()
        self._backup_bar.setRange(0, 0)
        self._backup_bar.setFixedHeight(8)
        self._backup_bar.setTextVisible(False)
        v.addWidget(self._backup_bar)
        return w

    # ── done ──────────────────────────────────────────────────────────────────

    def _build_done_widget(self) -> QWidget:
        w = QWidget()
        self._done_vbox = QVBoxLayout(w)
        self._done_vbox.setContentsMargins(0, 6, 0, 0)
        self._done_vbox.setSpacing(0)
        return w

    def _populate_done(self, results: list[tuple[str, str]]) -> None:
        while self._done_vbox.count():
            item = self._done_vbox.takeAt(0)
            if item is not None:
                w = item.widget()
                if w is not None:
                    w.deleteLater()

        box = QWidget()
        box.setStyleSheet(
            f"QWidget {{ border: 1px solid {_OK_BD}; border-radius: 5px; background: {_OK_BG}; }}"
        )
        bv = QVBoxLayout(box)
        bv.setContentsMargins(14, 12, 14, 12)
        bv.setSpacing(10)

        hdr = QHBoxLayout()
        tick = QLabel("✓")
        tick.setFixedSize(24, 24)
        tick.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tick.setStyleSheet(
            f"color: {_OK_FG}; font-weight: 800; font-size: 15px; background: transparent; border: none;"
        )
        hdr.addWidget(tick)
        n = len(results)
        title_str = (
            f"Копија сачувана на {n} локације" if n > 1 else "Резервна копија сачувана"
        )
        t = QLabel(title_str)
        t.setStyleSheet(
            f"font-weight: 600; font-size: 14px; color: {_OK_FG}; background: transparent; border: none;"
        )
        hdr.addWidget(t)
        hdr.addStretch()
        bv.addLayout(hdr)

        for dest_id, path_str in results:
            if dest_id == "folder":
                rl = QLabel("Фасцикла на рачунару")
                rl.setStyleSheet(
                    f"font-weight: 600; color: {_TEXT}; background: transparent; border: none;"
                )
                bv.addWidget(rl)
                pl = QLabel(path_str)
                pl.setStyleSheet(
                    f"font-family: Consolas, monospace; font-size: 11px; color: {_TEXT}; "
                    f"background: {_WHITE}; border: 1px solid {_OK_BD}; border-radius: 3px; padding: 5px 8px;"
                )
                pl.setWordWrap(True)
                pl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                bv.addWidget(pl)
                folder = Path(path_str).parent
                btn_open = QPushButton("Отвори фасциклу")
                btn_open.setStyleSheet("border: none; background: transparent;")
                btn_open.clicked.connect(
                    lambda _=False, p=folder: __import__("subprocess").Popen(
                        ["explorer", str(p)]
                    )
                )
                br = QHBoxLayout()
                br.addWidget(btn_open)
                br.addStretch()
                bv.addLayout(br)
            elif dest_id == "email":
                el = QLabel("Прилог мејла — мејл програм је отворен")
                el.setStyleSheet(
                    f"color: {_TEXT2}; background: transparent; border: none;"
                )
                bv.addWidget(el)

        dr = QHBoxLayout()
        dr.addStretch()
        dismiss = QPushButton("Затвори")
        dismiss.clicked.connect(self._reset)
        dr.addWidget(dismiss)
        bv.addLayout(dr)

        self._done_vbox.addWidget(box)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _pick_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Изабери фасциклу за резервну копију", str(self._folder_path)
        )
        if path:
            self._folder_path = Path(path)
            self._path_lbl.setText(str(self._folder_path))

    def _on_dest_changed(self, _: bool) -> None:
        self._folder_sub.setVisible(self._tile_folder.isChecked())
        self._update_btn()

    def _update_btn(self) -> None:
        n = sum([self._tile_folder.isChecked(), self._tile_email.isChecked()])
        if self._state == "working":
            self._btn.setEnabled(False)
            self._btn.setText("Прави се копија…")
        elif n == 0:
            self._btn.setEnabled(False)
            self._btn.setText("Направи резервну копију")
        elif n > 1:
            self._btn.setEnabled(True)
            self._btn.setText(
                "Направи нову копију" if self._state == "done" else f"Сачувај на {n} локације"
            )
        else:
            self._btn.setEnabled(True)
            self._btn.setText(
                "Направи нову копију" if self._state == "done" else "Направи резервну копију"
            )

    def _set_tiles_enabled(self, v: bool) -> None:
        self._tile_folder.setEnabled(v)
        self._tile_email.setEnabled(v)

    # ── run ───────────────────────────────────────────────────────────────────

    def _run(self) -> None:
        do_folder = self._tile_folder.isChecked()
        do_email = self._tile_email.isChecked()
        if not do_folder and not do_email:
            return

        self._state = "working"
        self._set_tiles_enabled(False)
        self._status.setCurrentIndex(1)
        self._update_btn()

        folder_path = self._folder_path if do_folder else None
        self._worker, self._thread = start_worker(self, _do_backup, folder_path, do_email)
        self._worker.finished.connect(self._on_done)
        self._worker.failed.connect(self._on_error)

    def _on_done(self, results: object) -> None:
        self._state = "done"
        self._set_tiles_enabled(True)
        self._populate_done(results)  # type: ignore[arg-type]
        self._status.setCurrentIndex(2)
        self._update_btn()
        self._refresh_idle()

    def _on_error(self, msg: str) -> None:
        self._state = "idle"
        self._set_tiles_enabled(True)
        self._status.setCurrentIndex(0)
        self._update_btn()
        QMessageBox.critical(self, "Резервна копија", f"Грешка:\n{msg}")

    def _reset(self) -> None:
        self._state = "idle"
        self._refresh_idle()
        self._status.setCurrentIndex(0)
        self._update_btn()


# ── restore panel ─────────────────────────────────────────────────────────────

class _RestorePanel(QGroupBox):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setTitle(self.tr("Restore from backup"))
        self._zip_path: Path | None = None
        self._worker = None
        self._thread = None

        v = QVBoxLayout(self)
        v.setSpacing(12)
        v.setContentsMargins(16, 20, 16, 16)

        # Warning banner
        warn = QWidget()
        warn.setStyleSheet(
            f"QWidget {{ border: 1px solid {_WN_BD}; border-radius: 5px; background: {_WN_BG}; }}"
        )
        wh = QHBoxLayout(warn)
        wh.setContentsMargins(12, 10, 12, 10)
        wh.setSpacing(10)
        bang = QLabel("!")
        bang.setFixedSize(22, 22)
        bang.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bang.setStyleSheet(
            f"color: white; background: {_WN_FG}; border-radius: 11px; "
            f"font-weight: 800; font-size: 13px; border: none;"
        )
        wh.addWidget(bang, alignment=Qt.AlignmentFlag.AlignTop)
        msg = QLabel(
            "Враћање <b>замењује</b> тренутне поставке и базу. "
            "Пре замене се <b>аутоматски</b> прави сигурносна копија тренутног стања."
        )
        msg.setWordWrap(True)
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setStyleSheet(f"color: {_WN_FG}; border: none; background: transparent;")
        wh.addWidget(msg, stretch=1)
        v.addWidget(warn)

        # Main content: drop zone OR file view (stacked)
        self._stack = QStackedWidget()
        self._drop_zone = _DropZone()
        self._drop_zone.file_chosen.connect(self._on_file_chosen)
        self._stack.addWidget(self._drop_zone)        # 0
        self._stack.addWidget(self._build_file_page()) # 1
        v.addWidget(self._stack, stretch=1)

    def _build_file_page(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)

        self._file_card = _FileCard()
        self._file_card.remove_clicked.connect(self._reset)
        v.addWidget(self._file_card)

        v.addStretch()

        # Footer stack: button / progress / done
        self._footer = QStackedWidget()
        self._footer.setMaximumHeight(130)

        # page 0 — restore button
        bp = QWidget()
        bv = QVBoxLayout(bp)
        bv.setContentsMargins(0, 0, 0, 0)
        self._btn_restore = QPushButton("Врати из ове копије")
        self._btn_restore.setObjectName("DangerButton")
        self._btn_restore.clicked.connect(self._run_restore)
        bv.addWidget(self._btn_restore)
        self._footer.addWidget(bp)  # 0

        # page 1 — progress
        pp = QWidget()
        pv = QVBoxLayout(pp)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(8)
        pv.addWidget(QLabel("Враћа се копија…"))
        self._restore_bar = QProgressBar()
        self._restore_bar.setRange(0, 0)
        self._restore_bar.setFixedHeight(8)
        self._restore_bar.setTextVisible(False)
        pv.addWidget(self._restore_bar)
        self._footer.addWidget(pp)  # 1

        # page 2 — done
        dp = QWidget()
        dv = QVBoxLayout(dp)
        dv.setContentsMargins(0, 0, 0, 0)
        dv.setSpacing(8)
        self._done_lbl = QLabel()
        self._done_lbl.setTextFormat(Qt.TextFormat.RichText)
        self._done_lbl.setWordWrap(True)
        self._done_lbl.setStyleSheet(
            f"border: 1px solid {_OK_BD}; border-radius: 5px; background: {_OK_BG}; "
            f"color: {_OK_FG}; padding: 10px 12px;"
        )
        dv.addWidget(self._done_lbl)
        btn_another = QPushButton("Врати другу копију")
        btn_another.clicked.connect(self._reset)
        dv.addWidget(btn_another)
        self._footer.addWidget(dp)  # 2

        v.addWidget(self._footer)
        return w

    def _on_file_chosen(self, path: Path) -> None:
        from biracki_odbor import app_paths
        from biracki_odbor.core.backup import inspect_zip

        try:
            info = inspect_zip(path, app_paths.home())
        except Exception as e:
            QMessageBox.critical(self, "Грешка", f"Не могу да отворим архиву:\n{e}")
            return

        self._zip_path = path
        self._file_card.set_info(info)
        self._btn_restore.setText(
            "Замени и врати" if info.has_stale_entries else "Врати из ове копије"
        )
        self._btn_restore.setEnabled(True)
        self._footer.setCurrentIndex(0)
        self._stack.setCurrentIndex(1)

    def _run_restore(self) -> None:
        if self._zip_path is None:
            return
        self._btn_restore.setEnabled(False)
        self._footer.setCurrentIndex(1)
        self._worker, self._thread = start_worker(self, _do_restore, self._zip_path)
        self._worker.finished.connect(self._on_restore_done)
        self._worker.failed.connect(self._on_restore_error)

    def _on_restore_done(self, result: object) -> None:
        self._done_lbl.setText(
            "<b>✓ Стање је враћено</b><br>"
            "Поставке и база су враћене. Поново покрените апликацију."
        )
        self._footer.setCurrentIndex(2)
        win = self.window()
        if hasattr(win, "statusBar"):
            win.statusBar().showMessage("Враћено. Поново покрените апликацију.", 12000)

    def _on_restore_error(self, msg: str) -> None:
        self._footer.setCurrentIndex(0)
        self._btn_restore.setEnabled(True)
        QMessageBox.critical(self, "Грешка при враћању", f"Враћање није успело:\n{msg}")

    def _reset(self) -> None:
        self._zip_path = None
        self._btn_restore.setEnabled(True)
        self._footer.setCurrentIndex(0)
        self._stack.setCurrentIndex(0)


# ── drop zone ─────────────────────────────────────────────────────────────────

class _DropZone(QWidget):
    file_chosen = Signal(Path)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._drag = False
        self._build()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.setSpacing(12)

        badge = QLabel("ZIP")
        badge.setFixedHeight(30)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"color: white; background: {_PRI}; border-radius: 3px; "
            f"font-weight: 700; font-size: 12px; padding: 0 12px;"
        )
        v.addWidget(badge, alignment=Qt.AlignmentFlag.AlignCenter)

        t = QLabel("Превуците .zip фајл овде")
        t.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {_TEXT};")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(t)

        or_lbl = QLabel("или")
        or_lbl.setObjectName("MutedLabel")
        or_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(or_lbl)

        btn = QPushButton("Изабери .zip…")
        btn.clicked.connect(self._pick)
        v.addWidget(btn, alignment=Qt.AlignmentFlag.AlignCenter)
        self._restyle()

    def _restyle(self) -> None:
        bd = _PRI if self._drag else _BORDER
        bg = _PRI_S if self._drag else _GRAY
        self.setStyleSheet(
            f"QWidget#DropZone {{ border: 2px dashed {bd}; border-radius: 6px; background: {bg}; }}"
        )

    def _pick(self) -> None:
        try:
            from biracki_odbor import app_paths
            start = str(app_paths.home())
        except Exception:
            start = str(Path.home())
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Изабери резервну копију", start, "ZIP архива (*.zip)"
        )
        if path_str:
            self.file_chosen.emit(Path(path_str))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._pick()
        else:
            super().mousePressEvent(event)

    def dragEnterEvent(self, event) -> None:
        urls = event.mimeData().urls() if event.mimeData().hasUrls() else []
        if any(u.toLocalFile().lower().endswith(".zip") for u in urls):
            event.acceptProposedAction()
            self._drag = True
            self._restyle()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._drag = False
        self._restyle()

    def dropEvent(self, event) -> None:
        self._drag = False
        self._restyle()
        for url in event.mimeData().urls():
            p = url.toLocalFile()
            if p.lower().endswith(".zip"):
                self.file_chosen.emit(Path(p))
                break


# ── file card ─────────────────────────────────────────────────────────────────

class _FileCard(QWidget):
    remove_clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # Header
        hdr = QWidget()
        hdr.setStyleSheet(
            f"QWidget {{ background: {_GRAY}; border: 1px solid {_BORDER}; "
            f"border-radius: 5px 5px 0 0; }}"
        )
        hh = QHBoxLayout(hdr)
        hh.setContentsMargins(12, 10, 12, 10)
        hh.setSpacing(10)

        badge = QLabel("ZIP")
        badge.setFixedHeight(26)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"color: white; background: {_PRI}; border-radius: 3px; "
            f"font-weight: 700; font-size: 11px; padding: 0 8px; border: none;"
        )
        hh.addWidget(badge)

        info_col = QVBoxLayout()
        info_col.setSpacing(1)
        self._name_lbl = QLabel()
        self._name_lbl.setStyleSheet(
            f"font-family: Consolas, monospace; font-size: 13px; color: {_TEXT}; "
            f"background: transparent; border: none;"
        )
        info_col.addWidget(self._name_lbl)
        self._meta_lbl = QLabel()
        self._meta_lbl.setStyleSheet(
            f"font-size: 12px; color: {_MUTED}; background: transparent; border: none;"
        )
        info_col.addWidget(self._meta_lbl)
        hh.addLayout(info_col, stretch=1)

        rm_btn = QPushButton("Уклони")
        rm_btn.clicked.connect(self.remove_clicked)
        hh.addWidget(rm_btn)
        v.addWidget(hdr)

        # Body
        body = QWidget()
        body.setStyleSheet(
            f"QWidget {{ background: {_WHITE}; border: 1px solid {_BORDER}; "
            f"border-top: none; border-radius: 0 0 5px 5px; }}"
        )
        bv = QVBoxLayout(body)
        bv.setContentsMargins(12, 10, 12, 10)
        bv.setSpacing(6)
        bv.addWidget(_section_label("САДРЖАЈ КОПИЈЕ"))
        self._content_rows = QVBoxLayout()
        self._content_rows.setSpacing(4)
        bv.addLayout(self._content_rows)
        v.addWidget(body)

    def set_info(self, info) -> None:
        self._name_lbl.setText(info.path.name)
        parts = []
        if info.newest_entry_mtime:
            parts.append(f"сачувано {info.newest_entry_mtime.strftime('%d.%m.%Y. у %H:%M')}")
        if info.file_count:
            parts.append(f"{info.file_count} фајлова")
        self._meta_lbl.setText(" · ".join(parts))

        while self._content_rows.count():
            item = self._content_rows.takeAt(0)
            if item is not None:
                w = item.widget()
                if w is not None:
                    w.deleteLater()

        self._content_rows.addWidget(_check_row("Поставке", "ОИК, изборна конфигурација, странке"))
        self._content_rows.addWidget(_check_row("База података"))


# ── top-level page ────────────────────────────────────────────────────────────

class _BackupRestorePage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)

        row = QHBoxLayout()
        row.setSpacing(24)
        row.addWidget(_BackupPanel(), stretch=1)
        row.addWidget(_RestorePanel(), stretch=1)
        layout.addLayout(row)
        layout.addStretch()


class AlatiPage(QWidget):
    def __init__(self, state: AppState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        tabs = QTabWidget()
        tabs.addTab(PdfImportWidget(state), self.tr("PDF Converter"))
        # The companion app sits beside the PDF tool rather than after
        # Backup: both are things the operator reaches for mid-task.
        tabs.addTab(FormalizatorPage(state), self.tr("Formalizator"))
        tabs.addTab(_BackupRestorePage(), self.tr("Backup"))
        layout.addWidget(tabs)
