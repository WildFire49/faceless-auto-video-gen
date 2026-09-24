"""The script service: generate, validate, retry, write.

Offline: a fake model returns scripted answers, one per attempt.

The ways this can go wrong, written before the code:

 1. a valid first draft is regenerated anyway      -> one attempt, then stop
 2. a failed draft is retried WITHOUT saying why   -> the second prompt must
                                                      carry the broken rules
 3. every attempt fails and the service raises     -> no: the best attempt is
                                                      written WITH its
                                                      violations, for Gate C
 4. ...or writes the LAST attempt, not the best    -> fewest violations wins
 5. no approved facts                              -> refused, not a script
                                                      about nothing
 6. the model returns the wrong shape              -> a script with
                                                      violations, not a crash
 7. the model invents source URLs                  -> sources come from the
                                                      cited facts only
 8. the angle leaks into facts                     -> it is labelled tone-only
                                                      in the prompt, and an
                                                      empty angle adds nothing
 9. script.json cannot be read back                -> round-trips intact

Found by the first live Gate C run (qwen3:8b wrote 23-31 word beats):
10. `attempts` records the attempt KEPT, not how many were MADE -> after
    three tries Gate C said "tried 1 time"
11. a draft broken only beat-by-beat is regenerated whole -> good beats
    break: the live retry lost year stamps and invented numbers while
    shortening lines. Local problems are REPAIRED, other beats locked.
12. a repair touches a beat that was not broken     -> ignored
13. a repair changes which facts a beat cites       -> ignored; numbers are
                                                      checked against them
14. a structural problem (wrong beat count) is "repaired" -> no: regenerated
                                                      whole, with feedback
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from rewind_ai.core.errors import ValidationFailedError
from rewind_ai.formats.providers.history_timeline import HistoryTimeline
from rewind_ai.llm.templates import Templates
from rewind_ai.script import codec
from rewind_ai.script.context import Limits
from rewind_ai.script.service import ScriptConfig, ScriptService
from tests.test_script_rules import FACTS, REFS, valid_script

FACTS_WITH_SOURCES = [
    dataclasses.replace(f, source_url=f"https://en.wikipedia.org/wiki/{f.id}") for f in FACTS
]


def model_output(script: Any = None, **beat_changes: Any) -> dict[str, Any]:
    """What a model would return: the script, minus what it may not write."""
    data = codec.to_json(script or valid_script())
    for beat in data["beats"]:
        beat.pop("n")
        if beat_changes and beat is data["beats"][beat_changes.get("index", 3)]:
            beat.update({k: v for k, v in beat_changes.items() if k != "index"})
    data.pop("sources")
    return data


INVALID_ONCE = model_output(voice="In 1775, a Birkenstock registered as a shoemaker.")
#: A structural failure: one beat short. Only full regeneration can fix it.
STRUCTURAL = model_output(valid_script().__class__(beats=valid_script().beats[:8]))
WORSE_STRUCTURAL = model_output(valid_script().__class__(beats=valid_script().beats[:5]))


def repair(n: int, **fields: Any) -> dict[str, Any]:
    """What the model returns when asked to rewrite specific beats."""
    return {"beats": [{"n": n, **fields}]}


GOOD_BEAT_4 = "In 1774, a Birkenstock registered as a shoemaker. Just paperwork."
INVALID_TWICE = model_output(
    voice="In 1775, in seventeen seventy-five, a Birkenstock registered. Twice wrong."
)


class FakeLLM:
    def __init__(self, answers: list[dict[str, Any]]) -> None:
        self._answers = answers
        self.prompts: list[str] = []

    def complete_json(self, *, system: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        del system, schema
        self.prompts.append(prompt)
        return self._answers[min(len(self.prompts) - 1, len(self._answers) - 1)]


def build(tmp_path: Path, answers: list[dict[str, Any]]) -> tuple[ScriptService, FakeLLM]:
    llm = FakeLLM(answers)
    service = ScriptService(
        llm=llm,
        content_format=HistoryTimeline(),
        style_bible="Dry. Deadpan.",
        config=ScriptConfig(
            limits=Limits(
                beats=9,
                max_words_per_beat=14,
                max_sfx_per_beat=1,
                max_references=3,
                loop_min_shared_words=2,
            ),
            max_attempts=3,
        ),
        templates=Templates(),
        projects_dir=tmp_path,
    )
    return service, llm


def generate(service: ScriptService, angle: str = "") -> Any:
    return service.generate(
        video_id="sandals",
        topic="sandals",
        angle=angle,
        facts=FACTS_WITH_SOURCES,
        references=REFS,
    )


def test_1_a_valid_first_draft_is_kept(tmp_path: Path) -> None:
    service, llm = build(tmp_path, [model_output()])
    script = generate(service)
    assert len(llm.prompts) == 1
    assert script.attempts == 1
    assert script.violations == []


def test_2_a_regeneration_says_what_was_wrong(tmp_path: Path) -> None:
    service, llm = build(tmp_path, [STRUCTURAL, model_output()])
    script = generate(service)
    assert script.attempts == 2 and script.violations == []
    assert "PREVIOUS ATTEMPT" not in llm.prompts[0]
    assert "PREVIOUS ATTEMPT" in llm.prompts[1]
    assert "8 beats" in llm.prompts[1], "the second prompt must name what was wrong"


def test_3_every_attempt_failing_still_writes_a_script_with_its_violations(
    tmp_path: Path,
) -> None:
    service, llm = build(tmp_path, [INVALID_ONCE])
    script = generate(service)
    # Every budget spent: 3 drafts, each followed by 3 repair passes.
    assert len(llm.prompts) == 3 * (1 + 3)
    assert script.attempts == 3
    assert script.violations, "an invalid script must never be passed off as valid"
    on_disk = json.loads((tmp_path / "sandals" / "script.json").read_text(encoding="utf-8"))
    assert on_disk["violations"], "Gate C reads the violations from script.json"


def test_4_the_best_attempt_wins_not_the_last(tmp_path: Path) -> None:
    service, _ = build(tmp_path, [STRUCTURAL, WORSE_STRUCTURAL, WORSE_STRUCTURAL])
    script = generate(service)
    assert len(script.beats) == 8, "attempt 1 had the fewest violations and must be kept"


def test_10_attempts_counts_attempts_made_not_the_one_kept(tmp_path: Path) -> None:
    service, llm = build(tmp_path, [STRUCTURAL, WORSE_STRUCTURAL, WORSE_STRUCTURAL])
    script = generate(service)
    assert len(llm.prompts) == 3
    assert script.attempts == 3, "three tries were made; Gate C must not say 'tried 1 time'"


def test_11_a_local_problem_is_repaired_with_other_beats_locked(tmp_path: Path) -> None:
    service, llm = build(tmp_path, [INVALID_ONCE, repair(4, voice=GOOD_BEAT_4)])
    script = generate(service)

    assert script.violations == [] and script.attempts == 1, "a repair is not a new draft"
    assert "REWRITE ONLY" in llm.prompts[1], "a local problem must be repaired, not regenerated"
    assert "BEAT PLAN" not in llm.prompts[1]
    untouched = [b for b in valid_script().beats if b.n != 4]
    assert [b for b in script.beats if b.n != 4] == untouched


def test_12_a_repair_cannot_touch_a_beat_that_was_not_broken(tmp_path: Path) -> None:
    rogue = {"beats": [{"n": 4, "voice": GOOD_BEAT_4}, {"n": 1, "voice": "Rewritten hook."}]}
    service, _ = build(tmp_path, [INVALID_ONCE, rogue])
    script = generate(service)
    assert script.beats[3].voice == GOOD_BEAT_4, "the repair itself must have happened"
    assert script.beats[0].voice == valid_script().beats[0].voice


def test_13_a_repair_cannot_change_which_facts_a_beat_cites(tmp_path: Path) -> None:
    service, _ = build(tmp_path, [INVALID_ONCE, repair(4, voice=GOOD_BEAT_4, fact_ids=["f5"])])
    script = generate(service)
    assert script.beats[3].voice == GOOD_BEAT_4, "the repair itself must have happened"
    assert script.beats[3].fact_ids == ["f4"]


def test_14_the_repair_prompt_names_the_beat_its_problem_and_its_facts(
    tmp_path: Path,
) -> None:
    service, llm = build(tmp_path, [INVALID_ONCE, repair(4, voice=GOOD_BEAT_4)])
    generate(service)
    prompt = llm.prompts[1]
    assert "REWRITE ONLY" in prompt, "this must be the repair prompt, not a regeneration"
    assert "beat 4" in prompt and "1775" in prompt
    assert "Johann Adam Birkenstock" in prompt, "the repair must see the quote it may draw on"


def test_5_no_approved_facts_is_refused(tmp_path: Path) -> None:
    service, _ = build(tmp_path, [model_output()])
    with pytest.raises(ValidationFailedError):
        service.generate(video_id="x", topic="x", angle="", facts=[], references=[])


def test_6_the_wrong_shape_becomes_violations_not_a_crash(tmp_path: Path) -> None:
    service, _ = build(tmp_path, [{"title_options": "one", "beats": "not a list"}])
    script = generate(service)
    assert any(v.rule == "BEAT_COUNT" for v in script.violations)


def test_7_sources_come_from_the_cited_facts(tmp_path: Path) -> None:
    invented = model_output()
    invented["sources"] = ["https://made-up.example/proof"]
    service, _ = build(tmp_path, [invented])
    script = generate(service)
    assert "https://made-up.example/proof" not in script.sources
    assert script.sources[0] == "https://en.wikipedia.org/wiki/f1"


def test_8_the_angle_is_tone_only(tmp_path: Path) -> None:
    service, llm = build(tmp_path, [model_output()])
    generate(service, angle="focus on how ugly they were")
    assert "focus on how ugly they were" in llm.prompts[0]
    assert "TONE AND EMPHASIS ONLY" in llm.prompts[0]

    service, llm = build(tmp_path, [model_output()])
    generate(service, angle="")
    assert "TONE AND EMPHASIS ONLY" not in llm.prompts[0]


def test_9_script_json_round_trips(tmp_path: Path) -> None:
    service, _ = build(tmp_path, [model_output()])
    script = generate(service)
    on_disk = json.loads((tmp_path / "sandals" / "script.json").read_text(encoding="utf-8"))
    assert codec.from_json(on_disk) == script


# --------------------------------------------- what the model is NOT trusted with
#
# Found by the second live run: the model rounded dates ("By 1700 AD" for a
# fact about 1709), wrote "IKEA flat-pack instructions" without declaring r3,
# and ran 2-3 words over on most beats. The first two are taken off it
# entirely, in ways that can only make a script MORE truthful:
#
# 15. the year stamp is the cited fact's own label, never the model's
# 16. a mentioned comparison is declared -- which puts it UNDER the cap and the
#     brand-claim check -- but only when the beat cites its fact
# 17. ...otherwise it is left undeclared, so the violation stands
# 18. the model writes a beat as a short fact line and a short punch, which
#     are joined into the narration


def test_15_the_year_stamp_is_the_cited_facts_label(tmp_path: Path) -> None:
    drifted = model_output(year_stamp="By 1700 AD")  # beat 4 cites f4, labelled "1774"
    service, _ = build(tmp_path, [drifted])
    script = generate(service)
    assert script.beats[3].year_stamp == "1774"


def test_16_a_mentioned_comparison_is_declared_when_its_fact_is_cited(tmp_path: Path) -> None:
    undeclared = model_output(index=2, ref_ids=[])  # beat 3 says "A limited drop.", cites f3
    service, _ = build(tmp_path, [undeclared])
    script = generate(service)
    assert script.beats[2].ref_ids == ["r2"]
    assert script.violations == []


def test_17_a_comparison_whose_fact_is_not_cited_stays_undeclared(tmp_path: Path) -> None:
    # r1 (Crocs) is attached to f2; beat 4 cites f4.
    stray = model_output(voice="In 1774, a Birkenstock registered. Basically Crocs.")
    service, _ = build(tmp_path, [stray])
    script = generate(service)
    assert "r1" not in script.beats[3].ref_ids
    assert any(v.rule == "UNDECLARED_REFERENCE" for v in script.violations)


def test_18_a_fact_line_and_a_punch_become_the_narration(tmp_path: Path) -> None:
    two_part = model_output(
        voice="", fact_line="In 1774, a Birkenstock registered.", punch="Just paperwork."
    )
    service, _ = build(tmp_path, [two_part])
    script = generate(service)
    assert script.beats[3].voice == "In 1774, a Birkenstock registered. Just paperwork."


# ------------------------------------------------ repairs within a draft
#
# Found by the third live run: 20+ violations -> 4 after one repair -> 3,
# then the budget ran out. Repairs took 6-12s against ~60s for a draft, and
# were spending the 3-DRAFT budget SPEC.md 5.4 sets for regenerations.
#
# 19. repairs consume draft attempts            -> no: each draft gets its own
#                                                  repair budget; `attempts`
#                                                  counts drafts
# 20. a repair offers every comparison          -> the model dropped one into
#     a beat that does not cite its fact; offer only those tied to the beat
# 21. "reuse key words from beat 1" is too vague -> the repair names the words


def test_19_repairs_do_not_spend_draft_attempts(tmp_path: Path) -> None:
    still_bad = repair(4, voice="In 1775, a Birkenstock registered as a shoemaker.")
    service, llm = build(
        tmp_path, [INVALID_ONCE, still_bad, still_bad, repair(4, voice=GOOD_BEAT_4)]
    )
    script = generate(service)
    assert script.violations == []
    assert script.attempts == 1, "one draft, three repairs: that is one attempt"
    assert len(llm.prompts) == 4


def test_20_a_repair_offers_only_comparisons_tied_to_the_beats_facts(tmp_path: Path) -> None:
    # Beat 4 cites f4; r1 is tied to f2 and r2 to f3 -- neither may be offered.
    service, llm = build(tmp_path, [INVALID_ONCE, repair(4, voice=GOOD_BEAT_4)])
    generate(service)
    fix_section = llm.prompts[1].split("FIX THESE BEATS:")[1]
    assert "Crocs" not in fix_section
    assert "limited drop" not in fix_section


def test_21_a_loop_repair_names_the_words_to_reuse(tmp_path: Path) -> None:
    no_loop = model_output(index=8, voice="Today they come in every colour imaginable.")
    service, llm = build(tmp_path, [no_loop, repair(9, voice=valid_script().beats[8].voice)])
    script = generate(service)
    assert script.violations == []
    words_line = next(line for line in llm.prompts[1].splitlines() if "reuse" in line.lower())
    assert "sandals" in words_line and "oldest" in words_line


# ------------------------------------------------- each draft repairs itself
#
# Found by the fourth live run: drafts 2 and 3 ended on EXACTLY the six
# violations draft 1's repairs had stalled on. A new draft that started with
# more violations than the best so far was discarded on arrival, and the
# repairs carried on patching the old, stuck script -- two drafts wasted.
#
# 22. a later draft is repaired, not the stale best      -> each draft gets its
#                                                          own repair lineage
# 23. repairs run as hot as drafting                    -> a repair is an edit;
#                                                          it gets the cooler
#                                                          repair model


NOOP: dict[str, Any] = {"beats": []}
DRAFT_TWO = model_output(index=6, voice="By 1963, flip-flops had taken over America.")


def test_22_a_later_draft_is_repaired_not_the_stale_best(tmp_path: Path) -> None:
    fixed_beat_7 = valid_script().beats[6].voice
    service, _ = build(
        tmp_path, [INVALID_ONCE, NOOP, NOOP, NOOP, DRAFT_TWO, repair(7, voice=fixed_beat_7)]
    )
    script = generate(service)
    assert script.violations == [], "draft 2's broken beat was fixable; draft 1's was not"
    assert script.attempts == 2


def test_23_repairs_use_the_repair_model(tmp_path: Path) -> None:
    drafter = FakeLLM([INVALID_ONCE])
    editor = FakeLLM([repair(4, voice=GOOD_BEAT_4)])
    service = ScriptService(
        llm=drafter,
        repair_llm=editor,
        content_format=HistoryTimeline(),
        style_bible="",
        config=ScriptConfig(
            limits=Limits(
                beats=9,
                max_words_per_beat=14,
                max_sfx_per_beat=1,
                max_references=3,
                loop_min_shared_words=2,
            )
        ),
        templates=Templates(),
        projects_dir=tmp_path,
    )
    script = generate(service)
    assert script.violations == []
    assert len(drafter.prompts) == 1 and len(editor.prompts) == 1
    assert "REWRITE ONLY" in editor.prompts[0]
