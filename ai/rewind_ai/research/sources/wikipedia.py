"""Wikipedia source (SPEC.md 5.2).

Uses the public action API: search for the topic, screen the hits for ones
actually about it (see ``relevance``), and download plain text extracts. No
key, no scraping, no rate-limit games -- the API is explicitly provided for
this.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from typing import Any

from rewind_ai.core.errors import SourceUnreachableError
from rewind_ai.core.logging import get_logger
from rewind_ai.core.registry import register
from rewind_ai.research.base import Document
from rewind_ai.research.relevance import select_subjects

log = get_logger(__name__)

API = "https://en.wikipedia.org/w/api.php"

#: Wikipedia asks for a descriptive agent with contact information. Being a
#: good citizen of a free API we depend on is not optional.
USER_AGENT = (
    "REWIND/0.1 (faceless history shorts; https://github.com/WildFire49/faceless-auto-video-gen)"
)


@register("research_source", "wikipedia")
class WikipediaSource:
    """Searches Wikipedia and returns plain-text article extracts."""

    name = "wikipedia"

    def __init__(
        self,
        *,
        max_articles: int = 3,
        search_pool: int = 3,
        offtopic_markers: Sequence[str] = (),
        timeout: int = 20,
    ) -> None:
        self._max_articles = max_articles
        # Hits considered to fill the cap. Never below it; above it lets a
        # rejected hit be replaced, at the cost of more word-overlap drift.
        self._search_pool = max(search_pool, max_articles)
        self._markers = list(offtopic_markers)
        self._timeout = timeout

    def fetch(self, topic: str, *, extra_urls: list[str]) -> list[Document]:
        del extra_urls  # handled by the user_url source

        titles = self._search(topic)
        if not titles:
            log.warning("no wikipedia articles found", topic=topic)
            return []

        descriptions = self._descriptions(titles)
        selection = select_subjects(
            [(title, descriptions.get(title)) for title in titles],
            self._markers,
            limit=self._max_articles,
        )
        for title, marker in selection.rejected:
            log.info("skipped off-topic article", topic=topic, title=title, marker=marker)

        documents: list[Document] = []
        for title in selection.kept:
            doc = self._extract(title)
            if doc is not None and doc.text.strip():
                documents.append(doc)
        return documents

    def _search(self, topic: str) -> list[str]:
        """Find the best-matching article titles for a topic."""
        params = {
            "action": "query",
            "list": "search",
            "srsearch": topic,
            "srlimit": str(self._search_pool),
            # Articles only; categories and talk pages are noise.
            "srnamespace": "0",
            "format": "json",
        }
        data = self._get(params)
        return [str(hit["title"]) for hit in data.get("query", {}).get("search", [])]

    def _descriptions(self, titles: list[str]) -> dict[str, str]:
        """Short descriptions for every title, in one request."""
        params = {
            "action": "query",
            "prop": "description",
            "titles": "|".join(titles),
            "format": "json",
        }
        pages: dict[str, Any] = self._get(params).get("query", {}).get("pages", {})
        return {
            str(page["title"]): str(page["description"])
            for page in pages.values()
            if "title" in page and page.get("description")
        }

    def _extract(self, title: str) -> Document | None:
        """Download one article as plain text."""
        params = {
            "action": "query",
            "prop": "extracts",
            "titles": title,
            # Plain text, whole article: the History section is what we want
            # and it is rarely the intro.
            "explaintext": "1",
            "format": "json",
        }
        data = self._get(params)

        pages: dict[str, Any] = data.get("query", {}).get("pages", {})
        for page_id, page in pages.items():
            if page_id == "-1":  # missing page
                continue
            text = page.get("extract", "")
            if not text:
                continue
            quoted = urllib.parse.quote(title.replace(" ", "_"))
            return Document(
                url=f"https://en.wikipedia.org/wiki/{quoted}",
                title=title,
                text=text,
                fetcher=self.name,
            )
        return None

    def _get(self, params: dict[str, str]) -> dict[str, Any]:
        url = f"{API}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise SourceUnreachableError("cannot reach the Wikipedia API", detail=str(exc)) from exc
        except json.JSONDecodeError as exc:
            raise SourceUnreachableError(
                "Wikipedia returned something that is not JSON", detail=str(exc)
            ) from exc

        if not isinstance(payload, dict):
            raise SourceUnreachableError("Wikipedia returned an unexpected shape")
        return payload
