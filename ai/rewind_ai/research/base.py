"""The research contracts.

LAYER 2 (module base) of SPEC.md 14.1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class Document:
    """Plain text fetched from one source, ready to extract from."""

    url: str
    title: str
    text: str
    #: Which fetcher produced it: "wikipedia", "user_url", ...
    fetcher: str

    @property
    def char_count(self) -> int:
        return len(self.text)


@dataclass(slots=True)
class Fact:
    """One verified item (SPEC.md 5.2).

    Format-neutral by design: for a timeline ``label`` is a year and
    ``sort_key`` orders chronologically; for a myth-buster ``label`` is the
    belief and ``sort_key`` is how surprising the correction is. What never
    varies is the pairing of ``claim`` with the ``evidence`` that supports it.

    Mutable, unlike Document: ids are assigned and verification results are
    attached after extraction.
    """

    label: str
    sort_key: int
    context: str
    claim: str
    evidence: str
    source_url: str
    source_title: str = ""

    #: Variety bucket, computed by the format. Gate A requires the approved
    #: items to span several distinct groups.
    group: str = ""
    #: Fields a format wanted that the generic pipeline knows nothing about.
    extra: dict[str, Any] = field(default_factory=dict)

    id: str = ""
    confidence: str = "low"
    conflict: bool = False
    approved: bool = False
    match_score: float = 0.0


@dataclass(frozen=True, slots=True)
class ResearchResult:
    """Everything BuildFactSheet produces."""

    topic: str
    facts: list[Fact]
    documents: list[Document]
    facts_json_path: str
    #: Which format produced this sheet, and how its variety is described.
    format_name: str = ""
    group_noun: str = "group"
    min_items: int = 8
    min_groups: int = 4
    #: How many the model proposed, and how many the verifier threw out.
    candidates_extracted: int = 0
    candidates_rejected: int = 0
    #: Why each rejected candidate was rejected, for the logs.
    rejections: list[str] = field(default_factory=list)


@runtime_checkable
class SourceFetcher(Protocol):
    """Fetches plain text for a topic.

    Adding a source -- SearXNG, a specific archive, a PDF reader -- is one new
    file under ``sources/`` with one @register line (SPEC.md 14.2).
    """

    #: Stable identifier, e.g. "wikipedia". Appears in config and in the UI.
    name: str

    def fetch(self, topic: str, *, extra_urls: list[str]) -> list[Document]:
        """Return documents for the topic.

        Should return an empty list rather than raise when it simply finds
        nothing: one source coming up empty is normal, not a failure of the
        whole research step. Raise only when the source itself is broken.
        """
        ...
