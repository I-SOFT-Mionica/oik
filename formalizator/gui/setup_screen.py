"""Screen 1 — session setup: pick a template (or create a new one),
fill in whatever session-fixed data that document actually needs (the
operator's own "universal" custom fields — a list name, a certifier,
or anything else, named per template rather than a handful of concepts
hardcoded here), and set the print copy count.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from biracki_odbor.gui.widgets.spinbox import inset_spinbox_text
from formalizator.core import export_template_catalog, template_catalog
from formalizator.core.models import CalibratedTemplate, SessionInfo
from formalizator.core.print_pdf import SAVE_AS_PDF
from formalizator.gui.export_template_wizard import ExportTemplateDialog
from formalizator.gui.fillout_screen import _page_order_key
from formalizator.gui.template_wizard import NewTemplateDialog

_NEW_TEMPLATE_LABEL = "+ Нови шаблон…"
_NO_EXPORT_LABEL = "(без извоза)"
_NEW_EXPORT_TEMPLATE_LABEL = "+ Нови извозни шаблон…"
_NEW_EXPORT_TEMPLATE_SENTINEL = "__new_export_template__"


class SetupScreen(QWidget):
    """Emits `session_ready(SessionInfo, CalibratedTemplate)` once the
    operator has picked a template and filled the permanent fields."""

    session_ready = Signal(object, object)

    def __init__(self, catalog_dir: Path, home_dir: Path | None = None, parent=None) -> None:
        super().__init__(parent)
        self._catalog_dir = catalog_dir
        self._home_dir = home_dir or catalog_dir.parent
        self._templates: list[CalibratedTemplate] = []

        # Same available-height problem as FilloutScreen, and worse here
        # because this screen's height is driven by the template: the
        # "Додатна поља овог шаблона" group grows a row per session field
        # the operator defined during calibration. Measured at 940 px
        # before this, against the 816 logical pixels a 1920x1080 laptop
        # at 125% scaling actually has below the taskbar — so the
        # Настави button and the last fields fell off the bottom.
        #
        # The content scrolls; the Настави button is deliberately left
        # outside the scroll area, pinned to the bottom, so the way
        # forward is never something the operator has to scroll to find.
        outer = QVBoxLayout(self)
        content_widget = QWidget()
        root = QVBoxLayout(content_widget)

        title = QLabel("Нова сесија прикупљања подршке")
        title.setStyleSheet("font-size:18px;font-weight:600;")
        root.addWidget(title)

        tpl_box = QGroupBox("Шаблон изјаве")
        tpl_layout = QHBoxLayout(tpl_box)
        self.cb_template = QComboBox()
        self.cb_template.currentIndexChanged.connect(self._on_template_index_changed)
        tpl_layout.addWidget(self.cb_template, stretch=1)
        # Calibrating a template is a lot of fiddly clicking — without
        # this, finishing every field correctly in one sitting was the
        # only option; a mistake or an interruption meant starting the
        # whole template over from a blank document.
        self.btn_edit_template = QPushButton("Уреди…")
        self.btn_edit_template.clicked.connect(self._edit_selected_template)
        self.btn_edit_template.setEnabled(False)
        tpl_layout.addWidget(self.btn_edit_template)
        root.addWidget(tpl_box)

        self.lbl_pick_template_hint = QLabel(
            "Прво изаберите шаблон изјаве за оверу потписа — стални подаци"
            " и наставак постају доступни тек онда."
        )
        self.lbl_pick_template_hint.setWordWrap(True)
        self.lbl_pick_template_hint.setStyleSheet("color:#666;font-style:italic;")
        root.addWidget(self.lbl_pick_template_hint)

        self.copies_box = QGroupBox("Штампа")
        copies_form = QFormLayout(self.copies_box)
        self.sb_copies = QSpinBox()
        self.sb_copies.setRange(1, 10)
        self.sb_copies.setValue(1)
        inset_spinbox_text(self.sb_copies)
        copies_form.addRow("Број примерака за штампу:", self.sb_copies)

        # Naming the printer outright beats every attempt to infer it.
        # On a domain-managed machine the default printer is set by
        # Group Policy and reapplied behind the operator's back, so a
        # locally-changed default does not survive — reported from the
        # field after a long fight to print from exactly such a machine.
        printer_row = QHBoxLayout()
        self.cb_printer = QComboBox()
        printer_row.addWidget(self.cb_printer, stretch=1)
        self.btn_refresh_printers = QPushButton("Освежи")
        self.btn_refresh_printers.setToolTip(
            "Поново потражи штампаче — ако сте штампач прикључили након"
            " покретања програма."
        )
        self.btn_refresh_printers.clicked.connect(self._reload_printers)
        printer_row.addWidget(self.btn_refresh_printers)
        copies_form.addRow("Штампач:", printer_row)
        self._reload_printers()
        self.copies_box.setVisible(False)
        root.addWidget(self.copies_box)

        # Rebuilt per template — this document's own "same for every
        # copy in the session" fields (e.g. NPRS-3's certifier name),
        # named by the operator during calibration rather than
        # hardcoded here, since a different document calibrated later
        # may need a completely different set of them.
        self.custom_universal_box = QGroupBox("Додатна поља овог шаблона (уносе се једном за сесију)")
        self.custom_universal_form = QFormLayout(self.custom_universal_box)
        self.custom_universal_box.setVisible(False)
        root.addWidget(self.custom_universal_box)
        self._custom_universal_edits: dict[str, QLineEdit] = {}

        # Optional — configured here, once, right after a template is
        # picked/created, rather than mid-session: which cumulative
        # Excel layout (if any) "Заврши сесију и извези" produces for
        # this sitting. "(без извоза)" (no export) is the default so
        # nothing about this is mandatory.
        self.export_box = QGroupBox("Извоз у Excel (опционо)")
        export_layout = QHBoxLayout(self.export_box)
        self.cb_export_template = QComboBox()
        self.cb_export_template.currentIndexChanged.connect(self._on_export_template_index_changed)
        export_layout.addWidget(self.cb_export_template, stretch=1)
        self.btn_edit_export_template = QPushButton("Уреди…")
        self.btn_edit_export_template.clicked.connect(self._edit_export_template)
        export_layout.addWidget(self.btn_edit_export_template)
        self.export_box.setVisible(False)
        root.addWidget(self.export_box)
        self._export_templates: list = []

        root.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(content_widget)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll, stretch=1)

        self.btn_continue = QPushButton("Настави →")
        self.btn_continue.setObjectName("PrimaryButton")
        self.btn_continue.clicked.connect(self._on_continue)
        self.btn_continue.setVisible(False)
        outer.addWidget(self.btn_continue)

        self.reload_catalog()

    def reload_catalog(self) -> None:
        self._templates = template_catalog.load_catalog(self._catalog_dir)
        self.cb_template.blockSignals(True)
        self.cb_template.clear()
        for t in self._templates:
            self.cb_template.addItem(t.name)
        self.cb_template.addItem(_NEW_TEMPLATE_LABEL)
        self.cb_template.setCurrentIndex(-1)
        self.cb_template.blockSignals(False)
        self._sync_data_section_visibility()

    def _on_template_index_changed(self, index: int) -> None:
        if self.cb_template.itemText(index) == _NEW_TEMPLATE_LABEL:
            self._create_new_template()
            return
        self._sync_data_section_visibility()

    def _sync_data_section_visibility(self) -> None:
        template = self.selected_template()
        has_template = template is not None
        self.copies_box.setVisible(has_template)
        self.btn_continue.setVisible(has_template)
        self.btn_edit_template.setEnabled(has_template)
        self.export_box.setVisible(has_template)
        self.lbl_pick_template_hint.setVisible(not has_template)
        self._rebuild_custom_universal_fields(template)
        if has_template:
            self._reload_export_templates()

    def _rebuild_custom_universal_fields(self, template: CalibratedTemplate | None) -> None:
        while self.custom_universal_form.rowCount():
            self.custom_universal_form.removeRow(0)
        self._custom_universal_edits.clear()
        universal = [cf for cf in template.custom_fields if cf.kind == "universal"] if template else []
        # Same reasoning as the fill-out screen's individual fields:
        # follow the document's own top-to-bottom order, not whatever
        # order the fields happened to be defined in during
        # calibration — filling the page by hand is confusing
        # otherwise.
        if template is not None:
            universal.sort(key=lambda cf: _page_order_key(template, cf.key))
        for cf in universal:
            ed = QLineEdit(cf.default_value)
            self.custom_universal_form.addRow(f"{cf.label}:", ed)
            self._custom_universal_edits[cf.key] = ed
        self.custom_universal_box.setVisible(bool(universal))

    def _reload_export_templates(self, select_name: str = "") -> None:
        self._export_templates = export_template_catalog.load_catalog(self._home_dir)
        self.cb_export_template.blockSignals(True)
        self.cb_export_template.clear()
        self.cb_export_template.addItem(_NO_EXPORT_LABEL, "")
        for t in self._export_templates:
            self.cb_export_template.addItem(t.name, t.name)
        self.cb_export_template.addItem(_NEW_EXPORT_TEMPLATE_LABEL, _NEW_EXPORT_TEMPLATE_SENTINEL)
        idx = self.cb_export_template.findData(select_name)
        self.cb_export_template.setCurrentIndex(idx if idx >= 0 else 0)
        self.cb_export_template.blockSignals(False)

    def _on_export_template_index_changed(self, index: int) -> None:
        if self.cb_export_template.itemData(index) == _NEW_EXPORT_TEMPLATE_SENTINEL:
            self._create_new_export_template()

    def _create_new_export_template(self) -> None:
        template = self.selected_template()
        custom_fields = template.custom_fields if template is not None else []
        dlg = ExportTemplateDialog(custom_fields, self, home_dir=self._home_dir)
        if dlg.exec() == dlg.DialogCode.Accepted:
            result = dlg.result_template()
            if result is not None:
                export_template_catalog.save_template(self._home_dir, result)
                self._reload_export_templates(select_name=result.name)
                return
        # Cancelled — don't leave "+ Нови извозни шаблон…" selected.
        self._reload_export_templates()

    def _edit_export_template(self) -> None:
        name = self.cb_export_template.currentData()
        if not name or name == _NEW_EXPORT_TEMPLATE_SENTINEL:
            # "(без извоза)" (or the sentinel, if ever reached this
            # way) selected — clicking "Уреди…" with nothing real
            # chosen silently did nothing before; define a new one
            # instead of leaving the button a dead end.
            self._create_new_export_template()
            return
        existing = export_template_catalog.find_by_name(self._home_dir, name)
        if existing is None:
            return
        template = self.selected_template()
        custom_fields = template.custom_fields if template is not None else []
        dlg = ExportTemplateDialog(custom_fields, self, home_dir=self._home_dir)
        dlg.load_template(existing)
        if dlg.exec() == dlg.DialogCode.Accepted:
            result = dlg.result_template()
            if result is not None:
                export_template_catalog.save_template(self._home_dir, result)
                self._reload_export_templates(select_name=result.name)

    def _create_new_template(self) -> None:
        dlg = NewTemplateDialog(self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            tpl = dlg.result_template()
            if tpl is not None:
                template_catalog.save_template(self._catalog_dir, tpl)
                self.reload_catalog()
                self.cb_template.setCurrentText(tpl.name)
                return
        # Cancelled — don't leave "+ Нови шаблон…" selected.
        self.cb_template.setCurrentIndex(-1)

    def _edit_selected_template(self) -> None:
        template = self.selected_template()
        if template is None:
            return
        dlg = NewTemplateDialog(self)
        dlg.load_template(template)
        if dlg.exec() == dlg.DialogCode.Accepted:
            updated = dlg.result_template()
            if updated is not None:
                template_catalog.save_template(self._catalog_dir, updated)
                self.reload_catalog()
                self.cb_template.setCurrentText(updated.name)

    def selected_template(self) -> CalibratedTemplate | None:
        name = self.cb_template.currentText()
        for t in self._templates:
            if t.name == name:
                return t
        return None

    def _on_continue(self) -> None:
        template = self.selected_template()
        if template is None:
            QMessageBox.warning(self, "Изаберите шаблон", "Прво изаберите или направите шаблон изјаве.")
            return

        export_name = self.cb_export_template.currentData() or ""
        if export_name == _NEW_EXPORT_TEMPLATE_SENTINEL:
            export_name = ""  # defensive — shouldn't be reachable, never left selected

        info = SessionInfo(
            template_name=template.name,
            copies=self.sb_copies.value(),
            printer_name=self.cb_printer.currentData() or "",
            custom_values={
                key: ed.text().strip() for key, ed in self._custom_universal_edits.items()
            },
            export_template_name=export_name,
        )
        self.session_ready.emit(info, template)

    def _reload_printers(self) -> None:
        """List the real printers, keeping whatever was already chosen.

        Real printer names only — offering a virtual one like
        "Microsoft Print to PDF" *by name* here would hand the operator
        a one-click way to silently produce a file instead of a signed
        declaration on paper, which is the exact failure this app has
        already been bitten by once. Leaving the choice on "Подразумевани"
        keeps that behaviour — follow Windows' default, with the
        virtual-printer refusal in core.print_pdf applied on top.

        "Сачувај као PDF" is not a printer name at all, and is offered
        unconditionally rather than only appearing when the machine
        happens to have no real printer — an operator testing the app,
        or an office that emails declarations instead of printing them,
        needs this every time, not only by accident of what hardware is
        plugged in."""
        previous = self.cb_printer.currentData() if self.cb_printer.count() else ""
        try:
            from formalizator.core.print_pdf import list_real_printers
            names = list_real_printers()
        except Exception:  # noqa: BLE001 — no win32print, or the spooler is unreachable
            names = []

        self.cb_printer.clear()
        self.cb_printer.addItem("Подразумевани у Windows-у", "")
        self.cb_printer.addItem("Сачувај као PDF (без штампе)", SAVE_AS_PDF)
        for name in names:
            self.cb_printer.addItem(name, name)

        if previous:
            index = self.cb_printer.findData(previous)
            # A printer chosen earlier and now gone is kept in the list
            # rather than silently swapped for the default — otherwise
            # the session quietly starts printing somewhere else.
            if index < 0:
                self.cb_printer.addItem(f"{previous} (недоступан)", previous)
                index = self.cb_printer.count() - 1
            self.cb_printer.setCurrentIndex(index)

    def load_from_info(self, info: SessionInfo) -> None:
        """Pre-fill from a resumed session."""
        self.sb_copies.setValue(info.copies or 1)
        if info.printer_name:
            index = self.cb_printer.findData(info.printer_name)
            if index < 0:
                self.cb_printer.addItem(f"{info.printer_name} (недоступан)", info.printer_name)
                index = self.cb_printer.count() - 1
            self.cb_printer.setCurrentIndex(index)
        if info.template_name:
            self.cb_template.setCurrentText(info.template_name)
        for key, ed in self._custom_universal_edits.items():
            ed.setText(info.custom_values.get(key, ""))
        if info.export_template_name:
            idx = self.cb_export_template.findData(info.export_template_name)
            if idx >= 0:
                self.cb_export_template.setCurrentIndex(idx)
