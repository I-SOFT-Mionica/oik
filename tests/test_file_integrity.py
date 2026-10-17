"""Tests for core.file_integrity — tamper/corruption detection for
load-bearing internal .xlsx files (Stalni_sastav.xlsx, master.xlsx,
nacelnik_sablion.xlsx)."""

from __future__ import annotations

from pathlib import Path

import pytest

from biracki_odbor.core.file_integrity import (
    IntegrityMismatchError,
    check_or_raise,
    compute_hash,
    has_verified_copy,
    record_verified,
    restore_verified,
)


def test_compute_hash_is_stable_for_same_content(tmp_path: Path) -> None:
    f = tmp_path / "a.xlsx"
    f.write_bytes(b"hello world")
    assert compute_hash(f) == compute_hash(f)


def test_compute_hash_differs_for_different_content(tmp_path: Path) -> None:
    f1 = tmp_path / "a.xlsx"
    f1.write_bytes(b"hello world")
    f2 = tmp_path / "b.xlsx"
    f2.write_bytes(b"goodbye world")
    assert compute_hash(f1) != compute_hash(f2)


def test_check_or_raise_ok_after_record_verified(tmp_path: Path) -> None:
    f = tmp_path / "Stalni_sastav.xlsx"
    f.write_bytes(b"PK\x03\x04 fake xlsx content")
    record_verified(f)
    check_or_raise(f)  # must not raise


def test_check_or_raise_no_baseline_bootstraps_silently(tmp_path: Path) -> None:
    """A file with no prior fingerprint (feature just rolled out, or an
    existing install upgrading) must not be treated as tampered — it
    silently establishes a baseline instead of blocking."""
    f = tmp_path / "Stalni_sastav.xlsx"
    f.write_bytes(b"PK\x03\x04 fake xlsx content")
    check_or_raise(f)  # must not raise
    assert has_verified_copy(f)


def test_check_or_raise_missing_file_is_a_noop(tmp_path: Path) -> None:
    """A file that doesn't exist yet (e.g. template never imported) is
    not this module's concern — callers already handle 'not configured'
    separately."""
    f = tmp_path / "does_not_exist.xlsx"
    check_or_raise(f)  # must not raise


def test_check_or_raise_detects_mismatch(tmp_path: Path) -> None:
    f = tmp_path / "master.xlsx"
    f.write_bytes(b"original content")
    record_verified(f)

    # Simulate an out-of-band modification (tampering, corruption, a
    # ransomware pass, or just a manual edit outside the app).
    f.write_bytes(b"modified content, not through the app")

    with pytest.raises(IntegrityMismatchError) as exc_info:
        check_or_raise(f)
    assert exc_info.value.path == f
    assert exc_info.value.verified_at


def test_check_or_raise_ok_after_legitimate_rewrite_and_reverify(tmp_path: Path) -> None:
    """A legitimate app-driven rewrite followed by re-recording must
    clear any prior mismatch state — this is the normal Phase 2 /
    Save-changes / template-re-import flow, not tampering."""
    f = tmp_path / "master.xlsx"
    f.write_bytes(b"v1")
    record_verified(f)

    f.write_bytes(b"v2 - a real app write")
    record_verified(f)  # the app's own write path re-records immediately

    check_or_raise(f)  # must not raise


def test_restore_verified_recovers_last_known_good(tmp_path: Path) -> None:
    f = tmp_path / "master.xlsx"
    f.write_bytes(b"good content")
    record_verified(f)

    f.write_bytes(b"corrupted!!")
    assert restore_verified(f) is True
    assert f.read_bytes() == b"good content"
    check_or_raise(f)  # restored content must pass verification again


def test_restore_verified_returns_false_without_prior_snapshot(tmp_path: Path) -> None:
    f = tmp_path / "master.xlsx"
    f.write_bytes(b"content, never verified")
    assert restore_verified(f) is False
    # File must be untouched — no-op on failure.
    assert f.read_bytes() == b"content, never verified"


def test_has_verified_copy_false_before_any_record(tmp_path: Path) -> None:
    f = tmp_path / "master.xlsx"
    f.write_bytes(b"content")
    assert not has_verified_copy(f)


def test_record_verified_overwrites_prior_snapshot(tmp_path: Path) -> None:
    """Each verified write must replace the previous snapshot, not
    accumulate — otherwise `.verified/` grows unbounded and restore
    could silently bring back stale, no-longer-current content."""
    f = tmp_path / "master.xlsx"
    f.write_bytes(b"v1")
    record_verified(f)
    f.write_bytes(b"v2")
    record_verified(f)

    f.write_bytes(b"tampered")
    assert restore_verified(f) is True
    assert f.read_bytes() == b"v2"


def test_corrupt_sidecar_is_treated_as_no_baseline(tmp_path: Path) -> None:
    """A malformed fingerprint sidecar (partial write, disk error) must
    not itself become a permanent false-positive tamper alarm."""
    f = tmp_path / "master.xlsx"
    f.write_bytes(b"content")
    verified_dir = tmp_path / ".verified"
    verified_dir.mkdir()
    (verified_dir / "master.xlsx.json").write_text("{not valid json", encoding="utf-8")

    check_or_raise(f)  # must not raise — re-establishes a clean baseline
    check_or_raise(f)  # and now a real baseline exists and still passes
