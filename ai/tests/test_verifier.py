"""Tests for the evidence verifier.

This is the component that makes "the LLM is never the source of a fact"
(CLAUDE.md) true rather than aspirational, so it gets the most attention in
the suite. The cases below are organised around the two ways it can fail:

* letting through a fact the model invented  -- the dangerous failure
* rejecting a fact the model copied honestly -- the annoying failure

Both matter, but they are not equally bad, and the threshold is tuned to
prefer the annoying one.
"""

from __future__ import annotations

import pytest

from rewind_ai.research.verifier import (
    confidence_for,
    normalise,
    similarity,
    verify_evidence,
)

THRESHOLD = 0.90

# A realistic slice of a Wikipedia article, with the citation markers and
# typographic quirks that real source text actually contains.
SOURCE = """
Sandals are an open type of footwear, consisting of a sole held to the wearer's
foot by straps going over the instep and around the ankle.[1]

The oldest known footwear in the world are sandals woven from sagebrush bark,
dated to approximately 7000 or 8000 BC, found at the Fort Rock Cave in the
U.S. state of Oregon in 1938.[2] Roman soldiers wore caligae, heavy-soled
hobnailed military sandals, which were standard issue throughout the Republic
and early Empire.

In 1962, the flip-flop became popular in the United States following the
return of soldiers from World War II, who brought Japanese zori home with them.
"""

SOURCES = {"https://en.wikipedia.org/wiki/Sandal": SOURCE}


# ------------------------------------------------------- honest evidence passes


def test_exact_sentence_verifies() -> None:
    evidence = (
        "The oldest known footwear in the world are sandals woven from sagebrush "
        "bark, dated to approximately 7000 or 8000 BC, found at the Fort Rock Cave "
        "in the U.S. state of Oregon in 1938."
    )
    result = verify_evidence(evidence, SOURCES, threshold=THRESHOLD)

    assert result.verified
    assert result.score >= 0.99
    assert result.source_url == "https://en.wikipedia.org/wiki/Sandal"


def test_citation_markers_are_ignored() -> None:
    # The source has "[2]" after the sentence; a model copying it will usually
    # drop the marker. Rejecting that would be pedantic, not safe.
    evidence = "found at the Fort Rock Cave in the U.S. state of Oregon in 1938."
    assert verify_evidence(evidence, SOURCES, threshold=THRESHOLD).verified


def test_whitespace_and_line_breaks_are_ignored() -> None:
    # The source wraps this sentence across lines.
    evidence = (
        "Roman soldiers wore caligae, heavy-soled hobnailed military sandals, "
        "which were standard issue throughout the Republic and early Empire."
    )
    assert verify_evidence(evidence, SOURCES, threshold=THRESHOLD).verified


def test_typographic_apostrophe_is_ignored() -> None:
    # A model will happily normalise a curly apostrophe to a straight one.
    evidence = "consisting of a sole held to the wearer’s foot by straps going over the instep"
    assert verify_evidence(evidence, SOURCES, threshold=THRESHOLD).verified


# -------------------------------------------------- invented evidence is caught


def test_fabricated_sentence_is_rejected() -> None:
    # Plausible, well-formed, entirely absent from the source. This is the
    # case the whole project depends on catching.
    evidence = (
        "Archaeologists discovered the oldest leather sandals in Armenia, "
        "dated to 3500 BC, preserved in sheep dung."
    )
    result = verify_evidence(evidence, SOURCES, threshold=THRESHOLD)

    assert not result.verified
    assert "not found" in result.reason


def test_reworded_sentence_is_rejected() -> None:
    # The dangerous middle ground: same meaning, different words. If this
    # passed, the verifier would be laundering paraphrase as citation, and a
    # subtly altered date would slip through with it.
    evidence = (
        "The world's oldest known shoes are sandals made of sagebrush bark, "
        "roughly 7000 BC, discovered at Fort Rock Cave in Oregon."
    )
    result = verify_evidence(evidence, SOURCES, threshold=THRESHOLD)

    assert not result.verified, (
        f"a reworded sentence scored {result.score:.2f} and passed; "
        "the verifier is not distinguishing quotation from paraphrase"
    )


def test_altered_date_is_rejected() -> None:
    """The exact attack the verifier exists to stop.

    Copy a real sentence, change the number. This scores 0.99 on prose
    similarity -- four characters out of a hundred and eighty -- so NO prose
    threshold catches it. Only the exact number check does.
    """
    evidence = (
        "The oldest known footwear in the world are sandals woven from sagebrush "
        "bark, dated to approximately 3000 or 4000 BC, found at the Fort Rock Cave "
        "in the U.S. state of Oregon in 1938."
    )
    result = verify_evidence(evidence, SOURCES, threshold=THRESHOLD)

    assert not result.verified, (
        f"a sentence with a falsified date scored {result.score:.2f} and passed"
    )
    # It must be rejected for the RIGHT reason, and say which numbers are wrong.
    assert set(result.missing_numbers) == {"3000", "4000"}
    assert "altered" in result.reason


def test_altered_date_survives_a_high_prose_score() -> None:
    # Demonstrates the point above: the prose really does match almost
    # perfectly, which is why fuzzy matching alone was unsafe.
    evidence = (
        "The oldest known footwear in the world are sandals woven from sagebrush "
        "bark, dated to approximately 3000 or 4000 BC, found at the Fort Rock Cave "
        "in the U.S. state of Oregon in 1938."
    )
    result = verify_evidence(evidence, SOURCES, threshold=THRESHOLD)
    assert result.score > 0.97, "expected the prose to match closely"
    assert not result.verified


def test_inserted_number_is_rejected() -> None:
    # Adding a figure the source never gave is the same class of falsehood as
    # changing one.
    evidence = (
        "Roman soldiers wore caligae, heavy-soled hobnailed military sandals, "
        "which were standard issue for 400 years throughout the Republic and "
        "early Empire."
    )
    result = verify_evidence(evidence, SOURCES, threshold=THRESHOLD)
    assert not result.verified
    assert "400" in result.missing_numbers


def test_correct_numbers_pass_the_number_check() -> None:
    # The guard must not reject honest evidence that contains numbers -- that
    # would throw away nearly every fact worth having.
    evidence = (
        "In 1962, the flip-flop became popular in the United States following "
        "the return of soldiers from World War II, who brought Japanese zori "
        "home with them."
    )
    result = verify_evidence(evidence, SOURCES, threshold=THRESHOLD)
    assert result.verified, result.reason
    assert result.missing_numbers == ()


def test_thousands_separators_are_equivalent() -> None:
    # "7,000" and "7000" are the same number; treating them as different
    # would reject honest copies.
    from rewind_ai.research.verifier import numbers_in

    assert numbers_in("about 7,000 years") == numbers_in("about 7000 years")


def test_sentence_final_period_is_not_a_decimal() -> None:
    from rewind_ai.research.verifier import numbers_in

    assert numbers_in("found in 1938.") == ["1938"]


def test_short_fragments_are_rejected_outright() -> None:
    # "in 1962" appears verbatim in the source, so a naive matcher would
    # verify it. But a fragment that short supports no claim at all -- passing
    # it would let the model attach any invented claim to a real substring.
    result = verify_evidence("in 1962", SOURCES, threshold=THRESHOLD)

    assert not result.verified
    assert "too short" in result.reason


def test_empty_evidence_is_rejected() -> None:
    for value in ("", "   ", "\n"):
        assert not verify_evidence(value, SOURCES, threshold=THRESHOLD).verified


def test_no_sources_means_nothing_verifies() -> None:
    result = verify_evidence("a" * 60, {}, threshold=THRESHOLD)
    assert not result.verified
    assert "no source text" in result.reason


# ---------------------------------------------------------------- mechanics


def test_normalise_keeps_digits_and_punctuation() -> None:
    # Dates are the thing being verified, so normalisation must not eat them.
    assert "7000" in normalise("dated to approximately 7000 or 8000 BC.[2]")
    assert "[2]" not in normalise("dated to approximately 7000 BC.[2]")


def test_normalise_folds_typography() -> None:
    assert normalise("the wearer’s foot") == normalise("the wearer's foot")
    assert normalise("1900–1910") == normalise("1900-1910")


def test_similarity_is_windowed_not_whole_document() -> None:
    # A perfect sentence match inside a large document must score ~1.0. A
    # whole-document ratio would score near zero and reject everything.
    needle = normalise("Roman soldiers wore caligae")
    assert similarity(needle, normalise(SOURCE)) >= 0.99


def test_similarity_handles_empty_input() -> None:
    assert similarity("", "abc") == 0.0
    assert similarity("abc", "") == 0.0


@pytest.mark.parametrize(
    ("score", "expected"),
    [(1.0, "high"), (0.995, "high"), (0.96, "medium"), (0.91, "low")],
)
def test_confidence_labels(score: float, expected: str) -> None:
    assert confidence_for(score) == expected


def test_best_matching_source_is_reported() -> None:
    # With several sources, the fact should be attributed to the one it was
    # actually found in, not the first one checked.
    other = {"https://example.com/unrelated": "Completely unrelated text about bicycles."}
    result = verify_evidence(
        "Roman soldiers wore caligae, heavy-soled hobnailed military sandals,",
        {**other, **SOURCES},
        threshold=THRESHOLD,
    )

    assert result.verified
    assert result.source_url == "https://en.wikipedia.org/wiki/Sandal"
