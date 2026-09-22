"""User-supplied URLs (SPEC.md 5.2).

When you paste a URL at Gate A or in --notes, this fetches it and extracts the
article text with trafilatura, which strips navigation, adverts and comments.
"""

from __future__ import annotations

from rewind_ai.core.logging import get_logger
from rewind_ai.core.registry import register
from rewind_ai.research.base import Document

log = get_logger(__name__)


@register("research_source", "user_url")
class UserURLSource:
    """Fetches and extracts article text from URLs a human supplied."""

    name = "user_url"

    def __init__(self, *, timeout: int = 25) -> None:
        self._timeout = timeout

    def fetch(self, topic: str, *, extra_urls: list[str]) -> list[Document]:
        del topic  # this source is driven entirely by the supplied URLs
        if not extra_urls:
            return []

        # Imported lazily: trafilatura pulls in a sizeable dependency tree, and
        # most runs supply no URLs at all.
        try:
            import trafilatura
        except ImportError:
            log.warning("trafilatura is not installed; skipping user URLs")
            return []

        documents: list[Document] = []
        for url in extra_urls:
            if not url.startswith(("http://", "https://")):
                log.warning("skipping URL with an unsupported scheme", url=url)
                continue

            try:
                downloaded = trafilatura.fetch_url(url)
                if not downloaded:
                    log.warning("could not download URL", url=url)
                    continue

                text = trafilatura.extract(downloaded, include_comments=False)
                if not text:
                    log.warning("no article text found at URL", url=url)
                    continue

                metadata = trafilatura.extract_metadata(downloaded)
                title = getattr(metadata, "title", None) or url

            except Exception as exc:  # noqa: BLE001
                # One bad URL must not fail the whole research step -- the
                # other sources may still have produced plenty.
                log.warning("failed to fetch URL", url=url, error=str(exc))
                continue

            documents.append(Document(url=url, title=str(title), text=text, fetcher=self.name))

        return documents
