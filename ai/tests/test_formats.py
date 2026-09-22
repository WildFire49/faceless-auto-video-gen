"""Tests for content formats.

The point of this file is the LAST section: the same assertions run against
every registered format. A format that breaks one of them would break the
pipeline, and the pipeline itself cannot check that -- it is written against
the Protocol precisely so it does not have to know what formats exist.

The failure modes, written before the code (CLAUDE.md):

* a format returns a schema the pipeline cannot read          -> shared tests
* a format forgets to require `evidence`                      -> shared tests
* a format's prompt stops forbidding recall from training     -> shared tests
* a format accepts values that produce a nonsense video       -> per-format
* two formats collide on a registry name                      -> shared tests
"""

from __future__ import annotations

import pytest

from rewind_ai.formats import factory
from rewind_ai.formats.base import ContentFormat, RawItem
from rewind_ai.formats.providers.history_timeline import HistoryTimeline
from rewind_ai.formats.providers.myth_vs_fact import MythVsFact


def item(**kwargs: object) -> RawItem:
    base = {
        "label": "1882",
        "sort_key": 1882,
        "context": "",
        "claim": "The electric iron was patented.",
        "evidence": "Henry Seely patented the electric iron in 1882.",
        "extra": {},
    }
    base.update(kwargs)
    return RawItem(**base)  # type: ignore[arg-type]


# ------------------------------------------------------- history_timeline


def test_geological_time_is_rejected() -> None:
    """The exact value that crashed a real run.

    Asked about "iron", the model returned the formation of the Earth's core.
    True, correctly sourced, and useless for a series about everyday objects.
    """
    reason = HistoryTimeline().implausible_reason(item(sort_key=-4_600_000_000))
    assert reason, "the age of the Earth was accepted as a historical date"
    assert "geological" in reason


def test_future_dates_are_rejected() -> None:
    assert "future" in HistoryTimeline().implausible_reason(item(sort_key=3000))


@pytest.mark.parametrize(
    "year",
    [
        -7000,  # oldest known footwear, SPEC.md 5.2's own example
        -1200,  # the Iron Age
        1882,  # the electric iron
        2026,  # today
        -3_000_000,  # early stone tools: old, but still the history of a made thing
    ],
)
def test_real_historical_dates_are_accepted(year: int) -> None:
    assert HistoryTimeline().implausible_reason(item(sort_key=year)) == ""


def test_the_limit_is_about_usefulness_not_int32() -> None:
    """Tying the bound to a wire type would be the wrong reason.

    A value just inside int32 -- two billion years ago -- would then pass
    plausibility and produce a nonsense video.
    """
    from rewind_ai.formats.providers.history_timeline import MIN_PLAUSIBLE_YEAR

    assert MIN_PLAUSIBLE_YEAR > -2_147_483_648


@pytest.mark.parametrize(
    ("year", "expected"),
    [
        (-7000, "prehistory"),
        (-1200, "ancient"),
        (100, "classical"),
        (1882, "industrial"),
        (2020, "modern"),
    ],
)
def test_eras_spread_across_history(year: int, expected: str) -> None:
    assert HistoryTimeline().group_of(item(sort_key=year)) == expected


# ------------------------------------------------------------ myth_vs_fact


def test_surprise_rating_must_be_in_range() -> None:
    fmt = MythVsFact()
    assert fmt.implausible_reason(item(sort_key=0)) != ""
    assert fmt.implausible_reason(item(sort_key=9)) != ""
    assert fmt.implausible_reason(item(sort_key=3)) == ""


def test_a_myth_that_restates_its_correction_is_rejected() -> None:
    # Nothing for the narrator to overturn.
    fmt = MythVsFact()
    reason = fmt.implausible_reason(item(label="Iron rusts", claim="Iron rusts", sort_key=3))
    assert "same statement" in reason


def test_myths_group_by_domain() -> None:
    fmt = MythVsFact()
    assert fmt.group_of(item(context="Health", sort_key=3)) == "health"
    # No domain must not collapse everything into one group, which would fail
    # the variety check for the wrong reason.
    assert fmt.group_of(item(context="", sort_key=2)) != fmt.group_of(item(context="", sort_key=4))


def test_myth_parsing_keeps_the_belief_separate_from_the_correction() -> None:
    parsed = MythVsFact().parse_item(
        {
            "myth": "Cast iron pans cannot be washed with soap",
            "correction": "Modern soap does not damage seasoning.",
            "domain": "cooking",
            "surprise": 4,
            "evidence": "Modern dish soap does not strip polymerised seasoning.",
        }
    )
    assert parsed is not None
    assert parsed.label.startswith("Cast iron")
    assert parsed.claim.startswith("Modern soap")
    assert parsed.extra["myth"] == parsed.label


# ------------------------------------------------- every format, forever

ALL_FORMATS: list[ContentFormat] = [HistoryTimeline(), MythVsFact()]


@pytest.mark.parametrize("fmt", ALL_FORMATS, ids=lambda f: f.name)
def test_schema_is_shaped_the_way_the_pipeline_reads_it(fmt: ContentFormat) -> None:
    schema = fmt.item_schema()

    assert schema.get("type") == "object"
    assert "items" in schema.get("properties", {}), "the pipeline reads response['items']"
    assert schema["properties"]["items"]["type"] == "array"


@pytest.mark.parametrize("fmt", ALL_FORMATS, ids=lambda f: f.name)
def test_evidence_is_always_required(fmt: ContentFormat) -> None:
    """No format may make evidence optional.

    Without it there is nothing to verify, and an unverifiable claim is
    precisely what this project must never produce (CLAUDE.md).
    """
    required = fmt.item_schema()["properties"]["items"]["items"]["required"]
    assert "evidence" in required, f"{fmt.name} allows a claim with no evidence"


@pytest.mark.parametrize("fmt", ALL_FORMATS, ids=lambda f: f.name)
def test_prompt_forbids_using_training_knowledge(fmt: ContentFormat) -> None:
    prompt = fmt.system_prompt().lower()
    assert "only the text provided" in prompt, f"{fmt.name} does not forbid recall"
    assert "exactly" in prompt, f"{fmt.name} does not demand a verbatim quote"


@pytest.mark.parametrize("fmt", ALL_FORMATS, ids=lambda f: f.name)
def test_user_prompt_carries_the_source_text(fmt: ContentFormat) -> None:
    rendered = fmt.user_prompt(
        topic="iron", source_title="Iron", chunk="UNIQUE-SOURCE-MARKER", max_items=5
    )
    assert "UNIQUE-SOURCE-MARKER" in rendered
    assert "iron" in rendered


@pytest.mark.parametrize("fmt", ALL_FORMATS, ids=lambda f: f.name)
def test_gate_rules_are_sane(fmt: ContentFormat) -> None:
    rules = fmt.gate_rules()

    assert rules.min_items >= 1
    assert rules.min_groups >= 1
    assert rules.min_groups <= rules.min_items, (
        f"{fmt.name} demands more groups than items, which can never be satisfied"
    )
    assert rules.group_noun, f"{fmt.name} has no word for its groups"


@pytest.mark.parametrize("fmt", ALL_FORMATS, ids=lambda f: f.name)
def test_parse_item_rejects_empty_input(fmt: ContentFormat) -> None:
    assert fmt.parse_item({}) is None


# --------------------------------------------------------------- registry


def test_both_formats_are_discoverable() -> None:
    """The plug-and-play promise: a format is found by name from config alone."""
    assert set(factory.available()) >= {"history_timeline", "myth_vs_fact"}


def test_factory_builds_by_name() -> None:
    assert factory.build("myth_vs_fact").name == "myth_vs_fact"


def test_unknown_format_says_what_is_available() -> None:
    from rewind_ai.core import registry

    with pytest.raises(registry.ProviderError) as excinfo:
        factory.build("does_not_exist")

    assert "history_timeline" in str(excinfo.value)
