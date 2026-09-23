"""The evergreen reference bank and the daily trend cache.

LAYER 2 of SPEC.md 14.1.

Two jobs that both answer "what modern things could we compare this to?":

* the BANK is curated by the human in config/reference_bank.yaml and never
  goes stale
* the CACHE holds what the live sources found today, refreshed at most once a
  day so a video never waits on a trend scan and a flaky source never blocks
  an episode
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from rewind_ai.core.io import read_json, write_json_atomic
from rewind_ai.core.logging import get_logger
from rewind_ai.relevance.base import Trend, TrendSource

log = get_logger(__name__)

#: How long a trend scan stays usable. A day: these sources publish daily, and
#: re-fetching per video would be rude to a free service and no more accurate.
CACHE_TTL = timedelta(days=1)


@dataclass(frozen=True, slots=True)
class ReferenceBank:
    """The curated references, and which topics they apply to."""

    categories: dict[str, list[str]] = field(default_factory=dict)
    topic_categories: dict[str, list[str]] = field(default_factory=dict)
    always: list[str] = field(default_factory=list)
    never: list[str] = field(default_factory=list)

    def for_topic(self, topic: str) -> dict[str, list[str]]:
        """Return the categories worth offering for this topic.

        Matching is on whole words, and both sides are compared in singular
        and plural form. Singularising only the keyword was a real bug: the
        topic "sandals" never matched the keyword "sandal", which silently
        left SPEC.md's own example topic with no footwear references at all.
        """
        words = set(re.findall(r"[a-z]+", topic.lower()))
        words |= {_singular(w) for w in words}

        matched: list[str] = []
        for category, keywords in self.topic_categories.items():
            if category in self.never:
                continue
            if any(k in words or _singular(k) in words for k in keywords):
                matched.append(category)

        for category in self.always:
            if category not in matched and category not in self.never:
                matched.append(category)

        # A topic nobody categorised still needs material, so fall back to
        # everything rather than handing the model an empty list.
        if not matched:
            matched = [c for c in self.categories if c not in self.never]
            log.info("topic matched no category; offering all", topic=topic)

        return {c: self.categories.get(c, []) for c in matched if self.categories.get(c)}


def _singular(word: str) -> str:
    return word[:-1] if word.endswith("s") and len(word) > 3 else word


def load_bank(config_dir: Path) -> ReferenceBank:
    """Read config/reference_bank.yaml.

    A missing or broken bank is NOT fatal: the live trends and the human's own
    suggestions at Gate B are enough to make an episode, and refusing to
    research because a YAML file has a typo would be disproportionate.
    """
    path = config_dir / "reference_bank.yaml"
    if not path.is_file():
        log.warning("no reference bank found", path=str(path))
        return ReferenceBank()

    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        log.error("reference bank is not valid YAML", path=str(path), error=str(exc))
        return ReferenceBank()

    if not isinstance(raw, dict):
        log.error("reference bank must be a YAML mapping", path=str(path))
        return ReferenceBank()

    return ReferenceBank(
        categories={
            str(k): [str(v) for v in vals]
            for k, vals in (raw.get("categories") or {}).items()
            if isinstance(vals, list)
        },
        topic_categories={
            str(k): [str(v).lower() for v in vals]
            for k, vals in (raw.get("topic_categories") or {}).items()
            if isinstance(vals, list)
        },
        always=[str(v) for v in (raw.get("always") or [])],
        never=[str(v) for v in (raw.get("never") or [])],
    )


@dataclass(frozen=True, slots=True)
class CachedTrends:
    """What the live sources found, and when."""

    trends: list[Trend]
    fetched_at: datetime
    sources: list[str]

    @property
    def is_fresh(self) -> bool:
        return datetime.now(UTC) - self.fetched_at < CACHE_TTL


class TrendCache:
    """Reads and refreshes the daily trend scan."""

    def __init__(self, path: Path, sources: list[TrendSource]) -> None:
        self._path = path
        self._sources = sources

    def get(self, *, force: bool = False) -> CachedTrends:
        """Return today's trends, scanning only when the cache is stale."""
        if not force:
            cached = self._read()
            if cached is not None and cached.is_fresh:
                log.info("using cached trends", count=len(cached.trends))
                return cached

        return self.refresh()

    def refresh(self) -> CachedTrends:
        """Scan every source and write the cache.

        One source failing is normal -- they are free services with no uptime
        promise -- so failures are logged and the rest are kept.
        """
        trends: list[Trend] = []
        used: list[str] = []

        for source in self._sources:
            try:
                found = source.fetch()
            except Exception as exc:  # noqa: BLE001 - a dead source must not block a video
                log.warning("trend source failed", source=source.name, error=str(exc))
                continue

            if found:
                trends.extend(found)
                used.append(source.name)

        cached = CachedTrends(trends=trends, fetched_at=datetime.now(UTC), sources=used)
        self._write(cached)
        log.info("refreshed trends", count=len(trends), sources=used)
        return cached

    # ---------------------------------------------------------------- disk

    def _read(self) -> CachedTrends | None:
        if not self._path.is_file():
            return None
        try:
            raw = read_json(self._path)
            return CachedTrends(
                trends=[
                    Trend(
                        term=str(t["term"]),
                        source=str(t.get("source", "")),
                        context=str(t.get("context", "")),
                    )
                    for t in raw.get("trends", [])
                ],
                fetched_at=datetime.fromisoformat(raw["fetched_at"]),
                sources=[str(s) for s in raw.get("sources", [])],
            )
        except (OSError, KeyError, ValueError, TypeError) as exc:
            # A corrupt cache is a reason to re-scan, not to fail.
            log.warning("trend cache unreadable; will re-scan", error=str(exc))
            return None

    def _write(self, cached: CachedTrends) -> None:
        write_json_atomic(
            self._path,
            {
                "fetched_at": cached.fetched_at.isoformat(),
                "sources": cached.sources,
                "trends": [
                    {"term": t.term, "source": t.source, "context": t.context}
                    for t in cached.trends
                ],
            },
        )
