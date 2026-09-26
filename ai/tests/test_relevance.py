"""Tests for research subject selection.

Wikipedia search ranks by word overlap, not by meaning. A real run for "iron"
researched "Iron Man" (the Marvel superhero) as its third article, and
"sandals" returns "Sandals Resorts" and "Source Sandals" -- two companies. The
evidence verifier cannot catch this: every fact from those articles is true to
its source. It is simply not about the topic, and a brand is a product rule
violation on top.

Written as the list of ways the filter could fail, before the filter existed:

* lets a work of fiction through                -- the observed bug
* lets a company or brand through               -- the observed bug, sandals
* rejects a genuine subject                     -- loses real history
* matches a marker inside another word          -- "band" in "bandage"
* is case-sensitive                             -- "Film" slips past "film"
* drops an article because its description is missing -- fails closed
* drops the best match itself                   -- the user chose that topic;
                                                   a brand-named topic would
                                                   then research nothing
* exceeds the article cap after backfilling
"""

from __future__ import annotations

from rewind_ai.research.relevance import select_subjects

MARKERS = [
    "superhero",
    "comics",
    "fictional",
    "film",
    "band",
    "video game",
    "company",
    "manufacturer",
    "operator",
]

# Descriptions below are the real Wikipedia short descriptions, 2026-09-26.
IRON = [
    ("Iron", "Chemical element with atomic number 26 (Fe)"),
    ("Iron Age", "Archaeological period"),
    ("Iron Man", "Marvel Comics superhero"),
    ("Cast iron", "Iron-carbon alloy"),
]
SANDALS = [
    ("Sandal", "Type of footwear with an open upper"),
    ("Sandals Resorts", "Jamaican operator of all-inclusive resorts"),
    ("Source Sandals", "Shoe manufacturer in Israel"),
    ("Caligae", "Heavy-soled military boots of ancient Rome"),
]


def test_rejects_a_work_of_fiction() -> None:
    selection = select_subjects(IRON, MARKERS, limit=3)
    assert "Iron Man" not in selection.kept
    assert selection.kept == ["Iron", "Iron Age", "Cast iron"]


def test_rejects_companies_and_brands() -> None:
    selection = select_subjects(SANDALS, MARKERS, limit=3)
    assert selection.kept == ["Sandal", "Caligae"]


def test_keeps_every_genuine_subject() -> None:
    mouse = [
        ("Computer mouse", "Pointing device used to control a computer"),
        ("Cursor (user interface)", "Indicator showing where text would be input"),
        ("Mouse jiggler", "Motion simulator device for a computer mouse"),
    ]
    assert select_subjects(mouse, MARKERS, limit=3).kept == [t for t, _ in mouse]


def test_a_marker_inside_another_word_does_not_match() -> None:
    candidates = [
        ("Bandage", "Strip of material used to support a medical device"),
        ("Headband", "Clothing accessory worn in the hair or around the forehead"),
        ("Filmstrip", "Spooled roll of 35 mm positive film"),  # "film" IS a word here
    ]
    kept = select_subjects([("Anchor", "x"), *candidates], MARKERS, limit=4).kept
    assert "Bandage" in kept
    assert "Headband" in kept
    assert "Filmstrip" not in kept


def test_matching_ignores_case() -> None:
    candidates = [("Anchor", "x"), ("Iron Man (2008)", "2008 American Film")]
    assert select_subjects(candidates, MARKERS, limit=3).kept == ["Anchor"]


def test_multi_word_markers_match_as_a_phrase() -> None:
    candidates = [
        ("Anchor", "x"),
        ("Iron Man 3 (game)", "2013 video game"),
        ("Game of skill", "Game where the outcome depends on skill, not a video"),
    ]
    kept = select_subjects(candidates, MARKERS, limit=3).kept
    assert "Iron Man 3 (game)" not in kept
    assert "Game of skill" in kept


def test_a_missing_description_keeps_the_article() -> None:
    # Many real articles have no short description. Dropping them would fail
    # closed on exactly the obscure pages a history video needs.
    candidates = [("Anchor", "x"), ("Obscure smelting site", None), ("Blank", "")]
    kept = select_subjects(candidates, MARKERS, limit=3).kept
    assert kept == ["Anchor", "Obscure smelting site", "Blank"]


def test_the_best_match_is_never_dropped() -> None:
    # A user who asks for "LEGO" means the company's product. The filter only
    # guards against search drifting AWAY from the topic.
    candidates = [
        ("Lego", "Danish toy production company"),
        ("Lego Group", "Danish toy manufacturer"),
        ("History of Lego", "Aspect of history"),
    ]
    kept = select_subjects(candidates, MARKERS, limit=3).kept
    assert kept == ["Lego", "History of Lego"]


def test_the_cap_holds_after_backfilling() -> None:
    selection = select_subjects(IRON, MARKERS, limit=2)
    assert selection.kept == ["Iron", "Iron Age"]


def test_rejections_are_reported_with_their_reason() -> None:
    rejected = dict(select_subjects(SANDALS, MARKERS, limit=3).rejected)
    assert rejected == {"Sandals Resorts": "operator", "Source Sandals": "manufacturer"}


def test_no_candidates_selects_nothing() -> None:
    selection = select_subjects([], MARKERS, limit=3)
    assert selection.kept == []
    assert selection.rejected == []
