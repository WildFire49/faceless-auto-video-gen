"""The myth-vs-fact format.

"Five things you believe about sleep that are wrong." Each item pairs a widely
held belief with the correction, and the correction is the part that must be
sourced.

This format exists to prove the seam. It shares NO assumptions with
history_timeline -- no dates, no chronology, no eras -- and yet the pipeline
around it is unchanged: same fetchers, same LLM provider, same evidence
verifier, same gate machinery. That is what SPEC.md 14.2 promises, and a
second format is the only way to demonstrate it rather than assert it.
"""

from __future__ import annotations

from typing import Any

from rewind_ai.core.registry import register
from rewind_ai.formats.base import GateRules, RawItem

#: Ordering is by how surprising the correction is, 1 (mild) to 5 (jaw-dropping).
#: A bounded scale rather than an open number: the script writer builds to a
#: peak, so it needs a comparable value, and an unbounded one invites the model
#: to invent precision it does not have.
MIN_SURPRISE = 1
MAX_SURPRISE = 5


@register("content_format", "myth_vs_fact")
class MythVsFact:
    """Common beliefs, paired with what the sources actually say."""

    name = "myth_vs_fact"
    description = "Widely held beliefs about a topic, paired with the sourced correction."

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
                            "myth": {"type": "string"},
                            "correction": {"type": "string"},
                            "domain": {"type": "string"},
                            "surprise": {"type": "integer"},
                            "evidence": {"type": "string"},
                        },
                        # `correction` is the claim and `evidence` supports it.
                        # The myth itself needs no source -- it is what people
                        # believe, not something asserted as true.
                        "required": ["myth", "correction", "evidence"],
                    },
                }
            },
            "required": ["items"],
        }

    def parse_item(self, raw: dict[str, Any]) -> RawItem | None:
        myth = str(raw.get("myth", "")).strip()
        correction = str(raw.get("correction", "")).strip()
        evidence = str(raw.get("evidence", "")).strip()

        if not myth or not correction or not evidence:
            return None

        try:
            surprise = int(raw.get("surprise", 3))
        except (TypeError, ValueError, OverflowError):
            surprise = 3

        return RawItem(
            # The myth is what the narrator says first, so it is the label.
            label=myth,
            # Sorted ascending, so the biggest surprise lands last -- the
            # script builds to it.
            sort_key=surprise,
            context=str(raw.get("domain", "")).strip(),
            claim=correction,
            evidence=evidence,
            extra={"myth": myth},
        )

    def implausible_reason(self, item: RawItem) -> str:
        if not (MIN_SURPRISE <= item.sort_key <= MAX_SURPRISE):
            return f"surprise rating {item.sort_key} is outside {MIN_SURPRISE}-{MAX_SURPRISE}"
        # A "myth" that restates its own correction is not a myth, and would
        # give the narrator nothing to overturn.
        if item.label.strip().lower() == item.claim.strip().lower():
            return "the myth and the correction are the same statement"
        return ""

    def group_of(self, item: RawItem) -> str:
        """Group by subject domain, so five myths are not all about one thing.

        Falls back to a bucket derived from the surprise rating when the model
        gave no domain, which still spreads items out rather than collapsing
        them all into one group and failing the variety check for the wrong
        reason.
        """
        domain = item.context.strip().lower()
        if domain:
            return domain
        return f"unspecified-{item.sort_key}"

    def gate_rules(self) -> GateRules:
        # Fewer items than a timeline: a myth needs setup and payoff, so each
        # takes more screen time. Three distinct domains keeps it varied.
        return GateRules(min_items=5, min_groups=3, group_noun="domain")


_SYSTEM = """\
You find widely believed claims that the source text contradicts or corrects.

ABSOLUTE RULES:
1. Use ONLY the text provided. Never use anything you know from training.
2. For every item, copy the sentence that supports the CORRECTION into
   "evidence" EXACTLY as it appears, character for character. Do not
   paraphrase, summarise, shorten or correct it.
3. The "myth" must be something people actually believe, stated plainly. Do
   not invent a strawman nobody holds.
4. The "correction" must be supported by the evidence sentence. If the source
   does not contradict the belief, do not include the item.
5. If the text corrects no common beliefs, return an empty list. An empty list
   is a correct answer. Inventing a myth is not.
6. Every number you write anywhere -- dates, amounts, percentages -- must
   appear in the evidence sentence. An item with a number the evidence does
   not contain is thrown away.
"""

_USER = """\
Topic: {topic}

Find common beliefs about this topic that the source text below corrects.
Return at most {max_items} items.

For each item:
- myth: the belief, as a person would state it, e.g. "You need eight hours
  of sleep every night"
- correction: what the source actually says, in one plain sentence
- domain: the subject area, e.g. "health", "manufacturing", "law".
  Use "" if unclear.
- surprise: 1 to 5, how surprising the correction is to an ordinary person.
  1 is mildly interesting, 5 is genuinely jaw-dropping.
- evidence: the exact sentence from the source below that supports the
  correction

SOURCE TEXT ({source_title}):
---
{chunk}
---
"""
