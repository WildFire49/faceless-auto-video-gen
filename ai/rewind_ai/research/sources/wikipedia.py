"""Wikipedia source (SPEC.md 5.2).

Uses the public action API: search for the topic, take the best matches, and
download plain text extracts. No key, no scraping, no rate-limit games -- the
API is explicitly provided for this.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from rewind_ai.core.errors import SourceUnreachableError
from rewind_ai.core.logging import get_logger
from rewind_ai.core.registry import register
from rewind_ai.research.base import Document

log = get_logger(__name__)

API = "https://en.wikipedia.org/w/api.php"

#: Wikipedia asks for a descriptive agent with contact information. Being a
#: good citizen of a free API we depend on is not optional.
USER_AGENT = (
    "REWIND/0.1 (faceless history shorts; https://github.com/WildFire49/faceless-auto-video-gen)"
)

#: How many search hits to consider per article kept. The pool is filtered to
#: the ones the topic's own article links to (see `_on_topic`).
SEARCH_POOL_FACTOR = 4

#: The API's limit on titles in one `pltitles` query.
_MAX_PLTITLES = 50


def _is_disambiguation(title: str) -> bool:
    """A list of other meanings is never a source about any one of them."""
    return title.endswith("(disambiguation)")


@register("research_source", "wikipedia")
class WikipediaSource:
    """Searches Wikipedia and returns plain-text article extracts."""

    name = "wikipedia"

    def __init__(self, *, max_articles: int = 3, timeout: int = 20) -> None:
        self._max_articles = max_articles
        self._timeout = timeout

    def fetch(self, topic: str, *, extra_urls: list[str]) -> list[Document]:
        del extra_urls  # handled by the user_url source

        hits = self._search(topic)
        if not hits:
            log.warning("no wikipedia articles found", topic=topic)
            return []

        titles = self._on_topic(hits)
        skipped = [t for t in hits if t not in titles]
        if skipped:
            log.info("skipped off-topic articles", anchor=hits[0], skipped=skipped)

        documents: list[Document] = []
        for title in titles[: self._max_articles]:
            doc = self._extract(title)
            if doc is not None and doc.text.strip():
                documents.append(doc)
        return documents

    def _on_topic(self, hits: list[str]) -> list[str]:
        """Keep the topic's own article and the hits it is linked with BOTH ways.

        The top hit is the anchor -- the article about the topic itself. Any
        other hit is kept only if the anchor links to it AND it links back.
        Searching "iron" used to return "Iron Man" and "Iron Maiden" among the
        top three.

        Both ways, because one way is not enough: a hatnote ("For the resort
        chain, see Sandals Resorts") is a link, so "Sandal" links to a hotel
        company. Measured on live topics, requiring the link back removed
        every off-topic article seen in a real run (Iron Man, Iron Maiden,
        Iron Cross, Sandals Resorts, Umbrella (song)). It is not perfect --
        "Toothbrush" and "Toothbrush moustache" hatnote each other -- which is
        why Gate A shows every source.

        Too few linked hits is NOT made up with unlinked ones: fewer sources
        beat off-topic ones.
        """
        anchor, rest = hits[0], [t for t in hits[1:] if not _is_disambiguation(t)]
        if not rest:
            return [anchor]
        forward = self._link_map(from_titles=[anchor], to_titles=rest).get(anchor, set())
        back = {
            title
            for title, links in self._link_map(from_titles=rest, to_titles=[anchor]).items()
            if anchor in links
        }
        kept = [anchor] + [title for title in rest if title in forward and title in back]
        return kept[: self._max_articles]

    def _link_map(self, *, from_titles: list[str], to_titles: list[str]) -> dict[str, set[str]]:
        """For each page in `from_titles`, which of `to_titles` it links to.

        Returned as a map rather than a set so the caller states which side
        it wants. A first version guessed the direction from how many titles
        were passed, and so read the wrong side whenever exactly one candidate
        remained -- silently dropping a good source (tests/test_wikipedia_source,
        case 9). One request each: `pltitles` limits the answer to the titles
        we care about rather than paging through every link in a long article.
        """
        params = {
            "action": "query",
            "prop": "links",
            "titles": "|".join(from_titles[:_MAX_PLTITLES]),
            "pltitles": "|".join(to_titles[:_MAX_PLTITLES]),
            "plnamespace": "0",
            "pllimit": "max",
            "format": "json",
        }
        data = self._get(params)
        pages: dict[str, Any] = data.get("query", {}).get("pages", {})
        return {
            str(page["title"]): {
                str(link["title"]) for link in page.get("links", []) if "title" in link
            }
            for page in pages.values()
            if "title" in page
        }

    def _search(self, topic: str) -> list[str]:
        """Find candidate article titles for a topic, best first.

        A wider pool than we keep, because `_on_topic` filters it: three hits
        filtered down would often leave only the anchor.
        """
        params = {
            "action": "query",
            "list": "search",
            "srsearch": topic,
            "srlimit": str(self._max_articles * SEARCH_POOL_FACTOR),
            # Articles only; categories and talk pages are noise.
            "srnamespace": "0",
            "format": "json",
        }
        data = self._get(params)
        return [str(hit["title"]) for hit in data.get("query", {}).get("search", [])]

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
