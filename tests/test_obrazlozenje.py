"""Tests for biracki_odbor.config.obrazlozenje."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from biracki_odbor.config import obrazlozenje


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path))
    obrazlozenje._cache = None
    obrazlozenje._cache_path = None
    yield


def test_dialog_module_importable() -> None:
    """Regression: the dialog had an embedded ASCII `"` inside a Python `"..."`
    string on the line that builds the `optional`-checkbox tooltip. Qt swallows
    slot exceptions, so the button silently did nothing on click. This test
    would have caught the SyntaxError at suite time."""
    from biracki_odbor.gui.dialogs import obrazlozenje_dialog  # noqa: F401


def test_dialog_constructs() -> None:
    """Smoke: dialog actually builds without throwing. Validates that the
    Qt widget tree is wired up correctly across the seed paragraphs."""
    from PySide6.QtWidgets import QApplication
    from biracki_odbor.gui.dialogs.obrazlozenje_dialog import ObrazlozenjeDialog
    app = QApplication.instance() or QApplication([])
    # Force the seed file to exist so the dialog has something to populate.
    obrazlozenje.load()
    dlg = ObrazlozenjeDialog()
    assert dlg.windowTitle() == "Уређивање текста образложења"
    cards = dlg._cards()  # noqa: SLF001 — test-only inspection
    assert cards, "expected at least one paragraph card from the seed"


def test_file_seeded_on_first_load(tmp_path: Path) -> None:
    from biracki_odbor import app_paths
    path = app_paths.obrazlozenje_path()
    assert not path.exists()
    obrazlozenje.load()
    assert path.exists()
    # Seed should contain the canonical paragraphs.
    paragraphs = obrazlozenje.load()
    ids = {p.id for p in paragraphs}
    assert "sastav-stalnog-odbora" in ids
    assert "zajednicki-izbori" in ids
    assert "slucaj-nedostavljenog-predloga" in ids
    assert "prelazna-odredba" in ids


def test_render_substitutes_placeholders() -> None:
    rendered = obrazlozenje.render(
        rik_decision="Одлуком РИК-а 02 број 013-376/26",
        municipality="Уб",
    )
    # Flatten all rendered text to one blob for easy lookup.
    blob = "".join(text for para in rendered for text, _ in para)
    assert "Одлуком РИК-а 02 број 013-376/26" in blob
    assert "у општини Уб" in blob


def test_render_returns_paragraphs_in_seed_order() -> None:
    rendered = obrazlozenje.render(rik_decision="X", municipality="Уб")
    # First paragraph starts with "Чланом 35."; "У складу са наведеним"
    # (zakljucak) now sits second-to-last, followed by
    # "uputstvo-pravno-sredstvo" (moved here from being hardcoded
    # directly in core/phase3_docx.py, outside the editable template).
    assert rendered[0][0][0].startswith("Чланом 35.")
    assert "У складу са наведеним" in rendered[-2][0][0]
    assert "УПУТСТВО О ПРАВНОМ СРЕДСТВУ" in rendered[-1][0][0]


def test_render_preserves_bold_flags() -> None:
    rendered = obrazlozenje.render(rik_decision="X", municipality="Уб")
    # First paragraph: first segment ("Чланом 35.") is bold, the rest isn't.
    first_para = rendered[0]
    assert first_para[0][1] is True   # "Чланом 35." → bold
    assert first_para[1][1] is False  # rest → not bold


def test_user_edited_file_overrides_seed() -> None:
    """If the user removes a paragraph from the JSON, render() reflects that."""
    obrazlozenje.load()
    from biracki_odbor import app_paths
    path = app_paths.obrazlozenje_path()
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Drop the "slucaj-nedostavljenog-predloga" paragraph entirely.
    data["paragraphs"] = [p for p in data["paragraphs"] if p["id"] != "slucaj-nedostavljenog-predloga"]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    # Force reload to pick up the change.
    obrazlozenje.load(force=True)
    rendered = obrazlozenje.render(rik_decision="X", municipality="Уб")
    blob = "".join(text for para in rendered for text, _ in para)
    assert "АКО НЕКА ПОСЛАНИЧКА ГРУПА" not in blob


def test_render_excludes_local_election_paragraphs_by_default() -> None:
    """Field report: the 2026 official RIK sample forms don't include the
    чл. 89/91/92 (concurrent local-election) paragraphs at all — "right
    now no one has them, but that doesn't make the case impossible" —
    so they must stay dormant unless THIS election actually coincides
    with a local one."""
    rendered = obrazlozenje.render(rik_decision="X", municipality="Уб")
    blob = "".join(text for para in rendered for text, _ in para)
    assert "Чланом 89." not in blob
    assert "Чланом 91." not in blob


def test_render_includes_local_election_paragraphs_when_flagged() -> None:
    rendered = obrazlozenje.render(
        rik_decision="X", municipality="Уб", local_elections=True,
    )
    blob = "".join(text for para in rendered for text, _ in para)
    assert "Чланом 89." in blob
    assert "Чланом 91." in blob


def test_render_recovers_from_unknown_placeholder() -> None:
    """A user typo like {muncpality} shouldn't crash — text passes through."""
    obrazlozenje.load()
    from biracki_odbor import app_paths
    path = app_paths.obrazlozenje_path()
    data = json.loads(path.read_text(encoding="utf-8"))
    data["paragraphs"][0]["segments"][0]["text"] = "Чланом {muncpality}."  # typo
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    obrazlozenje.load(force=True)
    rendered = obrazlozenje.render(rik_decision="X", municipality="Уб")
    # Unknown key → text returned as-is, no exception.
    assert rendered[0][0][0] == "Чланом {muncpality}."


def test_corrupt_json_falls_back_to_seed() -> None:
    from biracki_odbor import app_paths
    path = app_paths.obrazlozenje_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not valid {", encoding="utf-8")
    obrazlozenje._cache = None
    obrazlozenje._cache_path = None
    paragraphs = obrazlozenje.load(force=True)
    # Seed has 10 paragraphs (8 original + prelazna-odredba + uputstvo-pravno-sredstvo).
    assert len(paragraphs) == 10


def test_wrong_version_falls_back_to_seed() -> None:
    from biracki_odbor import app_paths
    path = app_paths.obrazlozenje_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": 999, "paragraphs": [{"id": "x", "segments": []}]}),
        encoding="utf-8",
    )
    obrazlozenje._cache = None
    obrazlozenje._cache_path = None
    paragraphs = obrazlozenje.load(force=True)
    assert any(p.id == "sastav-stalnog-odbora" for p in paragraphs)


def test_parse_markdown_plain_text() -> None:
    segments = obrazlozenje.parse_markdown_paragraph("Само обичан текст.")
    assert len(segments) == 1
    assert segments[0].text == "Само обичан текст."
    assert segments[0].bold is False


def test_parse_markdown_bold_at_start() -> None:
    segments = obrazlozenje.parse_markdown_paragraph("**Чланом 35.** Закона...")
    assert segments[0].text == "Чланом 35."
    assert segments[0].bold is True
    assert segments[1].text == " Закона..."
    assert segments[1].bold is False


def test_parse_markdown_bold_in_middle() -> None:
    segments = obrazlozenje.parse_markdown_paragraph("Прети дан **15 дана** касније.")
    assert [s.bold for s in segments] == [False, True, False]
    assert segments[0].text == "Прети дан "
    assert segments[1].text == "15 дана"
    assert segments[2].text == " касније."


def test_parse_markdown_only_bold() -> None:
    segments = obrazlozenje.parse_markdown_paragraph("**Цео текст је болд.**")
    assert len(segments) == 1
    assert segments[0].text == "Цео текст је болд."
    assert segments[0].bold is True


def test_parse_markdown_empty_input() -> None:
    segments = obrazlozenje.parse_markdown_paragraph("")
    assert len(segments) == 1
    assert segments[0].text == ""


def test_render_paragraph_markdown_roundtrip() -> None:
    original = "Прет **бол** норм **бол2** крај."
    parsed = obrazlozenje.parse_markdown_paragraph(original)
    rendered = obrazlozenje.render_paragraph_markdown(parsed)
    assert rendered == original


def test_render_skips_empty_segments() -> None:
    segments = [
        obrazlozenje.Segment("", bold=False),
        obrazlozenje.Segment("Чланом 35.", bold=True),
        obrazlozenje.Segment("", bold=False),
        obrazlozenje.Segment(" Закона.", bold=False),
    ]
    assert obrazlozenje.render_paragraph_markdown(segments) == "**Чланом 35.** Закона."


def test_prosireni_seed_differs_from_stalni() -> None:
    """Field report: prosireni's Phase 3 preview/решење showed stalni's
    legal text ("...сталном саставу...", "члан 35") even though the
    workflow says "У ПРОШИРЕНОМ САСТАВУ" — obrazlozenje_prosireni.json
    must seed with prosireni's own articles (чл. 10, 39 ст. 1, 92), not
    a copy of stalni's."""
    from biracki_odbor import app_paths
    from biracki_odbor.core.workflow import PROSIRENI_SPEC
    path = app_paths.obrazlozenje_path_for(PROSIRENI_SPEC)
    assert not path.exists()
    paragraphs = obrazlozenje.load(path=path)
    ids = {p.id for p in paragraphs}
    assert "sastav-prosirenog-odbora" in ids
    assert "sastav-stalnog-odbora" not in ids
    blob = "".join(seg.text for p in paragraphs for seg in p.segments)
    assert "сталном саставу" not in blob
    assert "Чланом 39. став 1." in blob


def test_render_with_path_reads_the_right_workflows_template() -> None:
    from biracki_odbor import app_paths
    from biracki_odbor.core.workflow import PROSIRENI_SPEC
    stalni_rendered = obrazlozenje.render(rik_decision="X", municipality="Уб")
    prosireni_rendered = obrazlozenje.render(
        rik_decision="X", municipality="Уб",
        path=app_paths.obrazlozenje_path_for(PROSIRENI_SPEC),
    )
    stalni_blob = "".join(t for para in stalni_rendered for t, _ in para)
    prosireni_blob = "".join(t for para in prosireni_rendered for t, _ in para)
    assert stalni_blob != prosireni_blob
    assert "сталном саставу" in stalni_blob
    assert "сталном саставу" not in prosireni_blob


def test_save_then_load_roundtrip() -> None:
    # Includes uputstvo-pravno-sredstvo so this test isolates pure
    # round-trip fidelity from the legal-remedy migration (covered
    # separately below) -- a list that already has it should come back
    # unchanged, not grown by one.
    new_paragraphs = [
        obrazlozenje.Paragraph(
            id="custom",
            segments=[obrazlozenje.Segment("Тест.", bold=True)],
            optional=False,
        ),
        obrazlozenje.Paragraph(
            id="uputstvo-pravno-sredstvo",
            segments=[obrazlozenje.Segment("Правно средство текст.", bold=False)],
            optional=False,
        ),
    ]
    obrazlozenje.save(new_paragraphs)
    loaded = obrazlozenje.load(force=True)
    assert len(loaded) == 2
    assert loaded[0].id == "custom"
    assert loaded[0].segments[0].text == "Тест."
    assert loaded[0].segments[0].bold is True


def test_load_migrates_an_existing_file_missing_the_legal_remedy_paragraph() -> None:
    """uputstvo-pravno-sredstvo used to be hardcoded directly in
    core/phase3_docx.py, outside the editable template -- an operator's
    file saved before it became a normal paragraph here has no way to
    already contain it. load() must add it (and persist that, not just
    return it in memory) rather than silently generating decisions
    without a legally-required instruction forever."""
    from biracki_odbor import app_paths

    old_style_paragraphs = [
        obrazlozenje.Paragraph(
            id="custom",
            segments=[obrazlozenje.Segment("Тест.", bold=True)],
            optional=False,
        ),
    ]
    # save() itself ends with an internal load(force=True) to refresh
    # the cache, which already triggers the migration before this test
    # does anything else -- so by the time save() returns, the file is
    # already migrated. That's fine: the point under test is the
    # end-to-end outcome (an "old-shape" file ends up WITH the
    # paragraph), not which exact call does the migrating.
    obrazlozenje.save(old_style_paragraphs)

    loaded = obrazlozenje.load(force=True)
    assert [p.id for p in loaded] == ["custom", "uputstvo-pravno-sredstvo"]

    # Persisted to disk, not just returned in memory -- a second load
    # (fresh process, cache cleared) must not need to migrate again.
    path = app_paths.obrazlozenje_path()
    on_disk_after = json.loads(path.read_text(encoding="utf-8"))
    assert any(p["id"] == "uputstvo-pravno-sredstvo" for p in on_disk_after["paragraphs"])


def test_missing_legal_remedy_is_always_restored_even_if_removed_on_purpose() -> None:
    """Known, deliberate tradeoff: load() can't tell "this file predates
    the migration" apart from "an operator removed the paragraph on
    purpose" -- both look identical (the id is simply absent) -- so it
    re-adds it every time either way. Given this text is a legally
    required instruction on an official decision, defaulting to "always
    present" is safer than defaulting to "respect the removal", which
    would risk a decision silently going out without it. If an operator
    ever needs to genuinely omit/replace it, blanking its segments
    (keeping the id) rather than deleting the paragraph is the way."""
    deliberately_without = [
        obrazlozenje.Paragraph(
            id="custom-only",
            segments=[obrazlozenje.Segment("Нешто друго.", bold=False)],
            optional=False,
        ),
    ]
    obrazlozenje.save(deliberately_without)
    loaded = obrazlozenje.load(force=True)
    assert any(p.id == "uputstvo-pravno-sredstvo" for p in loaded)


def test_legal_remedy_migration_never_touches_izmene_files(tmp_path: Path) -> None:
    """Regression: load() is shared infrastructure also used for izmene's
    izmena_obrazlozenje_{slug}.json files, which have their OWN
    legal-remedy paragraph under a different id ("pravna-pouka"). The
    migration must not inject the phase3-worded paragraph into those
    files as a spurious duplicate -- it did, once, before this guard
    (caught via a real operator's file after a live test session)."""
    izmene_style_path = tmp_path / "izmena_obrazlozenje_stalni.json"
    paragraphs_without_the_id = [
        obrazlozenje.Paragraph(
            id="pravna-pouka",
            segments=[obrazlozenje.Segment("Правна поука текст.", bold=False)],
            optional=False,
        ),
    ]
    obrazlozenje.save(paragraphs_without_the_id, path=izmene_style_path)
    loaded = obrazlozenje.load(force=True, path=izmene_style_path)
    assert [p.id for p in loaded] == ["pravna-pouka"]
    assert not any(p.id == "uputstvo-pravno-sredstvo" for p in loaded)
