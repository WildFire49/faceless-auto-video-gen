"""The relevance use case: bank + trends -> proposed comparisons.

LAYER 2 (service) of SPEC.md 14.1.

The shape mirrors the research service deliberately: gather material, ask the
model, then throw out anything that fails the rules, counting and explaining
every rejection. What differs is what is being checked. Research verifies that
a quoted sentence exists; relevance verifies that a joke is safe to tell.

FORMAT-NEUTRAL by design. A comparison attaches to an approved item's claim,
and "compare this to something people recognise" reads the same whether the
item is a date on a timeline or a debunked belief.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from rewind_ai.core.errors import ValidationFailedError
from rewind_ai.core.io import write_json_atomic
from rewind_ai.core.logging import get_logger
from rewind_ai.llm.base import LLM
from rewind_ai.relevance import rules
from rewind_ai.relevance.bank import ReferenceBank, TrendCache
from rewind_ai.relevance.base import Kind, Proposal, RelevanceResult

log = get_logger(__name__)

ProgressFn = Callable[[str, float], None]

#: How long a HOT reference stays usable. Three weeks: long enough to research,
#: script, record and render at a sustainable pace; short enough that a video
#: published after it has genuinely dated (SPEC.md 5.3).
HOT_SHELF_LIFE = timedelta(days=21)


@dataclass(frozen=True, slots=True)
class ApprovedFact:
    """The slice of a fact the relevance engine is allowed to see.

    Deliberately not the whole Fact: this service has no business with
    evidence or sources, and handing them over would invite the model to
    reason about their truth rather than just be funny about them.
    """

    id: str
    label: str
    claim: str
    group: str = ""


@dataclass(frozen=True, slots=True)
class RelevanceConfig:
    """Relevance settings from config/channel.yaml."""

    #: Hard ceiling on how many comparisons a human may SELECT. Three is the
    #: point at which a history video stops being history and starts being an
    #: advert (SPEC.md 5.3).
    max_selectable: int = 3
    #: How many to generate for the human to choose from.
    max_proposals: int = 8


SYSTEM_PROMPT = """\
You write short, dry comparisons between historical facts and things people
recognise today.

ABSOLUTE RULES:
1. NEVER state a fact about a brand, company or person. You may say what
   something LOOKS like, costs, feels like, or how people behave about it.
   "Roman caligae were basically Birkenstocks with spikes" is allowed.
   "Birkenstock was founded in Rome" is forbidden and false.
2. Every comparison must attach to ONE of the numbered facts given to you.
   Use its exact id.
3. Never reference tragedies, disasters, politics, religion, or real private
   individuals. No jokes about groups of people.
4. Be dry and understated. No exclamation marks. No "imagine if". The humour
   comes from the gap between then and now, not from being loud.
5. If you cannot make a good comparison for a fact, skip it. Fewer good ones
   beat more weak ones.

Write like someone unimpressed by history, not like an advert.
"""

USER_PROMPT = """\
Topic: {topic}

APPROVED FACTS — you may only attach a comparison to one of these:
{facts}

MODERN THINGS you may compare to — you may use NOTHING else:
{references}

Write at most {max_items} comparisons. For each:
- reference: the modern thing you used, copied EXACTLY from the list above.
  Copy one whole line. Anything not on that list is thrown away.
- linked_fact_id: the id of the fact it attaches to, e.g. "f3"
- comparison: the line itself, one sentence, as a narrator would say it
- why_funny: one short sentence on why it works
- accuracy_note: what exactly is being compared (look, price, hype,
  behaviour), so a reviewer can confirm it is not a claim about the brand
"""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "reference": {"type": "string"},
                    "linked_fact_id": {"type": "string"},
                    "comparison": {"type": "string"},
                    "why_funny": {"type": "string"},
                    "accuracy_note": {"type": "string"},
                },
                "required": ["reference", "linked_fact_id", "comparison", "why_funny"],
            },
        }
    },
    "required": ["items"],
}


class RelevanceService:
    """Proposes modern comparisons for approved facts."""

    def __init__(
        self,
        *,
        llm: LLM,
        bank: ReferenceBank,
        trends: TrendCache,
        config: RelevanceConfig,
        projects_dir: Path,
    ) -> None:
        self._llm = llm
        self._bank = bank
        self._trends = trends
        self._config = config
        self._projects_dir = projects_dir

    def propose(
        self,
        *,
        video_id: str,
        topic: str,
        facts: list[ApprovedFact],
        max_proposals: int | None = None,
        progress: ProgressFn | None = None,
    ) -> RelevanceResult:
        """Generate comparisons and write references.json."""
        report = progress or (lambda _stage, _pct: None)
        wanted = max_proposals or self._config.max_proposals

        if not facts:
            raise ValidationFailedError(
                "no approved facts to attach comparisons to",
                detail="approve some facts at Gate A first",
            )

        # ---- 1. gather material -------------------------------------------
        report("reading the reference bank", 0.1)
        bank_refs = self._bank.for_topic(topic)

        report("checking today's trends", 0.25)
        cached = self._trends.get()
        hot_terms = {t.term for t in cached.trends}

        # ---- 2. ask the model ---------------------------------------------
        report("writing comparisons", 0.5)
        candidates = self._generate(topic, facts, bank_refs, cached.trends, wanted)

        # ---- 3. check every one -------------------------------------------
        report("checking them against the rules", 0.8)
        offered = _offered(bank_refs, cached.trends)
        kept, rejections = self._filter(candidates, facts, hot_terms, offered)

        if not kept:
            raise ValidationFailedError(
                f"no usable comparisons for {topic!r}",
                detail=(
                    f"{len(candidates)} were proposed and all were rejected. "
                    "You can still write your own at Gate B."
                ),
            )

        _assign_ids(kept)

        # ---- 4. write ------------------------------------------------------
        report("writing references.json", 0.95)
        path = self._write(
            video_id,
            topic,
            kept,
            cached.sources,
            cached.fetched_at,
            generated=len(candidates),
            rejections=rejections,
        )

        log.info(
            "references proposed",
            video_id=video_id,
            kept=len(kept),
            generated=len(candidates),
            rejected=len(rejections),
        )

        return RelevanceResult(
            topic=topic,
            proposals=kept,
            references_json_path=str(path),
            max_selectable=self._config.max_selectable,
            trend_sources=cached.sources,
            trends_fetched_at=cached.fetched_at.isoformat(),
            candidates_generated=len(candidates),
            candidates_rejected=len(rejections),
            rejections=rejections,
        )

    # ------------------------------------------------------------------ steps

    def _generate(
        self,
        topic: str,
        facts: list[ApprovedFact],
        bank_refs: dict[str, list[str]],
        trends: list[Any],
        wanted: int,
    ) -> list[Proposal]:
        fact_lines = "\n".join(f"  {f.id}: [{f.label}] {f.claim}" for f in facts)

        # ONE ITEM PER LINE, and no category headings. An earlier version
        # grouped them ("home: Dyson, air fryer, IKEA flat-pack instructions")
        # and the model dutifully answered reference="home" -- Gate B then
        # showed a card titled "home". A flat list has nothing to confuse for
        # an answer, and _filter rejects anything that is not on it.
        reference_lines = [f"  {item}" for item in sorted(_offered(bank_refs, trends).values())]

        prompt = USER_PROMPT.format(
            topic=topic,
            facts=fact_lines,
            references="\n".join(reference_lines) or "  (nothing available)",
            max_items=wanted,
        )

        try:
            response = self._llm.complete_json(system=SYSTEM_PROMPT, prompt=prompt, schema=SCHEMA)
        except Exception as exc:
            log.warning("comparison generation failed", error=str(exc))
            raise

        trend_terms = {t.term.lower() for t in trends}
        out: list[Proposal] = []
        for raw in response.get("items", []):
            proposal = _to_proposal(raw, trend_terms)
            if proposal is not None:
                out.append(proposal)
        return out

    def _filter(
        self,
        candidates: list[Proposal],
        facts: list[ApprovedFact],
        hot_terms: set[str],
        offered: dict[str, str],
    ) -> tuple[list[Proposal], list[str]]:
        """Drop every comparison that breaks a rule, saying why."""
        known_ids = {f.id for f in facts}
        kept: list[Proposal] = []
        rejections: list[str] = []
        seen: set[str] = set()

        for proposal in candidates:
            # SAFETY FIRST, before the mechanical checks. A comparison can be
            # both tasteless and mis-referenced, and "reaches for a tragedy" is
            # the reason a human needs to read -- not "that brand is not on the
            # list". Whichever check runs first is the one that gets reported.
            reason = rules.check(proposal)
            if reason:
                rejections.append(f"{proposal.reference}: {reason}")
                log.info("rejected comparison", reference=proposal.reference, reason=reason)
                continue

            # The bank is curated by hand and is the single biggest lever on
            # whether the jokes land. A reference the model invented has had no
            # such judgement applied to it, so it does not get into a video.
            canonical = offered.get(proposal.reference.strip().lower())
            if canonical is None:
                rejections.append(f"{proposal.reference}: not one of the modern things on offer")
                continue
            # Normalise to the bank's own spelling, so two proposals that
            # differ only in case cannot both survive the duplicate check.
            proposal.reference = canonical

            # A comparison attached to a fact the human did not approve would
            # smuggle unapproved material into the script.
            if proposal.linked_fact_id not in known_ids:
                rejections.append(
                    f"{proposal.reference}: attached to {proposal.linked_fact_id!r}, "
                    "which is not an approved fact"
                )
                continue

            # The same reference twice makes the video feel like one joke.
            key = proposal.reference.strip().lower()
            if key in seen:
                rejections.append(f"{proposal.reference}: already used for another fact")
                continue
            seen.add(key)

            if proposal.reference in hot_terms:
                proposal.kind = Kind.HOT
                proposal.fresh_until = (datetime.now(UTC) + HOT_SHELF_LIFE).date()

            kept.append(proposal)

        return kept, rejections

    def _write(
        self,
        video_id: str,
        topic: str,
        proposals: list[Proposal],
        sources: list[str],
        fetched_at: datetime,
        *,
        generated: int,
        rejections: list[str],
    ) -> Path:
        path = self._projects_dir / video_id / "references.json"
        write_json_atomic(
            path,
            {
                "topic": topic,
                "max_selectable": self._config.max_selectable,
                "trend_sources": sources,
                "trends_fetched_at": fetched_at.isoformat(),
                # What the filter threw out and why. Persisted, not just
                # returned: Go rebuilds the whole Gate B view from this file
                # on every request, so anything missing here is a provenance
                # panel that reads "0 candidates, 0 rejected" forever.
                "candidates_generated": generated,
                "candidates_rejected": len(rejections),
                "rejections": rejections,
                "proposals": [
                    {
                        "id": p.id,
                        "reference": p.reference,
                        "kind": str(p.kind),
                        "linked_fact_id": p.linked_fact_id,
                        "comparison": p.comparison,
                        "why_funny": p.why_funny,
                        "accuracy_note": p.accuracy_note,
                        "fresh_until": p.fresh_until.isoformat() if p.fresh_until else "",
                        "source": p.source,
                        "selected": p.selected,
                    }
                    for p in proposals
                ],
            },
        )
        return path


def _offered(bank_refs: dict[str, list[str]], trends: list[Any]) -> dict[str, str]:
    """Every modern thing the model may use, as ``lowercase -> as written``.

    Built once and used twice: to write the prompt, and to check the answer.
    Deriving both from the same function is the point — if they could drift,
    the model would be blamed for breaking a rule it was never shown.

    Categories are how the BANK is organised, not something the model needs;
    they are flattened away here.
    """
    offered: dict[str, str] = {}
    for items in bank_refs.values():
        for item in items:
            offered.setdefault(item.strip().lower(), item.strip())
    for trend in trends[:12]:
        offered.setdefault(trend.term.strip().lower(), trend.term.strip())
    offered.pop("", None)
    return offered


def _to_proposal(raw: Any, trend_terms: set[str]) -> Proposal | None:
    """Convert one raw model object, or None if unusable."""
    if not isinstance(raw, dict):
        return None

    reference = str(raw.get("reference", "")).strip()
    comparison = str(raw.get("comparison", "")).strip()
    fact_id = str(raw.get("linked_fact_id", "")).strip()

    if not reference or not comparison or not fact_id:
        return None

    return Proposal(
        reference=reference,
        kind=Kind.HOT if reference.lower() in trend_terms else Kind.EVERGREEN,
        linked_fact_id=fact_id,
        comparison=comparison,
        why_funny=str(raw.get("why_funny", "")).strip(),
        accuracy_note=str(raw.get("accuracy_note", "")).strip(),
    )


def _assign_ids(proposals: list[Proposal]) -> None:
    """Number proposals r1..rN."""
    for index, proposal in enumerate(proposals, start=1):
        proposal.id = f"r{index}"


def stale_ids(proposals: list[Proposal], today: date | None = None) -> list[str]:
    """Selected HOT proposals whose freshness has passed (SPEC.md 5.3)."""
    now = today or datetime.now(UTC).date()
    return [
        p.id for p in proposals if p.selected and p.fresh_until is not None and p.fresh_until < now
    ]
