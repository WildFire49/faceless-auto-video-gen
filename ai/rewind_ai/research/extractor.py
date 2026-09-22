"""Item extraction.

LAYER 2 of SPEC.md 14.1. Turns fetched text into candidate items by asking the
LLM to point at sentences -- never to recall anything.

WHAT LIVES HERE and WHAT LIVES IN THE FORMAT
--------------------------------------------
This module owns the mechanics that are true for every kind of video: chunking
text so the model can attend to it, calling the LLM, and surviving a failure
without losing the rest of the run.

The ContentFormat owns everything about what an item IS -- the prompts, the
schema, the field meanings. Swapping a timeline for a myth-buster changes the
format, not this file (SPEC.md 14.2).

One constraint is NOT the format's to relax (CLAUDE.md): THE LLM IS NEVER THE
SOURCE OF A FACT. Three mechanisms enforce it, in increasing order of
strictness:

1. Every format's prompt tells the model to copy, not to remember.
2. Every format's schema makes ``evidence`` a required field, so it cannot
   return a claim without pointing at something.
3. The verifier checks the pointed-at sentence is really there, and drops the
   item when it is not.

Only the third is load-bearing. The first two just improve the hit rate.
"""

from __future__ import annotations

from rewind_ai.core.errors import DependencyUnavailableError
from rewind_ai.core.logging import get_logger
from rewind_ai.formats.base import ContentFormat, RawItem
from rewind_ai.llm.base import LLM
from rewind_ai.research.base import Document, Fact

log = get_logger(__name__)


def chunk_text(text: str, max_chars: int) -> list[str]:
    """Split text into chunks the model can attend to properly.

    Splits on paragraph boundaries rather than mid-sentence: a sentence cut in
    half cannot be copied as evidence, so it would be invisible to extraction
    and, worse, might tempt the model to complete it from memory.
    """
    if max_chars <= 0 or len(text) <= max_chars:
        return [text] if text.strip() else []

    chunks: list[str] = []
    current: list[str] = []
    size = 0

    for paragraph in text.split("\n\n"):
        para_len = len(paragraph) + 2

        if size + para_len > max_chars and current:
            chunks.append("\n\n".join(current))
            current, size = [], 0

        # A single paragraph larger than the budget is split on sentence
        # boundaries as a fallback, since it cannot be emitted whole.
        if para_len > max_chars:
            chunks.extend(_split_sentences(paragraph, max_chars))
            continue

        current.append(paragraph)
        size += para_len

    if current:
        chunks.append("\n\n".join(current))

    return [c for c in chunks if c.strip()]


def _split_sentences(paragraph: str, max_chars: int) -> list[str]:
    """Last-resort splitter for a paragraph bigger than one chunk."""
    out: list[str] = []
    current = ""
    for piece in paragraph.replace(". ", ".\n").split("\n"):
        if len(current) + len(piece) + 1 > max_chars and current:
            out.append(current)
            current = ""
        current += piece + " "
    if current.strip():
        out.append(current.strip())
    return out


def extract_from_document(
    llm: LLM,
    content_format: ContentFormat,
    topic: str,
    document: Document,
    *,
    max_chunk_chars: int,
    max_items_per_chunk: int = 12,
) -> list[Fact]:
    """Extract candidate items from one document.

    These are CANDIDATES. Nothing here is trusted until the verifier has
    checked each one's evidence against the source text.
    """
    candidates: list[Fact] = []
    system = content_format.system_prompt()
    schema = content_format.item_schema()

    for index, chunk in enumerate(chunk_text(document.text, max_chunk_chars)):
        prompt = content_format.user_prompt(
            topic=topic,
            source_title=document.title,
            chunk=chunk,
            max_items=max_items_per_chunk,
        )

        try:
            response = llm.complete_json(system=system, prompt=prompt, schema=schema)
        except DependencyUnavailableError:
            # The model is missing or the daemon is down. That is not a bad
            # chunk -- it will fail identically for every remaining chunk and
            # every remaining document. Propagating immediately means the
            # operator is told "the model is not pulled" rather than the far
            # more confusing "0 facts survived verification", and saves
            # hammering a dead service twenty more times.
            raise
        except Exception as exc:  # noqa: BLE001
            # A content problem with one chunk: unparseable output, a refusal.
            # Skipping it must not lose the items from every other chunk.
            log.warning(
                "extraction failed for a chunk",
                document=document.title,
                chunk_index=index,
                error=str(exc),
            )
            continue

        for raw in response.get("items", []):
            if not isinstance(raw, dict):
                continue
            item = content_format.parse_item(raw)
            if item is not None:
                candidates.append(_to_fact(item, content_format, document))

    log.info("extracted candidates", document=document.title, candidates=len(candidates))
    return candidates


def _to_fact(item: RawItem, content_format: ContentFormat, document: Document) -> Fact:
    """Attach provenance and the format's grouping to a parsed item."""
    return Fact(
        label=item.label,
        sort_key=item.sort_key,
        context=item.context,
        claim=item.claim,
        evidence=item.evidence,
        source_url=document.url,
        source_title=document.title,
        group=content_format.group_of(item),
        extra=dict(item.extra),
    )
