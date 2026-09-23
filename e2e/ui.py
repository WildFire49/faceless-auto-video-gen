"""Render dashboard pages the way a reviewer sees them, for the E2E artifact.

Until now the E2E drove the API only. Three milestones of UI bugs got through
that way: an approve bar that was white text on pale grey, failed videos
showing all six gates approved, approved gates still offering edit controls.
Every one was obvious the moment a person looked, and invisible to a test
that never did.

So the harness now looks. Each gate is rendered in headless Chrome -- the
browser already on this machine, so no new dependency -- and two things are
kept: a screenshot for the artifact, so a human reviewing a run sees what the
reviewer saw, and the rendered DOM, so the check can assert on it.

The ways a page check can go wrong, written before the code:

 1. the dashboard is not running            -> fail, saying to start it
 2. Chrome cannot be found                  -> fail, saying how to point at it
 3. the page renders Next.js's error screen -> fail with the error's heading
 4. data never arrives before the budget    -> the expected text is missing:
                                               fail NAMING that text
 5. a closed gate still offers its controls -> the forbidden text is present:
                                               fail naming it
 6. Chrome exits without a screenshot       -> fail; an artifact with a missing
                                               image claims a look that never
                                               happened

A DOM assertion cannot see contrast or layout -- the unreadable approve bar
would have passed one. That is what the screenshots are for: they put the page
in front of whoever reads the artifact.
"""

from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

#: Where Chrome usually lives, in the order they are tried.
_CHROME_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)
_CHROME_ON_PATH = ("google-chrome", "google-chrome-stable", "chromium", "chrome")

#: Text that only appears when Next.js failed to render the page.
_ERROR_MARKERS = (
    "Application error",
    "Unhandled Runtime Error",
    "This page could not be found",
    "Internal Server Error",
)


_COMMENT = re.compile(r"<!--.*?-->", re.S)
_SCRIPT = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


def visible_text(dom: str) -> str:
    """The page's text as a reader sees it.

    Asserting on raw HTML is fragile in a specific way: React separates
    adjacent pieces of text with <!-- --> markers and wraps emphasis in tags,
    so "40 facts" can be `<strong>40</strong><!-- --> facts` in the DOM. The
    check would then fail on a page that reads perfectly.
    """
    text = _SCRIPT.sub(" ", dom)
    text = _COMMENT.sub("", text)
    text = _TAG.sub(" ", text)
    return _SPACE.sub(" ", html.unescape(text)).strip()


class UIProblem(Exception):
    """A page did not render the way a reviewer needs it to."""


@dataclass(frozen=True, slots=True)
class Capture:
    """One page as rendered."""

    url: str
    screenshot: Path
    #: What the page says, tags and markup removed.
    text: str


def find_chrome(explicit: str | None) -> Path:
    """The Chrome to drive: the one asked for, else the first found."""
    if explicit:
        path = Path(explicit)
        if path.is_file():
            return path
        raise UIProblem(f"--chrome {explicit} does not exist")

    for candidate in _CHROME_CANDIDATES:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    for name in _CHROME_ON_PATH:
        found = shutil.which(name)
        if found:
            return Path(found)

    raise UIProblem(
        "Chrome not found. Install it, pass --chrome <path>, or run with --skip-ui "
        "(the artifact will then say the UI was not checked)."
    )


class Browser:
    """Headless Chrome, one throwaway profile per run."""

    def __init__(
        self,
        chrome: Path,
        *,
        width: int = 1440,
        height: int = 2400,
        budget_ms: int = 15_000,
    ) -> None:
        self._chrome = chrome
        self._size = f"{width},{height}"
        # Virtual time lets the page's own data fetches and timers settle
        # before capture, without the harness guessing a sleep.
        self._budget = str(budget_ms)
        self._profile = Path(tempfile.mkdtemp(prefix="rewind-e2e-chrome-"))

    def close(self) -> None:
        shutil.rmtree(self._profile, ignore_errors=True)

    def capture(self, url: str, screenshot: Path) -> Capture:
        screenshot.parent.mkdir(parents=True, exist_ok=True)
        if screenshot.exists():
            screenshot.unlink()

        dom = self._run("--dump-dom", url).stdout
        self._run(f"--screenshot={screenshot.resolve()}", url)

        if not screenshot.is_file() or screenshot.stat().st_size == 0:
            raise UIProblem(f"Chrome rendered {url} but wrote no screenshot")
        return Capture(url=url, screenshot=screenshot, text=visible_text(dom))

    def _run(self, mode: str, url: str) -> subprocess.CompletedProcess[str]:
        args = [
            str(self._chrome),
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={self._profile}",
            f"--window-size={self._size}",
            f"--virtual-time-budget={self._budget}",
            mode,
            url,
        ]
        try:
            return subprocess.run(
                args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=90,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise UIProblem(f"Chrome did not finish rendering {url} within 90s") from exc


def require_dashboard(base_url: str) -> None:
    """Fail early and clearly if the dashboard is not serving."""
    try:
        with urllib.request.urlopen(base_url, timeout=30) as resp:
            if resp.status >= 500:
                raise UIProblem(f"the dashboard at {base_url} answered HTTP {resp.status}")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UIProblem(
            f"the dashboard is not running at {base_url} ({exc}). Start it with "
            "`task dev`, or pass --skip-ui."
        ) from exc


def assert_page(
    capture: Capture,
    *,
    must_show: tuple[str, ...],
    must_not_show: tuple[str, ...] = (),
) -> None:
    """Fail unless the rendered page says what a reviewer needs it to."""
    for marker in _ERROR_MARKERS:
        if marker in capture.text:
            raise UIProblem(f"{capture.url} rendered an error page: {marker!r}")

    missing = [text for text in must_show if text not in capture.text]
    if missing:
        raise UIProblem(
            f"{capture.url} does not show {missing}. Either its data never arrived "
            f"or the page changed -- see {capture.screenshot.name}"
        )

    present = [text for text in must_not_show if text in capture.text]
    if present:
        raise UIProblem(
            f"{capture.url} shows {present}, which it must not -- see {capture.screenshot.name}"
        )
