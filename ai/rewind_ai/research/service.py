"""The research use case: fetch, extract, verify, write.

LAYER 2 (service) of SPEC.md 14.1. Depends on the SourceFetcher and LLM
protocols, never on Wikipedia or Ollama, which is why the tests below it run
offline against saved fixtures.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from rewind_ai.core.errors import ValidationFailedError
from rewind_ai.core.io import write_json_atomic
from rewind_ai.core.logging import get_logger
from rewind_ai.formats.base import ContentFormat, RawItem
from rewind_ai.llm.base import LLM
from rewind_ai.research.base import Document, Fact, ResearchResult, SourceFetcher
from rewind_ai.research.extractor import extract_from_document
from rewind_ai.research.verifier import confidence_for, verify_evidence

log = get_logger(__name__)

#: Called with (stage, percent) as work proceeds. The handler turns these into
#: gRPC Progress events; tests pass a no-op.
ProgressFn = Callable[[str, float], None]


@dataclass(frozen=True, slots=True)
class ResearchConfig:
    """Research settings from ``config/channel.yaml``.

    Note what is NOT here: how many items a gate needs, and how they are
    grouped. Those belong to the ContentFormat, because they differ by kind of
    video -- a timeline wants eight items across four eras, a myth-buster five
    across three domains.
    """

    evidence_match_threshold: float = 0.90
    max_chunk_chars: int = 6000
    #: Hard ceiling on items handed to a human. A reviewer scrolling 141 rows
    #: is a worse reviewer; the best-verified survive.
    max_items: int = 40


class ResearchService:
    """Builds a verified fact sheet for a topic."""

    def __init__(
        self,
        *,
        fetchers: list[SourceFetcher],
        llm: LLM,
        content_format: ContentFormat,
        config: ResearchConfig,
        projects_dir: Path,
    ) -> None:
        self._fetchers = fetchers
        self._llm = llm
        self._format = content_format
        self._config = config
        self._projects_dir = projects_dir

    def build(
        self,
        *,
        video_id: str,
        topic: str,
        extra_urls: list[str],
        min_facts: int | None = None,
        progress: ProgressFn | None = None,
    ) -> ResearchResult:
        """Research a topic and write facts.json.

        Raises:
            ValidationFailedError: when too few facts survive verification.
                Handing over a thin fact sheet would waste the reviewer's time
                and tempt them to approve weak material, so it fails loudly
                instead.
        """
        report = progress or (lambda _stage, _pct: None)
        rules = self._format.gate_rules()
        required = min_facts if min_facts and min_facts > 0 else rules.min_items

        # ---- 1. fetch -------------------------------------------------------
        documents = self._fetch(topic, extra_urls, report)
        if not documents:
            raise ValidationFailedError(
                f"no sources could be fetched for {topic!r}",
                detail="check your connection, or paste a source URL by hand",
            )

        # ---- 2. extract candidates -----------------------------------------
        # A DependencyUnavailableError from here is deliberately NOT caught:
        # "the model is not pulled" must reach the operator as itself, not
        # disguised as "no facts were found".
        candidates = self._extract(topic, documents, report)

        if not candidates:
            raise ValidationFailedError(
                f"the model returned no usable events for {topic!r}",
                detail=(
                    f"{len(documents)} source(s) were fetched and read, but nothing "
                    "dated could be extracted. The sources may have no timeline, or "
                    "the model may be ignoring the output schema."
                ),
            )

        # ---- 3. verify ------------------------------------------------------
        report("verifying evidence", 0.75)
        verified, rejections = self._verify(candidates, documents)

        # ---- 4. tidy --------------------------------------------------------
        report("sorting and de-duplicating", 0.9)
        facts = _sort_and_deduplicate(verified)
        facts = _cap(facts, self._config.max_items)
        _assign_ids(facts)
        _flag_conflicts(facts)

        if len(facts) < required:
            raise ValidationFailedError(
                f"only {len(facts)} facts survived verification, need {required}",
                detail=(
                    f"{len(candidates)} were proposed and {len(rejections)} were rejected. "
                    "Try a more specific topic, or paste a source URL."
                ),
            )

        # ---- 5. write -------------------------------------------------------
        report("writing facts.json", 0.97)
        path = self._write(
            video_id,
            topic,
            facts,
            documents,
            extracted=len(candidates),
            rejected=len(rejections),
            rejections=rejections,
        )

        log.info(
            "fact sheet built",
            video_id=video_id,
            facts=len(facts),
            proposed=len(candidates),
            rejected=len(rejections),
        )

        return ResearchResult(
            topic=topic,
            facts=facts,
            documents=documents,
            facts_json_path=str(path),
            format_name=self._format.name,
            group_noun=rules.group_noun,
            min_items=rules.min_items,
            min_groups=rules.min_groups,
            candidates_extracted=len(candidates),
            candidates_rejected=len(rejections),
            rejections=rejections,
        )

    # ------------------------------------------------------------------ steps

    def _fetch(self, topic: str, extra_urls: list[str], report: ProgressFn) -> list[Document]:
        documents: list[Document] = []

        for index, fetcher in enumerate(self._fetchers):
            report(f"fetching {fetcher.name}", 0.05 + 0.25 * (index / max(1, len(self._fetchers))))
            try:
                found = fetcher.fetch(topic, extra_urls=extra_urls)
            except Exception as exc:  # noqa: BLE001
                # One source being down must not lose the others.
                log.warning("source failed", source=fetcher.name, error=str(exc))
                continue

            log.info("fetched", source=fetcher.name, documents=len(found))
            documents.extend(found)

        return documents

    def _extract(self, topic: str, documents: list[Document], report: ProgressFn) -> list[Fact]:
        candidates: list[Fact] = []

        for index, document in enumerate(documents):
            report(
                f"reading {document.title}",
                0.3 + 0.45 * (index / max(1, len(documents))),
            )
            candidates.extend(
                extract_from_document(
                    self._llm,
                    self._format,
                    topic,
                    document,
                    max_chunk_chars=self._config.max_chunk_chars,
                )
            )

        return candidates

    def _verify(
        self, candidates: list[Fact], documents: list[Document]
    ) -> tuple[list[Fact], list[str]]:
        """Drop every candidate whose evidence is not in the source text.

        This is the step that makes a hallucinated date impossible rather than
        unlikely (SPEC.md 5.2, step 4).
        """
        sources = {doc.url: doc.text for doc in documents}

        verified: list[Fact] = []
        rejections: list[str] = []

        for fact in candidates:
            # Cheapest check first, and a different kind of wrong: the claim
            # may be true and sourced but still unusable FOR THIS FORMAT.
            problem = self._format.implausible_reason(
                RawItem(
                    label=fact.label,
                    sort_key=fact.sort_key,
                    context=fact.context,
                    claim=fact.claim,
                    evidence=fact.evidence,
                    extra=fact.extra,
                )
            )
            if problem:
                rejections.append(f"{fact.label}: {problem}")
                log.info("rejected implausible item", label=fact.label, reason=problem)
                continue

            result = verify_evidence(
                fact.evidence,
                sources,
                threshold=self._config.evidence_match_threshold,
            )

            if not result.verified:
                rejections.append(f"{fact.label}: {result.reason}")
                log.info(
                    "rejected unverifiable item",
                    label=fact.label,
                    claim=fact.claim[:80],
                    score=round(result.score, 3),
                )
                continue

            fact.match_score = result.score
            fact.confidence = confidence_for(result.score)
            # Attribute the fact to the document it was actually found in,
            # which is not always the one it was extracted from.
            if result.source_url:
                fact.source_url = result.source_url
                for doc in documents:
                    if doc.url == result.source_url:
                        fact.source_title = doc.title
                        break

            verified.append(fact)

        return verified, rejections

    def _write(
        self,
        video_id: str,
        topic: str,
        facts: list[Fact],
        documents: list[Document],
        *,
        extracted: int,
        rejected: int,
        rejections: list[str],
    ) -> Path:
        path = self._projects_dir / video_id / "facts.json"
        rules = self._format.gate_rules()

        payload = {
            "topic": topic,
            # The format and its rules travel WITH the sheet, so the Go gate
            # machinery can enforce a format's thresholds without knowing which
            # formats exist. Adding a format never touches Go.
            "format": self._format.name,
            "group_noun": rules.group_noun,
            "min_items": rules.min_items,
            "min_groups": rules.min_groups,
            # These used to be computed and discarded, which silently broke the
            # one objective measure of how much a model invents.
            "candidates_extracted": extracted,
            "candidates_rejected": rejected,
            "rejections": rejections,
            "facts": [
                {
                    "id": f.id,
                    "label": f.label,
                    "sort_key": f.sort_key,
                    "context": f.context,
                    "group": f.group,
                    "claim": f.claim,
                    "evidence": f.evidence,
                    "source_url": f.source_url,
                    "source_title": f.source_title,
                    "confidence": f.confidence,
                    "conflict": f.conflict,
                    "approved": f.approved,
                    "match_score": round(f.match_score, 4),
                    "added_by_human": False,
                }
                for f in facts
            ],
            "sources": [
                {
                    "url": d.url,
                    "title": d.title,
                    "fetcher": d.fetcher,
                    "char_count": d.char_count,
                }
                for d in documents
            ],
        }

        write_json_atomic(path, payload)
        return path


# ------------------------------------------------------------------ helpers


def _sort_and_deduplicate(facts: list[Fact]) -> list[Fact]:
    """Sort chronologically and drop near-duplicates.

    Several Wikipedia articles describing the same object will describe the
    same milestones, so the same event arrives more than once. Keeping the
    best-verified copy is better than showing a reviewer the same fact three
    times.
    """
    facts.sort(key=lambda f: (f.sort_key, f.label))

    kept: list[Fact] = []
    for fact in facts:
        duplicate_of = None
        for existing in kept:
            if _is_duplicate(existing, fact):
                duplicate_of = existing
                break

        if duplicate_of is None:
            kept.append(fact)
        elif fact.match_score > duplicate_of.match_score:
            # Keep whichever copy verified better.
            kept[kept.index(duplicate_of)] = fact

    return kept


def _is_duplicate(a: Fact, b: Fact) -> bool:
    """Two items are duplicates if they sort the same and say the same thing."""
    if a.sort_key != b.sort_key:
        return False

    a_words = set(a.claim.lower().split())
    b_words = set(b.claim.lower().split())
    if not a_words or not b_words:
        return False

    overlap = len(a_words & b_words) / min(len(a_words), len(b_words))
    return overlap >= 0.6


def _cap(facts: list[Fact], limit: int) -> list[Fact]:
    """Keep at most ``limit`` items, the best-verified ones.

    A real run produced 141 facts, which passes every threshold and is a
    miserable thing to review. Trimming by match score keeps the most
    defensible, then restores the format's ordering.
    """
    if limit <= 0 or len(facts) <= limit:
        return facts

    kept = sorted(facts, key=lambda f: f.match_score, reverse=True)[:limit]
    kept.sort(key=lambda f: (f.sort_key, f.label))
    return kept


def _assign_ids(facts: list[Fact]) -> None:
    """Number facts f1..fN in chronological order."""
    for index, fact in enumerate(facts, start=1):
        fact.id = f"f{index}"


def _flag_conflicts(facts: list[Fact]) -> None:
    """Mark facts that different sources date differently.

    Not an error: sources genuinely disagree about early history. Flagging it
    puts the disagreement in front of the human at Gate A, which is where the
    decision belongs.
    """
    for i, fact in enumerate(facts):
        for other in facts[i + 1 :]:
            if fact.source_url == other.source_url:
                continue
            if fact.sort_key == other.sort_key:
                continue
            if _is_same_event(fact, other):
                fact.conflict = True
                other.conflict = True


def _is_same_event(a: Fact, b: Fact) -> bool:
    a_words = set(a.claim.lower().split())
    b_words = set(b.claim.lower().split())
    if not a_words or not b_words:
        return False
    overlap = len(a_words & b_words) / min(len(a_words), len(b_words))
    return overlap >= 0.75


def load_facts(path: Path) -> Iterator[dict[str, object]]:
    """Read facts back from a written facts.json. Used by tests and tooling."""
    data = json.loads(path.read_text(encoding="utf-8"))
    yield from data.get("facts", [])
