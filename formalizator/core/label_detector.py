"""Auto-detect field positions on a rendered official-form PDF page.

These official forms consistently label a blank line with a
parenthesized Serbian phrase directly under it — e.g. the real NPRS-3
declaration has `"(име и презиме)"`, `"(датум рођења)"`,
`"(место и адреса становања)"`. This module finds each recognized
label's own position (word-level, via `pdfplumber` — so two labels
sharing one line, like the real form's "(име и презиме)" and
"(датум рођења)" side by side, are still told apart) and infers the
blank's overlay coordinate as sitting just above it.

Never guesses silently: an unrecognized label, or a label this module
knows is unsafe to auto-place (JMBG — real forms render it as 13
individual digit boxes, not one line, so a single inferred coordinate
would be wrong), is returned as `flagged`, for a human to place via the
click-to-calibrate review screen instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from pathlib import Path

import pdfplumber

from formalizator.core.models import FieldPosition

# Each entry: the label phrase's words (lowercase, as they'd appear
# extracted), and the VoterEntry field key it maps to. Phrases are
# matched as a contiguous run of words on the same line, so two labels
# sharing a line (tab-separated in the real form) are still resolved
# independently by their own word positions.
_LABELS: list[tuple[tuple[str, ...], str]] = [
    (("(име", "и", "презиме)"), "full_name"),
    (("(датум", "рођења)"), "date_of_birth"),
    # One blank for both — same reasoning as "(име и презиме)" mapping
    # straight to the given_name+surname composite: the label itself
    # says "место И адреса" (place AND address), so a single inferred
    # position needs the combined value, not just full_address alone.
    (("(место", "и", "адреса", "становања)"), "full_residence"),
    (("(место", "и", "адреса)"), "full_residence"),
]

# Labels that must never be auto-placed — flagged for manual
# calibration regardless of whether a text match is found, because a
# single inferred coordinate is structurally wrong for them (JMBG is
# rendered as 13 separate digit boxes, not one blank).
_ALWAYS_FLAG_SUBSTRINGS = ("јмбг",)

_ABOVE_OFFSET = 4.0  # points above the label's own top, in PDF space


@dataclass
class FlaggedLabel:
    text: str
    page_index: int
    x0: float
    top: float
    reason: str
    # x0/y in PDF space (bottom-left origin, matching FieldPosition) —
    # where the label text ITSELF sits, so the calibration screen can
    # show a "here's roughly where this one is" marker even before the
    # operator assigns and places it (x0/top are pdfplumber's own
    # top-down coordinates, kept for reference/tests).
    y: float = 0.0


@dataclass
class DetectionResult:
    detected: list[FieldPosition] = dc_field(default_factory=list)
    flagged: list[FlaggedLabel] = dc_field(default_factory=list)


def _words_match(words: list[dict], start: int, phrase: tuple[str, ...]) -> bool:
    if start + len(phrase) > len(words):
        return False
    for i, expected in enumerate(phrase):
        if words[start + i]["text"].lower() != expected:
            return False
    return True


def detect(pdf_path: Path | str) -> DetectionResult:
    result = DetectionResult()
    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages):
            words = page.extract_words()
            consumed: set[int] = set()

            for i in range(len(words)):
                if i in consumed:
                    continue
                lower = words[i]["text"].lower()
                if any(sub in lower for sub in _ALWAYS_FLAG_SUBSTRINGS):
                    result.flagged.append(FlaggedLabel(
                        text=words[i]["text"], page_index=page_index,
                        x0=words[i]["x0"], top=words[i]["top"],
                        y=page.height - words[i]["top"],
                        reason="ЈМБГ се приказује као 13 засебних поља —"
                               " потребно ручно постављање.",
                    ))
                    consumed.add(i)
                    continue

                for phrase, field_key in _LABELS:
                    if _words_match(words, i, phrase):
                        x0 = words[i]["x0"]
                        top = words[i]["top"]
                        pdf_y = page.height - top + _ABOVE_OFFSET
                        result.detected.append(FieldPosition(
                            field_key=field_key, page_index=page_index,
                            x=x0, y=pdf_y,
                        ))
                        for j in range(i, i + len(phrase)):
                            consumed.add(j)
                        break

            for i, w in enumerate(words):
                if i in consumed:
                    continue
                if w["text"].startswith("(") or w["text"].endswith(")"):
                    result.flagged.append(FlaggedLabel(
                        text=w["text"], page_index=page_index,
                        x0=w["x0"], top=w["top"], y=page.height - w["top"],
                        reason="Ознака поља није препозната — потребно"
                               " ручно постављање.",
                    ))
    return result
