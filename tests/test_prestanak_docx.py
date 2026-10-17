"""Tests for core.prestanak_docx — Решење о престанку функције (чл. 15)."""

from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document

from biracki_odbor.config.election import (
    DocumentInfo, ElectionConfig, ElectionDates, ElectionInfo,
)
from biracki_odbor.core.prestanak_docx import PrestanakSpec, generate_prestanak
from tests.test_phase1 import _make_oik


def _make_election() -> ElectionConfig:
    return ElectionConfig(
        election=ElectionInfo(
            dates=ElectionDates(date_full="25. октобар 2026. године"),
            types=["parliamentary"],
        ),
        document=DocumentInfo(number_prefix="013-5-30"),
    )


def _make_spec(**overrides) -> PrestanakSpec:
    defaults = dict(
        person_name="Петар Петровић",
        ceasing_role="члана",
        ceasing_sastav="prosireni",
        ceasing_bm=3,
        ceasing_decision_broj="013-5-30-9/2026",
        ceasing_decision_date="10. октобра 2026. године",
        existing_role="заменика члана",
        existing_sastav="stalni",
        existing_bm=1,
        existing_decision_broj="013-5-30-1/2026",
        existing_decision_date="6. октобра 2026. године",
        municipality="Мионица",
        session_date="12. октобра 2026. године",
        document_broj="Број: 013-5-30-15/2026",
    )
    defaults.update(overrides)
    return PrestanakSpec(**defaults)


def test_normal_style_uses_single_line_spacing(tmp_path: Path) -> None:
    """See core.phase3_docx's identical fix: python-docx's blank-document
    template defaults Normal to 1.15 line spacing, never overridden here
    before now."""
    from docx.enum.text import WD_LINE_SPACING

    out = tmp_path / "resenja"
    path = generate_prestanak(_make_spec(), _make_oik(1), _make_election(), out)
    doc = Document(path)
    assert doc.styles["Normal"].paragraph_format.line_spacing_rule == WD_LINE_SPACING.SINGLE


def test_header_and_footer_distance_is_1cm(tmp_path: Path) -> None:
    out = tmp_path / "resenja"
    path = generate_prestanak(_make_spec(), _make_oik(1), _make_election(), out)
    doc = Document(path)
    section = doc.sections[0]
    assert section.header_distance.cm == pytest.approx(1.0, abs=0.01)
    assert section.footer_distance.cm == pytest.approx(1.0, abs=0.01)


def test_signature_block_uses_chairman_by_default(tmp_path: Path) -> None:
    out = tmp_path / "resenja"
    oik = _make_oik(1)
    oik.chairman.name = "Петар Петровић"
    path = generate_prestanak(_make_spec(), oik, _make_election(), out)
    text = "\n".join(p.text for p in Document(path).paragraphs)
    assert "ПЕТАР ПЕТРОВИЋ" in text


def test_signature_block_uses_delegated_signer_when_authorized(tmp_path: Path) -> None:
    """Delegation is ONE shared setting (config.election.DocumentInfo),
    not izmena-only — a chairman who has delegated signing authority for
    the period has the delegate sign the Престанак decision too."""
    out = tmp_path / "resenja"
    oik = _make_oik(1)
    oik.chairman.name = "Петар Петровић"
    election = _make_election()
    election.document.use_authorization = True
    election.document.authorized_name = "Ивана Тешић"
    election.document.authorized_role = "заменик председника"
    path = generate_prestanak(_make_spec(), oik, election, out)
    text = "\n".join(p.text for p in Document(path).paragraphs)
    assert "ИВАНА ТЕШИЋ" in text
    assert "заменик председника" in text
    assert "ПЕТАР ПЕТРОВИЋ" not in text


def test_signature_block_ignores_delegation_when_toggled_off(tmp_path: Path) -> None:
    out = tmp_path / "resenja"
    oik = _make_oik(1)
    oik.chairman.name = "Петар Петровић"
    election = _make_election()
    election.document.use_authorization = False
    election.document.authorized_name = "Ивана Тешић"
    path = generate_prestanak(_make_spec(), oik, election, out)
    text = "\n".join(p.text for p in Document(path).paragraphs)
    assert "ПЕТАР ПЕТРОВИЋ" in text
    assert "ИВАНА ТЕШИЋ" not in text


def test_generates_a_readable_docx(tmp_path: Path) -> None:
    out = tmp_path / "resenja"
    path = generate_prestanak(_make_spec(), _make_oik(1), _make_election(), out)
    assert path.exists() and path.suffix == ".docx"
    Document(path)  # must open without raising


def test_disposition_names_the_right_seat_as_ceasing(tmp_path: Path) -> None:
    """The LATER (прошиени) appointment is the one that lapses — the
    EARLIER appointment, whatever composition it's in, is what's cited
    as the reason. RIK's own template only shows прошиени as the
    lapsing side — but confirmed with the user, that's just normal
    election scheduling (стали is normally finalized days before
    прошиени, so прошиени is almost always the later of the two), not
    a legal restriction — чл. 15's own wording is "...престаje функција
    у оном органу у којем је касније именовано" (ceases where appointed
    LATER, not the earlier one), with no composition named at all."""
    out = tmp_path / "resenja"
    path = generate_prestanak(
        _make_spec(existing_sastav="stalni"), _make_oik(1), _make_election(), out,
    )
    text = "\n".join(p.text for p in Document(path).paragraphs)
    assert "по сили закона престаје функција" in text
    assert "бирачког одбора у проширеном саставу" in text
    assert "у сталном саставу" in text  # existing_sastav="stalni" rendered correctly
    assert "касније именовано" in text  # verbatim statutory quote, not paraphrased


def test_existing_seat_can_be_prosireni_too(tmp_path: Path) -> None:
    """Confirmed scenario: the earlier, continuing seat can be EITHER
    composition — a person could already hold a prošireni seat in one
    municipality before being (later) duplicated into another."""
    out = tmp_path / "resenja"
    path = generate_prestanak(
        _make_spec(existing_sastav="prosireni"), _make_oik(1), _make_election(), out,
    )
    text = "\n".join(p.text for p in Document(path).paragraphs)
    # Both mentions of "проширеном саставу" in this case (ceasing seat
    # AND existing seat) -- just confirm it renders, not "сталном".
    assert "у сталном саставу" not in text


def test_ceasing_seat_can_be_stalni_too(tmp_path: Path) -> None:
    """RIK's own template only shows прошиени lapsing (form 2.3's own
    title/scope), but that's a scheduling artifact, not a legal rule —
    confirmed with the user: this cycle collapses the normal стали-
    before-прошиени gap to zero (both deadlines land the same day), so
    a стали seat lapsing is genuinely possible, not just a hypothetical
    direction RIK never bothered to template. Must render correctly,
    not silently force "проширеном" regardless of what's selected."""
    out = tmp_path / "resenja"
    path = generate_prestanak(
        _make_spec(ceasing_sastav="stalni", existing_sastav="prosireni"),
        _make_oik(1), _make_election(), out,
    )
    text = "\n".join(p.text for p in Document(path).paragraphs)
    assert "престаје функција члана бирачког одбора у сталном саставу" in text
    assert "именован за заменика члана бирачког одбора у проширеном саставу" in text
    assert text.count("проширеном саставу") >= 2


def test_legal_basis_default_cites_2026_articles(tmp_path: Path) -> None:
    out = tmp_path / "resenja"
    path = generate_prestanak(_make_spec(), _make_oik(1), _make_election(), out)
    text = "\n".join(p.text for p in Document(path).paragraphs)
    assert "члана 14. став 1. тачка 8)" in text
    assert "члана 15." in text
    assert "14/22 и 47/26" in text


def test_legal_basis_override_replaces_the_default(tmp_path: Path) -> None:
    out = tmp_path / "resenja"
    path = generate_prestanak(
        _make_spec(legal_basis="Сопствени текст правног основа."),
        _make_oik(1), _make_election(), out,
    )
    text = "\n".join(p.text for p in Document(path).paragraphs)
    assert "Сопствени текст правног основа." in text
    assert "14/22 и 47/26" not in text


def test_disposition_order_is_stupa_na_snagu_before_objavljuje_se(tmp_path: Path) -> None:
    """The opposite order from every other decision this app generates
    — confirmed against the official form, not a bug to "fix" into
    matching the others."""
    out = tmp_path / "resenja"
    path = generate_prestanak(_make_spec(), _make_oik(1), _make_election(), out)
    paras = [p.text for p in Document(path).paragraphs]
    idx_snaga = next(i for i, t in enumerate(paras) if "ступа на снагу" in t)
    idx_objava = next(i for i, t in enumerate(paras) if "објављује се на веб" in t)
    assert idx_snaga < idx_objava


def test_appeal_window_is_72_hours_not_48(tmp_path: Path) -> None:
    out = tmp_path / "resenja"
    path = generate_prestanak(_make_spec(), _make_oik(1), _make_election(), out)
    text = "\n".join(p.text for p in Document(path).paragraphs)
    assert "72 часа" in text
    assert "48 часова" not in text


def test_existing_municipality_overrides_this_oiks_own(tmp_path: Path) -> None:
    """Field bug: the whole reason this document exists is that the
    existing seat is normally in a DIFFERENT municipality (that's
    exactly why neither OIK could detect the double appointment on its
    own) — but the disposition used to print THIS OIK's own
    municipality for both seats regardless. Must name the existing
    seat's own municipality when given one."""
    out = tmp_path / "resenja"
    path = generate_prestanak(
        _make_spec(existing_municipality="Ваљево"), _make_oik(1), _make_election(), out,
    )
    text = "\n".join(p.text for p in Document(path).paragraphs)
    assert "у општини Ваљево" in text
    # The ceasing seat is still THIS OIK's own municipality.
    assert "на бирачком месту број 3 у општини Мионица" in text


def test_existing_municipality_in_obrazlozenje_narrative_too(tmp_path: Path) -> None:
    """The same bug existed a SECOND time — in the chronological
    образложење narrative paragraph, independent of item 1's
    disposition sentence — both must name the existing seat's own
    municipality, not this OIK's."""
    out = tmp_path / "resenja"
    path = generate_prestanak(
        _make_spec(existing_municipality="Ваљево"), _make_oik(1), _make_election(), out,
    )
    narrative = next(
        p.text for p in Document(path).paragraphs
        if p.text.startswith("Општинска изборна комисија је утврдила да је")
    )
    assert "у општини Ваљево" in narrative
    assert "у општини Мионица" in narrative  # the ceasing seat, still this OIK's own


def test_existing_municipality_blank_falls_back_to_this_oiks_own(tmp_path: Path) -> None:
    """Backward compatible: a spec built before this field existed (or
    a genuinely same-municipality case) still renders sensibly — both
    the ceasing and existing seat read "у општини Мионица" in the
    disposition sentence (other boilerplate elsewhere in the document
    also names the municipality, hence >=2 rather than an exact count)."""
    out = tmp_path / "resenja"
    path = generate_prestanak(_make_spec(), _make_oik(1), _make_election(), out)
    item = next(p.text for p in Document(path).paragraphs if p.text.startswith("1. \tУТВРЂУЈЕ СЕ"))
    assert item.count("у општини Мионица") == 2


def test_bm_numbers_and_decision_refs_appear_correctly(tmp_path: Path) -> None:
    out = tmp_path / "resenja"
    spec = _make_spec(
        ceasing_bm=7, existing_bm=2,
        ceasing_decision_broj="013-5-30-99/2026",
        existing_decision_broj="013-5-30-11/2026",
    )
    path = generate_prestanak(spec, _make_oik(1), _make_election(), out)
    text = "\n".join(p.text for p in Document(path).paragraphs)
    assert "7" in text
    assert "2" in text
    assert "013-5-30-99/2026" in text
    assert "013-5-30-11/2026" in text
