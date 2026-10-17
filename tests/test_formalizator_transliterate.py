"""Tests for formalizator.reader.transliterate — ported from
Celik/Instaler/serbian_id_reader.py."""

from __future__ import annotations

from formalizator.reader.transliterate import cyr_to_lat, lat_to_cyr, transliterate_dict


def test_cyr_to_lat_basic_word() -> None:
    assert cyr_to_lat("Марко") == "Marko"


def test_cyr_to_lat_digraphs() -> None:
    assert cyr_to_lat("Љубљана") == "Ljubljana"
    assert cyr_to_lat("Његош") == "Njegoš"
    assert cyr_to_lat("Џон") == "Džon"


def test_lat_to_cyr_basic_word() -> None:
    assert lat_to_cyr("Marko") == "Марко"


def test_lat_to_cyr_digraphs_consume_two_chars() -> None:
    assert lat_to_cyr("Ljubljana") == "Љубљана"
    assert lat_to_cyr("Njegoš") == "Његош"
    assert lat_to_cyr("Džon") == "Џон"


def test_round_trip_cyr_lat_cyr() -> None:
    original = "Ђорђевић Његош Љубица"
    assert lat_to_cyr(cyr_to_lat(original)) == original


def test_transliterate_dict_original_is_noop() -> None:
    data = {"surname": "Марковић"}
    assert transliterate_dict(data, "original") == data


def test_transliterate_dict_latin_only_touches_strings() -> None:
    data = {"surname": "Марковић", "count": 5, "empty": ""}
    result = transliterate_dict(data, "latin")
    assert result["surname"] == "Marković"
    assert result["count"] == 5
    assert result["empty"] == ""


def test_transliterate_dict_cyrillic() -> None:
    data = {"surname": "Markovic"}
    result = transliterate_dict(data, "cyrillic")
    assert result["surname"] == "Марковиц"
