"""Tests for biracki_odbor.core.gender (first-name gender inference)."""

from __future__ import annotations

import pytest

from biracki_odbor.core import gender


@pytest.mark.parametrize("name", [
    "Ана", "Маја", "Софија", "Ивана", "Драгана", "Јелена", "Милица",
    "Маријана", "Сања", "Тамара", "Снежана", "Биљана",
])
def test_a_ending_female(name: str) -> None:
    assert gender.infer_from_first_name(name) == "F"


@pytest.mark.parametrize("name", [
    "Марко", "Стефан", "Душан", "Бранко", "Михајло", "Александар",
    "Петар", "Урош", "Огњен", "Милан", "Слободан", "Драган", "Зоран",
])
def test_consonant_or_neuter_male(name: str) -> None:
    assert gender.infer_from_first_name(name) == "M"


@pytest.mark.parametrize("name", [
    # The pre-existing handful that the original heuristic shipped with.
    "Никола", "Лука", "Илија", "Андрија", "Алекса", "Матија", "Сава",
    "Јеремија", "Тома", "Захарија", "Зарија",
    # Added in v0.4.1 from Wikipedia's Serbian-masculine-given-names
    # category — every -а-ending masculine name we could source.
    "Немања", "Андреја", "Добрица", "Дражета", "Ивица", "Јовица",
    "Коста", "Љуба", "Матеја", "Милета", "Никодија", "Новица",
    "Периша", "Радиша", "Радоња", "Реља", "Саша", "Синиша",
    "Славиша", "Станиша", "Страхиња", "Тадија", "Угљеша", "Вања",
    "Васа", "Влада", "Владета", "Вукота", "Живота",
])
def test_male_exception_list_overrides_a_suffix(name: str) -> None:
    assert gender.infer_from_first_name(name) == "M"


def test_empty_returns_none() -> None:
    assert gender.infer_from_first_name("") is None
    assert gender.infer_from_first_name("   ") is None


def test_compound_first_name_uses_head_token() -> None:
    # "Ана Марија" — head is "Ана", female by -а suffix.
    assert gender.infer_from_first_name("Ана Марија") == "F"
    # "Никола Петар" — head is "Никола", male by exception list.
    assert gender.infer_from_first_name("Никола Петар") == "M"
