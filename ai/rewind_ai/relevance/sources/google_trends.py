"""Google Trends "Trending now" RSS (SPEC.md 5.3b).

Free, no key, no scraping: Google publishes this feed for exactly this use.
"""

from __future__ import annotations

import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from rewind_ai.core.logging import get_logger
from rewind_ai.core.registry import register
from rewind_ai.relevance.base import Trend

log = get_logger(__name__)

FEED = "https://trends.google.com/trending/rss?geo={geo}"

#: Wikipedia and Google both ask for a descriptive agent. Being a good citizen
#: of a free service we depend on is not optional.
USER_AGENT = "REWIND/0.1 (faceless shorts; https://github.com/WildFire49/faceless-auto-video-gen)"


@register("trend_source", "google_trends")
class GoogleTrendsSource:
    """Today's trending searches for a country."""

    name = "google_trends"

    def __init__(self, *, geo: str = "US", timeout: int = 15, limit: int = 20) -> None:
        self._geo = geo
        self._timeout = timeout
        self._limit = limit

    def fetch(self) -> list[Trend]:
        url = FEED.format(geo=self._geo)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as resp:
                body = resp.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            # A dead trend source must never block a video: the evergreen bank
            # alone is enough to make an episode.
            log.warning("google trends unreachable", error=str(exc))
            return []

        try:
            root = ET.fromstring(body)
        except ET.ParseError as exc:
            log.warning("google trends returned unparseable XML", error=str(exc))
            return []

        trends: list[Trend] = []
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            if not title:
                continue
            # The feed carries a news headline alongside each term, which is
            # useful context for judging whether a term is usable.
            headline = ""
            for child in item:
                if child.tag.endswith("news_item_title") and child.text:
                    headline = child.text.strip()
                    break
            trends.append(Trend(term=title, source=self.name, context=headline))
            if len(trends) >= self._limit:
                break

        log.info("fetched trends", source=self.name, count=len(trends))
        return trends
