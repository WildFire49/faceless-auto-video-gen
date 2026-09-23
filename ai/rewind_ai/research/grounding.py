"""Every number a viewer sees or hears must be in the quoted evidence.

The evidence verifier proves the QUOTE is real. It says nothing about the
label and claim the model wrote beside it -- and those are what reach the
viewer: the label is shown at Gate A and on screen, and the claim is what the
script reads aloud. A date invented there sails past a verbatim quote.

So: any number in the label or claim must also be in the evidence. Not in the
source article -- in the quote itself, because the quote is what the reviewer
is shown and what they can check the date against.

Deliberately format-neutral, like the verifier. CLAUDE.md (M2b): what a format
may NOT vary is the requirement that its items are grounded in evidence.

Uses the verifier's own ``numbers_in``, so "9,000" and "9000" are the same
number here exactly as they are there. Two checks that normalised numbers
differently would disagree about the same fact.

Known gap: spelled-out numbers ("nine thousand") are not parsed. Pinned by a
strict xfail in tests/test_grounding.py.
"""

from __future__ import annotations

from rewind_ai.research.verifier import numbers_in


def ungrounded_numbers(*, label: str, claim: str, evidence: str) -> tuple[str, ...]:
    """Numbers in ``label`` or ``claim`` that ``evidence`` does not contain.

    Empty means grounded. Order is first appearance, label before claim,
    each number reported once.
    """
    available = set(numbers_in(evidence))
    missing: list[str] = []

    for number in numbers_in(label) + numbers_in(claim):
        if number not in available and number not in missing:
            missing.append(number)

    return tuple(missing)
