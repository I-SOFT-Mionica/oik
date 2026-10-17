"""Guided-tour sample data: Phase 1 party files filled with fictional
people must pass the normal import unchanged, fill every slot with a
valid adult JMBG, and contain the promised cross-party conflicts."""

from __future__ import annotations

from collections import Counter
from datetime import date
from pathlib import Path

from biracki_odbor.config.election import ElectionConfig
from biracki_odbor.core import jmbg as jmbg_mod
from biracki_odbor.core.phase1_generate import generate_party_files
from biracki_odbor.core.popunjeni_io import import_file, parse_party_file
from biracki_odbor.core.sample_fill import fill_party_files
from tests.fixtures.stalni_sastav import build_template
from tests.test_phase1 import _make_oik


def _party_files(tmp_path: Path) -> tuple[list[Path], ElectionConfig]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    template = build_template(tmp_path / "t.xlsx", n_polling_stations=3, parties=("СНС", "СПС", "ДС"))
    election = ElectionConfig()
    election.election_uuid = "tour-test"
    res = generate_party_files(template, tmp_path / "stranke", _make_oik(3), election=election, run_ts=1)
    return res.files_written, election


def test_every_slot_filled_with_a_valid_adult(tmp_path) -> None:
    files, _ = _party_files(tmp_path)
    filled = fill_party_files(files, place="Мионица")
    people = [p for f in files for _, p in parse_party_file(f)[0]]
    assert filled == len(people) > 0
    for p in people:
        assert p.first_name and p.last_name and p.mesto == "Мионица"
        assert jmbg_mod.is_valid(p.jmbg), p.jmbg
        assert jmbg_mod.is_at_least_18_on(p.jmbg, date(2026, 1, 1))


def test_contains_cross_party_conflicts(tmp_path) -> None:
    files, _ = _party_files(tmp_path)
    fill_party_files(files, place="Мионица", conflicts=2)
    by_jmbg = Counter(p.jmbg for f in files for _, p in parse_party_file(f)[0])
    assert sum(1 for n in by_jmbg.values() if n > 1) == 2


def test_filled_files_pass_the_normal_import(tmp_path) -> None:
    files, election = _party_files(tmp_path)
    fill_party_files(files, place="Мионица")
    for f in files:
        outcome = import_file(f, election, tmp_path / "popunjeni", phase1_run_ts=1)
        assert outcome.status == "imported", outcome.issue and outcome.issue.message_sr


def test_same_seed_same_people(tmp_path) -> None:
    a, _ = _party_files(tmp_path / "a")
    b, _ = _party_files(tmp_path / "b")
    fill_party_files(a, place="Уб")
    fill_party_files(b, place="Уб")
    names = lambda fs: [(p.first_name, p.jmbg) for f in fs for _, p in parse_party_file(f)[0]]  # noqa: E731
    assert names(a) == names(b)
