#!/usr/bin/env python
"""REWIND end-to-end test.

This is the primary proof that a milestone works (CLAUDE.md, testing
philosophy). It drives the REAL three-service stack over HTTP, exactly as a
human using the dashboard would, and writes a verifiable, repeatable artifact
to ``artifacts/e2e/<run-id>/``.

    task e2e                      # full run, needs Ollama
    task e2e -- --fake-ai         # orchestration only, no model needed
    task e2e -- --topic sandals   # a different topic

What it proves, in order:

    1. all three services are up and can see each other
    2. a topic can be queued through the API
    3. the research step runs, streams progress, and finishes
    4. every returned fact carries evidence that is really in its source,
       re-checked against the sources downloaded again right now
    5. Gate A refuses to open until the fact sheet meets its bar
    6. approving Gate A advances the video
    7. Gate B refuses to open before any comparison has been proposed
    8. the relevance step runs and every comparison it proposes is attached to
       a fact the reviewer actually approved
    9. no more than three modern references can be selected
   10. approving Gate B advances the video, and BOTH decisions are in the
       review log

The artifact it leaves behind contains the full request/response transcript,
the fact sheet, the reference sheet, the review log, and a readable report --
so a run can be inspected later, diffed against another run, or attached to a
bug report.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "e2e"

# Source text is full of thin spaces, en dashes and curly quotes, and a Windows
# console defaults to cp1252. Without this, printing a FAILURE raises
# UnicodeEncodeError -- losing the artifact at the exact moment it matters.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ANSI colours, skipped when output is redirected so the log file stays clean.
_TTY = sys.stdout.isatty()
GREEN = "\033[32m" if _TTY else ""
RED = "\033[31m" if _TTY else ""
DIM = "\033[2m" if _TTY else ""
BOLD = "\033[1m" if _TTY else ""
RESET = "\033[0m" if _TTY else ""


class E2EFailure(Exception):
    """A check failed. Carries what was expected, for the report."""


@dataclass
class Step:
    """One checked step of the run."""

    name: str
    ok: bool
    detail: str = ""
    seconds: float = 0.0


@dataclass
class Run:
    """The whole run, and everything worth writing down about it."""

    topic: str
    started_at: datetime
    steps: list[Step] = field(default_factory=list)
    transcript: list[dict[str, Any]] = field(default_factory=list)
    facts: dict[str, Any] | None = None
    references: dict[str, Any] | None = None
    review_log: list[dict[str, Any]] = field(default_factory=list)
    video_id: str = ""
    content_format: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(s.ok for s in self.steps)


class Client:
    """Minimal Connect/JSON client, recording every exchange.

    Deliberately not the generated TypeScript client or a Go one: this test
    should exercise the API the way any HTTP caller would, with no shared code
    that could hide a contract mistake.
    """

    def __init__(self, base_url: str, run: Run, timeout: int = 30) -> None:
        self._base = base_url.rstrip("/")
        self._run = run
        self._timeout = timeout

    def call(self, service: str, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base}/rewind.v1.{service}/{method}"
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as resp:
                raw = resp.read().decode("utf-8")
                status = resp.status
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            status = exc.code
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            self._record(method, payload, None, 0, time.monotonic() - started, str(exc))
            raise E2EFailure(f"cannot reach the API at {url}: {exc}") from exc

        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {"_raw": raw}

        self._record(method, payload, parsed, status, time.monotonic() - started, "")
        return {"_status": status, **parsed}

    def _record(
        self,
        method: str,
        request: dict[str, Any],
        response: dict[str, Any] | None,
        status: int,
        seconds: float,
        error: str,
    ) -> None:
        self._run.transcript.append(
            {
                "at": datetime.now(UTC).isoformat(),
                "method": method,
                "request": request,
                "status": status,
                "response": response,
                "seconds": round(seconds, 3),
                "error": error,
            }
        )


def check(run: Run, name: str, fn: Any) -> Any:
    """Run one checked step, recording the outcome either way."""
    print(f"{DIM}...{RESET} {name}", end="", flush=True)
    started = time.monotonic()

    try:
        result = fn()
    except E2EFailure as exc:
        elapsed = time.monotonic() - started
        run.steps.append(Step(name, ok=False, detail=str(exc), seconds=elapsed))
        print(f"\r{RED}FAIL{RESET} {name}\n     {exc}")
        raise
    # Broad on purpose: the harness must report a crash as a failed step.
    except Exception as exc:
        elapsed = time.monotonic() - started
        run.steps.append(Step(name, ok=False, detail=f"unexpected: {exc}", seconds=elapsed))
        print(f"\r{RED}FAIL{RESET} {name}\n     unexpected: {exc}")
        raise E2EFailure(str(exc)) from exc

    elapsed = time.monotonic() - started
    detail = result if isinstance(result, str) else ""
    run.steps.append(Step(name, ok=True, detail=detail, seconds=elapsed))
    print(f"\r{GREEN}PASS{RESET} {name}{DIM} ({elapsed:.1f}s){RESET}")
    if detail:
        print(f"     {DIM}{detail}{RESET}")
    return result


# ---------------------------------------------------------------- the checks


def check_services_up(client: Client) -> str:
    resp = client.call("RewindService", "GetSystemHealth", {"deep": False})
    if resp["_status"] != 200:
        raise E2EFailure(f"health check returned HTTP {resp['_status']}: {resp}")

    api = resp.get("api", {}).get("status")
    ai = resp.get("ai", {}).get("status")
    if api != "HEALTH_STATUS_OK":
        raise E2EFailure(f"the Go API reports {api}")
    if ai != "HEALTH_STATUS_OK":
        raise E2EFailure(
            f"the Python worker reports {ai}: {resp.get('ai', {}).get('detail', '')}. "
            "Start it with `task dev`."
        )
    return f"api={api.split('_')[-1]} ai={ai.split('_')[-1]}"


def check_queue_topic(client: Client, run: Run, topic: str) -> str:
    resp = client.call("VideoService", "AddVideo", {"topic": topic, "priority": 1})
    if resp["_status"] != 200:
        raise E2EFailure(f"AddVideo returned HTTP {resp['_status']}: {resp.get('message')}")

    video = resp.get("video", {})
    run.video_id = video.get("id", "")
    if not run.video_id:
        raise E2EFailure(f"AddVideo returned no id: {resp}")
    if video.get("status") != "VIDEO_STATUS_QUEUED":
        raise E2EFailure(f"new video is {video.get('status')}, expected queued")
    return f"id={run.video_id}"


def check_gate_a_closed_without_facts(client: Client, video_id: str) -> str:
    """Gate A must refuse to open before there is anything to review."""
    resp = client.call("VideoService", "ApproveGate", {"videoId": video_id, "gate": "GATE_A_FACTS"})
    if resp["_status"] == 200:
        raise E2EFailure("Gate A was approved with no fact sheet at all")
    return f"refused with HTTP {resp['_status']}"


def run_step_and_wait(client: Client, video_id: str, what: str, timeout_seconds: int) -> str:
    """Kick the next pipeline step and watch it to completion.

    Shared by research and relevance on purpose: if progress reporting breaks
    for one step it must break for both, so the bug cannot hide in whichever
    step this harness happens not to cover.
    """
    resp = client.call("VideoService", "RunStep", {"videoId": video_id})
    if resp["_status"] != 200:
        raise E2EFailure(f"RunStep returned HTTP {resp['_status']}: {resp.get('message')}")
    if not resp.get("started"):
        raise E2EFailure(f"{what} did not start: {resp.get('reason')}")

    job_id = resp["job"]["id"]
    deadline = time.monotonic() + timeout_seconds
    last_stage = ""

    while time.monotonic() < deadline:
        job_resp = client.call("VideoService", "GetJob", {"jobId": job_id})
        job = job_resp.get("job", {})
        state = job.get("state")

        stage = job.get("stage", "")
        if stage and stage != last_stage:
            percent = float(job.get("percent", 0)) * 100
            print(
                f"\r{DIM}     {stage} ({percent:.0f}%){RESET}" + " " * 20,
                end="",
                flush=True,
            )
            last_stage = stage

        if state == "JOB_STATE_SUCCEEDED":
            if not last_stage:
                raise E2EFailure(
                    f"{what} succeeded but never reported a stage — the progress "
                    "stream is dead, which the dashboard shows as a frozen bar"
                )
            return f"finished in {job.get('stage', '')}"
        if state in {"JOB_STATE_FAILED", "JOB_STATE_INTERRUPTED"}:
            raise E2EFailure(f"{what} {state}: {job.get('error')}")

        time.sleep(1.5)

    raise E2EFailure(f"{what} did not finish within {timeout_seconds}s")


def check_research_runs(client: Client, video_id: str, timeout_seconds: int) -> str:
    return run_step_and_wait(client, video_id, "research", timeout_seconds)


def check_facts_are_sourced(client: Client, run: Run, video_id: str) -> str:
    """Every fact must carry evidence, a source, and a real match score.

    This is SPEC.md 5.2's acceptance criterion, asserted against the live API
    rather than a fixture.
    """
    resp = client.call("FactsService", "GetFacts", {"videoId": video_id})
    if resp["_status"] != 200:
        raise E2EFailure(f"GetFacts returned HTTP {resp['_status']}")

    view = resp.get("view", {})
    if not view.get("exists"):
        raise E2EFailure("no fact sheet was produced")

    sheet = view.get("sheet", {})
    run.facts = sheet
    facts = sheet.get("facts", [])

    if len(facts) < 8:
        raise E2EFailure(f"only {len(facts)} facts, SPEC.md 5.2 requires at least 8")

    problems: list[str] = []
    for fact in facts:
        fid = fact.get("id", "?")
        if not fact.get("evidence", "").strip():
            problems.append(f"{fid}: no evidence")
        if not fact.get("sourceUrl", "").strip():
            problems.append(f"{fid}: no source URL")
        if not fact.get("group", "").strip():
            problems.append(f"{fid}: no group, so it cannot count towards variety")
        if fact.get("approved"):
            problems.append(f"{fid}: arrived pre-approved, which a human must do")
        score = float(fact.get("matchScore", 0))
        if score < 0.9:
            problems.append(f"{fid}: match score {score:.2f} is below the threshold")

    if problems:
        raise E2EFailure("; ".join(problems[:5]))

    extracted = int(sheet.get("candidatesExtracted", 0))
    rejected = int(sheet.get("candidatesRejected", 0))

    # These counts were computed by the worker and then discarded for a while,
    # so Gate A showed 0/0. Assert they survive the round trip.
    if extracted == 0:
        raise E2EFailure(
            "the fact sheet reports 0 candidates extracted; the model-quality "
            "counts are being lost between the worker and Gate A"
        )

    run.content_format = str(sheet.get("format", ""))
    run.notes.append(
        f"Format: {run.content_format}. The model proposed {extracted} items; "
        f"{rejected} were rejected ({rejected / extracted * 100:.0f}%)."
    )
    return (
        f"{len(facts)} facts, all sourced and grouped; {rejected}/{extracted} candidates rejected"
    )


def check_evidence_is_really_in_the_source(run: Run) -> str:
    """Re-verify every fact against FRESHLY downloaded sources.

    What makes this independent is re-fetching the source text, not inventing a
    second standard. An earlier version demanded exact substring containment
    while the product uses fuzzy-prose-plus-exact-numbers, so it flagged
    legitimate near-verbatim quotes (0.99 matches) as failures. A check
    stricter than the thing it checks reports noise, not bugs.

    The score distribution is reported either way, because "how many are
    quoted verbatim rather than merely close" is worth knowing about a model.
    """
    sys.path.insert(0, str(REPO_ROOT / "ai"))
    from rewind_ai.research.verifier import verify_evidence

    facts = (run.facts or {}).get("facts", [])
    sources = _fetch_sources(run)
    if not sources:
        raise E2EFailure("could not re-download any source to check against")

    unverified: list[str] = []
    exact = 0
    close = 0

    for fact in facts:
        result = verify_evidence(fact.get("evidence", ""), sources, threshold=0.90)
        if not result.verified:
            unverified.append(f"{fact.get('id')} ({fact.get('label')}): {result.reason}")
        elif result.score >= 0.999:
            exact += 1
        else:
            close += 1

    if unverified:
        raise E2EFailure(
            f"{len(unverified)} of {len(facts)} facts do not appear in the freshly "
            "downloaded sources: " + "; ".join(unverified[:3])
        )

    run.notes.append(
        f"Re-verified against freshly downloaded sources: {exact} quoted verbatim, "
        f"{close} near-verbatim (>= 0.90 with every number confirmed)."
    )
    return f"all {len(facts)} facts re-verified ({exact} verbatim, {close} near-verbatim)"


def _fetch_sources(run: Run) -> dict[str, str]:
    """Re-download the sources the fact sheet cites."""
    sources: dict[str, str] = {}
    for source in (run.facts or {}).get("sources", []):
        url = source.get("url", "")
        if "wikipedia.org/wiki/" not in url:
            continue
        title = url.rsplit("/wiki/", 1)[-1]
        api = (
            "https://en.wikipedia.org/w/api.php?action=query&prop=extracts"
            f"&titles={title}&explaintext=1&format=json"
        )
        request = urllib.request.Request(api, headers={"User-Agent": "REWIND-e2e/0.1"})
        try:
            with urllib.request.urlopen(request, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            continue
        for page in data.get("query", {}).get("pages", {}).values():
            if page.get("extract"):
                sources[url] = page["extract"]
    return sources


def check_gate_a_blocked_until_approved(client: Client, video_id: str) -> str:
    """Facts exist, but none are ticked, so Gate A must still refuse."""
    resp = client.call("VideoService", "ApproveGate", {"videoId": video_id, "gate": "GATE_A_FACTS"})
    if resp["_status"] == 200:
        raise E2EFailure("Gate A opened with zero facts approved")
    return f"refused: {resp.get('message', '')[:90]}"


def check_approve_facts(client: Client, video_id: str) -> str:
    resp = client.call("FactsService", "ApproveAllFacts", {"videoId": video_id, "approved": True})
    if resp["_status"] != 200:
        raise E2EFailure(f"ApproveAllFacts returned HTTP {resp['_status']}")

    view = resp.get("view", {})
    if not view.get("canApprove"):
        raise E2EFailure(f"still cannot approve: {view.get('approvalBlocker')}")
    return (
        f"{view.get('approvedCount')} facts across {view.get('groupCount')} "
        f"{view.get('groupNoun', 'group')}s"
    )


def check_gate_a_opens(client: Client, video_id: str) -> str:
    resp = client.call(
        "VideoService",
        "ApproveGate",
        {"videoId": video_id, "gate": "GATE_A_FACTS", "note": "e2e run"},
    )
    if resp["_status"] != 200:
        raise E2EFailure(f"ApproveGate returned HTTP {resp['_status']}: {resp.get('message')}")

    status = resp.get("video", {}).get("status")
    if status != "VIDEO_STATUS_FACTS_APPROVED":
        raise E2EFailure(f"video is {status} after approval, expected facts_approved")
    return "video advanced to facts_approved"


def check_review_log_records_it(client: Client, run: Run, video_id: str) -> str:
    resp = client.call("VideoService", "ListReviewLog", {"videoId": video_id})
    if resp["_status"] != 200:
        raise E2EFailure(f"ListReviewLog returned HTTP {resp['_status']}")

    entries = resp.get("entries", [])
    run.review_log = entries

    actions = [e.get("action") for e in entries]
    for required in ("create", "approve"):
        if required not in actions:
            raise E2EFailure(f"the review log has no {required!r} entry: {actions}")

    # Both gates, not just the last one. The log is the evidence that a human
    # was asked at every point the spec says they must be (SPEC.md 8.4).
    gates = {e.get("gate") for e in entries if e.get("action") == "approve"}
    for gate in ("GATE_A_FACTS", "GATE_B_REFERENCES"):
        if gate not in gates:
            raise E2EFailure(f"no approval of {gate} was logged; only {sorted(gates)}")

    # SPEC.md 8.4: the log must also exist on disk as the evidence artifact.
    on_disk = REPO_ROOT / "projects" / video_id / "review_log.json"
    if not on_disk.is_file():
        raise E2EFailure(f"{on_disk} was not written")

    return f"{len(entries)} entries, mirrored to projects/{video_id}/review_log.json"


# ------------------------------------------------------------- Gate B checks


def check_gate_b_closed_without_references(client: Client, video_id: str) -> str:
    """Gate B must refuse before the relevance step has proposed anything."""
    resp = client.call(
        "VideoService",
        "ApproveGate",
        {"videoId": video_id, "gate": "GATE_B_REFERENCES"},
    )
    if resp["_status"] == 200:
        raise E2EFailure("Gate B was approved with no reference sheet at all")
    return f"refused with HTTP {resp['_status']}"


def check_relevance_runs(client: Client, video_id: str, timeout_seconds: int) -> str:
    return run_step_and_wait(client, video_id, "relevance", timeout_seconds)


def check_proposals_are_safe(client: Client, run: Run, video_id: str) -> str:
    """The claim Gate B exists to protect (SPEC.md 5.3).

    Every proposal must attach to a fact the reviewer APPROVED, must carry a
    reference and a line, and must not repeat a reference — three modern brands
    is the ceiling, and two of them being the same brand defeats the point.
    """
    resp = client.call("ReferencesService", "GetReferences", {"videoId": video_id})
    if resp["_status"] != 200:
        raise E2EFailure(f"GetReferences returned HTTP {resp['_status']}")

    view = resp.get("view", {})
    if not view.get("exists"):
        raise E2EFailure("the relevance step reported success but wrote no reference sheet")

    sheet = view.get("sheet", {})
    run.references = sheet
    proposals = sheet.get("proposals", [])
    if not proposals:
        raise E2EFailure(
            "0 comparisons survived the safety filter. Either the model refused "
            "everything or the reference bank has nothing for this topic — check "
            f"config/references.yaml and the recorded rejections: {sheet.get('rejections')}"
        )

    facts_resp = client.call("FactsService", "GetFacts", {"videoId": video_id})
    approved_ids = {
        f["id"]
        for f in facts_resp.get("view", {}).get("sheet", {}).get("facts", [])
        if f.get("approved")
    }

    seen: set[str] = set()
    for proposal in proposals:
        pid = proposal.get("id", "?")
        if not proposal.get("reference"):
            raise E2EFailure(f"{pid} has no reference")
        if not proposal.get("comparison"):
            raise E2EFailure(f"{pid} has no comparison line")

        linked = proposal.get("linkedFactId")
        if linked not in approved_ids:
            raise E2EFailure(
                f"{pid} is attached to {linked!r}, which is not an approved fact. "
                "A comparison with nothing to be funny about has escaped the filter."
            )

        key = proposal["reference"].strip().lower()
        if key in seen:
            raise E2EFailure(f"{proposal['reference']!r} was proposed twice")
        seen.add(key)

        if proposal.get("kind") == "REFERENCE_KIND_HOT" and not proposal.get("freshUntil"):
            raise E2EFailure(f"{pid} is a hot reference with no expiry date")

    generated = int(sheet.get("candidatesGenerated", 0))
    rejected = int(sheet.get("candidatesRejected", 0))
    if generated == 0:
        raise E2EFailure(
            "candidatesGenerated is 0, so the sheet cannot say what the filter threw "
            "out — Gate B would show an empty provenance panel"
        )

    return (
        f"{len(proposals)} comparisons from {generated} candidates "
        f"({rejected} rejected), all attached to approved facts"
    )


def check_max_three_enforced(client: Client, run: Run, video_id: str) -> str:
    """The product rule with teeth: no more than max_selectable references.

    Ticked one at a time through the real API, because the cap has to hold
    against the dashboard's own call, not only inside a batch validator.
    """
    sheet = run.references or {}
    proposals = sheet.get("proposals", [])
    limit = int(sheet.get("maxSelectable", 0))
    if limit <= 0:
        raise E2EFailure(f"the sheet reports maxSelectable={limit}, which would mean no limit")

    # The cap can only be PROVEN by being hit, and how many comparisons the
    # model writes varies run to run. If it wrote too few, add hand-written
    # ones through the same API a human would -- otherwise this check passes
    # every time without ever testing anything.
    while len(proposals) <= limit:
        spare = len(proposals) + 1
        resp = client.call(
            "ReferencesService",
            "AddProposal",
            {
                "videoId": video_id,
                "reference": f"e2e filler {spare}",
                "comparison": f"It was the e2e filler {spare} of its day.",
                "whyFunny": "written by the harness to make the cap reachable",
                "linkedFactId": proposals[0]["linkedFactId"] if proposals else "f1",
            },
        )
        if resp["_status"] != 200:
            raise E2EFailure(
                f"could not add a filler comparison to reach the cap: {resp.get('message')}"
            )
        proposals = resp.get("view", {}).get("sheet", {}).get("proposals", [])

    selected = 0
    for proposal in proposals:
        resp = client.call(
            "ReferencesService",
            "SelectProposal",
            {"videoId": video_id, "proposalId": proposal["id"], "selected": True},
        )

        if selected >= limit:
            if resp["_status"] == 200:
                raise E2EFailure(
                    f"a {limit + 1}th comparison was accepted. The cap on modern "
                    "references is not being enforced."
                )
            return f"{limit} selected, the {limit + 1}th refused with HTTP {resp['_status']}"

        if resp["_status"] != 200:
            raise E2EFailure(
                f"selecting comparison {selected + 1} of {limit} was refused: {resp.get('message')}"
            )
        selected += 1
        reported = int(resp.get("view", {}).get("selectedCount", -1))
        if reported != selected:
            raise E2EFailure(f"selected {selected} but the view reports {reported}")

    raise E2EFailure(
        f"unreachable: {len(proposals)} proposals and a limit of {limit}, "
        f"but only {selected} were selected and none were refused"
    )


def check_gate_b_opens(client: Client, run: Run, video_id: str) -> str:
    resp = client.call(
        "VideoService",
        "ApproveGate",
        {"videoId": video_id, "gate": "GATE_B_REFERENCES", "note": "e2e run"},
    )
    if resp["_status"] != 200:
        raise E2EFailure(f"ApproveGate B returned HTTP {resp['_status']}: {resp.get('message')}")

    status = resp.get("video", {}).get("status")
    if status != "VIDEO_STATUS_REFS_APPROVED":
        raise E2EFailure(f"video is {status} after Gate B, expected refs_approved")

    # Re-read the sheet as APPROVED, so the artifact records which comparisons
    # were actually chosen. The copy taken earlier predates every selection,
    # and an artifact that reports "0 selected" for a run that selected three
    # is worse than no artifact -- it is a confident, wrong record.
    final = client.call("ReferencesService", "GetReferences", {"videoId": video_id})
    sheet = final.get("view", {}).get("sheet")
    if sheet:
        run.references = sheet

    selected = sum(1 for p in (sheet or {}).get("proposals", []) if p.get("selected"))
    return f"video advanced to refs_approved with {selected} comparisons"


# --------------------------------------------------------------- the artifact


def write_artifact(run: Run, run_dir: Path) -> None:
    """Write everything worth keeping about this run."""
    run_dir.mkdir(parents=True, exist_ok=True)

    (run_dir / "transcript.json").write_text(json.dumps(run.transcript, indent=2), encoding="utf-8")
    if run.facts:
        (run_dir / "facts.json").write_text(json.dumps(run.facts, indent=2), encoding="utf-8")
    if run.references:
        (run_dir / "references.json").write_text(
            json.dumps(run.references, indent=2), encoding="utf-8"
        )
    if run.review_log:
        (run_dir / "review_log.json").write_text(
            json.dumps(run.review_log, indent=2), encoding="utf-8"
        )

    # The project folder as the pipeline actually left it.
    if run.video_id:
        project = REPO_ROOT / "projects" / run.video_id
        if project.is_dir():
            shutil.copytree(project, run_dir / "project", dirs_exist_ok=True)

    (run_dir / "report.md").write_text(_report(run), encoding="utf-8")

    summary = {
        "topic": run.topic,
        "format": run.content_format,
        "video_id": run.video_id,
        "started_at": run.started_at.isoformat(),
        "passed": run.passed,
        "steps": [
            {
                "name": s.name,
                "ok": s.ok,
                "detail": s.detail,
                "seconds": round(s.seconds, 2),
            }
            for s in run.steps
        ],
        "fact_count": len((run.facts or {}).get("facts", [])),
        "candidates_extracted": (run.facts or {}).get("candidatesExtracted", 0),
        "candidates_rejected": (run.facts or {}).get("candidatesRejected", 0),
        "reference_count": len((run.references or {}).get("proposals", [])),
        "references_selected": sum(
            1 for p in (run.references or {}).get("proposals", []) if p.get("selected")
        ),
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def _report(run: Run) -> str:
    """A readable report, for a human or a bug attachment."""
    verdict = "PASSED" if run.passed else "FAILED"
    facts = (run.facts or {}).get("facts", [])
    extracted = (run.facts or {}).get("candidatesExtracted", 0)
    rejected = (run.facts or {}).get("candidatesRejected", 0)

    lines = [
        f"# REWIND end-to-end run — {verdict}",
        "",
        f"- **Topic:** {run.topic}",
        f"- **Format:** {run.content_format or 'unknown'}",
        f"- **Video id:** `{run.video_id}`",
        f"- **Started:** {run.started_at.isoformat()}",
        f"- **Duration:** {sum(s.seconds for s in run.steps):.1f}s",
        "",
        "## Steps",
        "",
        "| | Step | Time | Detail |",
        "|---|---|---|---|",
    ]
    for step in run.steps:
        mark = "PASS" if step.ok else "FAIL"
        lines.append(f"| {mark} | {step.name} | {step.seconds:.1f}s | {step.detail} |")

    if extracted:
        lines += [
            "",
            "## What the verifier caught",
            "",
            f"The model proposed **{extracted}** facts. **{rejected}** were rejected "
            "because their evidence could not be found in the source text.",
            "",
            "A high rejection rate is a measurement of the MODEL, not of the topic: it is "
            "the one objective signal of how much a given model invents on this exact task.",
        ]

    if facts:
        lines += ["", "## Facts that survived verification", ""]
        for fact in facts:
            lines += [
                f"### {fact.get('id')} — {fact.get('label')}"
                + (f" · {fact['context']}" if fact.get("context") else ""),
                "",
                f"{fact.get('claim')}",
                "",
                f"> {fact.get('evidence')}",
                "",
                f"Source: [{fact.get('sourceTitle') or fact.get('sourceUrl')}]"
                f"({fact.get('sourceUrl')}) · match {float(fact.get('matchScore', 0)):.3f}"
                f" · {fact.get('confidence')}",
                "",
            ]

    proposals = (run.references or {}).get("proposals", [])
    if proposals:
        sheet = run.references or {}
        chosen = [p for p in proposals if p.get("selected")]
        lines += [
            "",
            "## Modern comparisons (Gate B)",
            "",
            f"**{len(chosen)} of {sheet.get('maxSelectable', '?')}** chosen from "
            f"{len(proposals)} proposals; {sheet.get('candidatesRejected', 0)} candidates "
            "were rejected for asserting something about a brand, reaching for a forbidden "
            "subject, or repeating a reference.",
            "",
            "| | Reference | Kind | Line | Fact |",
            "|---|---|---|---|---|",
        ]
        for proposal in proposals:
            mark = "USED" if proposal.get("selected") else ""
            kind = str(proposal.get("kind", "")).replace("REFERENCE_KIND_", "").lower()
            line = str(proposal.get("comparison", "")).replace("|", r"\|")
            lines.append(
                f"| {mark} | {proposal.get('reference')} | {kind} | {line} | "
                f"{proposal.get('linkedFactId')} |"
            )

        rejections = sheet.get("rejections", [])
        if rejections:
            lines += ["", "Rejected, with the reason recorded:", ""]
            lines += [f"- {reason}" for reason in rejections]

    if run.notes:
        lines += ["## Notes", ""] + [f"- {note}" for note in run.notes]

    lines += [
        "",
        "## Reproduce",
        "",
        "```bash",
        "task dev            # in one terminal",
        f"task e2e -- --topic {run.topic!r}",
        "```",
        "",
        "Artifacts: `transcript.json` (every request and response), `facts.json`, "
        "`references.json`, `review_log.json`, `project/` (the pipeline's own output), "
        "`summary.json`.",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="e2e", description=__doc__)
    parser.add_argument("--topic", default="iron", help="topic to research")
    parser.add_argument("--api", default="http://127.0.0.1:8080", help="Go API base URL")
    parser.add_argument(
        "--research-timeout",
        type=int,
        default=600,
        help="seconds to allow for research",
    )
    parser.add_argument(
        "--relevance-timeout",
        type=int,
        default=300,
        help="seconds to allow for relevance",
    )
    parser.add_argument(
        "--skip-reverify",
        action="store_true",
        help="skip re-downloading sources to double-check evidence (needs network)",
    )
    args = parser.parse_args(argv)

    run = Run(topic=args.topic, started_at=datetime.now(UTC))
    client = Client(args.api, run)

    run_id = run.started_at.strftime("%Y%m%d-%H%M%S") + f"-{args.topic.replace(' ', '-')}"
    run_dir = ARTIFACT_ROOT / run_id

    print(f"{BOLD}REWIND end-to-end{RESET}  topic={args.topic}  api={args.api}\n")

    try:
        check(run, "all three services are up", lambda: check_services_up(client))
        check(
            run,
            "a topic can be queued",
            lambda: check_queue_topic(client, run, args.topic),
        )
        check(
            run,
            "Gate A refuses to open with no fact sheet",
            lambda: check_gate_a_closed_without_facts(client, run.video_id),
        )
        check(
            run,
            "research runs and reports progress",
            lambda: check_research_runs(client, run.video_id, args.research_timeout),
        )
        check(
            run,
            "every fact is sourced and scored",
            lambda: check_facts_are_sourced(client, run, run.video_id),
        )
        if not args.skip_reverify:
            check(
                run,
                "evidence re-verified against the live sources",
                lambda: check_evidence_is_really_in_the_source(run),
            )
        check(
            run,
            "Gate A stays shut until facts are approved",
            lambda: check_gate_a_blocked_until_approved(client, run.video_id),
        )
        check(
            run,
            "facts can be approved",
            lambda: check_approve_facts(client, run.video_id),
        )
        check(run, "Gate A opens", lambda: check_gate_a_opens(client, run.video_id))

        check(
            run,
            "Gate B refuses to open with no comparisons",
            lambda: check_gate_b_closed_without_references(client, run.video_id),
        )
        check(
            run,
            "relevance runs and reports progress",
            lambda: check_relevance_runs(client, run.video_id, args.relevance_timeout),
        )
        check(
            run,
            "every comparison is safe and attached to an approved fact",
            lambda: check_proposals_are_safe(client, run, run.video_id),
        )
        check(
            run,
            "no more than three references can be selected",
            lambda: check_max_three_enforced(client, run, run.video_id),
        )
        check(run, "Gate B opens", lambda: check_gate_b_opens(client, run, run.video_id))

        check(
            run,
            "both gate decisions are in the review log",
            lambda: check_review_log_records_it(client, run, run.video_id),
        )
    except E2EFailure:
        pass  # recorded in run.steps; the artifact is still written
    except Exception as exc:
        # Anything unexpected is the harness's own bug. Record it as a failed
        # step so it appears in the report rather than vanishing up the stack.
        run.steps.append(Step("the harness itself", ok=False, detail=f"crashed: {exc!r}"))
    finally:
        # ALWAYS. An E2E test that loses its artifact when something breaks is
        # worse than useless -- that is the exact moment the artifact matters.
        write_artifact(run, run_dir)

    print()
    if run.passed:
        print(f"{GREEN}{BOLD}E2E PASSED{RESET} — {len(run.steps)} checks")
    else:
        failed = [s.name for s in run.steps if not s.ok]
        print(f"{RED}{BOLD}E2E FAILED{RESET} — {', '.join(failed)}")
    print(f"Artifact: {run_dir.relative_to(REPO_ROOT)}/report.md")

    return 0 if run.passed else 1


if __name__ == "__main__":
    sys.exit(main())
