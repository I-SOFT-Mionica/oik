"""Tests for formalizator.reader.eid_reader — the pure logic (DLL path
resolution, error-code mapping) that doesn't need real card hardware.
Actual card reads are verified manually, same as the original prototype.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from formalizator.reader.eid_reader import (
    EID_PORTRAIT, EidReaderError, EidReaderUnavailable, _resolve_dll_path,
)


def test_resolve_dll_path_explicit_path_used_when_it_exists(tmp_path: Path) -> None:
    dll = tmp_path / "CelikApi.dll"
    dll.write_bytes(b"fake")
    assert _resolve_dll_path(dll) == dll


def test_resolve_dll_path_explicit_path_missing_raises() -> None:
    with pytest.raises(FileNotFoundError):
        _resolve_dll_path("Z:/does/not/exist/CelikApi.dll")


def test_resolve_dll_path_prefers_bundled_over_system(monkeypatch, tmp_path: Path) -> None:
    """Fixes the bug present in every prior Celik/*.py copy: they only
    ever tried the hardcoded system path, never a bundled copy sitting
    right next to the app."""
    import formalizator.reader.eid_reader as mod

    bundled_dir = tmp_path / "resources"
    bundled_dir.mkdir()
    bundled_dll = bundled_dir / "CelikApi.dll"
    bundled_dll.write_bytes(b"fake")

    monkeypatch.setattr(mod, "__file__", str(tmp_path / "reader" / "eid_reader.py"))
    # __file__'s parent.parent / "resources" / "CelikApi.dll" is what
    # _resolve_dll_path checks first — build tmp_path to match that shape.
    (tmp_path / "reader").mkdir(exist_ok=True)

    result = _resolve_dll_path(None)
    assert result == bundled_dll


def test_resolve_dll_path_none_found_raises_with_both_paths_mentioned(monkeypatch, tmp_path: Path) -> None:
    import formalizator.reader.eid_reader as mod

    monkeypatch.setattr(mod, "__file__", str(tmp_path / "reader" / "eid_reader.py"))
    monkeypatch.setattr(mod, "_SYSTEM_DLL_PATH", str(tmp_path / "nonexistent" / "CelikApi.dll"))

    with pytest.raises(FileNotFoundError):
        _resolve_dll_path(None)


def test_error_message_for_known_code() -> None:
    err = EidReaderError(-7, "Читање картице")
    assert "није убачена" in str(err)
    assert err.code == -7


def test_error_message_for_unknown_code_still_readable() -> None:
    err = EidReaderError(-999, "Нешто")
    assert "Непозната грешка" in str(err)
    assert "-999" in str(err)


def test_reader_unavailable_is_a_real_exception_type() -> None:
    assert issubclass(EidReaderUnavailable, Exception)


def test_portrait_bytes_above_127_convert_without_error() -> None:
    """Real JPEG data routinely contains bytes >=128 — EID_PORTRAIT.
    portrait must be unsigned (c_ubyte), not signed (c_byte), or
    bytes(portrait.portrait[:n]) raises ValueError on any such byte.
    Confirmed directly against real card hardware: read_card() crashed
    on this exact line every time a photo was present."""
    portrait = EID_PORTRAIT()
    portrait.portrait[0] = 200
    portrait.portrait[1] = 255
    portrait.portraitSize = 2

    result = bytes(portrait.portrait[: portrait.portraitSize])

    assert result == bytes([200, 255])
