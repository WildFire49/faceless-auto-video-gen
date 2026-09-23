"""Read the year range a narrator's date label states.

A timeline fact carries two dates: the label a viewer sees ("5th century BC")
and a sort key the model computed from it (-450). Only the sort key used to be
checked, so a label could say geological time while the sort key looked
ordinary -- and the label is what reaches the screen. Reading the label lets
the timeline format check the two against each other (see
providers/history_timeline.py).

Deliberately modest. It understands the forms Wikipedia and the extraction
prompt actually produce -- years, BC/AD, ranges, decades, centuries,
millennia, "N years ago" -- and returns None for anything else, which means
"cannot compare", never "wrong". A parser that guessed would reject honest
facts.
"""

from __future__ import annotations

import re

#: "N years ago" in an encyclopaedia is measured from roughly when it was
#: written. Callers compare with generous slack, so the exact anchor matters
#: less than having one.
PRESENT_YEAR = 2000

_ORD = r"(\d{1,2})(?:st|nd|rd|th)"
_JOIN = r"\s*(?:-|to|and|or)\s*(?:the\s+)?"

_AGO = re.compile(r"(\d+(?:\.\d+)?)\s*(million|billion)?\s*years?\s+ago")
_CENTURY = re.compile(rf"{_ORD}(?:{_JOIN}{_ORD})?\s*centur(?:y|ies)")
_MILLENNIUM = re.compile(rf"{_ORD}(?:{_JOIN}{_ORD})?\s*millenni(?:um|a)")
_DECADE = re.compile(r"\b(\d{3,4})s\b")
_YEAR = re.compile(r"\b(\d{1,5})\b")
_BC = re.compile(r"\b(?:bc|bce|b\.c\.)")

_SCALE = {"million": 1_000_000, "billion": 1_000_000_000}


def label_years(label: str) -> tuple[int, int] | None:
    """The (earliest, latest) years a label states, or None if it states none."""
    text = _normalise(label)
    bc = bool(_BC.search(text))

    for reader in (_years_ago, _centuries, _millennia, _decades):
        span = reader(text, bc)
        if span is not None:
            return span

    years = [int(n) for n in _YEAR.findall(text)]
    if not years:
        return None
    signed = [-y if bc else y for y in years]
    return min(signed), max(signed)


def _normalise(label: str) -> str:
    text = label.lower()
    text = re.sub(r"(?<=\d),(?=\d{3})", "", text)  # 9,000 -> 9000
    return re.sub(r"[\u2012-\u2015\u2212]", "-", text)  # figure/en/em dashes, minus -> hyphen


def _years_ago(text: str, _bc: bool) -> tuple[int, int] | None:
    found = [
        PRESENT_YEAR - round(float(n) * _SCALE.get(scale, 1)) for n, scale in _AGO.findall(text)
    ]
    return (min(found), max(found)) if found else None


def _ordinal_span(match: re.Match[str], size: int, bc: bool) -> tuple[int, int]:
    first = int(match.group(1))
    last = int(match.group(2)) if match.group(2) else first
    if bc:
        # The 5th century BC runs from 500 BC to 401 BC.
        return -max(first, last) * size, -(min(first, last) - 1) * size - 1
    return (min(first, last) - 1) * size + 1, max(first, last) * size


def _centuries(text: str, bc: bool) -> tuple[int, int] | None:
    match = _CENTURY.search(text)
    return _ordinal_span(match, 100, bc) if match else None


def _millennia(text: str, bc: bool) -> tuple[int, int] | None:
    match = _MILLENNIUM.search(text)
    return _ordinal_span(match, 1000, bc) if match else None


def _decades(text: str, bc: bool) -> tuple[int, int] | None:
    match = _DECADE.search(text)
    if not match:
        return None
    start = int(match.group(1))
    return (-(start + 9), -start) if bc else (start, start + 9)
