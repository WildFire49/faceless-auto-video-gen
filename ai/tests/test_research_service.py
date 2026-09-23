"""Tests for the research pipeline.

Offline and deterministic (SPEC.md 10): a fake fetcher supplies saved source
text and a fake LLM returns scripted extractions, so these run with no
network, no Ollama and no GPU.

The fake LLM is where the interesting cases live -- it can be told to return a
fabricated fact, or one with a doctored date, and the test asserts the
verifier throws it away before it reaches a human.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from rewind_ai.core.errors import ValidationFailedError
from rewind_ai.formats.providers.history_timeline import HistoryTimeline
from rewind_ai.research.base import Document, Fact
from rewind_ai.research.service import ResearchConfig, ResearchService, _cap
from rewind_ai.research.verifier import normalise

# ------------------------------------------------------------------ fixtures

SANDALS_SOURCE = """
Sandals are an open type of footwear.

The oldest known footwear in the world are sandals woven from sagebrush bark,
dated to approximately 7000 or 8000 BC, found at the Fort Rock Cave in Oregon.

Roman soldiers wore caligae, heavy-soled hobnailed military sandals, which were
standard issue throughout the Republic and early Empire.

In the 12th century, the Japanese wore zori, flat sandals made of rice straw.

By 1962, the flip-flop had become popular in the United States.

During the 1960s counterculture movement, sandals became a symbol of a simple
lifestyle.

The Birkenstock footbed was patented in 1902 by Konrad Birkenstock.

In 1774, Johann Adam Birkenstock was registered as a shoemaker in church
archives in Germany.

Espadrilles, with soles of jute rope, have been worn in the Pyrenees since at
least the 13th century.

In 1985, sports sandals were designed for river guides in the Grand Canyon.
"""

SOURCE_URL = "https://en.wikipedia.org/wiki/Sandal"


class FakeFetcher:
    """Returns saved source text. Stands in for Wikipedia."""

    name = "fake"

    def __init__(self, documents: list[Document]) -> None:
        self._documents = documents

    def fetch(self, topic: str, *, extra_urls: list[str]) -> list[Document]:
        del topic, extra_urls
        return list(self._documents)


class FakeLLM:
    """Returns scripted extractions, one batch per call."""

    def __init__(self, batches: list[list[dict[str, Any]]]) -> None:
        self._batches = batches
        self.calls = 0

    def complete_json(self, *, system: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        del system, prompt, schema
        index = min(self.calls, len(self._batches) - 1)
        self.calls += 1
        return {"items": self._batches[index]}


def event(year_label: str, sort_year: int, claim: str, evidence: str) -> dict[str, Any]:
    """One item in the shape history_timeline asks the model for."""
    return {
        "year_label": year_label,
        "sort_year": sort_year,
        "place": "",
        "claim": claim,
        "evidence": evidence,
    }


#: Nine honest extractions, each quoting the source verbatim.
HONEST_EVENTS = [
    event(
        "~7000 BC",
        -7000,
        "Oldest known footwear found in Oregon.",
        "The oldest known footwear in the world are sandals woven from sagebrush bark, "
        "dated to approximately 7000 or 8000 BC, found at the Fort Rock Cave in Oregon.",
    ),
    event(
        "Roman Republic",
        -200,
        "Roman soldiers wore hobnailed sandals.",
        "Roman soldiers wore caligae, heavy-soled hobnailed military sandals, which were "
        "standard issue throughout the Republic and early Empire.",
    ),
    event(
        "12th century",
        1100,
        "Japanese zori were made of rice straw.",
        "In the 12th century, the Japanese wore zori, flat sandals made of rice straw.",
    ),
    event(
        "13th century",
        1200,
        "Espadrilles worn in the Pyrenees.",
        "Espadrilles, with soles of jute rope, have been worn in the Pyrenees since at "
        "least the 13th century.",
    ),
    event(
        "1774",
        1774,
        "A Birkenstock registered as a shoemaker.",
        "In 1774, Johann Adam Birkenstock was registered as a shoemaker in church "
        "archives in Germany.",
    ),
    event(
        "1902",
        1902,
        "The Birkenstock footbed was patented.",
        "The Birkenstock footbed was patented in 1902 by Konrad Birkenstock.",
    ),
    event(
        "1962",
        1962,
        "Flip-flops became popular in America.",
        "By 1962, the flip-flop had become popular in the United States.",
    ),
    event(
        "1960s",
        1965,
        "Sandals became a counterculture symbol.",
        "During the 1960s counterculture movement, sandals became a symbol of a simple lifestyle.",
    ),
    event(
        "1985",
        1985,
        "Sports sandals designed for river guides.",
        "In 1985, sports sandals were designed for river guides in the Grand Canyon.",
    ),
]


@pytest.fixture
def documents() -> list[Document]:
    return [Document(url=SOURCE_URL, title="Sandal", text=SANDALS_SOURCE, fetcher="fake")]


def build_service(
    tmp_path: Path,
    documents: list[Document],
    batches: list[list[dict[str, Any]]],
) -> tuple[ResearchService, FakeLLM]:
    llm = FakeLLM(batches)
    service = ResearchService(
        fetchers=[FakeFetcher(documents)],
        llm=llm,
        content_format=HistoryTimeline(),
        config=ResearchConfig(evidence_match_threshold=0.90),
        projects_dir=tmp_path,
    )
    return service, llm


# ------------------------------------------------------------- the happy path


def test_builds_a_verified_fact_sheet(tmp_path: Path, documents: list[Document]) -> None:
    service, _ = build_service(tmp_path, documents, [HONEST_EVENTS])

    result = service.build(video_id="sandals", topic="sandals", extra_urls=[])

    assert len(result.facts) >= 8
    assert result.candidates_rejected == 0

    # Facts are numbered and chronological.
    assert [f.id for f in result.facts] == [f"f{i}" for i in range(1, len(result.facts) + 1)]
    years = [f.sort_key for f in result.facts]
    assert years == sorted(years)

    # SPEC.md 5.2 acceptance: no fact without a source, and every evidence
    # string really is in that source.
    #
    # Compared after normalisation, because the source wraps sentences across
    # lines -- the same reason the verifier normalises rather than demanding
    # byte equality.
    normalised_source = normalise(SANDALS_SOURCE)
    for fact in result.facts:
        assert fact.source_url, f"fact {fact.id} has no source"
        assert normalise(fact.evidence) in normalised_source, (
            f"fact {fact.id} evidence is not in the source"
        )


def test_writes_facts_json(tmp_path: Path, documents: list[Document]) -> None:
    service, _ = build_service(tmp_path, documents, [HONEST_EVENTS])
    result = service.build(video_id="sandals", topic="sandals", extra_urls=[])

    path = Path(result.facts_json_path)
    assert path.exists()
    assert path.parent.name == "sandals"

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["topic"] == "sandals"
    assert len(data["facts"]) == len(result.facts)
    assert data["sources"][0]["url"] == SOURCE_URL

    # The sheet declares its own format and gate rules, so Go can enforce a
    # format's thresholds without knowing which formats exist.
    assert data["format"] == "history_timeline"
    assert data["group_noun"] == "era"
    assert data["min_items"] == 8
    assert data["min_groups"] == 4

    # These counts used to be computed and discarded, which silently broke the
    # one objective measure of how much a model invents.
    assert data["candidates_extracted"] == len(HONEST_EVENTS)
    assert data["candidates_rejected"] == 0
    assert "rejections" in data

    first = data["facts"][0]
    assert first["approved"] is False, "the worker must never pre-approve a fact"
    assert first["evidence"]
    assert first["source_url"]


# -------------------------------------------------- the verifier does its job


def test_fabricated_facts_are_dropped(tmp_path: Path, documents: list[Document]) -> None:
    fabricated = event(
        "3500 BC",
        -3500,
        "Oldest leather sandals found in Armenia.",
        "Archaeologists discovered the oldest leather shoes in Armenia, dated to 3500 BC, "
        "preserved under a layer of sheep dung.",
    )
    service, _ = build_service(tmp_path, documents, [[*HONEST_EVENTS, fabricated]])

    result = service.build(video_id="sandals", topic="sandals", extra_urls=[])

    assert result.candidates_rejected == 1
    assert all("Armenia" not in f.claim for f in result.facts)
    assert any("3500 BC" in r for r in result.rejections)


def test_facts_with_doctored_dates_are_dropped(tmp_path: Path, documents: list[Document]) -> None:
    """The subtlest attack: quote a real sentence but change the year.

    Prose similarity is ~0.99, so only the verifier's exact number check
    catches it. If this test ever fails, a falsified date can reach a human.
    """
    doctored = event(
        "~3000 BC",
        -3000,
        "Oldest known footwear found in Oregon.",
        "The oldest known footwear in the world are sandals woven from sagebrush bark, "
        "dated to approximately 3000 or 4000 BC, found at the Fort Rock Cave in Oregon.",
    )
    service, _ = build_service(tmp_path, documents, [[*HONEST_EVENTS, doctored]])

    result = service.build(video_id="sandals", topic="sandals", extra_urls=[])

    assert result.candidates_rejected == 1
    assert all(f.sort_key != -3000 for f in result.facts), (
        "a fact with a falsified date survived verification"
    )


def test_geological_dates_are_rejected_not_crashed(
    tmp_path: Path, documents: list[Document]
) -> None:
    """The exact E2E failure, as a regression test.

    A correctly sourced fact about the Earth's core must be rejected on
    plausibility grounds and COUNTED, not allowed through to overflow the wire
    format after all the work is done.
    """
    geological = event(
        "4.6 billion years ago",
        -4_600_000_000,
        "Iron formed in the Earth's core.",
        "The oldest known footwear in the world are sandals woven from sagebrush bark, "
        "dated to approximately 7000 or 8000 BC, found at the Fort Rock Cave in Oregon.",
    )
    service, _ = build_service(tmp_path, documents, [[*HONEST_EVENTS, geological]])

    result = service.build(video_id="sandals", topic="sandals", extra_urls=[])

    assert result.candidates_rejected == 1
    assert all(f.sort_key > -4_000_000 for f in result.facts), (
        "a geological date survived into the fact sheet"
    )
    assert any("geological" in r for r in result.rejections), (
        "the rejection must say WHY, so it is not mistaken for a verification failure"
    )


def test_every_sort_key_fits_the_wire_format(tmp_path: Path, documents: list[Document]) -> None:
    """Nothing reaching the wire may overflow int64.

    The bound above is far tighter, so this is belt and braces -- but the
    original bug was precisely a value that passed every check and then failed
    at serialization.
    """
    service, _ = build_service(tmp_path, documents, [HONEST_EVENTS])
    result = service.build(video_id="sandals", topic="sandals", extra_urls=[])

    for fact in result.facts:
        assert -(2**63) < fact.sort_key < 2**63 - 1, f"{fact.id} cannot be serialised"


def test_too_few_verified_facts_fails_loudly(tmp_path: Path, documents: list[Document]) -> None:
    # Handing a reviewer three facts would waste their time and tempt them to
    # approve thin material, so it fails instead.
    service, _ = build_service(tmp_path, documents, [HONEST_EVENTS[:3]])

    with pytest.raises(ValidationFailedError) as excinfo:
        service.build(video_id="sandals", topic="sandals", extra_urls=[])

    assert "need 8" in str(excinfo.value)


def test_no_sources_fails_loudly(tmp_path: Path) -> None:
    service, _ = build_service(tmp_path, [], [HONEST_EVENTS])

    with pytest.raises(ValidationFailedError) as excinfo:
        service.build(video_id="sandals", topic="sandals", extra_urls=[])

    assert "no sources" in str(excinfo.value)


# ------------------------------------------------------------------- tidying


def test_duplicate_facts_are_merged(tmp_path: Path, documents: list[Document]) -> None:
    # The same milestone described by two articles should appear once.
    duplicate = event(
        "~7000 BC",
        -7000,
        "Oldest known footwear found in Oregon cave.",
        "The oldest known footwear in the world are sandals woven from sagebrush bark, "
        "dated to approximately 7000 or 8000 BC, found at the Fort Rock Cave in Oregon.",
    )
    service, _ = build_service(tmp_path, documents, [[*HONEST_EVENTS, duplicate]])

    result = service.build(video_id="sandals", topic="sandals", extra_urls=[])

    oldest = [f for f in result.facts if f.sort_key == -7000]
    assert len(oldest) == 1, f"expected one fact for 7000 BC, got {len(oldest)}"


def test_progress_is_reported(tmp_path: Path, documents: list[Document]) -> None:
    service, _ = build_service(tmp_path, documents, [HONEST_EVENTS])

    seen: list[tuple[str, float]] = []
    service.build(
        video_id="sandals",
        topic="sandals",
        extra_urls=[],
        progress=lambda stage, pct: seen.append((stage, pct)),
    )

    assert seen, "no progress was reported; the dashboard would show a dead bar"
    stages = [s for s, _ in seen]
    assert any("fetch" in s for s in stages)
    assert any("verif" in s for s in stages)

    percents = [p for _, p in seen]
    assert percents == sorted(percents), "progress went backwards"
    assert all(0.0 <= p <= 1.0 for p in percents)


def test_a_failing_source_does_not_sink_the_run(tmp_path: Path, documents: list[Document]) -> None:
    class BrokenFetcher:
        name = "broken"

        def fetch(self, topic: str, *, extra_urls: list[str]) -> list[Document]:
            raise RuntimeError("DNS exploded")

    llm = FakeLLM([HONEST_EVENTS])
    service = ResearchService(
        fetchers=[BrokenFetcher(), FakeFetcher(documents)],
        llm=llm,
        content_format=HistoryTimeline(),
        config=ResearchConfig(evidence_match_threshold=0.90),
        projects_dir=tmp_path,
    )

    result = service.build(video_id="sandals", topic="sandals", extra_urls=[])
    assert len(result.facts) >= 8


# ------------------------------------------------------------------ the cap

# _cap is tested directly: it is a pure function whose failure modes are the
# point, and driving it through the service would need a format invented just
# for the test. Written before the fix (CLAUDE.md):
#
#   * keeps the best-scoring items and collapses the spread   <- the real bug
#   * returns items out of order
#   * drops below the number the gate requires
#   * starves a small group in favour of a large one


def capped(groups: dict[str, int], limit: int) -> list[Fact]:
    """Build facts in the named groups and run the cap over them."""
    facts: list[Fact] = []
    key = 0
    for group, count in groups.items():
        for i in range(count):
            key += 1
            facts.append(
                Fact(
                    label=str(key),
                    sort_key=key,
                    context="",
                    claim=f"{group} {i}",
                    evidence="x" * 40,
                    source_url="https://example.com",
                    group=group,
                    # Deliberately lopsided: one group scores highest across
                    # the board, which is what broke the real run.
                    match_score=0.99 if group == "industrial" else 0.93,
                )
            )
    return _cap(facts, limit)


def test_cap_preserves_variety() -> None:
    """The real bug: keeping the top-scoring items collapsed 172 facts into
    2 eras, and Gate A refused them for lacking spread."""
    kept = capped({"industrial": 30, "ancient": 6, "medieval": 5, "modern": 4}, limit=10)

    assert len(kept) == 10
    assert len({f.group for f in kept}) == 4, (
        f"the cap kept only {sorted({f.group for f in kept})}; the high-scoring "
        "group crowded everything else out"
    )


def test_cap_does_not_starve_a_small_group() -> None:
    kept = capped({"industrial": 40, "prehistory": 1}, limit=5)
    assert "prehistory" in {f.group for f in kept}


def test_cap_keeps_order() -> None:
    kept = capped({"a": 5, "b": 5, "c": 5}, limit=7)
    keys = [f.sort_key for f in kept]
    assert keys == sorted(keys), "the cap left the sheet out of order"


def test_cap_is_a_no_op_below_the_limit() -> None:
    kept = capped({"a": 3}, limit=10)
    assert len(kept) == 3


def test_cap_never_trims_below_the_gate_requirement(
    tmp_path: Path, documents: list[Document]
) -> None:
    """A low max_items must not make research fail with good facts in hand."""
    service = ResearchService(
        fetchers=[FakeFetcher(documents)],
        llm=FakeLLM([HONEST_EVENTS]),
        content_format=HistoryTimeline(),
        config=ResearchConfig(evidence_match_threshold=0.90, max_items=2),
        projects_dir=tmp_path,
    )

    result = service.build(video_id="sandals", topic="sandals", extra_urls=[])
    assert len(result.facts) >= 8, "the cap trimmed below what Gate A requires"


# ------------------------------------------ numbers the viewer sees or hears
#
# The unit rules live in tests/test_grounding.py. This proves the service
# actually applies them: a verbatim quote with an invented date beside it
# must not reach Gate A. Found by reading Gate A in a browser, where a fact
# labelled "around 9,000 years ago" quoted a sentence with no date at all.


def test_a_verbatim_quote_with_an_invented_date_is_rejected(
    tmp_path: Path, documents: list[Document]
) -> None:
    invented = event(
        "around 9,000 years ago",
        -7000,
        "Roman soldiers wore hobnailed sandals.",
        # Verbatim from the source, so the evidence verifier passes it. The
        # date is nowhere in it.
        "Roman soldiers wore caligae, heavy-soled hobnailed military sandals, which were "
        "standard issue throughout the Republic and early Empire.",
    )
    service, _ = build_service(tmp_path, documents, [[*HONEST_EVENTS, invented]])

    result = service.build(video_id="sandals", topic="sandals", extra_urls=[])

    assert all(f.label != "around 9,000 years ago" for f in result.facts)
    assert result.candidates_rejected == 1
    assert any("9000" in r and "model supplied" in r for r in result.rejections)


def test_an_invented_number_in_the_claim_is_rejected(
    tmp_path: Path, documents: list[Document]
) -> None:
    # The label is honest; the claim, which the script will READ ALOUD, is not.
    invented = event(
        "1902",
        1902,
        "The Birkenstock footbed was patented in 1903.",
        "The Birkenstock footbed was patented in 1902 by Konrad Birkenstock.",
    )
    honest_without_1902 = [e for e in HONEST_EVENTS if e["year_label"] != "1902"]
    service, _ = build_service(tmp_path, documents, [[*honest_without_1902, invented]])

    result = service.build(video_id="sandals", topic="sandals", extra_urls=[])

    assert all("1903" not in f.claim for f in result.facts)
    assert any("1903" in r for r in result.rejections)
