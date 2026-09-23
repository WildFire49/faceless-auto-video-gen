"""The Wikipedia source must stay on topic.

Found in E2E screenshots: for the topic "iron", research read the articles
"Iron Man" on one run and "Iron Maiden" on another, because it took the top
three search hits for the bare word. Their facts were real and verbatim -- the
verifier is about truth, not relevance -- so they reached Gate A, and on one
run all three comparisons chosen at Gate B were about a heavy-metal band.

The rule: the topic's own article (the top hit) is the anchor, and another
article is used only if it is linked with the anchor BOTH ways. No keyword
list to maintain, and no model deciding what is relevant.

The ways this can go wrong, written before the code:

 1. a hit not linked with the anchor at all (Iron Maiden)  -> dropped
 2. the anchor itself                                      -> always kept, first
 3. hits linked both ways                                  -> kept, search order
 4. fewer linked hits than wanted                          -> return fewer; do
                                                              NOT backfill with
                                                              unlinked hits,
                                                              which is the bug
 5. more linked hits than wanted                           -> capped
 6. no search hits at all                                  -> nothing, no crash
 7. the anchor links to nothing on the list                -> the anchor alone
 8. a ONE-WAY link, e.g. a hatnote ("For the resort chain, see Sandals
    Resorts")                                              -> dropped; found by
                                                              probing live
                                                              Wikipedia after
                                                              the first version
 9. a disambiguation page, however it is linked            -> dropped; a list
                                                              of meanings is
                                                              not a source
"""

from __future__ import annotations

from typing import Any

from rewind_ai.research.sources.wikipedia import WikipediaSource

SEARCH_HITS = ["Iron", "Iron Age", "Iron Man", "Cast iron", "Iron Maiden", "Pig iron"]
LINKED_BOTH_WAYS = {"Iron Age", "Cast iron", "Pig iron"}


class FakeWikipedia(WikipediaSource):
    """Answers the API calls the source makes from canned data."""

    def __init__(
        self,
        hits: list[str],
        forward: set[str],
        back: set[str] | None = None,
        max_articles: int = 3,
    ) -> None:
        super().__init__(max_articles=max_articles)
        self._hits = hits
        self._forward = forward  # titles the anchor links to
        self._back = forward if back is None else back  # titles linking to the anchor
        self.requests: list[dict[str, str]] = []

    def _get(self, params: dict[str, str]) -> dict[str, Any]:
        self.requests.append(params)

        if params.get("list") == "search":
            limit = int(params["srlimit"])
            return {"query": {"search": [{"title": t} for t in self._hits[:limit]]}}

        if params.get("prop") == "links":
            sources = params["titles"].split("|")
            targets = params["pltitles"].split("|")
            anchor = self._hits[0]
            pages = {}
            for i, source in enumerate(sources):
                if source == anchor:
                    links = [t for t in targets if t in self._forward]
                else:
                    links = [anchor] if anchor in targets and source in self._back else []
                pages[str(i)] = {"title": source, "links": [{"ns": 0, "title": t} for t in links]}
            return {"query": {"pages": pages}}

        title = params["titles"]
        return {"query": {"pages": {"1": {"title": title, "extract": f"Text of {title}."}}}}


def fetched_titles(source: WikipediaSource) -> list[str]:
    return [doc.title for doc in source.fetch("iron", extra_urls=[])]


def test_1_a_hit_not_linked_with_the_topic_is_dropped() -> None:
    titles = fetched_titles(FakeWikipedia(SEARCH_HITS, LINKED_BOTH_WAYS))
    assert "Iron Man" not in titles
    assert "Iron Maiden" not in titles


def test_2_and_3_the_anchor_first_then_linked_hits_in_search_order() -> None:
    titles = fetched_titles(FakeWikipedia(SEARCH_HITS, LINKED_BOTH_WAYS))
    assert titles == ["Iron", "Iron Age", "Cast iron"]


def test_4_too_few_linked_hits_is_not_backfilled_with_unlinked_ones() -> None:
    titles = fetched_titles(FakeWikipedia(SEARCH_HITS, {"Iron Age"}))
    assert titles == ["Iron", "Iron Age"]


def test_5_linked_hits_are_capped_at_max_articles() -> None:
    source = FakeWikipedia(SEARCH_HITS, LINKED_BOTH_WAYS, max_articles=2)
    assert fetched_titles(source) == ["Iron", "Iron Age"]


def test_6_no_search_hits_means_no_documents() -> None:
    assert fetched_titles(FakeWikipedia([], set())) == []


def test_7_an_anchor_that_links_to_nothing_on_the_list_stands_alone() -> None:
    assert fetched_titles(FakeWikipedia(SEARCH_HITS, set())) == ["Iron"]


def test_8_a_one_way_link_like_a_hatnote_is_dropped() -> None:
    hits = ["Sandal", "Sandals Resorts", "Espadrille"]
    # "Sandal" links to both; only "Espadrille" links back.
    source = FakeWikipedia(hits, forward={"Sandals Resorts", "Espadrille"}, back={"Espadrille"})
    assert [d.title for d in source.fetch("sandals", extra_urls=[])] == ["Sandal", "Espadrille"]


def test_9_a_disambiguation_page_is_never_a_source() -> None:
    hits = ["Sandal", "Sandal (disambiguation)", "Espadrille"]
    linked = {"Sandal (disambiguation)", "Espadrille"}
    source = FakeWikipedia(hits, forward=linked)
    assert [d.title for d in source.fetch("sandals", extra_urls=[])] == ["Sandal", "Espadrille"]


def test_more_hits_are_searched_than_are_kept() -> None:
    """Filtering three hits down would usually leave one; the pool is wider."""
    source = FakeWikipedia(SEARCH_HITS, LINKED_BOTH_WAYS)
    fetched_titles(source)
    search = next(r for r in source.requests if r.get("list") == "search")
    assert int(search["srlimit"]) > 3
