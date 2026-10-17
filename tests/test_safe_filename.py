"""Tests for the two _safe_filename() implementations.

Field report: a real coalition election-list name typed in at v0.72.0 —
319 characters, containing an embedded newline (copied verbatim from
its official multi-line layout) — broke Excel file generation entirely.
Reproduced directly: openpyxl's wb.save() raised
`OSError: [Errno 22] Invalid argument` because (1) a literal newline
character is fatal in a Windows filename and the old denylist regex
never stripped it, and (2) there was no length cap, so even after
sanitizing characters the resulting path exceeded Windows' MAX_PATH.
"""

from __future__ import annotations

from pathlib import Path

import openpyxl
import pytest


REAL_WORLD_LIST_NAME = (
    "СРБИЈА ПРОТИВ НАСИЉА - МИРОСЛАВ МИКИ АЛЕКСИЋ - МАРИНИКА ТЕПИЋ (СТРАНКА СЛОБОДЕ И ПРАВДЕ, НАРОДНИ\n"
    "ПОКРЕТ СРБИЈЕ, ЗЕЛЕНО-ЛЕВИ ФРОНТ, НЕ ДАВИМО БЕОГРАД, ЕКОЛОШКИ УСТАНАК - ЋУТА, ДЕМОКРАТСКА СТРАНКА,\n"
    "ПОКРЕТ СЛОБОДНИХ ГРАЂАНА, СРБИЈА ЦЕНТАР, ЗАЈЕДНО, ПОКРЕТ ЗА ПРЕОКРЕТ, УДРУЖЕНИ СИНДИКАТИ СРБИЈЕ\n"
    "'СЛОГА'', НОВО ЛИЦЕ СРБИЈЕ)"
)


@pytest.mark.parametrize("module_path", [
    "biracki_odbor.core.phase1_generate",
    "biracki_odbor.core.posmatraci_docx",
])
def test_safe_filename_strips_newlines(module_path) -> None:
    import importlib
    mod = importlib.import_module(module_path)
    result = mod._safe_filename("line one\nline two\r\nline three")
    assert "\n" not in result
    assert "\r" not in result


@pytest.mark.parametrize("module_path", [
    "biracki_odbor.core.phase1_generate",
    "biracki_odbor.core.posmatraci_docx",
])
def test_safe_filename_caps_length(module_path) -> None:
    import importlib
    mod = importlib.import_module(module_path)
    result = mod._safe_filename("A" * 500)
    assert len(result) <= 80


@pytest.mark.parametrize("module_path", [
    "biracki_odbor.core.phase1_generate",
    "biracki_odbor.core.posmatraci_docx",
])
def test_safe_filename_real_world_long_multiline_name_produces_valid_filename(
    module_path, tmp_path: Path,
) -> None:
    """The exact reproduction of the v0.72.0 field failure: sanitize the
    real coalition name, then actually save an xlsx under that filename
    — this must not raise OSError."""
    import importlib
    mod = importlib.import_module(module_path)
    safe = mod._safe_filename(REAL_WORLD_LIST_NAME)
    assert "\n" not in safe
    assert len(safe) <= 80

    target = tmp_path / f"{safe}.xlsx"
    wb = openpyxl.Workbook()
    wb.active["A1"] = "test"
    wb.save(target)  # must not raise
    assert target.exists()


def test_safe_filename_still_handles_windows_illegal_characters() -> None:
    from biracki_odbor.core.phase1_generate import _safe_filename
    result = _safe_filename('bad:name*with"illegal<chars>|and/slash\\es')
    for ch in ':*"<>|/\\':
        assert ch not in result


def test_safe_filename_empty_or_all_illegal_falls_back_to_placeholder() -> None:
    from biracki_odbor.core.phase1_generate import _safe_filename
    assert _safe_filename("") == "странка"
    assert _safe_filename("///\\\\\n\n") == "странка"
