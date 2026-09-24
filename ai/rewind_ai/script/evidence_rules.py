"""Rules that keep a script true (SPEC.md 5.4, CLAUDE.md).

The script is written by a model; the facts were approved by a human. These
rules make sure nothing the model writes adds to what the human saw:

  * every number in a beat -- spoken, on screen, or in its year stamp -- is in
    an approved fact THAT BEAT CITES. Not "somewhere in the sheet": a true
    year from another fact, dropped into the wrong beat, is still a false
    statement about this one, and it would make the fact_ids a reviewer sees
    meaningless.
  * numbers are digits, so the check above can see them at all.
  * comparisons come from Gate B, sit beside the fact they were attached to,
    and never assert anything about the brand.

Numbers are normalised by the verifier's own `numbers_in`, so "7,000" and
"7000" are one number here exactly as they are there.
"""

from __future__ import annotations

import re

from rewind_ai.relevance.rules import CLAIM_PATTERNS
from rewind_ai.research.verifier import numbers_in
from rewind_ai.script.base import Beat, Script, Violation
from rewind_ai.script.context import RuleContext
from rewind_ai.script.structure_rules import Rule

#: Number words. "one" is deliberately absent: "the one thing", "one of them"
#: are too common to police, and a claim resting on "one" is rare.
_NUMBER_WORDS = re.compile(
    r"\b(two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|"
    r"fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|"
    r"fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|billion)\b",
    re.I,
)

#: How far after a brand's name a claim verb still reads as being about it:
#: "Crocs invented", "Birkenstock was founded".
_BRAND_CLAIM_WINDOW = 40


def _beat_texts(beat: Beat) -> str:
    return " ".join((beat.voice, beat.on_screen_text, beat.year_stamp))


def facts_exist(script: Script, ctx: RuleContext) -> list[Violation]:
    return [
        Violation("UNKNOWN_FACT", beat.n, f"cites {fact_id!r}, which is not an approved fact")
        for beat in script.beats
        for fact_id in beat.fact_ids
        if fact_id not in ctx.facts
    ]


def numbers_come_from_cited_facts(script: Script, ctx: RuleContext) -> list[Violation]:
    out = []
    for beat in script.beats:
        cited = [ctx.facts[i] for i in beat.fact_ids if i in ctx.facts]
        available = set(numbers_in(" ".join(f"{f.label} {f.claim} {f.evidence}" for f in cited)))
        missing = [n for n in numbers_in(_beat_texts(beat)) if n not in available]
        if not missing:
            continue
        where = (
            f"the fact{'s' if len(cited) > 1 else ''} it cites ({', '.join(beat.fact_ids)})"
            if cited
            else "any fact, because it cites none"
        )
        out.append(
            Violation(
                "UNGROUNDED_NUMBER",
                beat.n,
                f"says {', '.join(missing)}, which is not in {where}",
            )
        )
    return out


def numbers_are_digits(script: Script, _ctx: RuleContext) -> list[Violation]:
    out = []
    for beat in script.beats:
        words = sorted({m.group(0).lower() for m in _NUMBER_WORDS.finditer(_beat_texts(beat))})
        if words:
            out.append(
                Violation(
                    "SPELLED_NUMBER",
                    beat.n,
                    f"writes {', '.join(words)} in words; use digits so the number can be "
                    "checked against the facts",
                )
            )
    return out


def references_exist(script: Script, ctx: RuleContext) -> list[Violation]:
    return [
        Violation(
            "UNKNOWN_REFERENCE",
            beat.n,
            f"uses {ref_id!r}, which was not selected at Gate B",
        )
        for beat in script.beats
        for ref_id in beat.ref_ids
        if ref_id not in ctx.references
    ]


def references_declared(script: Script, ctx: RuleContext) -> list[Violation]:
    """A selected comparison mentioned in a beat must be listed in its ref_ids.

    Found in a live run: 'like a limited drop' in a beat with ref_ids []. Every
    reference rule -- the cap of three, sitting with its fact, no claims about
    the brand -- is keyed on ref_ids, so an undeclared one escapes all three.

    Only SELECTED comparisons can be recognised here; a brand the model names
    from nowhere ("the IKEA of metallurgy") is not in any list this rule has.
    That residue is for the reviewer at Gate C.
    """
    out = []
    for beat in script.beats:
        text = _beat_texts(beat)
        for ref in ctx.references.values():
            name = ref.reference.strip()
            if not name or ref.id in beat.ref_ids:
                continue
            if re.search(rf"\b{re.escape(name)}\b", text, re.I):
                out.append(
                    Violation(
                        "UNDECLARED_REFERENCE",
                        beat.n,
                        f"mentions {name!r} without listing {ref.id} in ref_ids",
                    )
                )
    return out


def at_most_the_reference_limit(script: Script, ctx: RuleContext) -> list[Violation]:
    used = {ref_id for beat in script.beats for ref_id in beat.ref_ids}
    limit = ctx.limits.max_references
    if len(used) <= limit:
        return []
    return [
        Violation(
            "TOO_MANY_REFERENCES",
            0,
            f"{len(used)} modern references; at most {limit}, or it stops being history",
        )
    ]


def references_sit_with_their_fact(script: Script, ctx: RuleContext) -> list[Violation]:
    out = []
    for beat in script.beats:
        for ref_id in beat.ref_ids:
            ref = ctx.references.get(ref_id)
            if ref is not None and ref.linked_fact_id not in beat.fact_ids:
                out.append(
                    Violation(
                        "REFERENCE_WITHOUT_ITS_FACT",
                        beat.n,
                        f"uses {ref.reference!r}, which was attached to {ref.linked_fact_id}; "
                        "this beat does not cite it",
                    )
                )
    return out


def no_claims_about_brands(script: Script, ctx: RuleContext) -> list[Violation]:
    """A claim verb straight after a brand's name asserts something about it.

    Narrower than the relevance engine's check on purpose: a beat also states
    an approved fact ("Bessemer invented a process"), and that verb is fine.
    What is not fine is "Crocs invented ..." -- nothing about Crocs was ever
    researched, so nothing about Crocs may be asserted.
    """
    out = []
    for beat in script.beats:
        text = _beat_texts(beat)
        for ref_id in beat.ref_ids:
            ref = ctx.references.get(ref_id)
            if ref is None or not ref.reference.strip():
                continue
            name = re.escape(ref.reference.strip())
            for mention in re.finditer(name, text, re.I):
                after = text[mention.end() : mention.end() + _BRAND_CLAIM_WINDOW]
                claim = next((p.search(after) for p in CLAIM_PATTERNS if p.search(after)), None)
                if claim:
                    out.append(
                        Violation(
                            "BRAND_CLAIM",
                            beat.n,
                            f"'{ref.reference} ... {claim.group(0)}' asserts something about "
                            "the brand; compare look, price, hype or behaviour instead",
                        )
                    )
                    break
    return out


def metadata_is_grounded(script: Script, ctx: RuleContext) -> list[Violation]:
    """Titles and the description are read too. Their numbers must be in SOME
    approved fact -- they are not tied to one beat, so not to one fact."""
    available = set(
        numbers_in(" ".join(f"{f.label} {f.claim} {f.evidence}" for f in ctx.facts.values()))
    )
    texts = [("title", t) for t in [*script.title_options, script.chosen_title]]
    texts.append(("description", script.description))
    out = []
    for what, text in texts:
        missing = [n for n in numbers_in(text) if n not in available]
        if missing:
            out.append(
                Violation(
                    "UNGROUNDED_NUMBER",
                    0,
                    f"the {what} {text[:60]!r} says {', '.join(missing)}, which no approved "
                    "fact does",
                )
            )
    return out


def visuals_name_no_brands(script: Script, ctx: RuleContext) -> list[Violation]:
    """CLAUDE.md: no brand logos or product designs in generated images."""
    brands = [r.reference.strip() for r in ctx.references.values() if r.reference.strip()]
    out = []
    for beat in script.beats:
        for prompt in beat.visual_prompts:
            named = [b for b in brands if re.search(rf"\b{re.escape(b)}\b", prompt, re.I)]
            if named:
                out.append(
                    Violation(
                        "BRAND_IN_VISUAL",
                        beat.n,
                        f"an image prompt names {', '.join(named)}; images must never show "
                        "a brand -- describe the look instead",
                    )
                )
    return out


EVIDENCE_RULES: tuple[Rule, ...] = (
    facts_exist,
    numbers_come_from_cited_facts,
    numbers_are_digits,
    references_exist,
    references_declared,
    at_most_the_reference_limit,
    references_sit_with_their_fact,
    no_claims_about_brands,
    metadata_is_grounded,
    visuals_name_no_brands,
)
