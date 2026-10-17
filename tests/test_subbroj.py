"""Tests for the sub-broj-per-BM «Број» format on Phase 3.

The municipal archive issues a single base number per election cycle
(e.g. `013-5-30`); every document OIK writes after that claims a
sub-broj sequentially. Phase 3 now lets the operator set a starting
sub-broj + separator on the «Број решења» card and produces
`{prefix}{sep}{start + bm_offset}/{year}` per resenja.

Tests cover:
  - the pure `format_broj` helper across configured / empty / non-numeric
    `subbroj_start` values,
  - separator override,
  - ElectionDates.subbroj_* fields round-trip through to_dict/from_dict.
"""

from __future__ import annotations

from biracki_odbor.config.election import (
    DocumentInfo, ElectionConfig, ElectionDates, ElectionInfo,
)
from biracki_odbor.core.phase3_docx import format_broj


def _make_election(
    *,
    prefix: str = "013-5-30",
    date_full: str = "17. децембар 2026. године",
    subbroj_start: str = "200",
    subbroj_separator: str = "-",
) -> ElectionConfig:
    return ElectionConfig(
        election=ElectionInfo(dates=ElectionDates(
            date_full=date_full,
            subbroj_start=subbroj_start,
            subbroj_separator=subbroj_separator,
        )),
        document=DocumentInfo(number_prefix=prefix),
    )


def test_format_broj_increments_per_bm_offset() -> None:
    """The first BM (offset 0) lands on the start value; the next
    BM on start + 1; …. That's the entire contract of the feature —
    municipal archive sees sequential numbers."""
    ec = _make_election(subbroj_start="200")
    assert format_broj(ec, 1, 0) == "Број: 013-5-30-200/2026"
    assert format_broj(ec, 2, 1) == "Број: 013-5-30-201/2026"
    assert format_broj(ec, 42, 41) == "Број: 013-5-30-241/2026"


def test_format_broj_separator_override() -> None:
    """The OIK that uses `/` for sub-broj rather than `-` (Belgrade
    convention vs the `-` Uб uses) must produce the slash form."""
    ec = _make_election(subbroj_separator="/")
    assert format_broj(ec, 1, 0) == "Број: 013-5-30/200/2026"


def test_format_broj_falls_back_to_legacy_when_start_empty() -> None:
    """Empty `subbroj_start` means the OIK hasn't configured the new
    flow — keep the original `{prefix}-{bm}/{year}` format so existing
    election_config.json files don't change behavior on upgrade."""
    ec = _make_election(subbroj_start="")
    assert format_broj(ec, 1, 0) == "Број: 013-5-30-1/2026"
    assert format_broj(ec, 5, 4) == "Број: 013-5-30-5/2026"


def test_format_broj_handles_non_numeric_start() -> None:
    """An operator who typed letters into the starting-subbroj field
    (rare; defensive) must not get a confusing «013-5-30-abc/2026»
    rendering — fall back to legacy format instead."""
    ec = _make_election(subbroj_start="abc")
    assert format_broj(ec, 3, 2) == "Број: 013-5-30-3/2026"


def test_election_dates_subbroj_round_trip() -> None:
    """to_dict + from_dict must preserve subbroj_start + subbroj_separator
    exactly, so the operator's pick survives app restarts."""
    d = ElectionDates(
        date_full="17. децембар 2026. године",
        subbroj_start="500", subbroj_separator="/",
    )
    rt = ElectionDates.from_dict(d.to_dict())
    assert rt.subbroj_start == "500"
    assert rt.subbroj_separator == "/"


def test_election_dates_subbroj_separator_defaults_to_hyphen() -> None:
    """Legacy election_config.json files won't have subbroj_separator.
    The loader must default to `-` (Uб convention) rather than empty
    so the rendered broj never produces `013-5-30200/2026`."""
    rt = ElectionDates.from_dict({"date_full": "17. децембар 2026. године"})
    assert rt.subbroj_separator == "-"
    assert rt.subbroj_start == ""
