"""Gate C checks: the script (SPEC.md 5.4).

What these prove against the live stack:

  * the script step runs, and the script it writes passes every rule
  * INDEPENDENTLY of the worker: every number in every beat is in an approved
    fact that beat cites, every cited fact is approved, every comparison was
    selected -- recomputed here from the fact and reference sheets, not taken
    from the worker's own verdict
  * a wrong year edited in at Gate C is caught, and the gate refuses to open
  * the fix is accepted, a title can be chosen, and then the gate opens
  * SPEC.md 5.4's acceptance -- valid on the first or second try -- checked
    last, so a slow model still lets every other check run

The ways the Gate C flow could be wrong that only a live run shows:

  1. the step never registers or never runs         -> no script appears
  2. the worker says "valid" about an invalid script -> the independent
                                                        recheck disagrees
  3. an edit is saved without being re-checked       -> the injected year is
                                                        not flagged
  4. a flagged script can still be approved          -> ApproveGate succeeds
  5. fixing the edit leaves the old verdict behind   -> the fix is not accepted
"""

from __future__ import annotations

import re
import sys
from typing import Any

from harness import REPO_ROOT, Client, E2EFailure, Run, run_step_and_wait

# The worker's own number normaliser, so "7,000" and "7000" are one number
# here exactly as they are in the rules being re-checked. Imported after the
# path is set because the harness is not installed as part of the worker.
sys.path.insert(0, str(REPO_ROOT / "ai"))
from rewind_ai.research.verifier import numbers_in
from rewind_ai.script.structure_rules import content_words

_FIRST_NUMBER = re.compile(r"\d[\d,]*")


def _script_view(client: Client, video_id: str) -> dict[str, Any]:
    resp = client.call("ScriptsService", "GetScript", {"videoId": video_id})
    if resp["_status"] != 200:
        raise E2EFailure(f"GetScript returned HTTP {resp['_status']}: {resp.get('message')}")
    return dict(resp.get("view", {}))


def check_closed_without_script(client: Client, video_id: str) -> str:
    resp = client.call(
        "VideoService", "ApproveGate", {"videoId": video_id, "gate": "GATE_C_SCRIPT"}
    )
    if resp["_status"] == 200:
        raise E2EFailure("Gate C was approved with no script at all")
    return f"refused with HTTP {resp['_status']}"


def check_script_runs(client: Client, video_id: str, timeout_seconds: int) -> str:
    return run_step_and_wait(client, video_id, "script", timeout_seconds)


def check_script_written(client: Client, run: Run, video_id: str, beats: int) -> str:
    """The script arrives with every broken rule shown, and the gate shut.

    SPEC.md 5.4 as revised at M4: the writer delivers its best attempt; a
    human finishes it at Gate C. What this proves is that nothing broken can
    slip through -- not that the model got it right alone.
    """
    view = _script_view(client, video_id)
    if not view.get("exists"):
        raise E2EFailure("the script step reported success but wrote no script")

    script = view.get("script", {})
    run.script = script
    got = len(script.get("beats", []))
    if got != beats:
        raise E2EFailure(f"{got} beats; the channel makes {beats}-beat videos")

    violations = script.get("violations", [])
    unexplained = [v for v in violations if not str(v.get("message", "")).strip()]
    if unexplained:
        raise E2EFailure(f"{len(unexplained)} violations carry no message a reviewer can act on")

    attempts = script.get("attempts", "?")
    if not violations:
        return f"{got} beats after {attempts} draft(s); every rule already met"

    if view.get("canApprove"):
        raise E2EFailure(f"{len(violations)} rules are broken, yet Gate C says it can open")
    approve = client.call(
        "VideoService", "ApproveGate", {"videoId": video_id, "gate": "GATE_C_SCRIPT"}
    )
    if approve["_status"] == 200:
        raise E2EFailure("Gate C was approved with rules still broken")
    return (
        f"{got} beats after {attempts} draft(s); {len(violations)} problems shown, "
        f"Gate C refused (HTTP {approve['_status']})"
    )


def check_reviewer_fixes(client: Client, run: Run, video_id: str) -> str:
    """Act as the reviewer: fix each broken beat through the dashboard's API.

    A person would rewrite the line; this does the simplest safe thing a
    person could -- restate the beat's own cited fact, short, digits only --
    so what it proves is the PATH: every violation can be fixed by an edit,
    each edit is re-checked, and the gate opens only once none remain.
    """
    facts = _approved_facts(client, video_id)
    refs = _selected_refs(client, video_id)

    fixed: set[int] = set()
    for _ in range(3):
        script = _script_view(client, video_id).get("script", {})
        violations = script.get("violations", [])
        if not violations:
            run.script = script
            if not fixed:
                return "nothing to fix"
            return f"fixed {len(fixed)} beat(s) by hand; every rule met"

        stuck = [
            v for v in violations if v.get("rule") in _NOT_FIXABLE_BY_EDIT or not v.get("beat")
        ]
        if stuck:
            shown = [(v.get("rule"), str(v.get("message", ""))[:60]) for v in stuck[:3]]
            raise E2EFailure(
                f"a reviewer cannot fix these with an edit and must send the script back: {shown}"
            )

        beats = script.get("beats", [])
        for n in sorted({int(v["beat"]) for v in violations}):
            payload = _reviewer_rewrite(beats, n, facts, refs)
            resp = client.call("ScriptsService", "UpdateBeat", {**payload, "videoId": video_id})
            if resp["_status"] != 200:
                raise E2EFailure(
                    f"UpdateBeat {n} returned HTTP {resp['_status']}: {resp.get('message')}"
                )
            fixed.add(n)

    left = _script_view(client, video_id).get("script", {}).get("violations", [])
    shown = [(v.get("beat"), str(v.get("message", ""))[:60]) for v in left[:3]]
    raise E2EFailure(f"after 3 rounds of fixes {len(left)} rules are still broken: {shown}")


#: Rules a reviewer cannot clear by editing a beat's words or comparisons at
#: Gate C: which facts a beat cites, and the script's shape, are the writer's.
_NOT_FIXABLE_BY_EDIT = frozenset({"FACT_NOT_CITED", "UNKNOWN_FACT", "BEAT_COUNT", "BEAT_ROLE"})

_NUMBER_WORDS = frozenset(
    [
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
        "eleven",
        "twelve",
        "thirteen",
        "fourteen",
        "fifteen",
        "sixteen",
        "seventeen",
        "eighteen",
        "nineteen",
        "twenty",
        "thirty",
        "forty",
        "fifty",
        "sixty",
        "seventy",
        "eighty",
        "ninety",
        "hundred",
        "thousand",
        "million",
        "billion",
    ]
)


def _approved_facts(client: Client, video_id: str) -> dict[str, Any]:
    resp = client.call("FactsService", "GetFacts", {"videoId": video_id})
    facts = resp.get("view", {}).get("sheet", {}).get("facts", [])
    return {f["id"]: f for f in facts if f.get("approved")}


def _selected_refs(client: Client, video_id: str) -> dict[str, Any]:
    resp = client.call("ReferencesService", "GetReferences", {"videoId": video_id})
    proposals = resp.get("view", {}).get("sheet", {}).get("proposals", [])
    return {p["id"]: p for p in proposals if p.get("selected")}


def _reviewer_rewrite(
    beats: list[dict[str, Any]], n: int, facts: dict[str, Any], refs: dict[str, Any]
) -> dict[str, Any]:
    """A short, safe line for beat n, built only from what it cites."""
    beat = next(b for b in beats if int(b.get("n", 0)) == n)
    fact_ids = beat.get("factIds", [])
    cited = [facts[i] for i in fact_ids if i in facts]

    if cited:
        words = [
            w
            for w in str(cited[0].get("claim", "")).split()
            if w.strip(".,;:").lower() not in _NUMBER_WORDS
        ]
        line = " ".join(words[:10]).rstrip(".,;:") + "."
    else:
        line = "What came next?"  # a teaser states nothing as true

    if n == int(beats[-1].get("n", 0)):
        opening = sorted(content_words(str(beats[0].get("voice", ""))))
        echo = [w for w in opening if w.isalpha()][:2]
        line = f"{' '.join(echo).capitalize()}. {line}"

    keep = [
        r for r in beat.get("refIds", []) if r in refs and refs[r].get("linkedFactId") in fact_ids
    ]
    return {
        "n": n,
        "voice": line,
        "onScreenText": beat.get("yearStamp", ""),
        "yearStamp": beat.get("yearStamp", ""),
        "refIds": keep,
    }


def check_numbers_grounded(client: Client, run: Run, video_id: str) -> str:
    """Recompute, here, what the worker claims: nothing unapproved is stated."""
    facts = client.call("FactsService", "GetFacts", {"videoId": video_id})
    approved = {
        f["id"]: f
        for f in facts.get("view", {}).get("sheet", {}).get("facts", [])
        if f.get("approved")
    }
    refs = client.call("ReferencesService", "GetReferences", {"videoId": video_id})
    selected = {
        p["id"]
        for p in refs.get("view", {}).get("sheet", {}).get("proposals", [])
        if p.get("selected")
    }

    checked = 0
    problems: list[str] = []
    used_refs: set[str] = set()
    for beat in (run.script or {}).get("beats", []):
        n = beat.get("n", "?")
        cited = beat.get("factIds", [])
        problems += [f"beat {n} cites unapproved {f}" for f in cited if f not in approved]
        problems += [
            f"beat {n} uses unselected {r}" for r in beat.get("refIds", []) if r not in selected
        ]
        used_refs.update(beat.get("refIds", []))

        pool = set(
            numbers_in(
                " ".join(
                    f"{approved[f].get('label', '')} {approved[f].get('claim', '')} "
                    f"{approved[f].get('evidence', '')}"
                    for f in cited
                    if f in approved
                )
            )
        )
        said = numbers_in(" ".join(beat.get(k, "") for k in ("voice", "onScreenText", "yearStamp")))
        checked += len(said)
        problems += [f"beat {n} says {x}, not in {cited}" for x in said if x not in pool]

    if len(used_refs) > 3:
        problems.append(f"{len(used_refs)} modern references; the limit is 3")
    if problems:
        raise E2EFailure("; ".join(problems[:5]))
    return f"{checked} numbers checked independently; every one is in a fact its beat cites"


def check_wrong_year_caught(client: Client, run: Run, video_id: str) -> str:
    """Edit a wrong number in, the way a careless human would."""
    beats = (run.script or {}).get("beats", [])
    target = next((b for b in beats if _FIRST_NUMBER.search(b.get("voice", ""))), None)
    if target is None:
        # No number to nudge: add one no fact can contain.
        target = beats[0]
        bad_voice = f"{target.get('voice', '')} In 9999."
        wrong = "9999"
    else:
        match = _FIRST_NUMBER.search(target["voice"])
        assert match is not None
        wrong = str(int(match.group(0).replace(",", "")) + 1)
        bad_voice = target["voice"][: match.start()] + wrong + target["voice"][match.end() :]

    n = int(target.get("n", 1))
    run.injected = {
        "n": n,
        "voice": target.get("voice", ""),
        "onScreenText": target.get("onScreenText", ""),
        "yearStamp": target.get("yearStamp", ""),
        # UpdateBeat takes the beat's COMPLETE comparison list; leaving it
        # out would silently strip the beat's comparisons.
        "refIds": list(target.get("refIds", [])),
    }

    resp = client.call(
        "ScriptsService",
        "UpdateBeat",
        {**run.injected, "videoId": video_id, "voice": bad_voice},
    )
    if resp["_status"] != 200:
        raise E2EFailure(f"UpdateBeat returned HTTP {resp['_status']}: {resp.get('message')}")

    view = resp.get("view", {})
    flagged = [
        v
        for v in view.get("script", {}).get("violations", [])
        if v.get("rule") == "UNGROUNDED_NUMBER" and int(v.get("beat", 0)) == n
    ]
    if not flagged:
        raise E2EFailure(f"beat {n} now says {wrong}, and the validator did not flag it")
    if view.get("canApprove"):
        raise E2EFailure("a flagged script would still let Gate C open")

    approve = client.call(
        "VideoService", "ApproveGate", {"videoId": video_id, "gate": "GATE_C_SCRIPT"}
    )
    if approve["_status"] == 200:
        raise E2EFailure(f"Gate C was approved with a wrong year in beat {n}")
    return (
        f"beat {n} edited to say {wrong}: flagged, and Gate C refused (HTTP {approve['_status']})"
    )


def check_fix_accepted(client: Client, run: Run, video_id: str) -> str:
    resp = client.call("ScriptsService", "UpdateBeat", {**run.injected, "videoId": video_id})
    if resp["_status"] != 200:
        raise E2EFailure(f"UpdateBeat returned HTTP {resp['_status']}: {resp.get('message')}")
    violations = resp.get("view", {}).get("script", {}).get("violations", [])
    if violations:
        raise E2EFailure(
            f"putting beat {run.injected['n']} back left {len(violations)} violations: "
            f"{violations[0].get('message', '')}"
        )
    return f"beat {run.injected['n']} restored; the script is valid again"


def check_title(client: Client, run: Run, video_id: str) -> str:
    options = (run.script or {}).get("titleOptions", [])
    if not options:
        raise E2EFailure("the script offers no title options")
    resp = client.call("ScriptsService", "ChooseTitle", {"videoId": video_id, "title": options[0]})
    if resp["_status"] != 200:
        raise E2EFailure(f"ChooseTitle returned HTTP {resp['_status']}: {resp.get('message')}")
    view = resp.get("view", {})
    if not view.get("canApprove"):
        raise E2EFailure(
            f"a valid script with a title still cannot open: {view.get('approvalBlocker')}"
        )
    run.script = view.get("script", run.script)
    return f"chose {options[0]!r}"


def check_opens(client: Client, video_id: str) -> str:
    resp = client.call(
        "VideoService",
        "ApproveGate",
        {"videoId": video_id, "gate": "GATE_C_SCRIPT", "note": "e2e run"},
    )
    if resp["_status"] != 200:
        raise E2EFailure(f"ApproveGate C returned HTTP {resp['_status']}: {resp.get('message')}")
    status = resp.get("video", {}).get("status")
    if status != "VIDEO_STATUS_SCRIPT_APPROVED":
        raise E2EFailure(f"video is {status} after Gate C, expected script_approved")
    return "video advanced to script_approved"
