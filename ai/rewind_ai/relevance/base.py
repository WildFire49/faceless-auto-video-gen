"""The relevance contracts.

LAYER 2 (module base) of SPEC.md 14.1.

Format-neutral on purpose: a modern comparison attaches to an approved item's
claim, and "compare this to something people recognise" reads the same whether
the item is a date on a timeline or a debunked belief.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Protocol, runtime_checkable


class Kind(StrEnum):
    """Where a reference came from."""

    #: Curated in config/reference_bank.yaml. No expiry.
    EVERGREEN = "evergreen"
    #: Scraped from a live trend source today. Expires.
    HOT = "hot"
    #: Typed in by the human at Gate B.
    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class Trend:
    """One thing that is currently being talked about."""

    term: str
    #: Which source found it: "google_trends", "wiki_pageviews".
    source: str
    #: Free-text context the source offered, e.g. a headline.
    context: str = ""

    def __str__(self) -> str:
        return self.term


@dataclass(slots=True)
class Proposal:
    """One suggested comparison (SPEC.md 5.3)."""

    #: The modern thing: "Birkenstock", "Stanley cup".
    reference: str
    kind: Kind
    #: Which approved fact this attaches to. A comparison floating free of a
    #: fact has nothing to be funny about.
    linked_fact_id: str
    #: The line, as a narrator would say it.
    comparison: str
    why_funny: str
    #: What is being compared -- look, price, hype, behaviour -- stated so a
    #: reviewer can check it is not a factual claim about the brand.
    accuracy_note: str = ""

    id: str = ""
    source: str = ""
    #: For HOT references: when this stops being current.
    fresh_until: date | None = None
    selected: bool = False


@dataclass(frozen=True, slots=True)
class RelevanceResult:
    """Everything ProposeReferences produces."""

    topic: str
    proposals: list[Proposal]
    references_json_path: str
    max_selectable: int
    trend_sources: list[str] = field(default_factory=list)
    trends_fetched_at: str = ""
    candidates_generated: int = 0
    candidates_rejected: int = 0
    rejections: list[str] = field(default_factory=list)


@runtime_checkable
class TrendSource(Protocol):
    """Finds what is currently being talked about.

    Adding a source -- YouTube's mostPopular, a subreddit, a newsletter -- is
    one new file under ``sources/`` with one @register line (SPEC.md 14.2).
    """

    #: Stable identifier, e.g. "google_trends". Appears in config and the UI.
    name: str

    def fetch(self) -> list[Trend]:
        """Return today's trends.

        Should return an empty list rather than raise when it simply finds
        nothing. A dead trend source must never block a video: the evergreen
        bank alone is enough to make an episode.
        """
        ...
