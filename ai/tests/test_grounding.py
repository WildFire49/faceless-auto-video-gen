"""Every number a viewer sees or hears must be in the quoted evidence.

Found by reviewing Gate A in a browser, not by any test: a fact read

    label:    "around 9,000 years ago"
    claim:    "Iron played a significant role in the technological progress
               of humanity over thousands of years."
    evidence: "Iron is sometimes considered as a prototype for the entire
               block of transition metals, due to its abundance and the
               immense role it has played in the technological progress of
               humanity."

The evidence is verbatim and passed the verifier. The DATE -- the one thing a
viewer remembers -- appears nowhere in it. The model wrote it. The verifier
checked the numbers in the evidence against the source, but nothing checked
the numbers in the label and claim against the evidence.

The ways this can go wrong, written before the code:

 1. the label carries a number the evidence lacks           -> ungrounded
 2. the claim carries a number the evidence lacks           -> ungrounded
    (the script reads the claim aloud, so this is a fact the viewer HEARS)
 3. a number only appears inside a larger one ("200" vs "2000")
                                                            -> ungrounded
 4. the model converts units ("2631 BC" -> "4,600 years ago")
                                                            -> ungrounded;
    conversions are exactly where models get dates wrong
 5. thousands separators differ ("9,000" vs "9000")         -> grounded
 6. decades and ordinals ("1850s", "19th century")          -> grounded
 7. a sentence-final full stop ("in 1938.")                 -> grounded
 8. a label with no number at all ("pre-historical times")  -> grounded;
    there is nothing numeric to invent
 9. spelled-out numbers ("nine thousand years ago")         -> NOT CAUGHT.
    A known gap, pinned by a strict xfail so fixing it is noticed.
"""

from __future__ import annotations

import pytest

from rewind_ai.research.grounding import ungrounded_numbers

EVIDENCE = (
    "Iron metallurgical development occurred 2631–2458 BC at Lejja, in Nigeria, "
    "and by the 1850s steel was produced in bulk; in the 19th century demand "
    "rose to 9,000 tonnes a year, and output doubled in 1938."
)


# ------------------------------------------------------------ must be caught


def test_1_a_label_number_missing_from_the_evidence() -> None:
    assert ungrounded_numbers(
        label="around 9,000 years ago",
        claim="Iron was first worked in Nigeria.",
        evidence="Iron metallurgical development occurred 2631–2458 BC at Lejja.",
    ) == ("9000",)


def test_2_a_claim_number_missing_from_the_evidence() -> None:
    assert ungrounded_numbers(
        label="1938",
        claim="Output doubled in 1939.",
        evidence=EVIDENCE,
    ) == ("1939",)


def test_3_a_number_hiding_inside_a_larger_one() -> None:
    assert ungrounded_numbers(
        label="200 BC",
        claim="Iron spread.",
        evidence="Iron spread widely around 2000 BC.",
    ) == ("200",)


def test_4_a_unit_conversion_is_not_grounded() -> None:
    assert ungrounded_numbers(
        label="around 4,600 years ago",
        claim="Iron was worked at Lejja.",
        evidence="Iron metallurgical development occurred 2631–2458 BC at Lejja.",
    ) == ("4600",)


def test_every_missing_number_is_reported_once_in_order() -> None:
    assert ungrounded_numbers(
        label="1066",
        claim="Between 1066 and 1215 iron spread.",
        evidence="Nothing dated here.",
    ) == ("1066", "1215")


# ------------------------------------------------------- must NOT be caught


def test_5_thousands_separators_are_the_same_number() -> None:
    assert ungrounded_numbers(label="9000 tonnes", claim="", evidence=EVIDENCE) == ()


def test_6_decades_and_ordinals() -> None:
    assert ungrounded_numbers(label="1850s", claim="In the 19th century.", evidence=EVIDENCE) == ()


def test_7_a_sentence_final_full_stop() -> None:
    assert ungrounded_numbers(label="1938", claim="It doubled in 1938.", evidence=EVIDENCE) == ()


def test_8_a_label_with_no_numbers() -> None:
    assert (
        ungrounded_numbers(
            label="pre-historical times",
            claim="Ochre was used as a pigment.",
            evidence="Ochre has been used as a pigment since pre-historical times.",
        )
        == ()
    )


def test_a_range_copied_from_the_evidence() -> None:
    assert ungrounded_numbers(label="2631–2458 BC", claim="", evidence=EVIDENCE) == ()


# ------------------------------------------------------------- the known gap


@pytest.mark.xfail(
    strict=True,
    reason="spelled-out numbers are not parsed; models almost always use digits",
)
def test_9_spelled_out_numbers_are_not_yet_caught() -> None:
    assert (
        ungrounded_numbers(
            label="nine thousand years ago",
            claim="",
            evidence="Iron was worked in 2631 BC.",
        )
        != ()
    )
