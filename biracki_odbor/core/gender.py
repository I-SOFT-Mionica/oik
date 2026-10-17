"""Best-effort gender inference from a Serbian first name.

Used as one half of the JMBG-vs-name cross-check (the other half lives
in `core.jmbg.gender`). The rule is a simple morphology heuristic:

  - Names ending in «а» are usually female (Ана, Маја, Софија, Ивана…).
  - Names ending in a consonant or «о»/«е» are usually male
    (Марко, Стефан, Бранко, Душан, Михајло, Огњен…).
  - Exception list: a handful of common male names that end in «а»
    (Никола, Лука, Илија, Андрија, Алекса, Матија, Сава, Јеремија, Тома,
    Захарија, Зарија). These break the suffix rule.

This is intentionally lightweight — not a full name dictionary. Returns
None on empty/unclear input so the caller can downgrade to "undetermined"
rather than emit a false positive.
"""

from __future__ import annotations


# Male names that end in «а» — the suffix rule would otherwise mislabel them.
#
# Sourced from Wikipedia's [Category:Serbian masculine given names]
# (https://en.wikipedia.org/wiki/Category:Serbian_masculine_given_names),
# filtered to entries whose Cyrillic form ends in -а. Sorted alphabetically.
# Add new entries here as users report names not yet covered.
_MALE_A_ENDING: frozenset[str] = frozenset({
    "Алекса",
    "Андреја",
    "Андрија",
    "Анђелка",       # rare male form; defensive
    "Влада",
    "Владета",
    "Вања",
    "Васа",
    "Велиша",
    "Вукота",
    "Гаврила",
    "Добрица",
    "Дражета",
    "Ђока",
    "Ђура",
    "Живота",
    "Ивица",
    "Илија",
    "Јеремија",
    "Јовица",
    "Коста",
    "Лука",
    "Љуба",
    "Матеја",
    "Матија",
    "Милета",
    "Мита",
    "Немања",
    "Никодија",
    "Никола",
    "Новица",
    "Паја",
    "Перица",
    "Периша",
    "Радиша",
    "Радоња",
    "Реља",
    "Сава",
    "Саша",
    "Синиша",
    "Славиша",
    "Станиша",
    "Страхиња",
    "Тадија",
    "Тома",
    "Угљеша",
    "Захарија",
    "Зарија",
    # Defensive — non-«а» endings; left here so a name in this set is
    # always treated as male regardless of suffix.
    "Аћим",
    "Атанасије",
    "Михаила",       # masculine variant of Михаило
})


def infer_from_first_name(first_name: str) -> str | None:
    """Return "M", "F", or None when the first name is empty/ambiguous.

    Multi-token first names (e.g. "Ана Марија") inspect the FIRST token
    for the suffix signal — that's the head word in Serbian compound
    first names.
    """
    if not first_name:
        return None
    head = first_name.strip().split()[0] if first_name.strip() else ""
    if not head:
        return None
    # Title-case for the exception-list lookup (the list uses canonical case).
    normalized = head[:1].upper() + head[1:].lower() if len(head) > 1 else head.upper()
    if normalized in _MALE_A_ENDING:
        return "M"
    last_char = head[-1].lower()
    if last_char == "а":
        return "F"
    return "M"
