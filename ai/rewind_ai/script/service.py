"""The script use case: approved facts + chosen comparisons -> script.json.

LAYER 2 (service) of SPEC.md 14.1.

Draft, validate, and fix, up to the configured attempts (SPEC.md 5.4). A fix
is a REPAIR when every broken rule is inside a beat -- only those beats are
rewritten, every other beat locked (see repair.py for why) -- and a full
regeneration with the broken rules fed back otherwise. If none passes, the attempt with the
fewest violations is written anyway, violations included: Gate C shows them
and cannot be approved until they are gone, and a human fixing two rules
inline is faster and better than a fourth roll of the dice. The script is
never passed off as valid when it is not.

What the model does NOT write: the beat numbers (assigned by position) and
the source list (built from the facts the beats cite).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from rewind_ai.core.errors import ValidationFailedError
from rewind_ai.core.io import write_json_atomic
from rewind_ai.core.logging import get_logger
from rewind_ai.formats.base import ContentFormat
from rewind_ai.llm.base import LLM
from rewind_ai.llm.templates import Templates
from rewind_ai.script import codec, repair
from rewind_ai.script.base import Script, ScriptFact, ScriptReference, Violation
from rewind_ai.script.context import Limits, RuleContext
from rewind_ai.script.normalise import normalise
from rewind_ai.script.rules import validate

log = get_logger(__name__)

ProgressFn = Callable[[str, float], None]


@dataclass(frozen=True, slots=True)
class ScriptConfig:
    """The script: block of config/channel.yaml, and the reference limit."""

    limits: Limits
    max_attempts: int = 3
    max_repairs: int = 3
    title_options: int = 3
    punch_words: int = 5


class ScriptService:
    """Writes and checks beat scripts."""

    def __init__(
        self,
        *,
        llm: LLM,
        content_format: ContentFormat,
        style_bible: str,
        config: ScriptConfig,
        templates: Templates,
        projects_dir: Path,
        repair_llm: LLM | None = None,
    ) -> None:
        self._llm = llm
        # A repair is an edit, not a composition: it wants a model that does
        # what it is told. The fourth live run's repairs, at drafting
        # temperature, kept returning the same broken beats. Defaults to the
        # drafting model so a single-model setup still works.
        self._repair_llm = repair_llm or llm
        self._format = content_format
        self._style_bible = style_bible
        self._config = config
        self._templates = templates
        self._projects_dir = projects_dir

    # ------------------------------------------------------------ generate

    def generate(
        self,
        *,
        video_id: str,
        topic: str,
        angle: str,
        facts: list[ScriptFact],
        references: list[ScriptReference],
        progress: ProgressFn | None = None,
    ) -> Script:
        report = progress or (lambda _stage, _pct: None)
        if not facts:
            raise ValidationFailedError(
                "no approved facts to write a script from",
                detail="approve facts at Gate A first",
            )

        ctx = self._context(facts, references)
        drafts = self._config.max_attempts
        best: Script | None = None
        made = 0

        for attempt in range(1, drafts + 1):
            made = attempt
            how = "writing" if best is None else "rewriting"
            report(f"{how} the script (attempt {attempt} of {drafts})", attempt / (drafts + 1))
            feedback = best.violations if best else []
            draft = self._checked(self._draft(topic, angle, ctx, feedback), ctx, video_id, how)
            # Repair THIS draft, then compare it with the best so far. The
            # fourth live run compared first: a fresh draft with more
            # violations was discarded on arrival, and the repairs went on
            # patching the old, stuck script -- two whole drafts wasted.
            best = _better(best, self._repair_until_valid(draft, ctx, video_id, report))
            if not best.violations:
                break

        assert best is not None  # the loop runs at least once
        # Drafts MADE, not which was kept. The first live run kept draft 1 of
        # 3, and Gate C then said "tried 1 time". Repairs do not count: they
        # are passes within a draft (config: script.max_repairs).
        best = replace(best, attempts=made)
        report("writing script.json", 0.97)
        path = self._projects_dir / video_id / "script.json"
        write_json_atomic(path, codec.to_json(best))
        return best

    def _repair_until_valid(
        self, best: Script, ctx: RuleContext, video_id: str, report: ProgressFn
    ) -> Script:
        """Rewrite only the broken beats, up to max_repairs passes per draft.

        Each pass builds on the best version of THIS draft; a pass that makes
        things worse is discarded rather than repaired again.
        """
        for n in range(1, self._config.max_repairs + 1):
            if not repair.is_repairable(best.violations):
                break
            report(f"repairing {len({v.beat for v in best.violations})} beats (pass {n})", 0.9)
            best = _better(
                best, self._checked(self._repair(best, ctx), ctx, video_id, f"repair {n}")
            )
        return best

    def _checked(self, script: Script, ctx: RuleContext, video_id: str, how: str) -> Script:
        """Fill in what the model is not trusted with, then validate."""
        script = normalise(script, ctx)
        script = replace(
            script, sources=_sources(script, ctx.facts), violations=validate(script, ctx)
        )
        log.info(
            "script attempt",
            video_id=video_id,
            how=how,
            violations=[f"{v.rule}@{v.beat}" for v in script.violations],
        )
        return script

    def _repair(self, script: Script, ctx: RuleContext) -> Script:
        """Rewrite only the broken beats; every other beat stays as it is."""
        broken = repair.broken_beats(script, script.violations, ctx.facts, ctx.references)
        prompt = self._templates.render(
            "script_repair.jinja",
            beats=script.beats,
            broken=broken,
            loop_words=ctx.limits.loop_min_shared_words,
            **self._budget(ctx, headroom=repair.WORD_HEADROOM),
        )
        raw = self._repair_llm.complete_json(
            system=self._system_prompt(ctx), prompt=prompt, schema=repair.SCHEMA
        )
        return repair.merge(script, raw, allowed={b.beat.n for b in broken})

    def _system_prompt(self, ctx: RuleContext) -> str:
        return self._templates.render(
            "script_system.jinja",
            beats=ctx.limits.beats,
            style_bible=self._style_bible,
            max_words=ctx.limits.max_words_per_beat,
            **self._budget(ctx),
        )

    def _budget(self, ctx: RuleContext, headroom: int = 0) -> dict[str, int]:
        """Words for the fact line and the punch, summing to the beat limit."""
        total = max(2, ctx.limits.max_words_per_beat - headroom)
        punch = max(1, min(self._config.punch_words, total - 1))
        return {"fact_words": total - punch, "punch_words": punch}

    def _draft(self, topic: str, angle: str, ctx: RuleContext, feedback: list[Violation]) -> Script:
        system = self._system_prompt(ctx)
        prompt = self._templates.render(
            "script_user.jinja",
            topic=topic,
            angle=angle.strip(),
            facts=list(ctx.facts.values()),
            references=list(ctx.references.values()),
            max_references=ctx.limits.max_references,
            slots=ctx.shape.slots,
            title_options=self._config.title_options,
            feedback=feedback,
        )
        raw = self._llm.complete_json(system=system, prompt=prompt, schema=codec.SCHEMA)
        return codec.from_model(raw)

    # ------------------------------------------------------------ validate

    def check(
        self, script: Script, facts: list[ScriptFact], references: list[ScriptReference]
    ) -> list[Violation]:
        """Validate a script someone edited. No model involved."""
        return validate(script, self._context(facts, references))

    def _context(self, facts: list[ScriptFact], references: list[ScriptReference]) -> RuleContext:
        return RuleContext(
            shape=self._format.script_shape(self._config.limits.beats),
            facts={f.id: f for f in facts},
            references={r.id: r for r in references},
            limits=self._config.limits,
        )


def _better(best: Script | None, candidate: Script) -> Script:
    """The one with fewer violations; the incumbent on a tie."""
    if best is None or len(candidate.violations) < len(best.violations):
        return candidate
    return best


def _sources(script: Script, facts: dict[str, ScriptFact]) -> list[str]:
    """Source URLs of the cited facts, in order of first use.

    Built here, never by the model: a model asked for sources will produce
    plausible URLs that do not exist.
    """
    seen: list[str] = []
    for beat in script.beats:
        for fact_id in beat.fact_ids:
            fact = facts.get(fact_id)
            if fact and fact.source_url and fact.source_url not in seen:
                seen.append(fact.source_url)
    return seen
