"""Serbian Cyrillic <-> Latin transliteration.

Ported from `Celik/Instaler/serbian_id_reader.py` (character-map based,
no dependencies) — useful because eID chips store data in whichever
script was used at issuance, and the operator may want to view or
print in either script regardless.
"""

from __future__ import annotations

_CYR_TO_LAT: dict[str, str] = {
    "А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D",
    "Ђ": "Đ", "Е": "E", "Ж": "Ž", "З": "Z", "И": "I",
    "Ј": "J", "К": "K", "Л": "L", "Љ": "Lj", "М": "M",
    "Н": "N", "Њ": "Nj", "О": "O", "П": "P", "Р": "R",
    "С": "S", "Т": "T", "Ћ": "Ć", "У": "U", "Ф": "F",
    "Х": "H", "Ц": "C", "Ч": "Č", "Џ": "Dž", "Ш": "Š",
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d",
    "ђ": "đ", "е": "e", "ж": "ž", "з": "z", "и": "i",
    "ј": "j", "к": "k", "л": "l", "љ": "lj", "м": "m",
    "н": "n", "њ": "nj", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "ћ": "ć", "у": "u", "ф": "f",
    "х": "h", "ц": "c", "ч": "č", "џ": "dž", "ш": "š",
}

_LAT_TO_CYR: dict[str, str] = {
    "Lj": "Љ", "LJ": "Љ", "Nj": "Њ", "NJ": "Њ", "Dž": "Џ", "DŽ": "Џ",
    "A": "А", "B": "Б", "V": "В", "G": "Г", "D": "Д",
    "Đ": "Ђ", "E": "Е", "Ž": "Ж", "Z": "З", "I": "И",
    "J": "Ј", "K": "К", "L": "Л", "M": "М", "N": "Н",
    "O": "О", "P": "П", "R": "Р", "S": "С", "T": "Т",
    "Ć": "Ћ", "U": "У", "F": "Ф", "H": "Х", "C": "Ц",
    "Č": "Ч", "Š": "Ш",
    "lj": "љ", "nj": "њ", "dž": "џ",
    "a": "а", "b": "б", "v": "в", "g": "г", "d": "д",
    "đ": "ђ", "e": "е", "ž": "ж", "z": "з", "i": "и",
    "j": "ј", "k": "к", "l": "л", "m": "м", "n": "н",
    "o": "о", "p": "п", "r": "р", "s": "с", "t": "т",
    "ć": "ћ", "u": "у", "f": "ф", "h": "х", "c": "ц",
    "č": "ч", "š": "ш",
}


def cyr_to_lat(text: str) -> str:
    return "".join(_CYR_TO_LAT.get(ch, ch) for ch in text)


def lat_to_cyr(text: str) -> str:
    result: list[str] = []
    i = 0
    while i < len(text):
        two = text[i:i + 2]
        if two in _LAT_TO_CYR:
            result.append(_LAT_TO_CYR[two])
            i += 2
            continue
        result.append(_LAT_TO_CYR.get(text[i], text[i]))
        i += 1
    return "".join(result)


def transliterate_dict(data: dict, target_script: str) -> dict:
    """Transliterate every string value in `data`. `target_script` is
    "original" (no-op), "latin", or "cyrillic"."""
    if target_script == "original":
        return dict(data)
    fn = cyr_to_lat if target_script == "latin" else lat_to_cyr
    return {
        k: (fn(v) if isinstance(v, str) and v else v)
        for k, v in data.items()
    }
