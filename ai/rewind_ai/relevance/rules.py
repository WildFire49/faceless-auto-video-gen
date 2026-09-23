"""Safety and accuracy rules for proposed comparisons.

LAYER 2 of SPEC.md 14.1: pure functions, no I/O, no LLM. This is the Chain of
Responsibility of SPEC.md 14.3 -- each rule is an independent check, and the
list is what a reviewer reads to understand what the machine will refuse.

WHY THIS EXISTS. The evidence verifier makes the *facts* safe. Nothing makes
the *jokes* safe, and a joke is where this project can do real harm: a
comparison that asserts something false about a real company is a
defamation risk, and one that reaches for a tragedy or a living person is
simply cruel. SPEC.md 5.3 and 6 name the limits; this file enforces them.

The rules are deliberately blunt. A blunt rule that occasionally rejects a
harmless line costs one proposal. A subtle rule that occasionally lets a
tasteless one through costs the channel.

The failure modes, written before the code (CLAUDE.md):

    * a comparison asserts a fact about a brand   -> looks_like_factual_claim
    * a reference reaches for a tragedy           -> touches_forbidden_subject
    * it names a living private individual        -> touches_forbidden_subject
    * it is political                             -> touches_forbidden_subject
    * it attaches to no approved fact             -> checked by the service
    * it punches down at a group of people        -> touches_forbidden_subject
"""

from __future__ import annotations

import re
from collections.abc import Callable

from rewind_ai.relevance.base import Proposal

#: Subjects a comparison must never reach for (SPEC.md 5.3, 6).
#:
#: Matched as whole words, case-insensitively. Broad on purpose: "9/11 pricing"
#: is not a joke this channel makes, and the cost of over-rejecting is one
#: proposal from a list of several.
FORBIDDEN_SUBJECTS: dict[str, tuple[str, ...]] = {
    "tragedy": (
        "9/11",
        "terrorist",
        "terrorism",
        "massacre",
        "genocide",
        "holocaust",
        "shooting",
        "bombing",
        "famine",
        "atrocity",
        "war crime",
        "assassination",
        "suicide",
        "overdose",
        "pandemic death",
    ),
    "politics": (
        "trump",
        "biden",
        "putin",
        "election",
        "democrat",
        "republican",
        "brexit",
        "congress",
        "parliament",
        "president",
        "prime minister",
        "immigration policy",
        "abortion",
        "gun control",
    ),
    "identity": (
        "immigrant",
        "refugee",
        "disabled",
        "retard",
        "autistic",
        "mentally ill",
        "obese",
        "fat people",
        "homeless",
    ),
    "religion": (
        "muslim",
        "islam",
        "christian",
        "jewish",
        "hindu",
        "buddhist",
        "the pope",
        "sharia",
    ),
    # Real suffering, usually arriving in the "why is this funny" field rather
    # than the line itself -- which is exactly why the rules read both.
    # Phrases, not bare words: "died" alone would reject "died out", which is
    # ordinary English about an object falling out of use.
    "suffering": (
        "died in the fire",
        "burned alive",
        "burnt alive",
        "worked to death",
        "death toll",
        "child labour",
        "child labor",
        "slave labour",
        "slave labor",
        "slavery",
        "workers died",
        "people died",
    ),
}

#: Verbs that turn a comparison into an assertion about the brand.
#:
#: "Roman caligae were basically Birkenstocks" is a comparison -- "basically"
#: signals likeness. "Birkenstock invented the footbed in Rome" is a claim, and
#: we have no evidence for it because we never researched Birkenstock.
_CLAIM_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Any of these verbs asserts who did what. Earlier versions demanded the
    # verb be followed immediately by "in"/"by"/"during", which let
    # "Crocs invented the moulded sole in 1823" straight through -- the object
    # came first. The verb alone is the signal; the likeness-marker window
    # below is what rescues an innocent use.
    re.compile(
        r"\b(founded|invented|created|patented|trademarked|launched|designed|"
        r"manufactured|established|pioneered)\b",
        re.I,
    ),
    re.compile(r"\b(owns|acquired|bought|merged|sued|bankrupt)\b", re.I),
    re.compile(r"\bthe first\b.{0,30}\b(company|brand|firm)\b", re.I),
)


#: Words that mark a line as a likeness rather than an assertion. Their
#: presence is not a licence, but their ABSENCE alongside a claim verb is a
#: strong signal.
_LIKENESS_MARKERS = (
    "basically",
    "like",
    "essentially",
    "the equivalent",
    "equivalent of",
    "think of",
    "imagine",
    "same energy",
    "version of",
    "but with",
    "but for",
    "answer to",
    "would be",
    "is the",
    "was the",
)


def touches_forbidden_subject(proposal: Proposal) -> str:
    """Return why this proposal is off-limits, or "" if it is fine."""
    haystack = " ".join((proposal.reference, proposal.comparison, proposal.why_funny)).lower()

    for subject, terms in FORBIDDEN_SUBJECTS.items():
        for term in terms:
            if _contains_phrase(haystack, term):
                return (
                    f"mentions {term!r}, which falls under {subject}; "
                    "this channel does not joke about it (SPEC.md 6)"
                )
    return ""


def looks_like_factual_claim(proposal: Proposal) -> str:
    """Return why this reads as an assertion about the brand, or "".

    A comparison may say what something LOOKS like, costs, or feels like. It
    may not say what a company did, because we have no source for that -- the
    research step only ever verified facts about the topic.
    """
    text = proposal.comparison
    lowered = text.lower()

    for pattern in _CLAIM_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue

        # A claim verb inside an obvious likeness construction is usually
        # fine: "it was the Stanley cup of its day" asserts nothing about
        # Stanley. Require a marker near the verb rather than anywhere.
        window = lowered[max(0, match.start() - 60) : match.end() + 20]
        if any(marker in window for marker in _LIKENESS_MARKERS):
            continue

        return (
            f"reads as a factual claim about {proposal.reference!r} "
            f"({match.group(0)!r}); we have no source for that. Compare look, "
            "price, hype or behaviour instead"
        )
    return ""


def names_a_private_individual(proposal: Proposal) -> str:
    """Return why this names a real person, or "".

    Deliberately narrow: detecting names properly is not something a regex
    does, and a false positive here silently drops good material. This catches
    the explicit shapes -- possessives about a named human, "my <relative>" --
    and leaves the rest to the human at Gate B, who is reading every line
    anyway.
    """
    text = proposal.comparison.lower()

    for phrase in ("my mum", "my mom", "my dad", "my ex", "my neighbour", "my neighbor"):
        if phrase in text:
            return f"refers to a private individual ({phrase!r})"
    return ""


#: The chain, in the order a reviewer would care about. Adding a rule is one
#: function plus one line here (SPEC.md 14.3).
RULES: tuple[Callable[[Proposal], str], ...] = (
    touches_forbidden_subject,
    looks_like_factual_claim,
    names_a_private_individual,
)


def check(proposal: Proposal) -> str:
    """Run every rule. Returns the first failure reason, or "" if all pass."""
    for rule in RULES:
        reason = rule(proposal)
        if reason:
            return reason
    return ""


def _contains_phrase(haystack: str, phrase: str) -> bool:
    """Whole-word containment, tolerating a plural.

    Whole-word so "trump" does not match "trumpet" and "war crime" does not
    match "warm crimes". Plural-tolerant because listing every term twice is
    the kind of upkeep that silently rots -- "refugee" was in the list and
    "refugees" sailed straight through.
    """
    if not phrase:
        return False
    pattern = r"(?<!\w)" + re.escape(phrase) + r"(?:s|es)?(?!\w)"
    return re.search(pattern, haystack) is not None
