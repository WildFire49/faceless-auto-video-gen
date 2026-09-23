"""Tests for the relevance pipeline.

Offline and deterministic: a fake LLM returns scripted comparisons and a fake
trend source supplies fixed terms, so these run with no network and no Ollama.

The interesting cases are the ones where the model misbehaves -- attaching a
comparison to a fact nobody approved, repeating itself, or reaching for a
tragedy -- and the test asserts the service throws it away and says why.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from rewind_ai.core.errors import ValidationFailedError
from rewind_ai.relevance.bank import ReferenceBank, TrendCache
from rewind_ai.relevance.base import Kind, Proposal, Trend
from rewind_ai.relevance.service import (
    ApprovedFact,
    RelevanceConfig,
    RelevanceService,
    stale_ids,
)

FACTS = [
    ApprovedFact(id="f1", label="~7000 BC", claim="Oldest known sandals, woven from bark."),
    ApprovedFact(id="f2", label="Roman Republic", claim="Soldiers wore hobnailed caligae."),
    ApprovedFact(id="f3", label="1962", claim="Flip-flops became popular in America."),
]

BANK = ReferenceBank(
    categories={
        "footwear": ["Birkenstock", "Crocs", "Nike Air Force 1"],
        "internet": ["limited drop", "1-star review"],
    },
    topic_categories={"footwear": ["sandal", "shoe"]},
    always=["internet"],
)


class FakeLLM:
    def __init__(self, items: list[dict[str, Any]]) -> None:
        self._items = items
        self.prompts: list[str] = []

    def complete_json(self, *, system: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        del system, schema
        self.prompts.append(prompt)
        return {"items": self._items}


class FakeTrendSource:
    name = "fake_trends"

    def __init__(self, terms: list[str]) -> None:
        self._terms = terms

    def fetch(self) -> list[Trend]:
        return [Trend(term=t, source=self.name) for t in self._terms]


def comparison(
    reference: str = "Birkenstock",
    fact_id: str = "f2",
    line: str = "Roman caligae were basically Birkenstocks with spikes.",
) -> dict[str, Any]:
    return {
        "reference": reference,
        "linked_fact_id": fact_id,
        "comparison": line,
        "why_funny": "comfort brand vs brutal army kit",
        "accuracy_note": "shape only",
    }


def build(
    tmp_path: Path, items: list[dict[str, Any]], *, trends: list[str] | None = None
) -> tuple[RelevanceService, FakeLLM]:
    llm = FakeLLM(items)
    cache = TrendCache(tmp_path / "trends_cache.json", [FakeTrendSource(trends or [])])
    service = RelevanceService(
        llm=llm,
        bank=BANK,
        trends=cache,
        config=RelevanceConfig(max_selectable=3, max_proposals=8),
        projects_dir=tmp_path,
    )
    return service, llm


# --------------------------------------------------------------- happy path


def test_proposes_comparisons_tied_to_approved_facts(tmp_path: Path) -> None:
    service, _ = build(
        tmp_path,
        [
            comparison("Birkenstock", "f2"),
            comparison("Crocs", "f1", "The oldest shoes were basically bark Crocs."),
        ],
    )

    result = service.propose(video_id="sandals", topic="sandals", facts=FACTS)

    assert len(result.proposals) == 2
    assert [p.id for p in result.proposals] == ["r1", "r2"]
    for proposal in result.proposals:
        assert proposal.linked_fact_id in {f.id for f in FACTS}
        assert proposal.selected is False, "the worker must never pre-select a comparison"


def test_writes_references_json(tmp_path: Path) -> None:
    service, _ = build(tmp_path, [comparison()])
    result = service.propose(video_id="sandals", topic="sandals", facts=FACTS)

    path = Path(result.references_json_path)
    assert path.exists()

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["topic"] == "sandals"
    assert data["max_selectable"] == 3
    assert data["proposals"][0]["selected"] is False


def test_the_prompt_offers_bank_references_for_the_topic(tmp_path: Path) -> None:
    service, llm = build(tmp_path, [comparison()])
    service.propose(video_id="sandals", topic="sandals", facts=FACTS)

    prompt = llm.prompts[0]
    assert "Birkenstock" in prompt, "the footwear category was not offered for sandals"
    assert "limited drop" in prompt, "the always-on internet category was not offered"
    # Every approved fact must be visible, with its id, or the model cannot
    # attach a comparison to one.
    for fact in FACTS:
        assert fact.id in prompt
        assert fact.claim in prompt


def test_the_prompt_never_shows_evidence_or_sources(tmp_path: Path) -> None:
    """The relevance engine has no business with whether a fact is true.

    Handing it evidence would invite it to reason about the source rather than
    just be funny about the claim.
    """
    service, llm = build(tmp_path, [comparison()])
    service.propose(video_id="sandals", topic="sandals", facts=FACTS)

    prompt = llm.prompts[0].lower()
    assert "evidence" not in prompt
    assert "wikipedia" not in prompt
    assert "http" not in prompt


# ------------------------------------------------- the model misbehaving


def test_a_comparison_attached_to_an_unapproved_fact_is_dropped(tmp_path: Path) -> None:
    """Otherwise a comparison would smuggle unapproved material into the script."""
    service, _ = build(tmp_path, [comparison("Birkenstock", "f2"), comparison("Crocs", "f99")])

    result = service.propose(video_id="sandals", topic="sandals", facts=FACTS)

    assert len(result.proposals) == 1
    assert result.candidates_rejected == 1
    assert any("not an approved fact" in r for r in result.rejections)


def test_unsafe_comparisons_are_dropped_with_a_reason(tmp_path: Path) -> None:
    service, _ = build(
        tmp_path,
        [
            comparison("Birkenstock", "f2"),
            comparison("Crocs", "f1", "Birkenstock was founded in ancient Rome."),
            comparison("Nike", "f3", "Sold out faster than tickets after 9/11."),
        ],
    )

    result = service.propose(video_id="sandals", topic="sandals", facts=FACTS)

    assert len(result.proposals) == 1
    assert result.candidates_rejected == 2
    assert any("factual claim" in r for r in result.rejections)
    assert any("tragedy" in r for r in result.rejections)


def test_the_same_reference_twice_is_dropped(tmp_path: Path) -> None:
    # Reusing one brand makes the whole video feel like a single joke.
    service, _ = build(
        tmp_path,
        [
            comparison("Crocs", "f1", "The oldest shoes were basically bark Crocs."),
            comparison("Crocs", "f3", "Flip-flops: the Crocs of the beach."),
        ],
    )

    result = service.propose(video_id="sandals", topic="sandals", facts=FACTS)

    assert len(result.proposals) == 1
    assert any("already used" in r for r in result.rejections)


def test_everything_rejected_fails_loudly(tmp_path: Path) -> None:
    service, _ = build(
        tmp_path, [comparison("Crocs", "f1", "Crocs invented the moulded sole in 1823.")]
    )

    with pytest.raises(ValidationFailedError) as excinfo:
        service.propose(video_id="sandals", topic="sandals", facts=FACTS)

    assert "no usable comparisons" in str(excinfo.value)


def test_no_approved_facts_fails_loudly(tmp_path: Path) -> None:
    service, _ = build(tmp_path, [comparison()])

    with pytest.raises(ValidationFailedError) as excinfo:
        service.propose(video_id="sandals", topic="sandals", facts=[])

    assert "Gate A" in str(excinfo.value.detail or "")


# ------------------------------------------------------ hot vs evergreen


def test_a_trending_reference_is_marked_hot_and_given_an_expiry(tmp_path: Path) -> None:
    service, _ = build(
        tmp_path,
        [comparison("Stanley cup", "f2", "It was the Stanley cup of the legion.")],
        trends=["Stanley cup"],
    )

    result = service.propose(video_id="sandals", topic="sandals", facts=FACTS)
    proposal = result.proposals[0]

    assert proposal.kind is Kind.HOT
    assert proposal.fresh_until is not None, "a hot reference with no expiry never goes stale"
    assert proposal.fresh_until > datetime.now(UTC).date()


def test_a_bank_reference_is_evergreen_and_never_expires(tmp_path: Path) -> None:
    service, _ = build(tmp_path, [comparison("Birkenstock", "f2")], trends=["something else"])

    proposal = service.propose(video_id="sandals", topic="sandals", facts=FACTS).proposals[0]

    assert proposal.kind is Kind.EVERGREEN
    assert proposal.fresh_until is None


def test_stale_ids_only_flags_selected_expired_references() -> None:
    yesterday = (datetime.now(UTC) - timedelta(days=1)).date()
    tomorrow = (datetime.now(UTC) + timedelta(days=1)).date()

    proposals = [
        Proposal("a", Kind.HOT, "f1", "x", "y", id="r1", selected=True, fresh_until=yesterday),
        Proposal("b", Kind.HOT, "f1", "x", "y", id="r2", selected=False, fresh_until=yesterday),
        Proposal("c", Kind.HOT, "f1", "x", "y", id="r3", selected=True, fresh_until=tomorrow),
        Proposal("d", Kind.EVERGREEN, "f1", "x", "y", id="r4", selected=True),
    ]

    # Only r1: selected AND expired. An unselected stale one is not a problem,
    # and an evergreen one never expires.
    assert stale_ids(proposals) == ["r1"]


# --------------------------------------------------------------- the bank


def test_bank_matches_categories_by_whole_word() -> None:
    offered = BANK.for_topic("sandals")
    assert "footwear" in offered
    assert "internet" in offered, "the always-on category was missing"


def test_bank_falls_back_to_everything_for_an_unknown_topic() -> None:
    # A topic nobody categorised still needs material.
    offered = BANK.for_topic("astrolabe")
    assert offered, "an uncategorised topic was left with no references at all"


def test_trend_cache_reuses_a_fresh_scan(tmp_path: Path) -> None:
    source = FakeTrendSource(["one", "two"])
    cache = TrendCache(tmp_path / "trends.json", [source])

    first = cache.get()
    second = cache.get()

    assert len(first.trends) == 2
    assert [t.term for t in second.trends] == [t.term for t in first.trends]
    assert second.is_fresh


def test_a_dead_trend_source_does_not_block_anything(tmp_path: Path) -> None:
    class BrokenSource:
        name = "broken"

        def fetch(self) -> list[Trend]:
            raise RuntimeError("DNS exploded")

    cache = TrendCache(tmp_path / "trends.json", [BrokenSource(), FakeTrendSource(["ok"])])
    cached = cache.refresh()

    assert [t.term for t in cached.trends] == ["ok"]
    assert cached.sources == ["fake_trends"]


# ------------------------------------------- the reference must be on offer
#
# Found by the M3 end-to-end run, which proposed three comparisons whose
# references were "home", "internet" and "trending right now" -- the CATEGORY
# HEADINGS from the prompt, not modern things. Gate B showed a card titled
# "home". The ways this can go wrong, written before the guard:
#
#   1. the model answers with a category name              -> rejected
#   2. the model answers with the trend bucket's label     -> rejected
#   3. the model invents a brand that is not in the bank   -> rejected
#   4. the model uses an offered item in a different case  -> KEPT, normalised
#   5. nothing is on offer at all                          -> no crash
#   6. two proposals differ only by case                   -> the second is a
#                                                             duplicate
#
# Cases 1-3 matter because the bank is curated by hand and is the biggest
# lever on whether the jokes land; a reference the model invented has had no
# such judgement applied to it.


def test_a_category_name_is_not_a_reference(tmp_path: Path) -> None:
    service, _ = build(tmp_path, [comparison("footwear", "f1"), comparison("Crocs", "f2")])

    result = service.propose(video_id="sandals", topic="sandals", facts=FACTS)

    assert [p.reference for p in result.proposals] == ["Crocs"]
    assert any("footwear" in r for r in result.rejections)


def test_the_trend_bucket_label_is_not_a_reference(tmp_path: Path) -> None:
    service, _ = build(
        tmp_path,
        [comparison("trending right now", "f1"), comparison("Crocs", "f2")],
        trends=["barefoot shoes"],
    )

    result = service.propose(video_id="sandals", topic="sandals", facts=FACTS)

    assert [p.reference for p in result.proposals] == ["Crocs"]


def test_an_invented_brand_is_rejected(tmp_path: Path) -> None:
    service, _ = build(tmp_path, [comparison("Shoetopia", "f1"), comparison("Crocs", "f2")])

    result = service.propose(video_id="sandals", topic="sandals", facts=FACTS)

    assert [p.reference for p in result.proposals] == ["Crocs"]
    assert result.candidates_rejected == 1


def test_case_differences_are_normalised_to_the_banks_spelling(tmp_path: Path) -> None:
    service, _ = build(tmp_path, [comparison("bIRKENSTOCK", "f2")])

    result = service.propose(video_id="sandals", topic="sandals", facts=FACTS)

    assert [p.reference for p in result.proposals] == ["Birkenstock"]


def test_case_differences_cannot_smuggle_in_a_duplicate(tmp_path: Path) -> None:
    service, _ = build(tmp_path, [comparison("Birkenstock", "f1"), comparison("BIRKENSTOCK", "f2")])

    result = service.propose(video_id="sandals", topic="sandals", facts=FACTS)

    assert len(result.proposals) == 1
    assert any("already used" in r for r in result.rejections)


def test_nothing_on_offer_rejects_everything_without_crashing(tmp_path: Path) -> None:
    llm = FakeLLM([comparison("Crocs", "f1")])
    cache = TrendCache(tmp_path / "trends_cache.json", [FakeTrendSource([])])
    service = RelevanceService(
        llm=llm,
        bank=ReferenceBank(categories={}, topic_categories={}, always=[]),
        trends=cache,
        config=RelevanceConfig(max_selectable=3, max_proposals=8),
        projects_dir=tmp_path,
    )

    with pytest.raises(ValidationFailedError):
        service.propose(video_id="sandals", topic="sandals", facts=FACTS)


def test_the_prompt_lists_one_reference_per_line_with_no_headings(tmp_path: Path) -> None:
    """The prompt and the check are built from the same function, so a thing
    the model is shown is always a thing it is allowed to answer with."""
    service, llm = build(tmp_path, [comparison()])
    service.propose(video_id="sandals", topic="sandals", facts=FACTS)

    prompt = llm.prompts[0]
    assert "  Birkenstock\n" in prompt
    assert "footwear:" not in prompt, "a category heading is answerable and must not appear"
    assert "trending right now:" not in prompt


# ---------------------------------------------- the provenance panel's data
#
# Found by the same run: references.json carried no counts, so Gate B reported
# "0 candidates, 0 rejected" however many the filter had thrown out. Go
# rebuilds the whole view from this file, so a count that is only returned
# over gRPC is a count that is lost on the next page load.


def test_references_json_records_what_was_thrown_out(tmp_path: Path) -> None:
    service, _ = build(
        tmp_path,
        [
            comparison("Crocs", "f1"),
            comparison("Shoetopia", "f2"),
            comparison("Birkenstock", "f99"),
        ],
    )

    result = service.propose(video_id="sandals", topic="sandals", facts=FACTS)
    data = json.loads(Path(result.references_json_path).read_text(encoding="utf-8"))

    assert data["candidates_generated"] == 3
    assert data["candidates_rejected"] == 2
    assert len(data["rejections"]) == 2
    assert data["candidates_generated"] == result.candidates_generated
    assert data["candidates_rejected"] == result.candidates_rejected
