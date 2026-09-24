"""The REWIND end-to-end harness: what every check shares.

Split out of run.py at M4, when Gate C's checks moved into their own module
(gate_c.py) and run.py had grown past 1,000 lines. Holds the pieces every
gate's checks use: the run record, the Connect client, the check runner, the
step-waiter, the closed-gate check and the dashboard renderer. The checks
themselves live beside the gate they prove.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ui import Browser, UIProblem, assert_page, find_chrome, require_dashboard

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
    script: dict[str, Any] | None = None
    #: What a check deliberately broke, so a later check can put it back.
    injected: dict[str, Any] = field(default_factory=dict)
    review_log: list[dict[str, Any]] = field(default_factory=list)
    #: (caption, path relative to the run folder), in the order they were taken.
    screenshots: list[tuple[str, str]] = field(default_factory=list)
    ui_checked: bool = False
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


# ------------------------------------------------------------- closed gates


def check_closed_gate_refuses_edits(
    client: Client, *, service: str, method: str, payload: dict[str, Any], gate: str
) -> str:
    """An approved gate's sheet must not change.

    Relevance, and later the script, are built from what the human approved.
    Before this rule the API accepted edits after approval, so the approval on
    record could describe a sheet that no longer existed.
    """
    resp = client.call(service, method, payload)
    if resp["_status"] == 200:
        raise E2EFailure(
            f"Gate {gate} is approved, but {method} still changed its sheet. Everything "
            "downstream was built from what was approved; it must not move underneath."
        )
    message = str(resp.get("message", ""))
    if "gate closed" not in message:
        raise E2EFailure(f"{method} was refused, but not because Gate {gate} is closed: {message}")
    return f"refused with HTTP {resp['_status']}: gate closed"


# --------------------------------------------------------------- the dashboard


@dataclass
class Dashboard:
    """Where to look, and what to look with."""

    browser: Browser
    web: str
    run_dir: Path


def open_dashboard(web: str, chrome: str | None) -> Browser:
    try:
        require_dashboard(web)
        return Browser(find_chrome(chrome))
    except UIProblem as exc:
        raise E2EFailure(str(exc)) from exc


def check_page(
    dash: Dashboard,
    run: Run,
    *,
    name: str,
    caption: str,
    path: str,
    must_show: tuple[str, ...],
    must_not_show: tuple[str, ...] = (),
) -> str:
    """Render one page as the reviewer would see it, and check what it says."""
    png = dash.run_dir / "ui" / f"{name}.png"
    try:
        capture = dash.browser.capture(f"{dash.web}{path}", png)
        assert_page(capture, must_show=must_show, must_not_show=must_not_show)
    except UIProblem as exc:
        raise E2EFailure(str(exc)) from exc
    finally:
        # Kept even when the check fails -- that is when the picture matters.
        if png.is_file():
            run.screenshots.append((caption, f"ui/{png.name}"))
    return f"ui/{png.name}"
