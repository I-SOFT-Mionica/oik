"""Tests for formalizator.core.pdf_template's platform guard. The actual
Word->PDF export needs real Microsoft Word and is verified manually."""

from __future__ import annotations

import pytest

import formalizator.core.pdf_template as mod


def test_word_com_available_is_a_bool() -> None:
    assert isinstance(mod.WORD_COM_AVAILABLE, bool)


def test_export_to_pdf_raises_clear_error_when_word_unavailable(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(mod, "WORD_COM_AVAILABLE", False)
    with pytest.raises(mod.WordUnavailable, match="Word"):
        mod.export_to_pdf(tmp_path / "in.docx", tmp_path / "out.pdf")


def test_word_unavailable_is_a_real_exception_type() -> None:
    assert issubclass(mod.WordUnavailable, Exception)
