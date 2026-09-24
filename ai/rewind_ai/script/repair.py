"""Repair the beats that break a rule, and lock every other beat.

Found by the first live Gate C run. qwen3:8b wrote 23-31 word beats against a
14-word limit; regenerating the WHOLE script with the violations fed back made
it worse -- the retry lost year stamps and invented numbers while shortening
lines, because every beat was up for grabs again. A model is much better at
"shorten this one line, keep its facts" than at composing nine lines under a
word budget at once.

So when every problem is local to a beat, only those beats are rewritten, and
only their words: a repair can never change which facts a beat cites (the
numbers are checked against them), its role, or any beat that was not broken.
Problems that are not local -- the wrong number of beats, a title -- still go
back for full regeneration.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from rewind_ai.script.base import Beat, Script, ScriptFact, ScriptReference, Violation
from rewind_ai.script.codec import narration
from rewind_ai.script.structure_rules import content_words, word_count

#: Rules a rewrite of one beat's words can fix. Anything else is structural.
LOCAL_RULES = frozenset(
    {
        "BEAT_TOO_LONG",
        "UNGROUNDED_NUMBER",
        "SPELLED_NUMBER",
        "YEAR_STAMP_MISSING",
        "EMPTY_BEAT",
        "BRAND_CLAIM",
        "BRAND_IN_VISUAL",
        "TOO_MANY_SFX",
        "UNDECLARED_REFERENCE",
        # Fixable by dropping the reference from ref_ids. Treating it as
        # structural sent a live run back to a full rewrite that lost the
        # progress the repair had made.
        "REFERENCE_WITHOUT_ITS_FACT",
        "NO_LOOP",
    }
)

#: What a repair may change. fact_ids and role are deliberately absent.
_WRITABLE = ("year_stamp", "on_screen_text", "sfx", "visual_prompts", "ref_ids")

#: Models miscount words; asking for a little under the limit lands under it.
WORD_HEADROOM = 2


SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "beats": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer"},
                    "fact_line": {"type": "string"},
                    "punch": {"type": "string"},
                    "year_stamp": {"type": "string"},
                    "on_screen_text": {"type": "string"},
                    "sfx": {"type": "string"},
                    "visual_prompts": {"type": "array", "items": {"type": "string"}},
                    "ref_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["n", "fact_line", "punch"],
            },
        }
    },
    "required": ["beats"],
}


@dataclass(frozen=True, slots=True)
class BrokenBeat:
    """One beat to repair, with everything the prompt needs to show."""

    beat: Beat
    words: int
    violations: list[Violation]
    facts: list[ScriptFact]
    references: list[ScriptReference]
    #: For a beat that must loop back: the opening's words it may reuse.
    echo_words: list[str]


def is_repairable(violations: list[Violation]) -> bool:
    """True when every violation is inside a beat and a rewrite can fix it."""
    return bool(violations) and all(v.beat > 0 and v.rule in LOCAL_RULES for v in violations)


def broken_beats(
    script: Script,
    violations: list[Violation],
    facts: dict[str, ScriptFact],
    references: dict[str, ScriptReference],
) -> list[BrokenBeat]:
    """The beats to rewrite, in order, each with its own violations and facts."""
    by_beat: dict[int, list[Violation]] = {}
    for v in violations:
        by_beat.setdefault(v.beat, []).append(v)
    opening = sorted(content_words(script.beats[0].voice)) if script.beats else []
    return [
        BrokenBeat(
            beat=beat,
            words=word_count(beat.voice),
            violations=by_beat[beat.n],
            facts=[facts[i] for i in beat.fact_ids if i in facts],
            # Only comparisons tied to a fact THIS beat cites. A live repair
            # offered every one and the model dropped 'unboxing video' into a
            # beat that did not cite its fact.
            references=[r for r in references.values() if r.linked_fact_id in beat.fact_ids],
            echo_words=opening if any(v.rule == "NO_LOOP" for v in by_beat[beat.n]) else [],
        )
        for beat in script.beats
        if beat.n in by_beat
    ]


def merge(script: Script, raw: dict[str, Any], allowed: set[int]) -> Script:
    """Apply a repair: only beats in `allowed`, only their writable fields."""
    edits: dict[int, dict[str, Any]] = {}
    for item in raw.get("beats", []) if isinstance(raw.get("beats"), list) else []:
        if not isinstance(item, dict):
            continue
        try:
            n = int(item.get("n", 0))
        except (TypeError, ValueError):
            continue
        if n in allowed:
            edits[n] = item

    beats = [_apply(beat, edits[beat.n]) if beat.n in edits else beat for beat in script.beats]
    return replace(script, beats=beats)


def _apply(beat: Beat, item: dict[str, Any]) -> Beat:
    changes: dict[str, Any] = {}
    spoken = narration(item)
    if spoken:
        changes["voice"] = spoken
    for field in _WRITABLE:
        if field not in item:
            continue
        value = item[field]
        if field in ("visual_prompts", "ref_ids"):
            if isinstance(value, list):
                changes[field] = [str(v).strip() for v in value if str(v).strip()]
        elif isinstance(value, str):
            changes[field] = value.strip()
    return replace(beat, **changes)
