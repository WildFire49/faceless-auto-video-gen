"""Tests for the comparison safety rules.

The evidence verifier makes the FACTS safe. These rules make the JOKES safe,
and a joke is where this project can do real harm: a comparison that asserts
something false about a real company is a defamation risk, and one that
reaches for a tragedy is simply cruel.

Organised, like the verifier's tests, around the two ways to fail:

* letting through a line the channel should never say  -- the dangerous one
* rejecting a harmless comparison                      -- the annoying one

They are not equally bad. A blunt rule costs one proposal from a list of
several; a subtle one costs the channel.
"""

from __future__ import annotations

import pytest

from rewind_ai.relevance import rules
from rewind_ai.relevance.base import Kind, Proposal


def proposal(comparison: str, *, reference: str = "Birkenstock", why: str = "") -> Proposal:
    return Proposal(
        reference=reference,
        kind=Kind.EVERGREEN,
        linked_fact_id="f1",
        comparison=comparison,
        why_funny=why or "premium comfort brand vs brutal army footwear",
    )


# ------------------------------------------- lines the channel must refuse


@pytest.mark.parametrize(
    "comparison",
    [
        "Roman caligae sold out faster than tickets after 9/11.",
        "Cheaper than a Trump rally hat.",
        "The iron shortage was basically a famine for blacksmiths.",
        "Queued like refugees at a border.",
        "As unwanted as a terrorist on a plane.",
    ],
)
def test_forbidden_subjects_are_rejected(comparison: str) -> None:
    reason = rules.check(proposal(comparison))
    assert reason, f"the channel would have said: {comparison!r}"


def test_the_reason_names_the_category() -> None:
    reason = rules.check(proposal("Sold out faster than tickets after 9/11."))
    assert "tragedy" in reason


def test_forbidden_terms_match_whole_words_only() -> None:
    # "trumpet" must not trip the "trump" rule, or a history of brass
    # instruments becomes unmakeable.
    assert rules.check(proposal("Loud as a trumpet in a small room.")) == ""


# ----------------------------------- claims about brands, which we cannot make


@pytest.mark.parametrize(
    "comparison",
    [
        "Birkenstock was founded in ancient Rome.",
        "Crocs invented the moulded sole in 1823.",
        "Nike patented the hobnail in the 1400s.",
        "Stanley acquired the vacuum flask patent that year.",
    ],
)
def test_factual_claims_about_brands_are_rejected(comparison: str) -> None:
    """We researched the TOPIC, not the brand. There is no source for any of
    these, so asserting them would be exactly the failure the whole project
    exists to prevent -- just moved from the facts into the jokes."""
    reason = rules.check(proposal(comparison))
    assert reason, f"an unsourced claim about a brand slipped through: {comparison!r}"
    assert "factual claim" in reason


@pytest.mark.parametrize(
    "comparison",
    [
        "Roman soldiers basically wore Birkenstocks with metal spikes.",
        "It was the Stanley cup of ancient Egypt.",
        "Think of it as an air fryer, but powered by a fire and some regret.",
        "Limited drop energy: sold out because it took a blacksmith three days.",
        "Same energy as a phone at 1% battery.",
        "The 1882 version would be the Dyson of its day, if a Dyson weighed fifteen pounds.",
    ],
)
def test_real_comparisons_are_accepted(comparison: str) -> None:
    """These are the shapes SPEC.md 6 actually asks for. If the rules reject
    them, the rules have made the channel impossible to write."""
    assert rules.check(proposal(comparison)) == "", f"wrongly rejected: {comparison!r}"


def test_likeness_marker_rescues_a_claim_verb() -> None:
    # "was the X of its day" contains "was" but asserts nothing about X.
    assert rules.check(proposal("It was the Crocs of the 1700s.")) == ""


# ------------------------------------------------------- private individuals


def test_private_individuals_are_rejected() -> None:
    reason = rules.check(proposal("Uglier than my mum's garden clogs."))
    assert "private individual" in reason


def test_public_brand_names_are_not_individuals() -> None:
    assert rules.check(proposal("Basically the Lululemon of 1890.")) == ""


# ------------------------------------------------------------- the chain


def test_check_returns_the_first_failure_only() -> None:
    # One clear reason is more useful to a reviewer than a list.
    reason = rules.check(proposal("Birkenstock was founded after 9/11."))
    assert reason.count(";") <= 1


def test_every_rule_returns_empty_for_a_clean_proposal() -> None:
    clean = proposal("Roman caligae were basically Birkenstocks with spikes.")
    for rule in rules.RULES:
        assert rule(clean) == "", f"{rule.__name__} rejected a clean comparison"


def test_rules_read_the_why_funny_field_too() -> None:
    # A clean line with a tasteless justification is still tasteless, and the
    # justification is shown to the reviewer.
    tainted = proposal(
        "Basically the Crocs of 1850.",
        why="funny because the factory workers all died in the fire",
    )
    assert rules.check(tainted) != ""
