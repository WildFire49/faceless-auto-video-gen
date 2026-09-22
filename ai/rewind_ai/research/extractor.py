"""Fact extraction.

LAYER 2 of SPEC.md 14.1. Turns fetched text into candidate facts by asking the
LLM to point at sentences -- never to recall anything.

Everything here is built around one constraint (CLAUDE.md): THE LLM IS NEVER
THE SOURCE OF A FACT. Three mechanisms enforce it, in increasing order of
strictness:

1. The prompt tells the model to copy, not to remember.
2. The JSON schema makes ``evidence`` a required field, so it cannot return a
   claim without pointing at something.
3. The verifier (verifier.py) checks the pointed-at sentence is really there,
   and drops the fact when it is not.

Only the third one is load-bearing. The first two just improve the hit rate.
"""

from __future__ import annotations

from typing import Any

from rewind_ai.core.errors import DependencyUnavailableError
from rewind_ai.core.logging import get_logger
from rewind_ai.llm.base import LLM
from rewind_ai.research.base import Document, Fact

log = get_logger(__name__)

SYSTEM_PROMPT = """\
You extract historical timeline events from source text.

ABSOLUTE RULES:
1. Use ONLY the text provided. Never use anything you know from training.
2. For every event, copy the supporting sentence from the source into
   "evidence" EXACTLY as it appears, character for character. Do not
   paraphrase, summarise, shorten or correct it.
3. If the source does not state a date for an event, do not include that
   event. An undated event is useless to us.
4. Prefer events that mark a real change in how the object was made or used.
   Skip trivia, prices, and anything about a single individual's life.
5. If the text contains no usable dated events, return an empty list. An
   empty list is a correct answer. Inventing an event is not.

The "claim" is your own one-sentence summary for a narrator to read.
The "evidence" is the source's words, untouched.
"""

USER_PROMPT = """\
Topic: {topic}

Extract every dated historical event about this topic from the source text
below. Return at most {max_facts} events.

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

#: The JSON schema handed to the model. Ollama constrains generation to it, so
#: the model physically cannot return prose where an object is expected.
FACTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "events": {
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
                # evidence is required: without it there is nothing to verify,
                # and an unverifiable claim is exactly what this project must
                # never produce.
                "required": ["year_label", "sort_year", "claim", "evidence"],
            },
        }
    },
    "required": ["events"],
}


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
            for sentence in _split_sentences(paragraph, max_chars):
                chunks.append(sentence)
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
    topic: str,
    document: Document,
    *,
    max_chunk_chars: int,
    max_facts_per_chunk: int = 12,
) -> list[Fact]:
    """Extract candidate facts from one document.

    These are CANDIDATES. Nothing here is trusted until the verifier has
    checked each one's evidence against the source text.
    """
    candidates: list[Fact] = []

    for index, chunk in enumerate(chunk_text(document.text, max_chunk_chars)):
        prompt = USER_PROMPT.format(
            topic=topic,
            max_facts=max_facts_per_chunk,
            source_title=document.title,
            chunk=chunk,
        )

        try:
            response = llm.complete_json(
                system=SYSTEM_PROMPT,
                prompt=prompt,
                schema=FACTS_SCHEMA,
            )
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
            # Skipping it must not lose the facts from every other chunk.
            log.warning(
                "extraction failed for a chunk",
                document=document.title,
                chunk_index=index,
                error=str(exc),
            )
            continue

        for raw in response.get("events", []):
            fact = _to_fact(raw, document)
            if fact is not None:
                candidates.append(fact)

    log.info(
        "extracted candidates",
        document=document.title,
        candidates=len(candidates),
    )
    return candidates


def _to_fact(raw: Any, document: Document) -> Fact | None:
    """Convert one raw model object into a Fact, or None if unusable.

    Defensive despite the schema: a constrained decoder guarantees the shape,
    not that the strings are non-empty.
    """
    if not isinstance(raw, dict):
        return None

    evidence = str(raw.get("evidence", "")).strip()
    claim = str(raw.get("claim", "")).strip()
    year_label = str(raw.get("year_label", "")).strip()

    if not evidence or not claim or not year_label:
        return None

    try:
        sort_year = int(raw.get("sort_year", 0))
    except (TypeError, ValueError):
        return None

    return Fact(
        year_label=year_label,
        sort_year=sort_year,
        place=str(raw.get("place", "")).strip(),
        claim=claim,
        evidence=evidence,
        source_url=document.url,
        source_title=document.title,
    )
