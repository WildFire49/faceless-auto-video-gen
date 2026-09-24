"""What the script writer is not trusted with, filled in from the facts.

Found by the second live Gate C run: the model rounded dates in year stamps
("By 1700 AD" beside a fact about 1709) and mentioned a selected comparison
without declaring it. Both are taken off the model here, deterministically,
and only in directions that make a script MORE checkable:

  * the year stamp of a beat that needs one IS the cited fact's label -- the
    label was already grounded in its evidence (research/grounding.py), so the
    date on screen can no longer drift from the approved one;
  * a selected comparison mentioned in a beat that cites its fact is added to
    ref_ids. Declaring it subjects it to MORE rules -- the cap of three, the
    brand-claim check -- never fewer. One whose fact the beat does not cite is
    left alone, so UNDECLARED_REFERENCE stands and a human sees it.

The narration itself is never rewritten here: words are the model's job and
the validator's to judge.
"""

from __future__ import annotations

import re
from dataclasses import replace

from rewind_ai.script.base import Beat, Script
from rewind_ai.script.context import RuleContext


def normalise(script: Script, ctx: RuleContext) -> Script:
    beats = [
        _declare_references(_stamp_from_fact(beat, ctx, index), ctx)
        for index, beat in enumerate(script.beats)
    ]
    return replace(script, beats=beats)


def _stamp_from_fact(beat: Beat, ctx: RuleContext, index: int) -> Beat:
    slots = ctx.shape.slots
    if index >= len(slots) or not slots[index].needs_year_stamp:
        return beat
    fact = next((ctx.facts[i] for i in beat.fact_ids if i in ctx.facts), None)
    if fact is None or not fact.label.strip():
        return beat
    return replace(beat, year_stamp=fact.label.strip())


def _declare_references(beat: Beat, ctx: RuleContext) -> Beat:
    text = f"{beat.voice} {beat.on_screen_text}"
    added = [
        ref.id
        for ref in ctx.references.values()
        if ref.id not in beat.ref_ids
        and ref.linked_fact_id in beat.fact_ids
        and ref.reference.strip()
        and re.search(rf"\b{re.escape(ref.reference.strip())}\b", text, re.I)
    ]
    return replace(beat, ref_ids=[*beat.ref_ids, *added]) if added else beat
