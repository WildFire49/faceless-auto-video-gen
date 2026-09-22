"""The evidence verifier.

LAYER 2 of SPEC.md 14.1: pure functions, no I/O, no LLM. Heavily tested,
because this is the single component standing between the model and a
hallucinated date reaching a human.

THE RULE (CLAUDE.md, SPEC.md 5.2): the LLM is never the source of a fact. It
may only point at a sentence in text we fetched. This module checks that the
sentence it pointed at really is in that text, and drops the fact if not.

Two checks, because one is not enough
-------------------------------------
**1. Fuzzy prose match.** A model asked to copy a sentence reliably reproduces
the words while normalising a curly quote, collapsing a double space, or
dropping a citation marker. Demanding byte equality would reject good facts for
cosmetic reasons, so text is normalised and compared against a similarity floor.

**2. Exact number match.** Fuzzy matching alone is dangerously blind to the
attack that matters most here. Consider:

    source:   "...dated to approximately 7000 or 8000 BC, found at Fort Rock..."
    evidence: "...dated to approximately 3000 or 4000 BC, found at Fort Rock..."

That is a falsified date, and it scores **0.99** similarity -- four characters
out of a hundred and eighty. Every plausible prose threshold passes it. So
every digit sequence in the evidence must ALSO appear verbatim in the region of
the source that matched. Dates and quantities are exactly what a history
channel cannot get wrong, so they are compared exactly while the prose around
them is compared loosely.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

#: Matches Wikipedia-style citation markers: [1], [12], [citation needed].
_CITATION_MARKER = re.compile(r"\[[^\]]{0,24}\]")

#: Any run of whitespace, including newlines.
_WHITESPACE = re.compile(r"\s+")

#: A number as it appears in prose: 1938, 7,000, 3.5. Trailing separators are
#: trimmed afterwards so "1938." yields "1938".
_NUMBER = re.compile(r"\d[\d,.]*")

#: Characters that differ only typographically between a source and a copy.
_TYPOGRAPHY = {
    "‘": "'",
    "’": "'",
    "‚": "'",
    "‛": "'",
    "“": '"',
    "”": '"',
    "„": '"',
    "–": "-",
    "—": "-",
    "−": "-",
    "‐": "-",
    "‑": "-",
    " ": " ",
    " ": " ",
    " ": " ",
    "…": "...",
}


def normalise(text: str) -> str:
    """Reduce text to the form used for comparison.

    Lowercases, folds typographic variants, strips citation markers, collapses
    whitespace. Deliberately does NOT strip punctuation or digits: a date is
    exactly the thing being verified, so it must survive normalisation intact.
    """
    text = unicodedata.normalize("NFKC", text)
    for fancy, plain in _TYPOGRAPHY.items():
        text = text.replace(fancy, plain)
    text = _CITATION_MARKER.sub(" ", text)
    text = _WHITESPACE.sub(" ", text)
    return text.strip().lower()


def numbers_in(text: str) -> list[str]:
    """Every distinct number in ``text``, normalised for comparison.

    Thousands separators are removed so "7,000" and "7000" are the same
    number, and trailing full stops are trimmed so a sentence-final "1938."
    is not mistaken for a decimal.
    """
    found: list[str] = []
    for raw in _NUMBER.findall(text):
        cleaned = raw.replace(",", "").rstrip(".")
        if cleaned and cleaned not in found:
            found.append(cleaned)
    return found


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """The outcome of checking one evidence string."""

    verified: bool
    #: 0..1. How closely the best window of the source matched.
    score: float
    #: Which source the best match came from, when there was one.
    source_url: str = ""
    #: Human-readable reason when verification failed.
    reason: str = ""
    #: Numbers present in the evidence but absent from the matched source
    #: region. Non-empty means a date or quantity was altered.
    missing_numbers: tuple[str, ...] = ()


#: Tuning constants for the windowed search. Named rather than inline so the
#: trade-off between speed and thoroughness is visible and adjustable.
_ANCHOR_CHARS = 40
_MIN_PROBE_CHARS = 12
_MAX_CANDIDATES = 64
_MAX_SCAN_WINDOWS = 200
_NEAR_PERFECT = 0.999


@dataclass(frozen=True, slots=True)
class _Match:
    score: float
    window: str


def _candidate_positions(needle: str, haystack: str) -> list[int]:
    """Where in ``haystack`` a window matching ``needle`` might start.

    Anchors on the MIDDLE of the needle: the start and end of a sentence are
    where a model is most likely to have trimmed a few words, so the middle is
    the most reliable thing to search for.
    """
    anchor_len = min(len(needle), _ANCHOR_CHARS)
    anchor_start = max(0, (len(needle) - anchor_len) // 2)
    anchor = needle[anchor_start : anchor_start + anchor_len]

    positions: list[int] = []
    for probe_len in (anchor_len, anchor_len // 2, _MIN_PROBE_CHARS):
        if probe_len < _MIN_PROBE_CHARS:
            break

        probe = anchor[:probe_len]
        start = 0
        while len(positions) < _MAX_CANDIDATES:
            found = haystack.find(probe, start)
            if found == -1:
                break
            positions.append(max(0, found - anchor_start))
            start = found + 1

        if positions:
            return positions

    # No anchor anywhere: a coarse scan, so a genuinely close match is not
    # missed entirely, bounded so it stays cheap.
    step = max(1, len(needle) // 2)
    return list(range(0, max(1, len(haystack) - len(needle)), step))[:_MAX_SCAN_WINDOWS]


def _best_match(needle: str, haystack: str) -> _Match:
    """Best-scoring window of ``haystack`` for ``needle``, with its text.

    A whole-document ratio would be meaningless -- one sentence against fifty
    kilobytes scores near zero however perfect the match -- so the search is
    windowed.
    """
    if not needle or not haystack:
        return _Match(0.0, "")

    # Exact containment is the common case; skip the expensive path.
    position = haystack.find(needle)
    if position != -1:
        return _Match(1.0, haystack[position : position + len(needle)])

    best = _Match(0.0, "")
    window = len(needle)

    for pos in _candidate_positions(needle, haystack):
        candidate = haystack[pos : pos + window]
        if not candidate:
            continue

        score = SequenceMatcher(None, needle, candidate, autojunk=False).ratio()
        if score > best.score:
            best = _Match(score, candidate)
            if best.score >= _NEAR_PERFECT:
                break

    return best


def similarity(needle: str, haystack: str) -> float:
    """Best similarity between ``needle`` and any window of ``haystack``."""
    return _best_match(needle, haystack).score


def verify_evidence(
    evidence: str,
    sources: dict[str, str],
    *,
    threshold: float,
    min_length: int = 25,
    number_context_chars: int = 60,
) -> VerificationResult:
    """Check that ``evidence`` appears in one of ``sources``.

    Args:
        evidence: the sentence the model claims to have copied.
        sources: url -> fetched plain text.
        threshold: prose similarity floor, 0..1.
        min_length: shorter strings are rejected outright. A six-word fragment
            can match almost any document by luck, which would make the
            verifier worse than useless -- it would launder a guess.
        number_context_chars: how far either side of the matched window to
            look when confirming a number. Generous, because the window is
            approximate; the point is that the number exists nearby in the
            real text, not that the offsets line up exactly.

    Returns:
        A result carrying the best score and the source it came from. Both the
        prose check and the number check must pass.
    """
    if not evidence or not evidence.strip():
        return VerificationResult(False, 0.0, reason="no evidence given")

    normalised_evidence = normalise(evidence)
    if len(normalised_evidence) < min_length:
        return VerificationResult(
            False,
            0.0,
            reason=f"evidence is only {len(normalised_evidence)} characters; "
            f"too short to verify meaningfully (minimum {min_length})",
        )

    if not sources:
        return VerificationResult(False, 0.0, reason="no source text to check against")

    best_score = 0.0
    best_url = ""
    best_missing: tuple[str, ...] = ()

    for url, text in sources.items():
        normalised_source = normalise(text)
        match = _best_match(normalised_evidence, normalised_source)

        if match.score < threshold:
            if match.score > best_score:
                best_score, best_url = match.score, url
            continue

        # The prose matched. Now the part fuzzy matching cannot do: every
        # number in the evidence must really be in the source here.
        missing = _missing_numbers(
            normalised_evidence,
            normalised_source,
            match.window,
            context=number_context_chars,
        )

        if missing:
            # A near-perfect prose match with a wrong number is not a clumsy
            # copy -- it is a falsified figure, which is the failure this
            # project cannot tolerate. Recorded explicitly so Gate A can say so.
            if match.score > best_score:
                best_score, best_url, best_missing = match.score, url, missing
            continue

        return VerificationResult(True, match.score, source_url=url)

    if best_missing:
        listed = ", ".join(best_missing)
        return VerificationResult(
            False,
            best_score,
            source_url=best_url,
            missing_numbers=best_missing,
            reason=f"the wording matches the source ({best_score:.2f}) but these numbers "
            f"do not appear in it: {listed}. A date or quantity has been altered.",
        )

    return VerificationResult(
        False,
        best_score,
        source_url=best_url,
        reason=f"evidence not found in any source (best match {best_score:.2f}, "
        f"need {threshold:.2f}) -- the model may have reworded or invented it",
    )


def _missing_numbers(
    evidence: str,
    source: str,
    window: str,
    *,
    context: int,
) -> tuple[str, ...]:
    """Numbers in ``evidence`` that are absent from the matched region.

    Checked against the matched window plus some padding rather than the whole
    document: a document-wide check would pass any year that happens to appear
    anywhere in a long article, which for a history page is nearly all of them.
    """
    wanted = numbers_in(evidence)
    if not wanted:
        return ()

    position = source.find(window) if window else -1
    if position == -1:
        haystack = source
    else:
        start = max(0, position - context)
        end = min(len(source), position + len(window) + context)
        haystack = source[start:end]

    available = set(numbers_in(haystack))
    return tuple(n for n in wanted if n not in available)


def confidence_for(score: float) -> str:
    """Map a match score to the confidence label shown at Gate A."""
    if score >= 0.99:
        return "high"
    if score >= 0.95:
        return "medium"
    return "low"
