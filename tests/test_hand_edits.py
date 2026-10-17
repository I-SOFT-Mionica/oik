"""TODO §11: regenerating decisions must not silently overwrite ones the
operator edited in Word."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

from biracki_odbor.core.hand_edits import hand_edited, record_generated


def _gen(folder: Path, *names: str) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for n in names:
        p = folder / n
        p.write_bytes(f"generated {n}".encode())
        out.append(p)
    return out


def test_untouched_files_are_not_flagged(tmp_path) -> None:
    files = _gen(tmp_path, "БМ_01_STALNI.docx", "БМ_02_STALNI.docx")
    record_generated(tmp_path, files)
    assert hand_edited(tmp_path) == []


def test_edited_file_is_flagged(tmp_path) -> None:
    a, b = _gen(tmp_path, "БМ_01_STALNI.docx", "БМ_02_STALNI.docx")
    record_generated(tmp_path, [a, b])
    b.write_bytes(b"edited in Word")
    assert hand_edited(tmp_path) == [b]


def test_kept_file_stays_flagged_after_regeneration(tmp_path) -> None:
    a, b = _gen(tmp_path, "БМ_01_STALNI.docx", "БМ_02_STALNI.docx")
    record_generated(tmp_path, [a, b])
    b.write_bytes(b"edited in Word")
    # regeneration with "keep edited": generator rewrites both, the edit is put back
    _gen(tmp_path, "БМ_01_STALNI.docx", "БМ_02_STALNI.docx")
    b.write_bytes(b"edited in Word")
    record_generated(tmp_path, [a, b], keep={b.name})
    assert hand_edited(tmp_path) == [b]


def test_word_lock_files_are_ignored(tmp_path) -> None:
    (a,) = _gen(tmp_path, "БМ_01_STALNI.docx")
    record_generated(tmp_path, [a])
    (tmp_path / "~$_01_STALNI.docx").write_bytes(b"lock")
    assert hand_edited(tmp_path) == []


def test_files_from_before_the_manifest_use_the_generation_time(tmp_path) -> None:
    old, new = _gen(tmp_path, "БМ_01_STALNI.docx", "БМ_02_STALNI.docx")
    generated_at = datetime.now() - timedelta(hours=1)
    stamp = (generated_at - timedelta(minutes=1)).timestamp()
    os.utime(old, (stamp, stamp))  # untouched since generation
    assert hand_edited(tmp_path, generated_at.astimezone().isoformat()) == [new]


def test_phase3_keep_restores_the_edited_decision(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path / "home"))
    from biracki_odbor import app_paths
    from biracki_odbor.core.models import ValidationReport
    from biracki_odbor.core.phase3_docx import Phase3Result
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.phase3 import Phase3Tab
    state = AppState()
    state.app_settings.default_files_dir = str(tmp_path / "export")
    tab = Phase3Tab(state)
    folder = app_paths.resenja_dir_for(tab._spec)  # noqa: SLF001
    a, b = _gen(folder, "БМ_01_STALNI.docx", "БМ_02_STALNI.docx")
    record_generated(folder, [a, b])
    b.write_bytes(b"edited in Word")
    tab._preserved = {b: b.read_bytes()}  # operator chose "Keep edited"  # noqa: SLF001
    _gen(folder, "БМ_01_STALNI.docx", "БМ_02_STALNI.docx")  # the generator overwrote both
    tab._on_finished(Phase3Result(files_written=[a, b], report=ValidationReport()))  # noqa: SLF001
    assert b.read_bytes() == b"edited in Word"
    assert hand_edited(folder) == [b]
    tab.deleteLater()
