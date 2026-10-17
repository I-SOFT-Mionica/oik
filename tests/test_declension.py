"""Tests for biracki_odbor.config.declension."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from biracki_odbor.config import declension


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch):
    """Point BIRACKI_ODBOR_HOME at a temp dir so the override file is sandboxed.

    Without this, tests would read/write the real user's places_genitive.json.
    """
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path))
    # Wipe the in-memory cache so each test gets a fresh load.
    declension._overrides_cache = None
    declension._overrides_cache_path = None
    declension._prepositions_cache = None
    declension._prepositions_cache_path = None
    yield


def test_plural_sr_one() -> None:
    for n in (1, 21, 31, 101, 121):
        assert declension.plural_sr(n, "грешка", "грешке", "грешака") == "грешка", n


def test_plural_sr_few() -> None:
    for n in (2, 3, 4, 22, 23, 24, 102, 103, 104):
        assert declension.plural_sr(n, "грешка", "грешке", "грешака") == "грешке", n


def test_plural_sr_many() -> None:
    for n in (0, 5, 6, 10, 11, 12, 13, 14, 15, 20, 25, 111, 112, 113, 114):
        assert declension.plural_sr(n, "грешка", "грешке", "грешака") == "грешака", n


def test_plural_sr_teens_are_many_not_few() -> None:
    """11-14 must be 'many' even though they end in 1-4 -- the classic
    Slavic-plural edge case (11 грешака, not 11 грешка/грешке)."""
    assert declension.plural_sr(11, "грешка", "грешке", "грешака") == "грешака"
    assert declension.plural_sr(12, "грешка", "грешке", "грешака") == "грешака"
    assert declension.plural_sr(13, "грешка", "грешке", "грешака") == "грешака"
    assert declension.plural_sr(14, "грешка", "грешке", "грешака") == "грешака"


def test_format_basic() -> None:
    assert declension.format_serbian_date(2023, 12, 17) == "17. децембар 2023. године"
    assert declension.format_serbian_date(2026, 5, 8) == "8. мај 2026. године"


def test_format_invalid_month() -> None:
    with pytest.raises(ValueError):
        declension.format_serbian_date(2026, 13, 1)
    with pytest.raises(ValueError):
        declension.format_serbian_date(2026, 0, 1)


def test_parse_nominative() -> None:
    assert declension.parse_serbian_date("17. децембар 2023. године") == (2023, 12, 17)
    assert declension.parse_serbian_date("8. мај 2026. године") == (2026, 5, 8)


def test_parse_genitive() -> None:
    # Legacy stored values used genitive — parser must accept them too.
    assert declension.parse_serbian_date("17. децембра 2023. године") == (2023, 12, 17)
    assert declension.parse_serbian_date("6. децембра 2023. године") == (2023, 12, 6)


def test_parse_unknown_returns_none() -> None:
    assert declension.parse_serbian_date("") is None
    assert declension.parse_serbian_date("not a date") is None
    assert declension.parse_serbian_date("17. фебру 2023.") is None  # month truncated


def test_round_trip_all_months() -> None:
    for month in range(1, 13):
        s = declension.format_serbian_date(2026, month, 15)
        assert declension.parse_serbian_date(s) == (2026, month, 15)


def test_place_to_genitive_consonant_ending() -> None:
    # Masculine consonant: add «а».
    assert declension.place_to_genitive("Уб") == "Уба"
    assert declension.place_to_genitive("Београд") == "Београда"
    assert declension.place_to_genitive("Ниш") == "Ниша"
    assert declension.place_to_genitive("Љиг") == "Љига"


def test_place_to_genitive_a_ending() -> None:
    # Feminine -а → -е.
    assert declension.place_to_genitive("Мионица") == "Мионице"
    assert declension.place_to_genitive("Лозница") == "Лознице"


def test_place_to_genitive_o_e_ending() -> None:
    # Neuter -о/-е → -а.
    assert declension.place_to_genitive("Ваљево") == "Ваљева"
    assert declension.place_to_genitive("Ужице") == "Ужица"


def test_place_to_genitive_ac_suffix_rule() -> None:
    # -ац fugitive vowel handled by the rule (no override needed).
    assert declension.place_to_genitive("Алексинац") == "Алексинца"
    assert declension.place_to_genitive("Аранђеловац") == "Аранђеловца"
    assert declension.place_to_genitive("Деспотовац") == "Деспотовца"
    assert declension.place_to_genitive("Крушевац") == "Крушевца"
    assert declension.place_to_genitive("Свилајнац") == "Свилајнца"


def test_place_to_genitive_compound_adjective_noun() -> None:
    # Compound names: first word declines as adjective, rest as nouns.
    assert declension.place_to_genitive("Сремска Митровица") == "Сремске Митровице"
    assert declension.place_to_genitive("Бачка Топола") == "Бачке Тополе"
    assert declension.place_to_genitive("Доњи Милановац") == "Доњег Милановца"
    assert declension.place_to_genitive("Нови Сад") == "Новог Сада"
    assert declension.place_to_genitive("Стара Пазова") == "Старе Пазове"
    assert declension.place_to_genitive("Велика Плана") == "Велике Плане"
    assert declension.place_to_genitive("Бели Поток") == "Белог Потока"


def test_place_to_genitive_seed_irregulars_from_user_file() -> None:
    # First call seeds the file with our irregulars (Шабац, Чачак).
    assert declension.place_to_genitive("Шабац") == "Шапца"
    assert declension.place_to_genitive("Чачак") == "Чачка"


def test_place_to_genitive_empty() -> None:
    assert declension.place_to_genitive("") == ""


# ── Case-insensitivity (field report: all-caps declension) ─────────────
#
# A party typed "МИОНИЦА" (all caps) into their submission's Место
# column. The rule functions' suffix checks (`word.endswith("а")`) are
# literal and case-sensitive, so the all-caps "А" matched none of them
# and fell through to the "+а" fallback, producing "МИОНИЦАа" — visibly
# garbled, and nothing like the correct "Мионице". Confirmed live.


def test_place_to_genitive_all_caps_declines_correctly() -> None:
    assert declension.place_to_genitive("МИОНИЦА") == "Мионице"
    assert declension.place_to_genitive("БЕОГРАД") == "Београда"
    assert declension.place_to_genitive("НОВИ САД") == "Новог Сада"


def test_place_to_genitive_lowercase_declines_correctly() -> None:
    assert declension.place_to_genitive("мионица") == "Мионице"


def test_place_to_genitive_mixed_case_declines_correctly() -> None:
    assert declension.place_to_genitive("МиОницА") == "Мионице"


def test_place_to_locative_all_caps_declines_correctly() -> None:
    assert declension.place_to_locative("МИОНИЦА") == "Мионици"
    assert declension.place_to_locative("НОВИ САД") == "Новом Саду"


def test_normalize_place_name_collapses_any_casing_to_one_canonical_form() -> None:
    for variant in ("МИОНИЦА", "мионица", "Мионица", "МиОницА"):
        assert declension.normalize_place_name(variant) == "Мионица"


def test_decline_noun_and_adjective_normalize_internally_not_just_via_place_to_genitive() -> None:
    """corrections.py's _PlacesPanel._rule_only_genitive (the "rule
    engine preview" column) calls _decline_noun/_decline_adjective
    DIRECTLY on raw tokens, bypassing place_to_genitive's own top-level
    normalize_place_name call entirely. If the fix only normalized at
    that top level, this call site would stay broken for all-caps input
    even though place_to_genitive itself tested fine — confirmed by
    temporarily removing just the internal normalize and watching only
    the locative half of this fix's tests fail, not the genitive half,
    because place_to_genitive's redundant top-level normalize was
    silently covering for it. Calling the low-level functions directly,
    the way _rule_only_genitive does, is the only way to catch that gap."""
    assert declension._decline_noun("МИОНИЦА") == "Мионице"  # noqa: SLF001
    assert declension._decline_adjective("НОВИ") == "Новог"  # noqa: SLF001


# ── User-file override layer ────────────────────────────────


def test_overrides_file_seeded_on_first_load(tmp_path: Path) -> None:
    """No file present → loading creates one populated from the seed."""
    from biracki_odbor import app_paths
    path = app_paths.places_genitive_path()
    assert not path.exists()
    overrides = declension.load_overrides()
    assert path.exists()
    # Seed entries are present.
    assert overrides["Шабац"] == "Шапца"
    assert overrides["Чачак"] == "Чачка"
    # Comment keys are stripped out.
    assert "_comment" not in overrides


def test_user_override_wins_over_rule_engine() -> None:
    # "Уб" → rule gives "Уба". User overrides → "Убу" for testing.
    declension.set_user_override("Уб", "Убу")
    assert declension.place_to_genitive("Уб") == "Убу"


def test_user_override_persists_to_file() -> None:
    from biracki_odbor import app_paths
    declension.set_user_override("Сврљиг", "Сврљига")
    raw = json.loads(app_paths.places_genitive_path().read_text(encoding="utf-8"))
    assert raw["Сврљиг"] == "Сврљига"


def test_set_user_override_normalizes_the_key() -> None:
    """Writing through an all-caps place must land under the canonical
    key, not fragment the file into per-casing duplicates."""
    from biracki_odbor import app_paths
    declension.set_user_override("МИОНИЦА", "Мионичкој вароши")
    raw = json.loads(app_paths.places_genitive_path().read_text(encoding="utf-8"))
    assert raw["Мионица"] == "Мионичкој вароши"
    assert "МИОНИЦА" not in raw


def test_load_overrides_normalizes_a_pre_existing_raw_key() -> None:
    """Migration case: a file written before normalization existed can
    hold a raw all-caps key (the Places panel used to group — and let
    the operator save an override for — "МИОНИЦА" as its own distinct
    place). A lookup for the now-canonical "Мионица" must still find
    it, or every such pre-existing override silently stops applying."""
    from biracki_odbor import app_paths
    path = app_paths.places_genitive_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"МИОНИЦА": "Мионичкој вароши"}), encoding="utf-8")

    overrides = declension.load_overrides(force=True)

    assert overrides["Мионица"] == "Мионичкој вароши"
    assert declension.place_to_genitive("Мионица") == "Мионичкој вароши"
    assert declension.place_to_genitive("МИОНИЦА") == "Мионичкој вароши"


def test_user_override_removal_falls_back_to_rule() -> None:
    declension.set_user_override("Уб", "Убу")
    assert declension.place_to_genitive("Уб") == "Убу"
    # Empty value removes the override.
    declension.set_user_override("Уб", "")
    assert declension.place_to_genitive("Уб") == "Уба"


def test_user_added_seed_value_can_be_overridden() -> None:
    # Even seeded irregulars can be replaced by the user.
    declension.set_user_override("Чачак", "Чачакuserforced")
    assert declension.place_to_genitive("Чачак") == "Чачакuserforced"


# ── Preposition layer ──────────────────────────────────────


def test_preposition_default_is_iz() -> None:
    # Out-of-the-box: a generic place uses "из".
    assert declension.place_preposition("Београд") == "из"
    assert declension.place_preposition("Мионица") == "из"
    assert declension.place_preposition("") == "из"


def test_preposition_seeded_sa_cases() -> None:
    # Mountains, plateaus, and the local-convention case all seed to "са".
    for place in ("Авала", "Космај", "Копаоник", "Златибор", "Тара",
                  "Цетиње", "Умка", "Уб", "Стара планина"):
        assert declension.place_preposition(place) == "са", (
            f"{place} should default to 'са' via the seed file"
        )


def test_set_user_preposition_writes_and_clears() -> None:
    declension.set_user_preposition("Жабаљ", "са")
    assert declension.place_preposition("Жабаљ") == "са"
    # Setting to "из" (the default) removes the entry rather than storing it.
    declension.set_user_preposition("Жабаљ", "из")
    assert declension.place_preposition("Жабаљ") == "из"


def test_set_user_preposition_overrides_seed() -> None:
    # User can flip a seeded "са" entry back to "из" if local convention
    # differs (e.g. somebody insists "из Уба" everywhere).
    declension.set_user_preposition("Уб", "из")
    assert declension.place_preposition("Уб") == "из"


def test_preposition_cache_invalidates_after_write() -> None:
    # Read once to warm cache.
    assert declension.place_preposition("ТестМесто") == "из"
    declension.set_user_preposition("ТестМесто", "са")
    # Set_user_preposition forces a reload; the cache must reflect the new value.
    assert declension.place_preposition("ТестМесто") == "са"


def test_prepositions_file_seeded_on_first_load() -> None:
    from biracki_odbor import app_paths
    path = app_paths.places_prepositions_path()
    assert not path.exists()
    declension.load_prepositions()
    assert path.exists()


def test_prepositions_corrupt_json_falls_back_to_seed() -> None:
    from biracki_odbor import app_paths
    path = app_paths.places_prepositions_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not valid json {", encoding="utf-8")
    # Force a reload — corrupt file gets handled silently and we still get
    # the seed defaults so the user isn't locked out.
    prepositions = declension.load_prepositions(force=True)
    assert prepositions.get("Авала") == "са"
