"""Choose which search hits are actually about the topic (SPEC.md 5.2).

Search ranks by word overlap, not meaning: "iron" finds "Iron Man", "sandals"
finds "Sandals Resorts". The evidence verifier cannot help -- every fact from
those pages is true to its source, just not about the topic. So subjects are
screened on their Wikipedia short description, which names what a page IS
("Marvel Comics superhero", "Shoe manufacturer in Israel") in a few words.

Pure function, no I/O: the source fetches, this decides.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Selection:
    """Titles to research, and the ones turned away with the marker that did it."""

    kept: list[str] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)


def select_subjects(
    candidates: Sequence[tuple[str, str | None]],
    markers: Sequence[str],
    *,
    limit: int,
) -> Selection:
    """Keep up to ``limit`` candidates, in search order, that are on topic.

    ``candidates`` are ``(title, short_description)`` pairs, best match first.
    The best match is always kept: the user chose that topic, and a
    brand-named one ("LEGO") would otherwise research nothing. The screen only
    guards against search drifting AWAY from it. A missing description keeps
    the article -- obscure pages often lack one and are the ones worth having.
    """
    patterns = [(m, _whole_phrase(m)) for m in markers]
    selection = Selection()

    for index, (title, description) in enumerate(candidates):
        if len(selection.kept) >= limit:
            break
        marker = None if index == 0 else _first_match(description or "", patterns)
        if marker is None:
            selection.kept.append(title)
        else:
            selection.rejected.append((title, marker))
    return selection


def _whole_phrase(marker: str) -> re.Pattern[str]:
    # Word boundaries so "band" does not reject "Bandage" or "Headband".
    return re.compile(rf"\b{re.escape(marker)}\b", re.IGNORECASE)


def _first_match(description: str, patterns: list[tuple[str, re.Pattern[str]]]) -> str | None:
    for marker, pattern in patterns:
        if pattern.search(description):
            return marker
    return None
