"""Wikipedia's most-read articles from yesterday (SPEC.md 5.3b).

A good proxy for "what is in the air": products, films, events and people that
a lot of people looked up. Free, official, no key.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta

from rewind_ai.core.logging import get_logger
from rewind_ai.core.registry import register
from rewind_ai.relevance.base import Trend

log = get_logger(__name__)

API = (
    "https://wikimedia.org/api/rest_v1/metrics/pageviews/top/"
    "en.wikipedia.org/all-access/{year}/{month}/{day}"
)

USER_AGENT = "REWIND/0.1 (faceless shorts; https://github.com/WildFire49/faceless-auto-video-gen)"

#: Articles that top the list every single day and say nothing about what is
#: trending. Filtering them is the difference between a useful signal and a
#: list of Wikipedia's own plumbing.
_ALWAYS_POPULAR = {
    "Main_Page",
    "Special:Search",
    "Wikipedia:Featured_pictures",
    "Special:Random",
    "Portal:Current_events",
}


@register("trend_source", "wiki_pageviews")
class WikiPageviewsSource:
    """Yesterday's most-read English Wikipedia articles."""

    name = "wiki_pageviews"

    def __init__(self, *, timeout: int = 20, limit: int = 25) -> None:
        self._timeout = timeout
        self._limit = limit

    def fetch(self) -> list[Trend]:
        # Yesterday, because today's data is incomplete until the day ends.
        day = datetime.now(UTC) - timedelta(days=1)
        url = API.format(year=day.year, month=f"{day.month:02d}", day=f"{day.day:02d}")
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            log.warning("wikipedia pageviews unreachable", error=str(exc))
            return []
        except json.JSONDecodeError as exc:
            log.warning("wikipedia pageviews returned unparseable JSON", error=str(exc))
            return []

        trends: list[Trend] = []
        for items in payload.get("items", []):
            for article in items.get("articles", []):
                title = str(article.get("article", ""))
                if not title or title in _ALWAYS_POPULAR or title.startswith("Special:"):
                    continue
                trends.append(
                    Trend(
                        term=title.replace("_", " "),
                        source=self.name,
                        context=f"{article.get('views', 0):,} views yesterday",
                    )
                )
                if len(trends) >= self._limit:
                    break

        log.info("fetched trends", source=self.name, count=len(trends))
        return trends
