"""Алати → Коверте: envelope designer and generator (bonus tool).

Same block builder as observer ID cards (BlockLayoutEditor); here the
setup box picks the envelope type and which polling stations to print.
Output: one Word document, one envelope-sized landscape page per BM,
saved under the app home and copied to the export folder ("Коверте").
"""

from __future__ import annotations

import logging
import subprocess

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from biracki_odbor import app_paths
from biracki_odbor.config.commission import commission_terms
from biracki_odbor.core import envelopes
from biracki_odbor.core.observers import BLOCK_DIVIDER, BLOCK_SPACER, BLOCK_STATIC_TEXT
from biracki_odbor.gui.app_state import AppState
from biracki_odbor.gui.widgets.block_layout_editor import (
    BlockLayoutEditor, BlockPalette, no_wheel,
)

log = logging.getLogger(__name__)

EXPORT_PURPOSE = "Коверте"

_COLORS = {
    BLOCK_STATIC_TEXT: "#D0E8F5",
    envelopes.ENV_BM_TITLE: "#D5F0DA",
    envelopes.ENV_BM_NAME: "#D5F0DA",
    envelopes.ENV_BM_ADDRESS: "#D5F0DA",
    envelopes.ENV_COMMISSION: "#FDEBD0",
    envelopes.ENV_ELECTION: "#FDEBD0",
    BLOCK_DIVIDER: "#DADADA",
    BLOCK_SPACER: "#F8F8F8",
}


class KovertePage(BlockLayoutEditor):
    def __init__(self, state: AppState, parent=None) -> None:
        self.state = state
        self.TITLE = self.tr("Envelopes")
        self.BLOCKS_TITLE = self.tr("Envelope layout")
        self.PREVIEW_TITLE = self.tr("Envelope preview (first selected BM)")
        super().__init__(parent)
        self._type_combo.currentIndexChanged.connect(self._on_type_changed)
        self.state.oik_changed.connect(self._reload_stations)
        self.state.election_changed.connect(self._refresh_preview)
        self._load_from_state()

    # ── BlockLayoutEditor hooks ───────────────────────────────────
    def _palette(self) -> BlockPalette:
        return BlockPalette(
            types=list(envelopes.ENVELOPE_BLOCK_TYPES),
            labels=envelopes.ENVELOPE_BLOCK_LABELS,
            colors=_COLORS,
            preview_text=lambda blk: envelopes.block_text(blk, self._sample_station(), self._context()) or "…",
            static_hint=self.tr("e.g. ELECTION MATERIAL"),
            static_tooltip=self.tr(
                "Placeholders replaced for each envelope:\n"
                "  [bm]           → polling station number\n"
                "  [bm_name]      → polling station name\n"
                "  [municipality] → municipality name\n"
                "  [election]     → election name"
            ),
        )

    def _page_size_mm(self) -> tuple[float, float]:
        return envelopes.envelope_size_landscape(self._current_type())

    def _build_header_actions(self, row: QHBoxLayout) -> None:
        self.btn_open = QPushButton(self.tr("Open folder…"))
        self.btn_open.clicked.connect(self._open_folder)
        row.addWidget(self.btn_open)
        self.btn_generate = QPushButton(self.tr("Generate envelopes"))
        self.btn_generate.clicked.connect(self._generate)
        row.addWidget(self.btn_generate)

    def _build_setup_box(self) -> QWidget:
        box = QGroupBox(self.tr("Envelope"))
        lay = QVBoxLayout(box)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._type_combo = QComboBox()
        self._type_combo.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._type_combo.installEventFilter(no_wheel())
        for key, (label, w, h) in envelopes.ENVELOPE_TYPES.items():
            self._type_combo.addItem(f"{label}  ({int(w)}×{int(h)} mm)", key)
        form.addRow(self.tr("Envelope type:"), self._type_combo)
        lay.addLayout(form)

        lay.addWidget(QLabel(self.tr("Polling stations (one envelope each):")))
        self.list_bm = QListWidget()
        self.list_bm.setMinimumHeight(140)
        self.list_bm.setMaximumHeight(220)
        self.list_bm.itemChanged.connect(lambda _i: self._refresh_preview())
        lay.addWidget(self.list_bm)
        sel = QHBoxLayout()
        btn_all = QPushButton(self.tr("Select all"))
        btn_all.clicked.connect(lambda: self._check_all(True))
        btn_none = QPushButton(self.tr("Select none"))
        btn_none.clicked.connect(lambda: self._check_all(False))
        sel.addWidget(btn_all)
        sel.addWidget(btn_none)
        sel.addStretch()
        lay.addLayout(sel)
        return box

    def _stored_layout(self):
        return self.state.app_settings.koverte.layout

    def _store_layout(self, blocks) -> None:
        self.state.app_settings.koverte.layout = blocks

    def _default_layout(self):
        return envelopes.default_envelope_layout()

    def _save(self) -> None:
        try:
            self.state.save_app_settings()
        except OSError as e:
            log.warning("envelope settings save failed: %s", e)

    # ── data ──────────────────────────────────────────────────────
    def _current_type(self) -> str:
        if not hasattr(self, "_type_combo"):
            return envelopes.ENV_C4_POCKET
        return self._type_combo.currentData() or envelopes.ENV_C4_POCKET

    def _context(self) -> envelopes.EnvelopeContext:
        from biracki_odbor.gui.tabs.posmatraci_workspace import _election_label
        mun = self.state.oik.municipality
        return envelopes.EnvelopeContext(
            municipality=mun.name,
            commission=commission_terms(mun).preamble_subject if mun.name else "",
            election=_election_label(self.state),
        )

    def selected_stations(self) -> list:
        by_bm = {s.bm_number: s for s in self.state.oik.polling_stations}
        out = []
        for i in range(self.list_bm.count()):
            item = self.list_bm.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                st = by_bm.get(item.data(Qt.ItemDataRole.UserRole))
                if st is not None:
                    out.append(st)
        return out

    def _sample_station(self):
        if hasattr(self, "list_bm"):
            chosen = self.selected_stations()
            if chosen:
                return chosen[0]
        stations = self.state.oik.polling_stations
        if stations:
            return stations[0]
        from biracki_odbor.core.models import PollingStation
        return PollingStation(bm_number=1, name="Назив бирачког места", address="Адреса")

    def _reload_stations(self) -> None:
        checked = {s.bm_number for s in self.selected_stations()} if self.list_bm.count() else None
        self.list_bm.blockSignals(True)
        self.list_bm.clear()
        for st in sorted(self.state.oik.polling_stations, key=lambda s: s.bm_number):
            item = QListWidgetItem(f"{st.bm_number}. {st.full_name or st.name}")
            item.setData(Qt.ItemDataRole.UserRole, st.bm_number)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            on = checked is None or st.bm_number in checked
            item.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
            self.list_bm.addItem(item)
        self.list_bm.blockSignals(False)
        self._refresh_preview()

    def _check_all(self, on: bool) -> None:
        self.list_bm.blockSignals(True)
        for i in range(self.list_bm.count()):
            self.list_bm.item(i).setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        self.list_bm.blockSignals(False)
        self._refresh_preview()

    def _load_from_state(self) -> None:
        self._loading = True
        try:
            cfg = self.state.app_settings.koverte
            self._type_combo.setCurrentIndex(max(0, self._type_combo.findData(cfg.envelope_type)))
            self._load_layout(self._stored_layout())
            self._reload_stations()
        finally:
            self._loading = False
        self._refresh_preview()

    def _on_type_changed(self) -> None:
        if self._loading:
            return
        self.state.app_settings.koverte.envelope_type = self._current_type()
        self._refresh_preview()
        self._save()

    # ── output ────────────────────────────────────────────────────
    def output_path(self):
        return app_paths.home() / "koverte" / envelopes.output_filename(self._current_type())

    def _generate(self) -> None:
        stations = self.selected_stations()
        if not stations:
            QMessageBox.information(
                self, self.tr("Envelopes"),
                self.tr("Select at least one polling station (Поставке ИК → Бирачка места)."),
            )
            return
        cfg = envelopes.EnvelopeSettings(self._current_type(), self.blocks())
        try:
            out = envelopes.generate_envelopes(stations, cfg, self._context(), self.output_path())
        except OSError as exc:
            QMessageBox.warning(
                self, self.tr("Envelopes"),
                self.tr("Could not save the envelopes (is the file open in Word?):\n{error}").format(error=exc),
            )
            return
        self.state.export_generated(EXPORT_PURPOSE, [out])
        self._save_label.setText(
            self.tr("{n} envelope(s) saved: {name}").format(n=len(stations), name=out.name)
        )
        self._open_folder()

    def _open_folder(self) -> None:
        folder = self.state.files_dir(EXPORT_PURPOSE)
        try:
            subprocess.Popen(["explorer", str(folder)])
        except OSError:
            QMessageBox.information(
                self, self.tr("Folder"), self.tr("Output folder:\n{folder}").format(folder=folder),
            )
