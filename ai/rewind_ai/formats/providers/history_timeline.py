"""The history-timeline format: REWIND's original series concept.

An everyday object, traced from its oldest known version to today, one era per
beat. This is now ONE format rather than the whole product (SPEC.md 1).
"""

from __future__ import annotations

from typing import Any

from rewind_ai.core.registry import register
from rewind_ai.formats.base import GateRules, RawItem

#: The oldest year this format can use. Generous: the earliest stone tools are
#: around 3.3 million years old, so anything older is not the history of a made
#: object. It exists to reject geological time -- asked about "iron", a model
#: correctly offers the formation of the Earth's core at -4,600,000,000, which
#: is true, and useless for a video about everyday objects. That exact value
#: crashed a run once; see tests/test_verifier.py.
MIN_PLAUSIBLE_YEAR = -4_000_000

#: The newest. A fact dated past this is a mistake, not a prediction.
MAX_PLAUSIBLE_YEAR = 2100


@register("content_format", "history_timeline")
class HistoryTimeline:
    """A chronological timeline of a thing's history."""

    name = "history_timeline"
    description = "A timeline from the oldest known version of something to today."

    def system_prompt(self) -> str:
        return _SYSTEM

    def user_prompt(self, *, topic: str, source_title: str, chunk: str, max_items: int) -> str:
        return _USER.format(
            topic=topic,
            source_title=source_title,
            chunk=chunk,
            max_items=max_items,
        )

    def item_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "year_label": {"type": "string"},
                            "sort_year": {"type": "integer"},
                            "place": {"type": "string"},
                            "claim": {"type": "string"},
                            "evidence": {"type": "string"},
                        },
                        "required": ["year_label", "sort_year", "claim", "evidence"],
                    },
                }
            },
            "required": ["items"],
        }

    def parse_item(self, raw: dict[str, Any]) -> RawItem | None:
        label = str(raw.get("year_label", "")).strip()
        claim = str(raw.get("claim", "")).strip()
        evidence = str(raw.get("evidence", "")).strip()

        if not label or not claim or not evidence:
            return None

        try:
            sort_key = int(raw.get("sort_year", 0))
        except (TypeError, ValueError, OverflowError):
            return None

        return RawItem(
            label=label,
            sort_key=sort_key,
            context=str(raw.get("place", "")).strip(),
            claim=claim,
            evidence=evidence,
            extra={},
        )

    def implausible_reason(self, item: RawItem) -> str:
        if item.sort_key < MIN_PLAUSIBLE_YEAR:
            return (
                f"year {item.sort_key} is geological rather than historical "
                f"(older than {MIN_PLAUSIBLE_YEAR}); true, perhaps, but not the "
                "history of a made object"
            )
        if item.sort_key > MAX_PLAUSIBLE_YEAR:
            return f"year {item.sort_key} is in the future (later than {MAX_PLAUSIBLE_YEAR})"
        return ""

    def group_of(self, item: RawItem) -> str:
        """Bucket a year into a broad historical era.

        The buckets widen as they go back, because "7000 BC vs 6000 BC" is one
        era to a viewer while "1950 vs 1990" is clearly two. A rough measure of
        variety, not a historian's periodisation.
        """
        year = item.sort_key
        if year < -3000:
            return "prehistory"
        if year < -500:
            return "ancient"
        if year < 500:
            return "classical"
        if year < 1400:
            return "medieval"
        if year < 1750:
            return "early-modern"
        if year < 1900:
            return "industrial"
        if year < 1980:
            return "20th-century"
        return "modern"

    def gate_rules(self) -> GateRules:
        # SPEC.md 5.2: at least 8 facts spanning at least 4 eras.
        return GateRules(min_items=8, min_groups=4, group_noun="era")


_SYSTEM = """\
You extract historical timeline events from source text.

ABSOLUTE RULES:
1. Use ONLY the text provided. Never use anything you know from training.
2. For every event, copy the supporting sentence from the source into
   "evidence" EXACTLY as it appears, character for character. Do not
   paraphrase, summarise, shorten or correct it.
3. If the source does not state a date for an event, do not include that
   event. An undated event is useless to us.
4. Prefer events that mark a real change in how the thing was made or used.
   Skip trivia, prices, and anything about a single individual's life.
5. Ignore geological or astronomical timescales. We want human history, not
   the age of the Earth.
6. If the text contains no usable dated events, return an empty list. An
   empty list is a correct answer. Inventing an event is not.

The "claim" is your own one-sentence summary for a narrator to read.
The "evidence" is the source's words, untouched.
"""

_USER = """\
Topic: {topic}

Extract every dated historical event about this topic from the source text
below. Return at most {max_items} events.

For each event:
- year_label: how a narrator would say the date, e.g. "1882", "~7000 BC",
  "around 9,000 years ago"
- sort_year: the year as a number for sorting. Negative for BC.
  7000 BC is -7000. 1882 is 1882. If the text says "9,000 years ago",
  use approximately -7000.
- place: where it happened, e.g. "Oregon, USA", "Han dynasty China".
  Use "" if the source does not say.
- claim: your one-sentence summary, in plain language
- evidence: the exact sentence from the source below that supports it

SOURCE TEXT ({source_title}):
---
{chunk}
---
"""
