"""The script validator: every way a script can be wrong, written first.

SPEC.md 5.4's acceptance names three injected errors the validator must catch
-- a wrong year, a 20-word beat, a missing loop. They are here, along with the
rest of what the model can get wrong when it writes:

STRUCTURE
 1. the wrong number of beats                          -> BEAT_COUNT
 2. a beat in the wrong slot (rehook moved)            -> BEAT_ROLE
 3. a 20-word beat                                     -> BEAT_TOO_LONG   (spec)
 4. two sound effects in one beat                      -> TOO_MANY_SFX
 5. an era beat with no year stamp                     -> YEAR_STAMP_MISSING
 6. an era beat that cites no fact                     -> FACT_NOT_CITED
 7. the last beat does not echo the first              -> NO_LOOP         (spec)
 8. a beat with nothing to say                         -> EMPTY_BEAT

EVIDENCE -- the rule this project exists for
 9. a wrong year (1775 where the fact says 1774)       -> UNGROUNDED_NUMBER (spec)
10. a TRUE number from a fact the beat does not cite   -> UNGROUNDED_NUMBER;
    per-beat grounding is stricter than "somewhere in the sheet", and the
    only way the fact_ids a reviewer sees mean anything
11. a wrong year stamp                                 -> UNGROUNDED_NUMBER
12. a wrong number in the on-screen text               -> UNGROUNDED_NUMBER
13. a unit conversion ("9,000 years" from "7000 BC")   -> UNGROUNDED_NUMBER
14. a spelled-out number ("seventeen seventy-four")    -> SPELLED_NUMBER; the
    decision at M4 kickoff is digits in the script, precisely so 9-13 can be
    checked at all
15. a fact id that is not an approved fact            -> UNKNOWN_FACT
16. a reference that was not selected at Gate B       -> UNKNOWN_REFERENCE
17. more references than the limit                    -> TOO_MANY_REFERENCES
18. a reference in a beat that does not cite the fact it was attached to
                                                       -> REFERENCE_WITHOUT_ITS_FACT
    (SPEC.md 6: each must connect to a real fact in the same beat)
19. a claim about the brand ("Crocs invented ...")     -> BRAND_CLAIM
20. a number in a title that no approved fact contains -> UNGROUNDED_NUMBER
21. ... or in the description                          -> UNGROUNDED_NUMBER
22. an image prompt that names a brand                 -> BRAND_IN_VISUAL
23. a selected comparison used but not declared        -> UNDECLARED_REFERENCE
    (found live: "like a limited drop" with ref_ids [])
24. a closing beat citing nothing                      -> FACT_NOT_CITED
    (found live: "iron is everywhere" cited no fact)

AND WHAT MUST NOT BE FLAGGED
 - the valid script, clean                             (the baseline -- without
   it every "is caught" test could pass for the wrong reason)
 - "7,000" where the fact says "7000"
 - "one" as a word ("the one thing") -- too common to police
 - a claim verb about the FACT, not the brand ("Roman soldiers invented the
   hobnail. Basically Crocs.")
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from rewind_ai.formats.providers.history_timeline import HistoryTimeline
from rewind_ai.script.base import Beat, Script, ScriptFact, ScriptReference
from rewind_ai.script.rules import Limits, RuleContext, validate

FACTS = [
    ScriptFact(
        "f1",
        "~7000 BC",
        "The oldest known sandals were woven from sagebrush bark.",
        "The oldest known footwear in the world are sandals woven from sagebrush bark, "
        "dated to approximately 7000 or 8000 BC, found at the Fort Rock Cave in Oregon.",
    ),
    ScriptFact(
        "f2",
        "Roman Republic",
        "Roman soldiers wore hobnailed caligae.",
        "Roman soldiers wore caligae, heavy-soled hobnailed military sandals.",
    ),
    ScriptFact(
        "f3",
        "12th century",
        "Japanese zori were made of rice straw.",
        "In the 12th century, the Japanese wore zori, flat sandals made of rice straw.",
    ),
    ScriptFact(
        "f4",
        "1774",
        "A Birkenstock was registered as a shoemaker.",
        "In 1774, Johann Adam Birkenstock was registered as a shoemaker in Germany.",
    ),
    ScriptFact(
        "f5",
        "1902",
        "The Birkenstock footbed was patented.",
        "The Birkenstock footbed was patented in 1902 by Konrad Birkenstock.",
    ),
    ScriptFact(
        "f6",
        "1962",
        "Flip-flops became popular in America.",
        "By 1962, the flip-flop had become popular in the United States.",
    ),
    ScriptFact(
        "f7",
        "1960s",
        "Sandals became a counterculture symbol.",
        "During the 1960s counterculture movement, sandals became a symbol of a simple lifestyle.",
    ),
]

REFS = [
    ScriptReference("r1", "Crocs", "Roman caligae were basically Crocs with spikes.", "f2"),
    ScriptReference("r2", "limited drop", "Straw zori were a limited drop.", "f3"),
]


def valid_script() -> Script:
    return Script(
        title_options=["Roman Soldiers Wore Spiked Sandals", "Sandals Since 7000 BC"],
        beats=[
            Beat(
                1,
                "hook",
                "These are the oldest sandals ever found. Woven bark. Let's rewind.",
                year_stamp="~7000 BC",
                on_screen_text="7000 BC",
                sfx="rewind",
                fact_ids=["f1"],
            ),
            Beat(
                2,
                "era",
                "Roman soldiers wore hobnailed sandals. Basically Crocs with spikes.",
                year_stamp="Roman Republic",
                fact_ids=["f2"],
                ref_ids=["r1"],
                is_punch=True,
            ),
            Beat(
                3,
                "era",
                "In the 12th century, Japan wore rice straw. A limited drop.",
                year_stamp="12th century",
                fact_ids=["f3"],
                ref_ids=["r2"],
            ),
            Beat(
                4,
                "era",
                "In 1774, a Birkenstock registered as a shoemaker. Just paperwork.",
                year_stamp="1774",
                fact_ids=["f4"],
            ),
            Beat(5, "rehook", "And the next one got a patent."),
            Beat(
                6,
                "era",
                "In 1902, the footbed was patented. Arch support, officially.",
                year_stamp="1902",
                fact_ids=["f5"],
            ),
            Beat(
                7,
                "era",
                "By 1962, flip-flops had taken over America.",
                year_stamp="1962",
                fact_ids=["f6"],
            ),
            Beat(
                8,
                "era",
                "In the 1960s, sandals meant a simple lifestyle. Allegedly.",
                year_stamp="1960s",
                fact_ids=["f7"],
            ),
            Beat(
                9,
                "today",
                "Today they still sell. The oldest sandals ever found would approve.",
                fact_ids=["f7"],
            ),
        ],
    )


def context(**limit_overrides: int) -> RuleContext:
    limits = Limits(
        beats=9,
        max_words_per_beat=14,
        max_sfx_per_beat=1,
        max_references=3,
        loop_min_shared_words=2,
    )
    return RuleContext(
        shape=HistoryTimeline().script_shape(9),
        facts={f.id: f for f in FACTS},
        references={r.id: r for r in REFS},
        limits=dataclasses.replace(limits, **limit_overrides),
    )


def with_beat(script: Script, n: int, **changes: Any) -> Script:
    beats = [dataclasses.replace(b, **changes) if b.n == n else b for b in script.beats]
    return dataclasses.replace(script, beats=beats)


def rules_broken(script: Script, ctx: RuleContext | None = None) -> set[str]:
    return {v.rule for v in validate(script, ctx or context())}


# ---------------------------------------------------------------- baseline


def test_the_valid_script_is_clean() -> None:
    violations = validate(valid_script(), context())
    assert violations == [], [f"{v.rule} beat {v.beat}: {v.message}" for v in violations]


# ---------------------------------------------------------------- structure


def test_1_wrong_beat_count() -> None:
    script = valid_script()
    script = dataclasses.replace(script, beats=script.beats[:8])
    assert "BEAT_COUNT" in rules_broken(script)


def test_2_a_beat_in_the_wrong_slot() -> None:
    assert "BEAT_ROLE" in rules_broken(with_beat(valid_script(), 5, role="era"))


def test_3_a_20_word_beat() -> None:
    long = " ".join(["word"] * 20)
    assert "BEAT_TOO_LONG" in rules_broken(with_beat(valid_script(), 7, voice=long))


def test_4_two_sound_effects() -> None:
    assert "TOO_MANY_SFX" in rules_broken(with_beat(valid_script(), 3, sfx="whoosh, ding"))


def test_5_an_era_beat_without_a_year_stamp() -> None:
    assert "YEAR_STAMP_MISSING" in rules_broken(with_beat(valid_script(), 6, year_stamp=""))


def test_6_an_era_beat_citing_no_fact() -> None:
    assert "FACT_NOT_CITED" in rules_broken(with_beat(valid_script(), 7, fact_ids=[]))


def test_7_no_loop() -> None:
    script = with_beat(valid_script(), 9, voice="Today they come in every colour imaginable.")
    assert "NO_LOOP" in rules_broken(script)


def test_8_an_empty_beat() -> None:
    assert "EMPTY_BEAT" in rules_broken(with_beat(valid_script(), 5, voice="  "))


# ----------------------------------------------------------------- evidence


def test_9_a_wrong_year() -> None:
    script = with_beat(valid_script(), 4, voice="In 1775, a Birkenstock registered as a shoemaker.")
    violations = [v for v in validate(script, context()) if v.rule == "UNGROUNDED_NUMBER"]
    assert violations and violations[0].beat == 4
    assert "1775" in violations[0].message


def test_10_a_true_number_from_a_fact_the_beat_does_not_cite() -> None:
    # 1902 is a real, approved fact -- but beat 4 cites f4, not f5.
    script = with_beat(valid_script(), 4, voice="In 1902, a Birkenstock registered as a shoemaker.")
    assert "UNGROUNDED_NUMBER" in rules_broken(script)


def test_11_a_wrong_year_stamp() -> None:
    assert "UNGROUNDED_NUMBER" in rules_broken(with_beat(valid_script(), 6, year_stamp="1903"))


def test_12_a_wrong_number_on_screen() -> None:
    assert "UNGROUNDED_NUMBER" in rules_broken(
        with_beat(valid_script(), 1, on_screen_text="9000 BC")
    )


def test_13_a_unit_conversion() -> None:
    script = with_beat(valid_script(), 1, voice="These sandals are 9,000 years old. Let's rewind.")
    assert "UNGROUNDED_NUMBER" in rules_broken(script)


@pytest.mark.parametrize(
    "voice",
    ["In seventeen seventy-four, a Birkenstock registered.", "Nine thousand years of sandals."],
)
def test_14_a_spelled_out_number(voice: str) -> None:
    assert "SPELLED_NUMBER" in rules_broken(with_beat(valid_script(), 4, voice=voice))


def test_15_an_unknown_fact() -> None:
    assert "UNKNOWN_FACT" in rules_broken(with_beat(valid_script(), 7, fact_ids=["f99"]))


def test_16_a_reference_not_selected() -> None:
    assert "UNKNOWN_REFERENCE" in rules_broken(with_beat(valid_script(), 3, ref_ids=["r9"]))


def test_17_more_references_than_the_limit() -> None:
    assert "TOO_MANY_REFERENCES" in rules_broken(valid_script(), context(max_references=1))


def test_18_a_reference_without_its_fact() -> None:
    # r1 is attached to f2; beat 3 cites f3.
    assert "REFERENCE_WITHOUT_ITS_FACT" in rules_broken(
        with_beat(valid_script(), 3, ref_ids=["r1"])
    )


def test_19_a_claim_about_the_brand() -> None:
    script = with_beat(valid_script(), 2, voice="Crocs invented the hobnail for Roman soldiers.")
    assert "BRAND_CLAIM" in rules_broken(script)


def test_20_an_ungrounded_number_in_a_title() -> None:
    script = dataclasses.replace(valid_script(), title_options=["9000 Years of Sandals"])
    assert "UNGROUNDED_NUMBER" in rules_broken(script)


def test_21_an_ungrounded_number_in_the_description() -> None:
    script = dataclasses.replace(valid_script(), description="Sandals, 9000 years in the making.")
    assert "UNGROUNDED_NUMBER" in rules_broken(script)


def test_23_a_comparison_used_without_being_declared() -> None:
    """Found in a live run: 'like a limited drop' in a beat with ref_ids []. An
    undeclared comparison escapes the 3-reference cap, the must-sit-with-its-
    fact rule and the brand-claim check -- every rule keyed on ref_ids."""
    script = with_beat(
        valid_script(), 4, voice="In 1774, a Birkenstock registered. A limited drop."
    )
    assert "UNDECLARED_REFERENCE" in rules_broken(script)


def test_24_the_closing_beat_must_cite_a_fact() -> None:
    """Found in a live run: 'Today, iron is everywhere -- from skyscrapers to
    smartphones' cited nothing. 'The modern version' is a claim like any
    other; if it cites no approved fact, the model is its source."""
    assert "FACT_NOT_CITED" in rules_broken(with_beat(valid_script(), 9, fact_ids=[]))


def test_22_a_visual_prompt_that_names_a_brand() -> None:
    """CLAUDE.md: no brand logos or product designs in generated images. A
    prompt naming the brand is how one gets there, so it is stopped here --
    one rule now instead of a wasted render at Module 6."""
    script = with_beat(valid_script(), 2, visual_prompts=["Roman soldier wearing Crocs"])
    assert "BRAND_IN_VISUAL" in rules_broken(script)


# ------------------------------------------------------- must NOT be flagged


def test_a_thousands_separator_is_the_same_number() -> None:
    assert rules_broken(with_beat(valid_script(), 1, on_screen_text="7,000 BC")) == set()


def test_one_as_a_word_is_not_policed() -> None:
    script = with_beat(valid_script(), 5, voice="And the next one is the one that got a patent.")
    assert rules_broken(script) == set()


def test_a_claim_verb_about_the_fact_is_not_a_brand_claim() -> None:
    script = with_beat(
        valid_script(), 2, voice="Roman soldiers invented hobnailed sandals. Basically Crocs."
    )
    assert "BRAND_CLAIM" not in rules_broken(script)
