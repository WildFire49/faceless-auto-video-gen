"""Rules about the SHAPE of a script (SPEC.md 5.4).

Each rule is a plain function, (script, context) -> violations, and the tuple
at the bottom is the chain. Adding a rule is adding a function and a line;
no existing rule is edited (Chain of Responsibility, SPEC.md 14.3). Unlike
the relevance chain, every rule runs: a reviewer fixing a script inline wants
the whole list of what is wrong, not the first thing.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from rewind_ai.script.base import Script, Violation
from rewind_ai.script.context import RuleContext

Rule = Callable[[Script, RuleContext], list[Violation]]

#: Words, including ones written with a typographic apostrophe (\u2019),
#: which models produce as often as a plain one.
_WORD = re.compile("[\\w'\u2019]+")
_SFX_SPLIT = re.compile(r"\s*(?:,|;|\+|/|&|\band\b)\s*")

#: Words too common to count as the loop's echo.
_STOPWORDS = frozenset(
    """
    about after also been before being could every from have here into just
    like more most only over really some such than that their them then there
    these they this those very were what when where which while will with would
    your ever still today
    """.split()
)


def word_count(text: str) -> int:
    """Words as the BEAT_TOO_LONG rule counts them. Shared with the repair,
    so the count it asks the model to beat is the count it will be judged by."""
    return len(_WORD.findall(text))


def beat_count(script: Script, ctx: RuleContext) -> list[Violation]:
    if len(script.beats) == ctx.limits.beats:
        return []
    return [
        Violation(
            "BEAT_COUNT", 0, f"{len(script.beats)} beats; a video is exactly {ctx.limits.beats}"
        )
    ]


def roles_follow_shape(script: Script, ctx: RuleContext) -> list[Violation]:
    return [
        Violation(
            "BEAT_ROLE",
            beat.n,
            f"beat {beat.n} is a {beat.role!r} beat; this format puts a {slot.role!r} beat here",
        )
        for beat, slot in zip(script.beats, ctx.shape.slots, strict=False)
        if beat.role != slot.role
    ]


def words_per_beat(script: Script, ctx: RuleContext) -> list[Violation]:
    limit = ctx.limits.max_words_per_beat
    out = []
    for beat in script.beats:
        count = word_count(beat.voice)
        if count > limit:
            out.append(
                Violation(
                    "BEAT_TOO_LONG",
                    beat.n,
                    f"{count} words; a 5-second beat holds at most {limit}",
                )
            )
    return out


def sfx_per_beat(script: Script, ctx: RuleContext) -> list[Violation]:
    limit = ctx.limits.max_sfx_per_beat
    out = []
    for beat in script.beats:
        effects = [part for part in _SFX_SPLIT.split(beat.sfx.strip()) if part]
        if len(effects) > limit:
            out.append(
                Violation("TOO_MANY_SFX", beat.n, f"{len(effects)} sound effects; at most {limit}")
            )
    return out


def year_stamps_present(script: Script, ctx: RuleContext) -> list[Violation]:
    return [
        Violation("YEAR_STAMP_MISSING", beat.n, f"a {slot.role!r} beat needs an on-screen date")
        for beat, slot in zip(script.beats, ctx.shape.slots, strict=False)
        if slot.needs_year_stamp and not beat.year_stamp.strip()
    ]


def facts_cited_where_needed(script: Script, ctx: RuleContext) -> list[Violation]:
    return [
        Violation(
            "FACT_NOT_CITED",
            beat.n,
            f"a {slot.role!r} beat must cite the approved fact it states",
        )
        for beat, slot in zip(script.beats, ctx.shape.slots, strict=False)
        if slot.needs_fact and not beat.fact_ids
    ]


def no_empty_beats(script: Script, _ctx: RuleContext) -> list[Violation]:
    return [
        Violation("EMPTY_BEAT", beat.n, "the narrator has nothing to say")
        for beat in script.beats
        if not beat.voice.strip()
    ]


def loops_back(script: Script, ctx: RuleContext) -> list[Violation]:
    """The last line must echo the first, so the video loops (SPEC.md 5.4)."""
    if len(script.beats) < 2:
        return []
    first, last = script.beats[0], script.beats[-1]
    shared = content_words(first.voice) & content_words(last.voice)
    needed = ctx.limits.loop_min_shared_words
    if len(shared) >= needed:
        return []
    return [
        Violation(
            "NO_LOOP",
            last.n,
            f"the last beat shares {len(shared)} key words with the first; it needs {needed} "
            "so the video loops back into its opening",
        )
    ]


def content_words(text: str) -> set[str]:
    """The words that count towards the loop's echo. Shared with the repair,
    so the words it asks the model to reuse are the ones this rule counts."""
    words = {w.lower().replace("\u2019", "'") for w in _WORD.findall(text)}
    return {w for w in words if len(w) >= 4 and w not in _STOPWORDS}


STRUCTURE_RULES: tuple[Rule, ...] = (
    beat_count,
    roles_follow_shape,
    no_empty_beats,
    words_per_beat,
    sfx_per_beat,
    year_stamps_present,
    facts_cited_where_needed,
    loops_back,
)
