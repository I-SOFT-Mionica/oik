"""Tests for config.oik.DocumentFormat — line spacing, header/footer
distance, and title-block/body-paragraph spacing, applied to every
resenje type via core.phase3_docx.apply_document_format(). Title/body
spacing is edited on the generation screens themselves (Phase 3,
Измене), not Поставке ОИК — the operator wants to shrink spacing right
where they're about to generate and can see the page count."""

from __future__ import annotations

from biracki_odbor.config.oik import DocumentFormat, OikConstants


def test_defaults_restore_the_original_rik_look() -> None:
    """"RIK format" as the default, not a forced 0/0 -- before this was
    configurable, title-block paragraphs mixed 0/3/6/12pt and ordinary
    body paragraphs mostly used 6pt after. The operator shrinks spacing
    from here when a решење overflows onto an unwanted extra page."""
    fmt = DocumentFormat()
    assert fmt.line_spacing == "single"
    assert fmt.header_distance_cm == 1.0
    assert fmt.footer_distance_cm == 1.0
    assert fmt.title_before_pt == 0.0
    assert fmt.title_after_pt == 6.0
    assert fmt.body_before_pt == 0.0
    assert fmt.body_after_pt == 6.0


def test_roundtrip_through_oik_constants() -> None:
    oik = OikConstants()
    oik.document_format.line_spacing = "double"
    oik.document_format.header_distance_cm = 2.5
    oik.document_format.footer_distance_cm = 0.5
    oik.document_format.title_before_pt = 2.0
    oik.document_format.title_after_pt = 4.0
    oik.document_format.body_before_pt = 1.0
    oik.document_format.body_after_pt = 3.0

    restored = OikConstants.from_dict(oik.to_dict())

    assert restored.document_format.line_spacing == "double"
    assert restored.document_format.header_distance_cm == 2.5
    assert restored.document_format.footer_distance_cm == 0.5
    assert restored.document_format.title_before_pt == 2.0
    assert restored.document_format.title_after_pt == 4.0
    assert restored.document_format.body_before_pt == 1.0
    assert restored.document_format.body_after_pt == 3.0


def test_old_oik_constants_without_document_format_get_defaults() -> None:
    """A config saved before this field existed must still load."""
    old_dict = {"nacelnik_full_name": "начелника Општинске управе"}
    oik = OikConstants.from_dict(old_dict)
    assert oik.document_format.line_spacing == "single"
    assert oik.document_format.header_distance_cm == 1.0
    assert oik.document_format.title_after_pt == 6.0
    assert oik.document_format.body_after_pt == 6.0


def test_unknown_line_spacing_value_falls_back_to_single() -> None:
    """Defensive against a hand-edited or corrupted config file."""
    fmt = DocumentFormat.from_dict({"line_spacing": "triple"})
    assert fmt.line_spacing == "single"
