"""Serbian declension helpers — month genitives and election-type expansion.

Date forms used in решења follow the pattern:
    nominativ:  "17. децембар 2023. године"
    genitiv:    "17. децембра 2023. године"

The only thing that changes is the month name, so a simple lookup table
is enough. The program owns this; the user shouldn't have to type both forms.

Election types follow a canonical four-way taxonomy:
  - presidential  → "избора за председника Републике"
  - parliamentary → "избора за народне посланике Народне скупштине"
  - provincial    → "избора за посланике Скупштине Аутономне Покрајине Војводине"
  - local         → "избора за одборнике Скупштине општине {municipality}"

The municipality form for `local` uses the OIK `name` field (nominativ),
matching the existing convention in phase3_docx.
"""

from __future__ import annotations

import re


def plural_sr(n: int, one: str, few: str, many: str) -> str:
    """Pick the grammatically correct Serbian plural form for a count.

    Standard Slavic counting rule:
      - n ends in 1, but not 11        → `one`   (1, 21, 31, 101, ...)
      - n ends in 2-4, but not 12-14   → `few`   (2, 3, 4, 22, 23, 24, ...)
      - everything else                → `many`  (0, 5-20, 25-30, 11-14, ...)

    Field report: UI text used to interpolate the noun with a bare
    "(a)"/"/ke/ka" suffix hack (e.g. "{n} грешк(а)"), which isn't a real
    Serbian word for any n — this replaces that with the actual
    agreeing form so callers can build a grammatically correct sentence
    instead of a slash-delimited placeholder.
    """
    n_abs = abs(n)
    if n_abs % 10 == 1 and n_abs % 100 != 11:
        return one
    if 2 <= n_abs % 10 <= 4 and not (12 <= n_abs % 100 <= 14):
        return few
    return many


def count_word(
    n: int, ui_language: str,
    en_one: str, en_other: str,
    sr_one: str, sr_few: str, sr_many: str,
) -> str:
    """Pick the correctly-agreeing noun for `n`, in whichever language is
    currently displayed (`AppSettings.ui_language`, "sr" or "en").

    English only distinguishes one/other; Serbian needs the full
    one/few/many split (see `plural_sr`) -- this is the single place
    that reconciles the two so callers building a `{n} {word}` sentence
    don't have to special-case the language themselves.
    """
    if ui_language == "sr":
        return plural_sr(n, sr_one, sr_few, sr_many)
    return en_one if n == 1 else en_other


_MONTH_NOMINATIVE: tuple[str, ...] = (
    "јануар", "фебруар", "март", "април", "мај", "јун",
    "јул", "август", "септембар", "октобар", "новембар", "децембар",
)

_MONTH_GENITIVE: dict[str, str] = {
    "јануар": "јануара",
    "фебруар": "фебруара",
    "март": "марта",
    "април": "априла",
    "мај": "маја",
    "јун": "јуна",
    "јул": "јула",
    "август": "августа",
    "септембар": "септембра",
    "октобар": "октобра",
    "новембар": "новембра",
    "децембар": "децембра",
}

# Lowercase month → 1-based index, for reverse parsing.
_MONTH_INDEX_NOM: dict[str, int] = {m: i + 1 for i, m in enumerate(_MONTH_NOMINATIVE)}
_MONTH_INDEX_GEN: dict[str, int] = {
    g: i + 1 for i, g in enumerate(_MONTH_GENITIVE[m] for m in _MONTH_NOMINATIVE)
}

# Used by reverse-lookup to extract year from "17. децембар 2023. године".
_YEAR_RE = re.compile(r"\b(\d{4})\b")
# Day at the start (e.g. "17." or "17 ").
_DAY_RE = re.compile(r"\b(\d{1,2})\b")


def format_serbian_date(year: int, month: int, day: int) -> str:
    """Format a date the way the решења expect: '17. децембар 2023. године'.

    Raises ValueError on out-of-range month.
    """
    if month < 1 or month > 12:
        raise ValueError(f"month out of range: {month}")
    return f"{day}. {_MONTH_NOMINATIVE[month - 1]} {year}. године"


def parse_serbian_date(text: str) -> tuple[int, int, int] | None:
    """Reverse of `format_serbian_date`. Returns (year, month, day) or None.

    Accepts either the nominative form ("17. децембар 2023. године") or the
    genitive form ("17. децембра 2023. године") for forward-compatibility
    with legacy stored values.
    """
    if not text:
        return None
    s = text.strip().lower()
    # Year and day are pure digits; month is the Cyrillic word.
    year_m = _YEAR_RE.search(s)
    day_m = _DAY_RE.search(s)
    if year_m is None or day_m is None:
        return None
    try:
        year = int(year_m.group(1))
        day = int(day_m.group(1))
    except ValueError:
        return None
    month = None
    for tok in s.replace(".", " ").replace(",", " ").split():
        if tok in _MONTH_INDEX_NOM:
            month = _MONTH_INDEX_NOM[tok]
            break
        if tok in _MONTH_INDEX_GEN:
            month = _MONTH_INDEX_GEN[tok]
            break
    if month is None:
        return None
    if not (1 <= day <= 31):
        return None
    return year, month, day


def to_genitive(date_full: str) -> str:
    """Convert a Cyrillic nominative date into its genitive form.

    Example: '17. децембар 2023. године' -> '17. децембра 2023. године'
    Unknown formats are returned unchanged.
    """
    parts = date_full.split()
    for i, p in enumerate(parts):
        stripped = p.rstrip(".,")
        gen = _MONTH_GENITIVE.get(stripped.lower())
        if gen is None:
            continue
        # Preserve any trailing punctuation that was on the original token.
        tail = p[len(stripped):]
        parts[i] = gen + tail
        break
    return " ".join(parts)


def year_from(date_full: str) -> str:
    """Pull the 4-digit year out of a Cyrillic date string.

    Returns '' if no 4-digit number is present.
    """
    m = _YEAR_RE.search(date_full)
    return m.group(1) if m else ""


# ── Election types ───────────────────────────────────────────────────────

TYPE_KEYS = ("presidential", "parliamentary", "provincial", "local")

TYPE_LABELS: dict[str, str] = {
    "presidential": "Председнички избори",
    "parliamentary": "Парламентарни избори",
    "provincial": "Покрајински избори",
    "local": "Локални избори",
}

_TYPE_TEMPLATES: dict[str, str] = {
    "presidential": "избора за председника Републике",
    "parliamentary": "избора за народне посланике Народне скупштине",
    "provincial": "избора за посланике Скупштине Аутономне Покрајине Војводине",
    "local": "избора за одборнике {assembly}",
}


def expand_type(key: str, municipality_name: str, local_assembly: str = "") -> str:
    """Return the full lowercase 'избора за …' form for a type key.

    `local_assembly` is the unit's assembly in the genitive
    (config.commission.CommissionTerms.local_assembly, e.g. "Скупштине
    града Ваљева"); without it the municipality form is used.

    If `key` is not one of the canonical keys, returns the key itself
    unchanged — lets legacy free-text types continue to work.
    """
    tmpl = _TYPE_TEMPLATES.get(key)
    if tmpl is None:
        return key
    assembly = local_assembly or f"Скупштине општине {municipality_name}"
    return tmpl.format(assembly=assembly)


def expand_types(
    keys: list[str], municipality_name: str, local_assembly: str = "",
) -> list[tuple[str, str]]:
    """Map a list of type keys to (lowercase, UPPERCASE) tuples for use in решења."""
    out: list[tuple[str, str]] = []
    for k in keys:
        lower = expand_type(k, municipality_name, local_assembly)
        out.append((lower, lower.upper()))
    return out


# Reverse lookup: detect what canonical key a stored full-text type matches,
# so we can migrate existing election_config.json files.
_REVERSE_MARKERS: list[tuple[str, str]] = [
    ("председника Републике", "presidential"),
    ("народне посланике", "parliamentary"),
    ("Аутономне Покрајине", "provincial"),
    ("одборнике Скупштине", "local"),
]


def detect_key(full_text: str) -> str | None:
    """Reverse-classify a stored type string into a canonical key.

    Returns None if no marker matches — caller should keep the original
    string as a custom-typed entry.
    """
    for marker, key in _REVERSE_MARKERS:
        if marker in full_text:
            return key
    return None


# ── Place-name genitive (for "из {place}") ──────────────────────────────
#
# Layered resolution: user-file overrides win → rule engine.
# The user file is seeded with `_SEED_OVERRIDES` on first run (CMS-style
# "demo content"), then is owned by the user — never overwritten by us.


def normalize_place_name(place: str) -> str:
    """Canonical Title-Case-per-word form of a place name.

    Field report: a party typed "МИОНИЦА" (all caps) into their Excel
    submission; the declension rule functions below do case-sensitive
    suffix matching (`word.endswith("а")`), so the all-caps "А" matched
    nothing and fell through to the dumb "+а" fallback, producing the
    garbled "МИОНИЦАа". Worse, the Places panel groups by the raw
    string, so "МИОНИЦА" and "Мионица" showed as two separate places
    needing two separate overrides instead of one.

    `str.capitalize()` is Unicode-aware and handles Cyrillic correctly,
    so this collapses any casing a party might have typed — ALL CAPS,
    lowercase, mixed — to the one canonical form every lookup (rule
    engine, override file, Places panel grouping) agrees on.
    """
    return " ".join(w.capitalize() for w in place.strip().split())

import json
import logging
from pathlib import Path

# Irregulars the rule engine can't derive. The seed is written to the user
# file on first run. After that the user owns the file; add entries here
# only if you want them to ship to fresh installs.
_SEED_OVERRIDES: dict[str, str] = {
    # Voicing assimilation (-бц → -пц) — rule engine can't see this
    "Шабац": "Шапца",
    # -ак fugitive vowel — rule engine doesn't cover -ак reliably
    "Чачак": "Чачка",
}

_log = logging.getLogger(__name__)

# In-memory cache. Cleared when the file is rewritten via set_user_override.
_overrides_cache: dict[str, str] | None = None
_overrides_cache_path: Path | None = None


def _overrides_file_path() -> Path:
    """Return path to the user override JSON; defer import to avoid cycles."""
    from biracki_odbor import app_paths
    return app_paths.places_genitive_path()


def _seed_overrides_file(path: Path) -> None:
    """Write the seed dict to `path`, including helper comments via _* keys."""
    payload: dict[str, str] = {
        "_comment": (
            "Корисничка датотека за изузетке у падежу места. "
            "Аутоматска правила покривају већину градова; додајте овде само "
            "случајеве где правила греше. Кључеви који почињу са '_' се игноришу."
        ),
        "_format": "\"Место (номинатив)\": \"Места (генитив)\"",
        **_SEED_OVERRIDES,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    _log.info("seeded places_genitive overrides at %s", path)


def load_overrides(force: bool = False) -> dict[str, str]:
    """Read the user override file, seeding it on first run.

    Cached per-path; pass `force=True` after writes to invalidate.

    Keys are normalized (see `normalize_place_name`) on the way in, not
    just on the way out at lookup time — a file saved before that
    normalization existed can hold a raw key like "МИОНИЦА" from the
    Places panel grouping it as its own distinct place; without
    normalizing here too, a lookup for the now-canonical "Мионица"
    would stop matching that old entry entirely. Two raw keys that
    normalize to the same place (an old-data edge case) resolve to
    whichever the file lists last — not worth a conflict UI for.
    """
    global _overrides_cache, _overrides_cache_path
    path = _overrides_file_path()
    if not force and _overrides_cache is not None and _overrides_cache_path == path:
        return _overrides_cache
    if not path.exists():
        _seed_overrides_file(path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        _log.warning("could not read %s (%s) — falling back to seed", path, e)
        raw = dict(_SEED_OVERRIDES)
    overrides = {
        normalize_place_name(k): v
        for k, v in raw.items() if not k.startswith("_") and isinstance(v, str)
    }
    _overrides_cache = overrides
    _overrides_cache_path = path
    return overrides


def set_user_override(place: str, genitive: str) -> None:
    """Add or replace one entry in the user file.

    Passing an empty `genitive` removes the entry (lets the rule engine
    take over again).
    """
    place = normalize_place_name(place)
    if not place:
        return
    path = _overrides_file_path()
    if not path.exists():
        _seed_overrides_file(path)
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if genitive.strip():
        payload[place] = genitive.strip()
    else:
        payload.pop(place, None)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    load_overrides(force=True)


def _decline_noun(word: str) -> str:
    """Apply genitive rules to a noun-shaped token.

    Rule order matters: -ац is checked before generic consonant ending
    because the fugitive «а» drop is mechanical for -ац suffixes.

    Normalizes casing first — see `normalize_place_name` — so ALL-CAPS
    or lowercase input still matches the (lowercase-literal) suffix
    checks below instead of silently falling through every one of them.
    """
    word = normalize_place_name(word)
    if word.endswith("ац"):
        # Алексинац → Алексинца, Аранђеловац → Аранђеловца, Свилајнац → Свилајнца
        return word[:-2] + "ца"
    if word.endswith("а"):
        return word[:-1] + "е"
    if word.endswith(("о", "е")):
        return word[:-1] + "а"
    return word + "а"


def _decline_adjective(word: str) -> str:
    """Apply genitive rules to an adjective-shaped token.

    Used for the leading word in compound toponyms (Сремска Митровица,
    Доњи Милановац, Нови Сад). Standalone tokens always go through
    `_decline_noun`.

    Normalizes casing first — see `_decline_noun`'s docstring; same
    case-sensitive-suffix problem, same fix.
    """
    word = normalize_place_name(word)
    if word.endswith("њи"):  # Доњи → Доњег, Горњи → Горњег
        return word[:-2] + "њег"
    if word.endswith("ње"):  # Доње → Доњег (neuter palatal)
        return word[:-2] + "њег"
    if word.endswith("ња"):  # Доња → Доње (feminine palatal)
        return word[:-2] + "ње"
    if word.endswith("и"):   # Нови → Новог, Стари → Старог, Бели → Белог
        return word[:-1] + "ог"
    if word.endswith("а"):   # Сремска → Сремске, Бачка → Бачке
        return word[:-1] + "е"
    if word.endswith("о"):   # Бело → Белог (neuter adjective)
        return word[:-1] + "ог"
    return word + "ог"


def place_to_genitive(place: str) -> str:
    """Approximate Serbian genitive of a place name.

    Resolution order:
      1. User override file (`<BIRACKI_ODBOR_HOME>/places_genitive.json`).
      2. Rule engine:
         • Compound (multi-token) → first word as adjective, rest as nouns.
         • Single word → noun rules: -ац→-ца, -а→-е, -о/-е→-а, consonant→+а.

    Empty input passes through unchanged.
    """
    if not place:
        return place
    stripped = normalize_place_name(place)
    overrides = load_overrides()
    if stripped in overrides:
        return overrides[stripped]
    tokens = stripped.split()
    if len(tokens) >= 2:
        first = _decline_adjective(tokens[0])
        rest = [_decline_noun(t) for t in tokens[1:]]
        return " ".join([first] + rest)
    return _decline_noun(stripped)


# ── Place-name locative (for "у општини {place}") ───────────────────────


def _decline_noun_locative(word: str) -> str:
    word = normalize_place_name(word)
    if word.endswith("ац"):
        return word[:-2] + "цу"
    if word.endswith("а"):
        return word[:-1] + "и"
    if word.endswith(("о", "е")):
        return word[:-1] + "у"
    return word + "у"


def _decline_adjective_locative(word: str) -> str:
    word = normalize_place_name(word)
    if word.endswith("њи"):
        return word[:-2] + "њем"
    if word.endswith("ње"):
        return word[:-2] + "њем"
    if word.endswith("ња"):
        return word[:-2] + "њој"
    if word.endswith("и"):
        return word[:-1] + "ом"
    if word.endswith("а"):
        return word[:-1] + "ој"
    if word.endswith("о"):
        return word[:-1] + "ом"
    return word + "ом"


def place_to_locative(place: str) -> str:
    """Approximate Serbian locative of a place name (for 'у општини …').

    Rule-engine only — no user-override file. Users can correct the result
    directly in the form (setup wizard) or in OIK Settings.

    Examples: Мионица → Мионици, Уб → Убу, Ваљево → Ваљеву,
              Нови Сад → Новом Саду, Сремска Митровица → Сремској Митровици.
    """
    if not place:
        return place
    stripped = place.strip()
    tokens = stripped.split()
    if len(tokens) >= 2:
        first = _decline_adjective_locative(tokens[0])
        rest = [_decline_noun_locative(t) for t in tokens[1:]]
        return " ".join([first] + rest)
    return _decline_noun_locative(stripped)


# ── Preposition layer ("из {place}" vs "са {place}") ─────────────────────
#
# Default is "из". A small set of toponyms takes "са" by convention —
# mostly elevations (mountains, plateaus) plus a handful of regional cases.
# Same CMS-style seed pattern as places_genitive: written once, then user-
# owned. See `feedback_customization_pattern` memory for the principle.

_PREPOSITION_SEED: dict[str, str] = {
    # Mountains / hills
    "Авала": "са",
    "Космај": "са",
    "Копаоник": "са",
    "Златибор": "са",
    "Дивчибаре": "са",
    "Тара": "са",
    "Цер": "са",
    "Букуља": "са",
    "Маљен": "са",
    "Рудник": "са",
    "Стара планина": "са",
    # Elevated settlements
    "Цетиње": "са",
    "Умка": "са",
    # Local convention
    "Уб": "са",
}

DEFAULT_PREPOSITION = "из"

# Separate in-memory cache so preposition reads don't interfere with the
# genitive override cache above.
_prepositions_cache: dict[str, str] | None = None
_prepositions_cache_path: Path | None = None


def _prepositions_file_path() -> Path:
    from biracki_odbor import app_paths
    return app_paths.places_prepositions_path()


def _seed_prepositions_file(path: Path) -> None:
    payload: dict[str, str] = {
        "_comment": (
            "Корисничка датотека за изузетке у предлогу пред местом становања. "
            "Подразумевано је 'из', а уноси овде преписују са 'са'. "
            "Кључеви који почињу са '_' се игноришу."
        ),
        "_format": "\"Место (номинатив)\": \"са\" или \"из\"",
        **_PREPOSITION_SEED,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    _log.info("seeded places_prepositions overrides at %s", path)


def load_prepositions(force: bool = False) -> dict[str, str]:
    """Read the user preposition file, seeding it on first run.

    Keys normalized on the way in — see `load_overrides`' docstring,
    same reasoning applies to this file.
    """
    global _prepositions_cache, _prepositions_cache_path
    path = _prepositions_file_path()
    if not force and _prepositions_cache is not None and _prepositions_cache_path == path:
        return _prepositions_cache
    if not path.exists():
        _seed_prepositions_file(path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        _log.warning("could not read %s (%s) — falling back to seed", path, e)
        raw = dict(_PREPOSITION_SEED)
    overrides = {
        normalize_place_name(k): v for k, v in raw.items()
        if not k.startswith("_") and isinstance(v, str) and v.strip()
    }
    _prepositions_cache = overrides
    _prepositions_cache_path = path
    return overrides


def set_user_preposition(place: str, preposition: str) -> None:
    """Add or replace one preposition entry. Empty `preposition` removes the
    entry (falls back to the default "из")."""
    place = normalize_place_name(place)
    if not place:
        return
    path = _prepositions_file_path()
    if not path.exists():
        _seed_prepositions_file(path)
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    prep = preposition.strip()
    if prep and prep != DEFAULT_PREPOSITION:
        payload[place] = prep
    else:
        payload.pop(place, None)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    load_prepositions(force=True)


def place_preposition(place: str) -> str:
    """Return the right preposition for "{prep} {place_genitive}".

    "из" for most places; "са" for the curated set (mountains, plateaus,
    Уб by local convention). Empty input returns the default.
    """
    if not place:
        return DEFAULT_PREPOSITION
    overrides = load_prepositions()
    return overrides.get(normalize_place_name(place), DEFAULT_PREPOSITION)
