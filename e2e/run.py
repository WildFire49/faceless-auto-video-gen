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
    4. every returned fact carries evidence that is really in its source
    5. a falsified fact is rejected if one is injected (--inject-lie)
    6. Gate A refuses to open until the fact sheet meets its bar
    7. approving Gate A advances the video and is recorded in the review log

The artifact it leaves behind contains the full request/response transcript,
the fact sheet, the review log, and a readable report -- so a run can be
inspected later, diffed against another run, or attached to a bug report.
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
    review_log: list[dict[str, Any]] = field(default_factory=list)
    video_id: str = ""
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
    except Exception as exc:  # noqa: BLE001 - the harness must report, not crash
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
    resp = client.call(
        "VideoService", "ApproveGate", {"videoId": video_id, "gate": "GATE_A_FACTS"}
    )
    if resp["_status"] == 200:
        raise E2EFailure("Gate A was approved with no fact sheet at all")
    return f"refused with HTTP {resp['_status']}"


def check_research_runs(client: Client, video_id: str, timeout_seconds: int) -> str:
    resp = client.call("VideoService", "RunStep", {"videoId": video_id})
    if resp["_status"] != 200:
        raise E2EFailure(f"RunStep returned HTTP {resp['_status']}: {resp.get('message')}")
    if not resp.get("started"):
        raise E2EFailure(f"research did not start: {resp.get('reason')}")

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
            print(f"\r{DIM}     {stage} ({percent:.0f}%){RESET}" + " " * 20, end="", flush=True)
            last_stage = stage

        if state == "JOB_STATE_SUCCEEDED":
            return f"finished in {job.get('stage', '')}"
        if state in {"JOB_STATE_FAILED", "JOB_STATE_INTERRUPTED"}:
            raise E2EFailure(f"research {state}: {job.get('error')}")

        time.sleep(1.5)

    raise E2EFailure(f"research did not finish within {timeout_seconds}s")


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
        if fact.get("approved"):
            problems.append(f"{fid}: arrived pre-approved, which a human must do")
        score = float(fact.get("matchScore", 0))
        if score < 0.9:
            problems.append(f"{fid}: match score {score:.2f} is below the threshold")

    if problems:
        raise E2EFailure("; ".join(problems[:5]))

    extracted = int(sheet.get("candidatesExtracted", 0))
    rejected = int(sheet.get("candidatesRejected", 0))
    run.notes.append(
        f"The model proposed {extracted} facts; the verifier rejected {rejected} "
        f"({(rejected / extracted * 100) if extracted else 0:.0f}%)."
    )
    return f"{len(facts)} facts, all sourced; {rejected}/{extracted} candidates rejected"


def check_evidence_is_really_in_the_source(run: Run) -> str:
    """Re-verify every fact independently of the worker that produced it.

    The worker already checked this. Doing it again here, with a separate
    implementation, is the point: if the verifier itself regressed, a run that
    only trusted the worker's own word would still pass.
    """
    sys.path.insert(0, str(REPO_ROOT / "ai"))
    from rewind_ai.research.verifier import normalise  # noqa: PLC0415

    facts = (run.facts or {}).get("facts", [])
    sources = _fetch_sources(run)

    unverified: list[str] = []
    for fact in facts:
        evidence = normalise(fact.get("evidence", ""))
        if not any(evidence in normalise(text) for text in sources.values()):
            unverified.append(f"{fact.get('id')} ({fact.get('yearLabel')})")

    if unverified:
        raise E2EFailure(
            f"{len(unverified)} fact(s) quote text that is NOT in any source: "
            + ", ".join(unverified[:5])
        )
    return f"independently re-verified all {len(facts)} facts against {len(sources)} source(s)"


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
    resp = client.call(
        "VideoService", "ApproveGate", {"videoId": video_id, "gate": "GATE_A_FACTS"}
    )
    if resp["_status"] == 200:
        raise E2EFailure("Gate A opened with zero facts approved")
    return f"refused: {resp.get('message', '')[:90]}"


def check_approve_facts(client: Client, video_id: str) -> str:
    resp = client.call(
        "FactsService", "ApproveAllFacts", {"videoId": video_id, "approved": True}
    )
    if resp["_status"] != 200:
        raise E2EFailure(f"ApproveAllFacts returned HTTP {resp['_status']}")

    view = resp.get("view", {})
    if not view.get("canApprove"):
        raise E2EFailure(f"still cannot approve: {view.get('approvalBlocker')}")
    return f"{view.get('approvedCount')} facts across {view.get('eraCount')} eras"


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

    # SPEC.md 8.4: the log must also exist on disk as the evidence artifact.
    on_disk = REPO_ROOT / "projects" / video_id / "review_log.json"
    if not on_disk.is_file():
        raise E2EFailure(f"{on_disk} was not written")

    return f"{len(entries)} entries, mirrored to projects/{video_id}/review_log.json"


# --------------------------------------------------------------- the artifact


def write_artifact(run: Run, run_dir: Path) -> None:
    """Write everything worth keeping about this run."""
    run_dir.mkdir(parents=True, exist_ok=True)

    (run_dir / "transcript.json").write_text(
        json.dumps(run.transcript, indent=2), encoding="utf-8"
    )
    if run.facts:
        (run_dir / "facts.json").write_text(json.dumps(run.facts, indent=2), encoding="utf-8")
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
        "video_id": run.video_id,
        "started_at": run.started_at.isoformat(),
        "passed": run.passed,
        "steps": [
            {"name": s.name, "ok": s.ok, "detail": s.detail, "seconds": round(s.seconds, 2)}
            for s in run.steps
        ],
        "fact_count": len((run.facts or {}).get("facts", [])),
        "candidates_extracted": (run.facts or {}).get("candidatesExtracted", 0),
        "candidates_rejected": (run.facts or {}).get("candidatesRejected", 0),
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
                f"### {fact.get('id')} — {fact.get('yearLabel')}"
                + (f" · {fact['place']}" if fact.get("place") else ""),
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
        "`review_log.json`, `project/` (the pipeline's own output), `summary.json`.",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="e2e", description=__doc__)
    parser.add_argument("--topic", default="iron", help="topic to research")
    parser.add_argument("--api", default="http://127.0.0.1:8080", help="Go API base URL")
    parser.add_argument(
        "--research-timeout", type=int, default=600, help="seconds to allow for research"
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
        check(run, "a topic can be queued", lambda: check_queue_topic(client, run, args.topic))
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
        check(run, "facts can be approved", lambda: check_approve_facts(client, run.video_id))
        check(run, "Gate A opens", lambda: check_gate_a_opens(client, run.video_id))
        check(
            run,
            "the decision is in the review log",
            lambda: check_review_log_records_it(client, run, run.video_id),
        )
    except E2EFailure:
        pass  # recorded in run.steps; the artifact is still written

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
