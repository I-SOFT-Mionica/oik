"""Tests for formalizator.core.label_detector — auto-detecting field
positions on a rendered official-form PDF, never guessing silently."""

from __future__ import annotations

from pathlib import Path

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from formalizator.core.label_detector import detect
from formalizator.core.overlay_fill import _default_font  # noqa: SLF001


def _pdf_with_lines(path: Path, lines: list[tuple[float, float, str]]) -> Path:
    """`lines`: (x, y, text) in PDF points, bottom-left origin."""
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont(_default_font(), 10)
    for x, y, text in lines:
        c.drawString(x, y, text)
    c.showPage()
    c.save()
    return path


def test_detects_name_label_and_infers_position_above_it(tmp_path: Path) -> None:
    pdf = _pdf_with_lines(tmp_path / "t.pdf", [(100, 600, "(име и презиме)")])
    result = detect(pdf)

    assert len(result.detected) == 1
    pos = result.detected[0]
    assert pos.field_key == "full_name"
    assert pos.page_index == 0
    # Inferred position sits above the label (higher y, PDF bottom-up).
    assert pos.y > 600


def test_two_labels_on_the_same_line_resolved_independently(tmp_path: Path) -> None:
    """The real NPRS-3 form has '(име и презиме)' and '(датум рођења)'
    side by side, tab-separated, on one line."""
    pdf = _pdf_with_lines(tmp_path / "t.pdf", [
        (80, 600, "(име и презиме)"),
        (320, 600, "(датум рођења)"),
    ])
    result = detect(pdf)

    by_key = {p.field_key: p for p in result.detected}
    assert set(by_key) == {"full_name", "date_of_birth"}
    assert by_key["full_name"].x < by_key["date_of_birth"].x


def test_jmbg_label_is_always_flagged_not_auto_placed(tmp_path: Path) -> None:
    """JMBG renders as 13 individual digit boxes on the real form — a
    single inferred coordinate would be structurally wrong."""
    pdf = _pdf_with_lines(tmp_path / "t.pdf", [(100, 600, "(ЈМБГ)")])
    result = detect(pdf)

    assert result.detected == []
    assert len(result.flagged) == 1
    assert "13" in result.flagged[0].reason


def test_flagged_label_exposes_pdf_space_y_for_the_ghost_marker(tmp_path: Path) -> None:
    """The calibration screen shows a "here's roughly where this is"
    marker for flagged-but-unplaced rows using this — it has to be in
    the same bottom-up PDF space as a real FieldPosition.y, not
    pdfplumber's own top-down `top`."""
    pdf = _pdf_with_lines(tmp_path / "t.pdf", [(100, 600, "(ЈМБГ)")])
    result = detect(pdf)

    flagged = result.flagged[0]
    from reportlab.lib.pagesizes import A4
    assert flagged.y == pytest.approx(A4[1] - flagged.top)


def test_unrecognized_parenthesized_label_is_flagged_not_guessed(tmp_path: Path) -> None:
    pdf = _pdf_with_lines(tmp_path / "t.pdf", [(100, 600, "(нешто непознато)")])
    result = detect(pdf)

    assert result.detected == []
    assert len(result.flagged) >= 1


def test_no_labels_produces_empty_result(tmp_path: Path) -> None:
    pdf = _pdf_with_lines(tmp_path / "t.pdf", [(100, 600, "обичан текст без ознака")])
    result = detect(pdf)

    assert result.detected == []
    assert result.flagged == []


def test_address_label_variant_maps_to_full_residence(tmp_path: Path) -> None:
    """The label reads "место И адреса" (place AND address) — one
    blank, so the combined value, not just full_address alone."""
    pdf = _pdf_with_lines(tmp_path / "t.pdf", [(100, 600, "(место и адреса становања)")])
    result = detect(pdf)

    assert len(result.detected) == 1
    assert result.detected[0].field_key == "full_residence"
