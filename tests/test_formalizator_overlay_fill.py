"""Tests for formalizator.core.overlay_fill — the finished form of
Formalizator.py's sketched-but-never-completed overlay_on_pdf_template.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from formalizator.core import overlay_fill as overlay_fill_mod
from formalizator.core.models import (
    CalibratedTemplate, FieldPosition, SessionInfo, VoterEntry,
)
from formalizator.core.overlay_fill import fill_declaration


def _blank_background(path: Path, n_pages: int = 1) -> Path:
    c = canvas.Canvas(str(path), pagesize=A4)
    for _ in range(n_pages):
        c.showPage()
    c.save()
    return path


def test_fill_declaration_produces_a_pdf_with_expected_page_count(tmp_path: Path) -> None:
    bg = _blank_background(tmp_path / "bg.pdf", n_pages=1)
    tpl = CalibratedTemplate(
        name="t", background_pdf_path=str(bg),
        positions=[FieldPosition(field_key="full_name", page_index=0, x=100, y=700)],
    )
    entry = VoterEntry(given_name="Марко", surname="Марковић")

    out = fill_declaration(tpl, entry, tmp_path / "out.pdf")

    reader = PdfReader(out)
    assert len(reader.pages) == 1


def test_fill_declaration_draws_the_field_text(tmp_path: Path) -> None:
    bg = _blank_background(tmp_path / "bg.pdf")
    tpl = CalibratedTemplate(
        name="t", background_pdf_path=str(bg),
        positions=[FieldPosition(field_key="jmbg", page_index=0, x=50, y=650, font_size=12)],
    )
    entry = VoterEntry(jmbg="0101990123456")

    out = fill_declaration(tpl, entry, tmp_path / "out.pdf")

    reader = PdfReader(out)
    text = reader.pages[0].extract_text()
    assert "0101990123456" in text


def test_fill_declaration_draws_composite_residence_field(tmp_path: Path) -> None:
    """One calibrated position for the form's single "место и адреса"
    blank prints both underlying values together."""
    bg = _blank_background(tmp_path / "bg.pdf")
    tpl = CalibratedTemplate(
        name="t", background_pdf_path=str(bg),
        positions=[FieldPosition(field_key="full_residence", page_index=0, x=50, y=650)],
    )
    entry = VoterEntry(city="Мионица", full_address="Иве Андрића 15")

    out = fill_declaration(tpl, entry, tmp_path / "out.pdf")

    text = PdfReader(out).pages[0].extract_text()
    assert "Мионица" in text and "Иве Андрића 15" in text


def test_fill_declaration_empty_field_draws_nothing(tmp_path: Path) -> None:
    """A field with no value shouldn't draw an empty artifact/crash."""
    bg = _blank_background(tmp_path / "bg.pdf")
    tpl = CalibratedTemplate(
        name="t", background_pdf_path=str(bg),
        positions=[FieldPosition(field_key="city", page_index=0, x=50, y=650)],
    )
    entry = VoterEntry()  # city is empty

    out = fill_declaration(tpl, entry, tmp_path / "out.pdf")
    assert out.exists()


def test_fill_declaration_background_never_modified_on_disk(tmp_path: Path) -> None:
    """The whole point of the PDF-overlay design: filling never edits
    the frozen background file."""
    bg = _blank_background(tmp_path / "bg.pdf")
    original_bytes = bg.read_bytes()
    tpl = CalibratedTemplate(
        name="t", background_pdf_path=str(bg),
        positions=[FieldPosition(field_key="full_name", page_index=0, x=100, y=700)],
    )
    fill_declaration(tpl, VoterEntry(given_name="Марко"), tmp_path / "out.pdf")

    assert bg.read_bytes() == original_bytes


def test_fill_declaration_multi_page_only_overlays_pages_with_positions(tmp_path: Path) -> None:
    bg = _blank_background(tmp_path / "bg.pdf", n_pages=2)
    tpl = CalibratedTemplate(
        name="t", background_pdf_path=str(bg),
        positions=[FieldPosition(field_key="full_name", page_index=1, x=100, y=700)],
    )
    entry = VoterEntry(given_name="Марко", surname="Марковић")

    out = fill_declaration(tpl, entry, tmp_path / "out.pdf")

    reader = PdfReader(out)
    assert len(reader.pages) == 2
    assert "Марко" not in reader.pages[0].extract_text()
    assert "Марко" in reader.pages[1].extract_text()


def test_fill_declaration_draws_universal_field_from_session_info(tmp_path: Path) -> None:
    """A "universal" custom field (e.g. a certifier's name) is typed
    once on the setup screen, not per voter — its value has to come
    from SessionInfo, not VoterEntry."""
    bg = _blank_background(tmp_path / "bg.pdf")
    tpl = CalibratedTemplate(
        name="t", background_pdf_path=str(bg),
        positions=[FieldPosition(field_key="overitelj_ime", page_index=0, x=50, y=650)],
    )
    session = SessionInfo(custom_values={"overitelj_ime": "Петар Петровић"})

    out = fill_declaration(tpl, VoterEntry(), tmp_path / "out.pdf", session)

    text = PdfReader(out).pages[0].extract_text()
    assert "Петар Петровић" in text


def test_fill_declaration_without_session_info_leaves_universal_field_blank(tmp_path: Path) -> None:
    """No session_info passed (e.g. a template with no universal
    fields) shouldn't crash — just nothing drawn for that position."""
    bg = _blank_background(tmp_path / "bg.pdf")
    tpl = CalibratedTemplate(
        name="t", background_pdf_path=str(bg),
        positions=[FieldPosition(field_key="overitelj_ime", page_index=0, x=50, y=650)],
    )

    out = fill_declaration(tpl, VoterEntry(), tmp_path / "out.pdf")
    assert out.exists()


def test_font_for_style_registers_distinct_fonts_per_combination() -> None:
    regular = overlay_fill_mod._font_for_style(bold=False, italic=False)  # noqa: SLF001
    bold = overlay_fill_mod._font_for_style(bold=True, italic=False)  # noqa: SLF001
    italic = overlay_fill_mod._font_for_style(bold=False, italic=True)  # noqa: SLF001
    bold_italic = overlay_fill_mod._font_for_style(bold=True, italic=True)  # noqa: SLF001
    assert len({regular, bold, italic, bold_italic}) == 4


def test_default_font_is_the_plain_regular_style() -> None:
    assert overlay_fill_mod._default_font() == overlay_fill_mod._font_for_style()  # noqa: SLF001


def test_fill_declaration_center_aligns_within_the_calibrated_width(tmp_path: Path, monkeypatch) -> None:
    bg = _blank_background(tmp_path / "bg.pdf")
    tpl = CalibratedTemplate(
        name="t", background_pdf_path=str(bg),
        positions=[FieldPosition(
            field_key="full_name", page_index=0, x=100.0, y=650.0,
            font_size=10.0, width=200.0, align="center",
        )],
    )
    entry = VoterEntry(given_name="Ана", surname="Анић")

    captured = {}
    original = canvas.Canvas.drawString

    def spy(self, x, y, text, *a, **kw):
        captured["x"] = x
        return original(self, x, y, text, *a, **kw)

    monkeypatch.setattr(canvas.Canvas, "drawString", spy)
    fill_declaration(tpl, entry, tmp_path / "out.pdf")

    font_name = overlay_fill_mod._font_for_style()  # noqa: SLF001
    text_width = overlay_fill_mod.pdfmetrics.stringWidth("Ана Анић", font_name, 10.0)
    assert captured["x"] == pytest.approx(100.0 + (200.0 - text_width) / 2)


def test_fill_declaration_right_aligns_within_the_calibrated_width(tmp_path: Path, monkeypatch) -> None:
    bg = _blank_background(tmp_path / "bg.pdf")
    tpl = CalibratedTemplate(
        name="t", background_pdf_path=str(bg),
        positions=[FieldPosition(
            field_key="full_name", page_index=0, x=100.0, y=650.0,
            font_size=10.0, width=200.0, align="right",
        )],
    )
    entry = VoterEntry(given_name="Ана", surname="Анић")

    captured = {}
    original = canvas.Canvas.drawString

    def spy(self, x, y, text, *a, **kw):
        captured["x"] = x
        return original(self, x, y, text, *a, **kw)

    monkeypatch.setattr(canvas.Canvas, "drawString", spy)
    fill_declaration(tpl, entry, tmp_path / "out.pdf")

    font_name = overlay_fill_mod._font_for_style()  # noqa: SLF001
    text_width = overlay_fill_mod.pdfmetrics.stringWidth("Ана Анић", font_name, 10.0)
    assert captured["x"] == pytest.approx(100.0 + 200.0 - text_width)


def test_fill_declaration_left_align_draws_at_the_anchor(tmp_path: Path, monkeypatch) -> None:
    bg = _blank_background(tmp_path / "bg.pdf")
    tpl = CalibratedTemplate(
        name="t", background_pdf_path=str(bg),
        positions=[FieldPosition(
            field_key="full_name", page_index=0, x=100.0, y=650.0,
            width=200.0, align="left",
        )],
    )
    entry = VoterEntry(given_name="Ана", surname="Анић")

    captured = {}
    original = canvas.Canvas.drawString

    def spy(self, x, y, text, *a, **kw):
        captured["x"] = x
        return original(self, x, y, text, *a, **kw)

    monkeypatch.setattr(canvas.Canvas, "drawString", spy)
    fill_declaration(tpl, entry, tmp_path / "out.pdf")

    assert captured["x"] == pytest.approx(100.0)


def test_fill_declaration_center_align_with_no_width_falls_back_to_anchor(tmp_path: Path, monkeypatch) -> None:
    """With no calibrated width there's no box to center within — draw
    at the plain anchor rather than guessing at one."""
    bg = _blank_background(tmp_path / "bg.pdf")
    tpl = CalibratedTemplate(
        name="t", background_pdf_path=str(bg),
        positions=[FieldPosition(
            field_key="full_name", page_index=0, x=100.0, y=650.0, align="center",
        )],
    )
    entry = VoterEntry(given_name="Ана", surname="Анић")

    captured = {}
    original = canvas.Canvas.drawString

    def spy(self, x, y, text, *a, **kw):
        captured["x"] = x
        return original(self, x, y, text, *a, **kw)

    monkeypatch.setattr(canvas.Canvas, "drawString", spy)
    fill_declaration(tpl, entry, tmp_path / "out.pdf")

    assert captured["x"] == pytest.approx(100.0)




# ── Shrink-to-fit ────────────────────────────────────────────────────
#
# These forms have no second line a value can wrap into — a blank is
# one line on the real, hand-tuned page, and whatever the form prints
# beside or below it has no reserved room for an overflowing name. A
# value wider than its box shrinks to fit on that one line instead of
# spilling past it uncontrolled.


def _spy_on_set_font(monkeypatch) -> list[tuple[str, float]]:
    """Records every (font name, size) reportlab actually draws with,
    while still performing the real call — the resulting PDF stays
    valid and readable by the other assertions in these tests."""
    from reportlab.pdfgen import canvas as canvas_mod

    calls: list[tuple[str, float]] = []
    original = canvas_mod.Canvas.setFont

    def spy(self, psfontname, size, *a, **kw):
        calls.append((psfontname, size))
        return original(self, psfontname, size, *a, **kw)

    monkeypatch.setattr(canvas_mod.Canvas, "setFont", spy)
    return calls


_LONG_NAME = "Александар-Константин Радovановић-Николић-Стефановић"


def test_a_short_value_keeps_its_calibrated_font_size(tmp_path, monkeypatch) -> None:
    """The common case must be completely unaffected — this is a safety
    net for the rare long value, not a change to ordinary output."""
    calls = _spy_on_set_font(monkeypatch)
    bg = _blank_background(tmp_path / "bg.pdf")
    tpl = CalibratedTemplate(
        name="t", background_pdf_path=str(bg),
        positions=[FieldPosition(field_key="full_name", page_index=0, x=50, y=650, font_size=12)],
    )
    entry = VoterEntry(given_name="Ана", surname="Анић")

    fill_declaration(tpl, entry, tmp_path / "out.pdf")

    assert calls == [(calls[0][0], 12)]


def test_a_long_value_is_shrunk_to_fit_an_explicit_width(tmp_path, monkeypatch) -> None:
    calls = _spy_on_set_font(monkeypatch)
    bg = _blank_background(tmp_path / "bg.pdf")
    tpl = CalibratedTemplate(
        name="t", background_pdf_path=str(bg),
        positions=[FieldPosition(
            field_key="full_name", page_index=0, x=50, y=650, font_size=12, width=80,
        )],
    )
    entry = VoterEntry(given_name=_LONG_NAME, surname="")

    out = fill_declaration(tpl, entry, tmp_path / "out.pdf")

    assert calls[0][1] < 12, "must shrink when the calibrated width is too narrow"
    # Shrinking must never drop characters — the whole name still prints.
    assert _LONG_NAME in PdfReader(out).pages[0].extract_text()


def test_a_long_value_shrinks_even_without_an_explicit_width(tmp_path, monkeypatch) -> None:
    """No FieldPosition.width was ever set for this field (0 = "auto")
    — must still get *some* protection, from the same auto-computed box
    the calibration wizard already shows as the field's preview."""
    calls = _spy_on_set_font(monkeypatch)
    bg = _blank_background(tmp_path / "bg.pdf")
    tpl = CalibratedTemplate(
        name="t", background_pdf_path=str(bg),
        positions=[FieldPosition(
            field_key="full_name", page_index=0, x=50, y=650, font_size=12,
        )],  # width left at its 0.0 default
    )
    entry = VoterEntry(given_name=_LONG_NAME * 2, surname="")  # long enough to beat even the generous auto box

    fill_declaration(tpl, entry, tmp_path / "out.pdf")

    assert calls[0][1] < 12


def test_shrinking_never_goes_below_the_legible_floor(tmp_path, monkeypatch) -> None:
    """Past the floor, an extreme value is allowed to overflow rather
    than be crushed into illegibility."""
    calls = _spy_on_set_font(monkeypatch)
    bg = _blank_background(tmp_path / "bg.pdf")
    tpl = CalibratedTemplate(
        name="t", background_pdf_path=str(bg),
        positions=[FieldPosition(
            field_key="full_name", page_index=0, x=50, y=650, font_size=12, width=40,
        )],
    )
    entry = VoterEntry(given_name=_LONG_NAME * 10, surname="")

    fill_declaration(tpl, entry, tmp_path / "out.pdf")

    assert calls[0][1] == overlay_fill_mod._MIN_SHRINK_FONT_PT  # noqa: SLF001


def test_right_alignment_uses_the_shrunk_width_not_the_original(tmp_path, monkeypatch) -> None:
    """A subtle way this could regress: computing the alignment offset
    from the pre-shrink text width would misplace the text — the whole
    point of right-aligning it to the box is defeated if the offset is
    computed against a width the drawn text no longer has."""
    from reportlab.pdfgen import canvas as canvas_mod

    draws: list[tuple[float, str]] = []
    fonts: list[tuple[str, float]] = []
    original_draw = canvas_mod.Canvas.drawString
    original_set_font = canvas_mod.Canvas.setFont

    def spy_draw(self, x, y, text, *a, **kw):
        draws.append((x, text))
        return original_draw(self, x, y, text, *a, **kw)

    def spy_set_font(self, name, size, *a, **kw):
        fonts.append((name, size))
        return original_set_font(self, name, size, *a, **kw)

    monkeypatch.setattr(canvas_mod.Canvas, "drawString", spy_draw)
    monkeypatch.setattr(canvas_mod.Canvas, "setFont", spy_set_font)

    bg = _blank_background(tmp_path / "bg.pdf")
    box_x, box_width, font_size = 50.0, 80.0, 12.0
    tpl = CalibratedTemplate(
        name="t", background_pdf_path=str(bg),
        positions=[FieldPosition(
            field_key="full_name", page_index=0, x=box_x, y=650, font_size=font_size,
            width=box_width, align="right",
        )],
    )
    entry = VoterEntry(given_name=_LONG_NAME, surname="")

    fill_declaration(tpl, entry, tmp_path / "out.pdf")

    font_name, drawn_size = fonts[0]
    drawn_x, drawn_text = draws[0]
    assert drawn_size < font_size, "sanity: this name must actually have triggered a shrink"

    # The correct right-aligned x, computed independently using the
    # font size actually drawn with — this is the value that would be
    # wrong if the implementation aligned against the original,
    # pre-shrink text width instead.
    measuring = canvas_mod.Canvas(str(tmp_path / "_measure.pdf"))
    expected_text_width = measuring.stringWidth(drawn_text, font_name, drawn_size)
    expected_x = box_x + box_width - expected_text_width

    assert drawn_x == pytest.approx(expected_x, abs=0.5)
