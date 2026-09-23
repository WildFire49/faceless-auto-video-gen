"""A timeline fact's sort year must agree with the date its label states.

Found in an E2E screenshot of Gate A: a fact labelled

    "between 3,700 million years ago and 1,800 million years ago"

(banded iron formations) reached a human. The label was grounded -- the
numbers really were in the quote -- and the format rejects geological time.
But that check read `sort_key`, the number the MODEL chose for sorting, and
the model had chosen an ordinary-looking one. The label said one thing and
the sort key another, and only the sort key was checked.

So the format now reads the label itself. The ways this can go wrong,
written before the code:

 1. the label is geological, the sort key is not     -> rejected, judged by
                                                        the label
 2. a BC date sorted as AD ("6000 BC" as 6000)       -> rejected; the classic
                                                        sign error
 3. a century on the wrong side of zero ("5th century BC" as 450)
                                                     -> rejected
 4. a decade sorted a century out ("1850s" as 1950)  -> rejected
 5. "N years ago" sorted as if it were a year        -> rejected
 6. an honest approximation ("around 3000 BC" as -2950, "9,000 years ago"
    as -7000)                                        -> accepted; the slack
                                                        exists for this
 7. a label with no date in it ("Roman Republic")    -> accepted; nothing to
                                                        compare, so no claim
                                                        of a mismatch
 8. deep but human time ("3.3 million years ago", the oldest stone tools)
                                                     -> accepted; the
                                                        format's floor is
                                                        -4,000,000
"""

from __future__ import annotations

import pytest

from rewind_ai.formats.base import RawItem
from rewind_ai.formats.providers.history_timeline import HistoryTimeline
from rewind_ai.formats.timeline_dates import label_years


def item(label: str, sort_key: int) -> RawItem:
    return RawItem(label=label, sort_key=sort_key, context="", claim="c", evidence="e", extra={})


# ------------------------------------------------------- reading the label


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("1709", (1709, 1709)),
        ("6000 BC", (-6000, -6000)),
        ("3500 BC or earlier", (-3500, -3500)),
        ("between 3000 and 2700 BC", (-3000, -2700)),
        ("2631–2458 BC", (-2631, -2458)),
        ("1850s", (1850, 1859)),
        ("late 1850s", (1850, 1859)),
        ("19th century", (1801, 1900)),
        ("c. 5th century BC", (-500, -401)),
        ("12th–13th century", (1101, 1300)),
        # From a live run: read as "7th century BC" alone, which rejected an
        # honest fact sorted at -1000.
        ("between the 10th and the 7th centuries BC", (-1000, -601)),
        ("3rd millennium BC", (-3000, -2001)),
        ("AD 43", (43, 43)),
    ],
)
def test_reads_the_date_a_label_states(label: str, expected: tuple[int, int]) -> None:
    assert label_years(label) == expected


def test_years_ago_are_counted_back_from_about_now() -> None:
    span = label_years("around 9,000 years ago")
    assert span is not None
    assert -7100 <= span[0] <= -6900


def test_geological_labels_read_as_geological() -> None:
    span = label_years("between 3,700 million years ago and 1,800 million years ago")
    assert span is not None
    assert span[0] < -3_000_000_000


@pytest.mark.parametrize("label", ["Roman Republic", "pre-historical times", "the Iron Age"])
def test_a_label_without_a_date_reads_as_none(label: str) -> None:
    assert label_years(label) is None


# --------------------------------------------------- what the format rejects


@pytest.mark.parametrize(
    ("label", "sort_key"),
    [
        ("between 3,700 million years ago and 1,800 million years ago", -3000),  # 1
        ("6000 BC", 6000),  # 2
        ("c. 5th century BC", 450),  # 3
        ("1850s", 1950),  # 4
        ("around 9,000 years ago", 9000),  # 5
    ],
)
def test_a_sort_key_that_contradicts_its_label_is_rejected(label: str, sort_key: int) -> None:
    assert HistoryTimeline().implausible_reason(item(label, sort_key)), (label, sort_key)


@pytest.mark.parametrize(
    ("label", "sort_key"),
    [
        ("around 3000 BC", -2950),  # 6
        ("between the 10th and the 7th centuries BC", -1000),
        ("around 9,000 years ago", -7000),  # 6
        ("1850s", 1855),
        ("c. 5th century BC", -450),
        ("Roman Republic", -200),  # 7
        ("around 3.3 million years ago", -3_300_000),  # 8
    ],
)
def test_an_honest_sort_key_is_accepted(label: str, sort_key: int) -> None:
    assert HistoryTimeline().implausible_reason(item(label, sort_key)) == "", (label, sort_key)
