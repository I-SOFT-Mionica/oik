"""Tests for formalizator.gui.template_wizard.NewTemplateDialog's custom-field
mechanism — naming a field that isn't part of the ID card's own data (e.g.
a certifier's name) and marking it "individual" (typed per voter) or
"universal" (typed once for the whole session). The modal _CustomFieldDialog
itself isn't driven here (exec() blocks headlessly) — these exercise the
surrounding logic directly, the same way a real accept would drive it.
"""

from __future__ import annotations

import io
import time
from pathlib import Path

import pytest

from formalizator.core.models import CustomFieldDef


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _blank_background(path: Path) -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path), pagesize=A4)
    c.showPage()
    c.save()
    return path


def _make_dialog(app):
    from formalizator.gui.template_wizard import NewTemplateDialog
    return NewTemplateDialog()


class _FakeProcess:
    """Stands in for subprocess.Popen — real Word conversions run in
    their own OS process (not a background thread: pywin32's blocking
    COM calls hold the GIL while waiting, so a stuck Word instance on a
    thread can freeze this whole interpreter too, confirmed directly —
    a conversion once sat "in progress" for 5+ minutes with the
    supposed safety-net timeout never firing). `poll()` mirrors Popen's
    contract: None while still running, the exit code once it isn't."""

    def __init__(self, returncode: int | None = None, stderr: bytes = b"") -> None:
        self.returncode = returncode
        self.stderr = io.BytesIO(stderr)
        self.killed = False

    def poll(self):
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


def test_pick_docx_starts_conversion_as_its_own_process(app, monkeypatch, tmp_path: Path) -> None:
    import formalizator.gui.template_wizard as mod

    calls = []
    fake_proc = _FakeProcess(returncode=None)  # still "running"

    def fake_start_conversion_process(doc_path, out_path):
        calls.append((doc_path, out_path))
        return fake_proc

    monkeypatch.setattr(mod.pdf_template, "start_conversion_process", fake_start_conversion_process)
    monkeypatch.setattr(mod.pdf_template, "WORD_COM_AVAILABLE", True)
    # Never resolve the real working directory from a test — that would
    # create (and migrate into) the operator's own folder as a side effect.
    monkeypatch.setattr(mod, "default_home", lambda: tmp_path)
    src = tmp_path / "official.docx"
    src.write_bytes(b"fake docx")
    monkeypatch.setattr(
        mod.QFileDialog, "getOpenFileName", staticmethod(lambda *a, **kw: (str(src), "")),
    )

    dlg = _make_dialog(app)
    try:
        dlg._on_pick_file()  # noqa: SLF001

        assert len(calls) == 1
        assert calls[0][0] == src
        assert dlg._convert_proc is fake_proc  # noqa: SLF001
        # Disabled immediately, before any conversion has actually run —
        # the whole point is the GUI never blocks on this.
        assert not dlg.btn_pick_file.isEnabled()
    finally:
        # Leaving this conversion running left a live 200ms timer behind
        # that later fired its timeout inside an unrelated test and took
        # the whole run down with a modal box on a dead parent.
        dlg.close()
        dlg.deleteLater()


def test_closing_the_wizard_abandons_an_in_flight_conversion(app, monkeypatch, tmp_path: Path) -> None:
    """Closing the window has to stop the poll timer and take Word down
    with it. A conversion left running raised its timeout error against
    a dialog that no longer existed — which crashed the process."""
    import formalizator.gui.template_wizard as mod

    fake_proc = _FakeProcess(returncode=None)  # never finishes
    monkeypatch.setattr(
        mod.pdf_template, "start_conversion_process", lambda *a: fake_proc,
    )
    monkeypatch.setattr(mod.pdf_template, "WORD_COM_AVAILABLE", True)
    monkeypatch.setattr(mod, "default_home", lambda: tmp_path)
    src = tmp_path / "official.docx"
    src.write_bytes(b"fake docx")
    monkeypatch.setattr(
        mod.QFileDialog, "getOpenFileName", staticmethod(lambda *a, **kw: (str(src), "")),
    )

    dlg = _make_dialog(app)
    try:
        dlg._on_pick_file()  # noqa: SLF001
        assert dlg._convert_timer.isActive()  # noqa: SLF001

        dlg.close()

        assert not dlg._convert_timer.isActive()  # noqa: SLF001
        assert fake_proc.killed
        assert dlg._convert_proc is None  # noqa: SLF001
    finally:
        dlg.deleteLater()


def test_polling_after_the_conversion_was_abandoned_is_silent(app, monkeypatch) -> None:
    """Any timer event still queued when the wizard closed must not put
    an error dialog on screen."""
    import formalizator.gui.template_wizard as mod
    from PySide6.QtCore import QTimer

    shown = []
    monkeypatch.setattr(mod.QMessageBox, "critical", lambda *a, **kw: shown.append(a))

    dlg = _make_dialog(app)
    try:
        dlg._convert_proc = None  # noqa: SLF001
        dlg._convert_timer = QTimer(dlg)  # noqa: SLF001
        dlg._convert_timer.start()  # noqa: SLF001

        dlg._poll_conversion()  # noqa: SLF001

        assert shown == []
        assert not dlg._convert_timer.isActive()  # noqa: SLF001
    finally:
        dlg.deleteLater()


def test_poll_conversion_success_loads_background_and_reenables_button(app, tmp_path: Path) -> None:
    dlg = _make_dialog(app)
    try:
        bg = _blank_background(tmp_path / "bg.pdf")
        dlg.btn_pick_file.setEnabled(False)
        dlg._convert_proc = _FakeProcess(returncode=0)  # noqa: SLF001
        dlg._convert_src = tmp_path / "official.docx"  # noqa: SLF001
        dlg._convert_out = bg  # noqa: SLF001
        from PySide6.QtCore import QTimer
        dlg._convert_timer = QTimer(dlg)  # noqa: SLF001

        dlg._poll_conversion()  # noqa: SLF001

        assert dlg.btn_pick_file.isEnabled()
        assert dlg._background_pdf_path == str(bg)  # noqa: SLF001
        assert dlg.ed_name.text() == "official"
    finally:
        dlg.deleteLater()


def test_poll_conversion_nonzero_exit_shows_stderr(app, monkeypatch) -> None:
    import formalizator.gui.template_wizard as mod

    shown = []
    monkeypatch.setattr(mod.QMessageBox, "critical", lambda *a: shown.append(a))

    dlg = _make_dialog(app)
    try:
        dlg.btn_pick_file.setEnabled(False)
        dlg._convert_proc = _FakeProcess(returncode=1, stderr="Команда није успела".encode("utf-8"))  # noqa: SLF001
        from PySide6.QtCore import QTimer
        dlg._convert_timer = QTimer(dlg)  # noqa: SLF001

        dlg._poll_conversion()  # noqa: SLF001

        assert dlg.btn_pick_file.isEnabled()
        assert len(shown) == 1
        assert "Команда није успела" in shown[0][-1]
    finally:
        dlg.deleteLater()


def test_poll_conversion_timeout_kills_process_and_shows_error(app, monkeypatch) -> None:
    import formalizator.gui.template_wizard as mod

    shown = []
    monkeypatch.setattr(mod.QMessageBox, "critical", lambda *a: shown.append(a))

    dlg = _make_dialog(app)
    try:
        dlg.btn_pick_file.setEnabled(False)
        proc = _FakeProcess(returncode=None)  # never finishes on its own
        dlg._convert_proc = proc  # noqa: SLF001
        dlg._convert_started_at = time.monotonic() - (mod._CONVERT_TIMEOUT_SECONDS + 1)  # noqa: SLF001
        from PySide6.QtCore import QTimer
        dlg._convert_timer = QTimer(dlg)  # noqa: SLF001

        dlg._poll_conversion()  # noqa: SLF001

        assert proc.killed
        assert dlg.btn_pick_file.isEnabled()
        assert len(shown) == 1
    finally:
        dlg.deleteLater()


def test_convert_failed_shows_actionable_error_and_reenables_button(app, monkeypatch) -> None:
    import formalizator.gui.template_wizard as mod

    shown = []
    monkeypatch.setattr(mod.QMessageBox, "critical", lambda *a: shown.append(a))

    dlg = _make_dialog(app)
    try:
        dlg.btn_pick_file.setEnabled(False)

        dlg._on_convert_failed("Команда није успела")  # noqa: SLF001

        assert dlg.btn_pick_file.isEnabled()
        assert len(shown) == 1
        assert "Команда није успела" in shown[0][-1]
    finally:
        dlg.deleteLater()


def test_custom_field_dialog_kind_picker_is_a_dropdown(app) -> None:
    """Was a QRadioButton pair — its indicator dot wasn't rendering
    under this app's stylesheet, so there was no visible way to tell
    the two options apart or select one. A combo box always shows
    something selected."""
    import formalizator.gui.template_wizard as mod

    dlg = mod._CustomFieldDialog()
    try:
        assert dlg.cb_kind.count() == 2
        assert dlg.field_kind() == "individual"  # default, before any change
        dlg.cb_kind.setCurrentIndex(dlg.cb_kind.findData("universal"))
        assert dlg.field_kind() == "universal"
    finally:
        dlg.deleteLater()


def test_custom_field_dialog_default_value_is_optional_and_blank_by_default(app) -> None:
    import formalizator.gui.template_wizard as mod

    dlg = mod._CustomFieldDialog()
    try:
        assert dlg.default_value() == ""
        dlg.ed_default.setText("  Мионица  ")
        assert dlg.default_value() == "Мионица"  # stripped, like the label field
    finally:
        dlg.deleteLater()


def test_defining_a_custom_field_carries_its_default_value(app, monkeypatch) -> None:
    """The dialog's default-value box has to actually reach the saved
    CustomFieldDef, not just exist cosmetically."""
    import formalizator.gui.template_wizard as mod

    class _FakeDialog:
        DialogCode = mod.QDialog.DialogCode

        def __init__(self, parent=None) -> None:
            pass

        def exec(self):
            return self.DialogCode.Accepted

        def field_label(self):
            return "Оверитељ"

        def field_kind(self):
            return "universal"

        def default_value(self):
            return "Наташа Пауновић"

    monkeypatch.setattr(mod, "_CustomFieldDialog", _FakeDialog)

    dlg = _make_dialog(app)
    try:
        dlg._append_row("", 0, 0.0, 0.0, 10.0, source="ручно додато")  # noqa: SLF001
        combo = dlg.table.cellWidget(0, 1)
        dlg._define_new_custom_field(combo)  # noqa: SLF001

        assert dlg._custom_fields[-1].default_value == "Наташа Пауновић"  # noqa: SLF001
    finally:
        dlg.deleteLater()


def test_manage_custom_fields_button_opens_existing_fields_for_editing(app) -> None:
    """The gap this whole dialog exists to close: "+ Ново поље…" only
    offers a default at creation time, so a field defined earlier (or
    loaded from an existing template) had no way back in at all."""
    import formalizator.gui.template_wizard as mod

    fields = [
        CustomFieldDef(key="overitelj", label="Оверитељ", kind="universal", default_value=""),
        CustomFieldDef(key="napomena", label="Напомена", kind="individual", default_value="Нема"),
    ]
    dlg = mod._ManageCustomFieldsDialog(fields)  # noqa: SLF001
    try:
        assert dlg.table.rowCount() == 2
        assert dlg.table.item(0, 0).text() == "Оверитељ"
        assert dlg.table.item(1, 0).text() == "Напомена"
        assert dlg.table.cellWidget(1, 2).text() == "Нема"
    finally:
        dlg.deleteLater()


def test_manage_custom_fields_saves_edits_back_onto_the_same_objects(app) -> None:
    """The dialog mutates the CalibratedTemplate's own CustomFieldDef
    list in place — the parent dialog must see the change without any
    extra copy-back step, same as how a new field is appended today."""
    import formalizator.gui.template_wizard as mod

    fields = [CustomFieldDef(key="overitelj", label="Оверитељ", kind="universal")]
    dlg = mod._ManageCustomFieldsDialog(fields)  # noqa: SLF001
    try:
        dlg.table.cellWidget(0, 2).setText("  Наташа Пауновић  ")
        dlg._on_save()  # noqa: SLF001

        assert fields[0].default_value == "Наташа Пауновић"  # stripped, key/label/kind untouched
        assert fields[0].key == "overitelj"
        assert fields[0].label == "Оверитељ"
    finally:
        dlg.deleteLater()


def test_manage_custom_fields_label_and_kind_are_not_editable(app) -> None:
    """Scoped deliberately narrow: the key (derived from the label at
    creation) is referenced by every placed position and every stored
    session/voter value — editing it here would silently break those."""
    from PySide6.QtCore import Qt
    import formalizator.gui.template_wizard as mod

    fields = [CustomFieldDef(key="overitelj", label="Оверитељ", kind="universal")]
    dlg = mod._ManageCustomFieldsDialog(fields)  # noqa: SLF001
    try:
        assert not (dlg.table.item(0, 0).flags() & Qt.ItemIsEditable)
        assert not (dlg.table.item(0, 1).flags() & Qt.ItemIsEditable)
    finally:
        dlg.deleteLater()


def test_manage_custom_fields_button_reaches_a_loaded_templates_fields(app, monkeypatch) -> None:
    """The actual reported scenario: an existing calibrated template
    (loaded for editing, not created fresh) already has custom fields —
    the button has to operate on those, not an empty list."""
    from formalizator.core.models import CalibratedTemplate
    import formalizator.gui.template_wizard as mod

    opened_with = []

    class _FakeManageDialog:
        def __init__(self, custom_fields, parent=None) -> None:
            opened_with.append(custom_fields)

        def exec(self):
            return None

    monkeypatch.setattr(mod, "_ManageCustomFieldsDialog", _FakeManageDialog)

    dlg = _make_dialog(app)
    try:
        template = CalibratedTemplate(
            name="t", background_pdf_path="",
            custom_fields=[CustomFieldDef(key="overitelj", label="Оверитељ", kind="universal")],
        )
        dlg.load_template(template)

        dlg._on_manage_custom_fields()  # noqa: SLF001

        assert len(opened_with) == 1
        assert opened_with[0][0].key == "overitelj"
    finally:
        dlg.deleteLater()


def test_make_custom_key_slugifies_cyrillic_label(app) -> None:
    dlg = _make_dialog(app)
    try:
        key = dlg._make_custom_key("Оверитељ — име и презиме")  # noqa: SLF001
        assert key and key.islower()
        assert " " not in key
        assert all(ch.isascii() for ch in key)
    finally:
        dlg.deleteLater()


def test_make_custom_key_avoids_collision_with_fixed_keys(app) -> None:
    dlg = _make_dialog(app)
    try:
        key = dlg._make_custom_key("Full Name")  # noqa: SLF001
        assert key != "full_name"  # already a fixed VoterEntry key
    finally:
        dlg.deleteLater()


def test_make_custom_key_avoids_collision_with_existing_custom_fields(app) -> None:
    dlg = _make_dialog(app)
    try:
        dlg._custom_fields.append(CustomFieldDef(key="overitelj", label="Оверитељ"))  # noqa: SLF001
        key = dlg._make_custom_key("Оверитељ")  # noqa: SLF001
        assert key != "overitelj"
    finally:
        dlg.deleteLater()


def test_defining_a_custom_field_appears_in_every_row_combo(app) -> None:
    dlg = _make_dialog(app)
    try:
        dlg._append_row("", 0, 0.0, 0.0, 10.0, source="ручно додато")  # noqa: SLF001
        dlg._append_row("", 0, 0.0, 0.0, 10.0, source="ручно додато")  # noqa: SLF001

        cf = CustomFieldDef(key="overitelj_ime", label="Оверитељ — име и презиме", kind="universal")
        dlg._custom_fields.append(cf)  # noqa: SLF001
        dlg._refresh_all_field_combos()  # noqa: SLF001

        for row in range(dlg.table.rowCount()):
            combo = dlg.table.cellWidget(row, 1)
            assert combo.findData("overitelj_ime") >= 0
    finally:
        dlg.deleteLater()


def test_selecting_a_custom_field_and_saving_produces_matching_position(app, tmp_path: Path) -> None:
    dlg = _make_dialog(app)
    try:
        bg = _blank_background(tmp_path / "bg.pdf")
        dlg._background_pdf_path = str(bg)  # noqa: SLF001
        dlg.ed_name.setText("Тест шаблон")

        dlg._append_row("", 0, 0.0, 0.0, 10.0, source="ручно додато")  # noqa: SLF001
        cf = CustomFieldDef(key="overitelj_ime", label="Оверитељ — име и презиме", kind="universal")
        dlg._custom_fields.append(cf)  # noqa: SLF001
        dlg._refresh_all_field_combos()  # noqa: SLF001

        combo = dlg.table.cellWidget(0, 1)
        combo.setCurrentIndex(combo.findData("overitelj_ime"))
        dlg.table.cellWidget(0, 2).setValue(50.0)
        dlg.table.cellWidget(0, 3).setValue(60.0)

        dlg._on_save()  # noqa: SLF001

        result = dlg.result_template()
        assert result is not None
        assert result.positions[0].field_key == "overitelj_ime"
        assert result.custom_fields[0].key == "overitelj_ime"
        assert result.custom_fields[0].kind == "universal"
    finally:
        dlg.deleteLater()


def test_unused_custom_field_not_saved(app, tmp_path: Path) -> None:
    """A field the operator defined but then never assigned/placed
    shouldn't linger in the saved template."""
    dlg = _make_dialog(app)
    try:
        bg = _blank_background(tmp_path / "bg.pdf")
        dlg._background_pdf_path = str(bg)  # noqa: SLF001
        dlg.ed_name.setText("Тест шаблон")

        dlg._append_row("full_name", 0, 10.0, 20.0, 10.0, source="ручно додато")  # noqa: SLF001
        cf = CustomFieldDef(key="never_used", label="Никад коришћено")
        dlg._custom_fields.append(cf)  # noqa: SLF001

        dlg._on_save()  # noqa: SLF001

        result = dlg.result_template()
        assert result is not None
        assert result.custom_fields == []
    finally:
        dlg.deleteLater()


def test_jmbg_individual_digit_keys_not_offered_in_dropdown(app) -> None:
    """Only the comb tool's own entry should be selectable — 14
    JMBG-flavored dropdown items (whole-string plus 13 individual
    digits) was pure clutter now that the comb handles all 13 at once."""
    import formalizator.gui.template_wizard as mod

    dlg = _make_dialog(app)
    try:
        dlg._append_row("", 0, 0.0, 0.0, 10.0, source="ручно додато")  # noqa: SLF001
        combo = dlg.table.cellWidget(0, 1)
        assert combo.findData("jmbg") < 0
        for i in range(1, 14):
            assert combo.findData(f"jmbg_{i}") < 0
        assert combo.findData(mod._JMBG_COMB_KEY) >= 0
    finally:
        dlg.deleteLater()


def test_composite_fields_are_selectable(app) -> None:
    """The real form has one blank for "место и адреса" and one for
    "документ: врста, број, датум, издавалац" — not separate blanks per
    underlying value — so the composites (like full_name already is
    for given_name+surname) have to be pickable as single fields."""
    dlg = _make_dialog(app)
    try:
        dlg._append_row("", 0, 0.0, 0.0, 10.0, source="ручно додато")  # noqa: SLF001
        combo = dlg.table.cellWidget(0, 1)
        assert combo.findData("full_residence") >= 0
        assert combo.findData("full_document_info") >= 0
    finally:
        dlg.deleteLater()


def test_session_fixed_fields_not_offered_in_the_generic_field_picker(app) -> None:
    """list_name/submitter_name/municipality/certifier_name are NPRS-3/
    NPRS-4-specific, not generic — offering them in the field picker
    used by every calibrated template regardless of document would
    show meaningless options on an unrelated future document. They're
    still real, resolvable keys (see overlay_fill and
    gui.export_template_wizard) — just not offered here."""
    dlg = _make_dialog(app)
    try:
        dlg._append_row("", 0, 0.0, 0.0, 10.0, source="ручно додато")  # noqa: SLF001
        combo = dlg.table.cellWidget(0, 1)
        for key in ("list_name", "submitter_name", "municipality", "certifier_name"):
            assert combo.findData(key) < 0
    finally:
        dlg.deleteLater()


def test_field_combo_popup_sized_to_fit_its_longest_item(app) -> None:
    """The "Поље" column is narrow (has to be, to leave room for
    "Извор"), but the dropdown *popup* isn't stuck at that width on
    every style — some styles clamp it to the closed combo's width by
    default, rendering long labels ("ЈМБГ — цифра 12", "Датум
    издавања") as unreadable "…"-truncated mush. The popup view has to
    be explicitly widened past the column."""
    dlg = _make_dialog(app)
    try:
        dlg._append_row("", 0, 0.0, 0.0, 10.0, source="ручно додато")  # noqa: SLF001
        combo = dlg.table.cellWidget(0, 1)

        longest_item_px = max(
            combo.fontMetrics().horizontalAdvance(combo.itemText(i))
            for i in range(combo.count())
        )
        assert combo.view().minimumWidth() >= longest_item_px
    finally:
        dlg.deleteLater()


def test_width_height_auto_marker_is_short_not_truncated(app) -> None:
    """"авто" as the special-value text for an unset width/height
    didn't fit the narrow column at any sane size and rendered as
    unreadable mush — a single character always fits."""
    dlg = _make_dialog(app)
    try:
        dlg._append_row("full_name", 0, 10.0, 20.0, 10.0, source="ручно додато")  # noqa: SLF001
        sb_width = dlg.table.cellWidget(0, 4)
        sb_height = dlg.table.cellWidget(0, 5)

        assert len(sb_width.specialValueText()) == 1
        assert len(sb_height.specialValueText()) == 1
    finally:
        dlg.deleteLater()


def test_the_wizard_uses_core_models_auto_box_size(app) -> None:
    """auto_box_size() moved to core.models (see test_formalizator_models.py
    for the function's own behaviour) so overlay_fill's shrink-to-fit and
    this wizard's preview box can never compute two different answers.
    This just pins that the wizard still gets it from there, not a
    reintroduced local copy."""
    import formalizator.gui.template_wizard as mod
    from formalizator.core.models import auto_box_size

    assert mod.auto_box_size is auto_box_size


def test_width_and_height_override_round_trips_to_saved_position(app, tmp_path: Path) -> None:
    dlg = _make_dialog(app)
    try:
        bg = _blank_background(tmp_path / "bg.pdf")
        dlg._background_pdf_path = str(bg)  # noqa: SLF001
        dlg.ed_name.setText("Тест шаблон")

        dlg._append_row("full_name", 0, 100.0, 200.0, 10.0, source="ручно додато")  # noqa: SLF001
        dlg.table.cellWidget(0, 4).setValue(15.0)  # width
        dlg.table.cellWidget(0, 5).setValue(12.0)  # height

        dlg._on_save()  # noqa: SLF001

        result = dlg.result_template()
        assert result.positions[0].width == 15.0
        assert result.positions[0].height == 12.0
    finally:
        dlg.deleteLater()


def test_unplaced_flagged_row_shows_a_ghost_marker_at_its_detected_position(app) -> None:
    """A row flagged by the detector but not yet assigned+placed still
    has to be findable on the page — otherwise "where's row 8" has no
    answer until after it's placed, which was the whole complaint."""
    dlg = _make_dialog(app)
    try:
        dlg._append_row(
            "", 0, 0.0, 0.0, 10.0, source='означено: „(ЈМБГ)“ — ...',
            ref_point=(428.7, 493.0),
        )  # noqa: SLF001

        captured = {}
        dlg.canvas.redraw_markers = lambda rows, ref_rows=None: captured.update(
            rows=rows, ref_rows=ref_rows,
        )
        dlg._redraw_markers()  # noqa: SLF001

        assert captured["rows"] == []  # nothing actually placed
        assert captured["ref_rows"] == [(1, 428.7, 493.0, False)]
    finally:
        dlg.deleteLater()


def test_selecting_an_unplaced_row_highlights_its_ghost_marker(app) -> None:
    """Clicking an unplaced (flagged) row in the table should turn its
    on-page marker red too, same as an already-placed row — previously
    it stayed the generic gray regardless of table selection, so there
    was no visible feedback for which unplaced row you'd clicked."""
    dlg = _make_dialog(app)
    try:
        dlg._append_row(
            "", 0, 0.0, 0.0, 10.0, source='означено: „(ЈМБГ)“',
            ref_point=(428.7, 493.0),
        )  # noqa: SLF001

        captured = {}
        dlg.canvas.redraw_markers = lambda rows, ref_rows=None: captured.update(
            rows=rows, ref_rows=ref_rows,
        )
        dlg.table.selectRow(0)  # fires _redraw_markers via itemSelectionChanged

        assert captured["ref_rows"] == [(1, 428.7, 493.0, True)]
    finally:
        dlg.deleteLater()


def test_ref_point_survives_row_removal_and_renumbering(app) -> None:
    dlg = _make_dialog(app)
    try:
        dlg._append_row("full_name", 0, 10.0, 20.0, 10.0, source="аутоматски препознато")  # noqa: SLF001
        dlg._append_row("", 0, 0.0, 0.0, 10.0, source="означено", ref_point=(50.0, 60.0))  # noqa: SLF001

        dlg.table.selectRow(0)
        dlg._on_remove_field()  # noqa: SLF001

        assert dlg._row_ref_point(0) == (50.0, 60.0)  # noqa: SLF001
    finally:
        dlg.deleteLater()


def test_source_not_shown_as_a_column_but_still_tracked_internally(app) -> None:
    """"Извор" was removed from the UI (redundant clutter once the
    field picker shows real labels and unplaced rows get their own
    on-page marker) — but the detected label text is still tracked
    internally, since _remove_unassigned_jmbg_flag_rows depends on it."""
    dlg = _make_dialog(app)
    try:
        dlg._append_row(
            "", 0, 0.0, 0.0, 10.0,
            source='означено: „(ЈМБГ)“ — ЈМБГ се приказује као 13 засебних поља.',
        )  # noqa: SLF001

        headers = [dlg.table.horizontalHeaderItem(c).text() for c in range(dlg.table.columnCount())]
        assert "Извор" not in headers
        assert "13 засебних поља" in dlg._row_source(0)  # noqa: SLF001
    finally:
        dlg.deleteLater()


def test_jmbg_comb_creates_one_row_representing_all_13_digits(app, tmp_path: Path) -> None:
    """The comb is one editable unit (start x, cell width/height/font
    shared by all 13) — not 13 rows to hand-tune individually. It only
    expands into 13 real jmbg_N positions at save time."""
    import formalizator.gui.template_wizard as mod

    dlg = _make_dialog(app)
    try:
        bg = _blank_background(tmp_path / "bg.pdf")
        dlg._background_pdf_path = str(bg)  # noqa: SLF001
        dlg.ed_name.setText("Тест шаблон")

        dlg._apply_jmbg_comb(100.0, 500.0, 230.0, 500.0)  # noqa: SLF001

        assert dlg.table.rowCount() == 1
        combo = dlg.table.cellWidget(0, 1)
        assert combo.currentData() == mod._JMBG_COMB_KEY
        assert dlg.table.cellWidget(0, 2).value() == pytest.approx(100.0)  # start x
        # 13 evenly-spaced cells across a 130pt span -> 10pt each.
        assert dlg.table.cellWidget(0, 4).value() == pytest.approx(10.0)  # cell width
    finally:
        dlg.deleteLater()


def test_jmbg_comb_expands_to_13_positions_on_save(app, tmp_path: Path) -> None:
    dlg = _make_dialog(app)
    try:
        bg = _blank_background(tmp_path / "bg.pdf")
        dlg._background_pdf_path = str(bg)  # noqa: SLF001
        dlg.ed_name.setText("Тест шаблон")
        dlg._apply_jmbg_comb(100.0, 500.0, 230.0, 500.0)  # noqa: SLF001

        dlg._on_save()  # noqa: SLF001

        result = dlg.result_template()
        assert [p.field_key for p in result.positions] == [f"jmbg_{i}" for i in range(1, 14)]
        assert result.positions[0].x == pytest.approx(100.0)
        assert result.positions[1].x - result.positions[0].x == pytest.approx(10.0)
        assert all(p.width == pytest.approx(10.0) for p in result.positions)
    finally:
        dlg.deleteLater()


def test_jmbg_comb_backwards_click_order_still_works(app) -> None:
    """The operator might click right-to-left just as easily."""
    dlg = _make_dialog(app)
    try:
        dlg._apply_jmbg_comb(230.0, 500.0, 100.0, 500.0)  # noqa: SLF001

        assert dlg.table.cellWidget(0, 2).value() == pytest.approx(100.0)
    finally:
        dlg.deleteLater()


def test_jmbg_comb_rejects_zero_width_click_pair(app, monkeypatch) -> None:
    import formalizator.gui.template_wizard as mod

    shown = []
    monkeypatch.setattr(mod.QMessageBox, "warning", lambda *a: shown.append(a))

    dlg = _make_dialog(app)
    try:
        dlg._apply_jmbg_comb(100.0, 500.0, 100.0, 500.0)  # noqa: SLF001
        assert dlg.table.rowCount() == 0
        assert len(shown) == 1
    finally:
        dlg.deleteLater()


def test_jmbg_comb_recalibration_via_toolbar_button_replaces_not_duplicates(app) -> None:
    """Clicking the toolbar button again (not the row's own "Постави")
    starts a fresh comb — shouldn't leave the old one behind too."""
    dlg = _make_dialog(app)
    try:
        dlg._apply_jmbg_comb(100.0, 500.0, 230.0, 500.0)  # noqa: SLF001
        dlg._apply_jmbg_comb(150.0, 500.0, 280.0, 500.0)  # noqa: SLF001

        assert dlg.table.rowCount() == 1
        assert dlg.table.cellWidget(0, 2).value() == pytest.approx(150.0)
    finally:
        dlg.deleteLater()


def test_jmbg_comb_recalibrating_via_its_own_row_updates_in_place(app) -> None:
    """Re-arming through the row's own "Постави" button (not the
    toolbar) is how an already-placed comb gets nudged — it updates
    that one row rather than creating a second one."""
    dlg = _make_dialog(app)
    try:
        dlg._apply_jmbg_comb(100.0, 500.0, 230.0, 500.0)  # noqa: SLF001
        dlg._arm_row(0)  # noqa: SLF001
        assert dlg._jmbg_comb_target_row == 0  # noqa: SLF001

        dlg._on_canvas_clicked(150.0, 500.0)  # noqa: SLF001
        dlg._on_canvas_clicked(280.0, 500.0)  # noqa: SLF001

        assert dlg.table.rowCount() == 1
        assert dlg.table.cellWidget(0, 2).value() == pytest.approx(150.0)
    finally:
        dlg.deleteLater()


def test_jmbg_comb_removes_original_unassigned_flag_row(app) -> None:
    """Before calibration there's one generic flagged "(ЈМБГ)" row from
    the detector — the comb tool supersedes it, so it shouldn't linger
    as a dangling, never-assignable extra row afterward."""
    dlg = _make_dialog(app)
    try:
        dlg._append_row(
            "", 0, 0.0, 0.0, 10.0,
            source='означено: „(ЈМБГ)“ — ЈМБГ се приказује као 13 засебних поља.',
        )  # noqa: SLF001

        dlg._apply_jmbg_comb(100.0, 500.0, 230.0, 500.0)  # noqa: SLF001

        assert dlg.table.rowCount() == 1
    finally:
        dlg.deleteLater()


def test_jmbg_comb_two_click_flow_via_canvas(app) -> None:
    dlg = _make_dialog(app)
    try:
        dlg._on_place_jmbg_comb()  # noqa: SLF001
        assert dlg._jmbg_comb_armed  # noqa: SLF001

        dlg._on_canvas_clicked(100.0, 500.0)  # noqa: SLF001
        assert dlg._jmbg_comb_click1 == (100.0, 500.0)  # noqa: SLF001

        dlg._on_canvas_clicked(230.0, 500.0)  # noqa: SLF001

        assert not dlg._jmbg_comb_armed  # noqa: SLF001
        assert dlg.table.rowCount() == 1
    finally:
        dlg.deleteLater()


def test_arming_a_single_row_cancels_jmbg_comb_mode(app) -> None:
    dlg = _make_dialog(app)
    try:
        dlg._append_row("full_name", 0, 0.0, 0.0, 10.0, source="ручно додато")  # noqa: SLF001
        dlg._on_place_jmbg_comb()  # noqa: SLF001

        dlg._arm_row(0)  # noqa: SLF001

        assert not dlg._jmbg_comb_armed  # noqa: SLF001
    finally:
        dlg.deleteLater()


def test_arming_jmbg_comb_cancels_single_row_placement(app) -> None:
    dlg = _make_dialog(app)
    try:
        dlg._append_row("full_name", 0, 0.0, 0.0, 10.0, source="ручно додато")  # noqa: SLF001
        dlg._arm_row(0)  # noqa: SLF001

        dlg._on_place_jmbg_comb()  # noqa: SLF001

        assert dlg._armed_row is None  # noqa: SLF001
    finally:
        dlg.deleteLater()


def test_undo_button_disabled_until_something_happens(app) -> None:
    dlg = _make_dialog(app)
    try:
        assert not dlg.btn_undo.isEnabled()
    finally:
        dlg.deleteLater()


def test_undo_restores_row_removed_by_remove_field(app) -> None:
    dlg = _make_dialog(app)
    try:
        dlg._append_row("full_name", 0, 10.0, 20.0, 10.0, source="ручно додато")  # noqa: SLF001
        dlg.table.selectRow(0)

        dlg._on_remove_field()  # noqa: SLF001
        assert dlg.table.rowCount() == 0
        assert dlg.btn_undo.isEnabled()

        dlg._on_undo()  # noqa: SLF001

        assert dlg.table.rowCount() == 1
        assert dlg.table.cellWidget(0, 1).currentData() == "full_name"
        assert dlg.table.cellWidget(0, 2).value() == pytest.approx(10.0)
        assert not dlg.btn_undo.isEnabled()
    finally:
        dlg.deleteLater()


def test_undo_reverts_row_added_by_add_field(app) -> None:
    dlg = _make_dialog(app)
    try:
        dlg._on_add_field()  # noqa: SLF001
        assert dlg.table.rowCount() == 1

        dlg._on_undo()  # noqa: SLF001

        assert dlg.table.rowCount() == 0
    finally:
        dlg.deleteLater()


def test_undo_reverts_a_misclick_placement(app) -> None:
    dlg = _make_dialog(app)
    try:
        dlg._append_row("full_name", 0, 0.0, 0.0, 10.0, source="ручно додато")  # noqa: SLF001
        dlg._arm_row(0)  # noqa: SLF001
        dlg._on_canvas_clicked(999.0, 888.0)  # noqa: SLF001
        assert dlg.table.cellWidget(0, 2).value() == pytest.approx(999.0)

        dlg._on_undo()  # noqa: SLF001

        assert dlg.table.cellWidget(0, 2).value() == pytest.approx(0.0)
    finally:
        dlg.deleteLater()


def test_undo_reverts_a_whole_jmbg_comb_placement_in_one_step(app) -> None:
    """The comb operation removes an old row and adds a new one — that
    has to undo as a single atomic step, not leave things half-reverted."""
    dlg = _make_dialog(app)
    try:
        dlg._apply_jmbg_comb(100.0, 500.0, 230.0, 500.0)  # noqa: SLF001
        assert dlg.table.rowCount() == 1

        dlg._on_undo()  # noqa: SLF001

        assert dlg.table.rowCount() == 0
    finally:
        dlg.deleteLater()


def test_undo_stack_is_last_in_first_out(app) -> None:
    dlg = _make_dialog(app)
    try:
        dlg._on_add_field()  # noqa: SLF001  # row 0
        dlg._on_add_field()  # noqa: SLF001  # row 1
        assert dlg.table.rowCount() == 2

        dlg._on_undo()  # noqa: SLF001
        assert dlg.table.rowCount() == 1

        dlg._on_undo()  # noqa: SLF001
        assert dlg.table.rowCount() == 0

        dlg._on_undo()  # noqa: SLF001  # nothing left — must not raise
        assert dlg.table.rowCount() == 0
    finally:
        dlg.deleteLater()


def test_place_button_arms_its_own_current_row_after_earlier_removal(app) -> None:
    """Reported bug: clicking a row's own "Постави" ended up moving a
    DIFFERENT field several rows away. Root cause — the button's row
    number was captured once at creation time; removing an earlier row
    (here, via the JMBG comb tool replacing the original flagged row)
    shifts every later row's true index without updating that captured
    number. The button has to find its own current row at click time."""
    dlg = _make_dialog(app)
    try:
        dlg._append_row("given_name", 0, 0.0, 0.0, 10.0, source="ручно додато")  # row 0
        dlg._append_row("surname", 0, 0.0, 0.0, 10.0, source="ручно додато")  # row 1
        dlg._append_row(
            "", 0, 0.0, 0.0, 10.0, source='означено: „(ЈМБГ)“',
        )  # row 2 — the original unassigned JMBG flag row

        # The comb tool removes row 2 (the unassigned JMBG flag row) and
        # appends a new comb row — row indices for anything after it
        # would shift if there were any, same class of change as
        # removing a row directly.
        dlg._apply_jmbg_comb(100.0, 500.0, 230.0, 500.0)  # noqa: SLF001
        assert dlg.table.rowCount() == 3  # given_name, surname, jmbg comb

        # Click row 1's ("surname") own place button.
        btn_surname = dlg.table.cellWidget(1, 9)
        btn_surname.click()

        assert dlg._armed_row == 1  # noqa: SLF001
        assert dlg.table.cellWidget(1, 1).currentData() == "surname"
    finally:
        dlg.deleteLater()


def test_load_template_restores_name_background_and_positions(app, tmp_path: Path) -> None:
    from formalizator.core.models import CalibratedTemplate, FieldPosition

    bg = _blank_background(tmp_path / "bg.pdf")
    tpl = CalibratedTemplate(
        name="НПРС-3 2026", background_pdf_path=str(bg),
        positions=[FieldPosition(field_key="full_name", page_index=0, x=50.0, y=60.0, font_size=11.0)],
    )

    dlg = _make_dialog(app)
    try:
        dlg.load_template(tpl)  # noqa: SLF001

        assert dlg.ed_name.text() == "НПРС-3 2026"
        assert dlg._background_pdf_path == str(bg)  # noqa: SLF001
        assert dlg.table.rowCount() == 1
        assert dlg.table.cellWidget(0, 1).currentData() == "full_name"
        assert dlg.table.cellWidget(0, 2).value() == pytest.approx(50.0)
        assert dlg.table.cellWidget(0, 3).value() == pytest.approx(60.0)
    finally:
        dlg.deleteLater()


def test_load_template_collapses_jmbg_positions_back_into_one_comb_row(app, tmp_path: Path) -> None:
    import formalizator.gui.template_wizard as mod
    from formalizator.core.models import CalibratedTemplate, FieldPosition

    bg = _blank_background(tmp_path / "bg.pdf")
    positions = [
        FieldPosition(field_key=f"jmbg_{i}", page_index=0, x=100.0 + (i - 1) * 10.0, y=500.0,
                      font_size=10.0, width=10.0, height=10.0)
        for i in range(1, 14)
    ]
    tpl = CalibratedTemplate(name="t", background_pdf_path=str(bg), positions=positions)

    dlg = _make_dialog(app)
    try:
        dlg.load_template(tpl)  # noqa: SLF001

        assert dlg.table.rowCount() == 1  # not 13
        combo = dlg.table.cellWidget(0, 1)
        assert combo.currentData() == mod._JMBG_COMB_KEY
        assert dlg.table.cellWidget(0, 2).value() == pytest.approx(100.0)  # leftmost x
    finally:
        dlg.deleteLater()


def test_load_template_restores_custom_fields(app, tmp_path: Path) -> None:
    from formalizator.core.models import CalibratedTemplate, CustomFieldDef, FieldPosition

    bg = _blank_background(tmp_path / "bg.pdf")
    cf = CustomFieldDef(key="overitelj_ime", label="Оверитељ — име и презиме", kind="universal")
    tpl = CalibratedTemplate(
        name="t", background_pdf_path=str(bg), custom_fields=[cf],
        positions=[FieldPosition(field_key="overitelj_ime", page_index=0, x=10.0, y=20.0)],
    )

    dlg = _make_dialog(app)
    try:
        dlg.load_template(tpl)  # noqa: SLF001

        assert dlg._custom_fields == [cf]  # noqa: SLF001
        combo = dlg.table.cellWidget(0, 1)
        assert combo.currentData() == "overitelj_ime"
    finally:
        dlg.deleteLater()


def test_editing_and_resaving_a_loaded_template_lets_more_fields_be_added(app, tmp_path: Path) -> None:
    """The whole point: reopen a saved template, add one more field,
    save again — without starting the whole calibration over."""
    from formalizator.core.models import CalibratedTemplate, FieldPosition

    bg = _blank_background(tmp_path / "bg.pdf")
    tpl = CalibratedTemplate(
        name="t", background_pdf_path=str(bg),
        positions=[FieldPosition(field_key="full_name", page_index=0, x=50.0, y=60.0)],
    )

    dlg = _make_dialog(app)
    try:
        dlg.load_template(tpl)  # noqa: SLF001
        dlg._on_add_field()  # noqa: SLF001
        combo = dlg.table.cellWidget(1, 1)
        combo.setCurrentIndex(combo.findData("surname"))
        dlg.table.cellWidget(1, 2).setValue(70.0)
        dlg.table.cellWidget(1, 3).setValue(80.0)

        dlg._on_save()  # noqa: SLF001

        result = dlg.result_template()
        assert result is not None
        keys = {p.field_key for p in result.positions}
        assert keys == {"full_name", "surname"}
    finally:
        dlg.deleteLater()


def test_new_row_defaults_to_normal_style_and_center_alignment(app) -> None:
    dlg = _make_dialog(app)
    try:
        dlg._append_row("full_name", 0, 0.0, 0.0, 10.0, source="ручно додато")  # noqa: SLF001
        cb_style = dlg.table.cellWidget(0, 7)
        cb_align = dlg.table.cellWidget(0, 8)
        assert cb_style.currentData() == "normal"
        assert cb_align.currentData() == "center"
    finally:
        dlg.deleteLater()


def test_style_and_alignment_round_trip_to_saved_position(app, tmp_path: Path) -> None:
    dlg = _make_dialog(app)
    try:
        bg = _blank_background(tmp_path / "bg.pdf")
        dlg._background_pdf_path = str(bg)  # noqa: SLF001
        dlg.ed_name.setText("Тест шаблон")

        dlg._append_row("full_name", 0, 10.0, 20.0, 10.0, source="ручно додато")  # noqa: SLF001
        cb_style = dlg.table.cellWidget(0, 7)
        cb_align = dlg.table.cellWidget(0, 8)
        cb_style.setCurrentIndex(cb_style.findData("bolditalic"))
        cb_align.setCurrentIndex(cb_align.findData("right"))

        dlg._on_save()  # noqa: SLF001

        pos = dlg.result_template().positions[0]
        assert pos.bold is True
        assert pos.italic is True
        assert pos.align == "right"
    finally:
        dlg.deleteLater()


def test_jmbg_comb_expansion_applies_row_style_and_alignment_to_all_digits(app, tmp_path: Path) -> None:
    dlg = _make_dialog(app)
    try:
        bg = _blank_background(tmp_path / "bg.pdf")
        dlg._background_pdf_path = str(bg)  # noqa: SLF001
        dlg.ed_name.setText("Тест шаблон")

        dlg._apply_jmbg_comb(100.0, 500.0, 230.0, 500.0)  # noqa: SLF001
        cb_style = dlg.table.cellWidget(0, 7)
        cb_style.setCurrentIndex(cb_style.findData("bold"))

        dlg._on_save()  # noqa: SLF001

        positions = dlg.result_template().positions
        assert len(positions) == 13
        assert all(p.bold for p in positions)
        assert all(not p.italic for p in positions)
    finally:
        dlg.deleteLater()


def test_undo_restores_style_and_alignment(app) -> None:
    dlg = _make_dialog(app)
    try:
        dlg._append_row("full_name", 0, 10.0, 20.0, 10.0, source="ручно додато")  # noqa: SLF001
        cb_style = dlg.table.cellWidget(0, 7)
        cb_style.setCurrentIndex(cb_style.findData("bold"))

        dlg.table.selectRow(0)
        dlg._on_remove_field()  # noqa: SLF001
        dlg._on_undo()  # noqa: SLF001

        cb_style_restored = dlg.table.cellWidget(0, 7)
        assert cb_style_restored.currentData() == "bold"
    finally:
        dlg.deleteLater()
