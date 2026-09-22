"""Probe: is ffmpeg on PATH? Needed from M5 (voice) onward."""

from __future__ import annotations

import shutil
import subprocess

from rewind_ai.core.registry import register
from rewind_ai.health.base import ProbeResult, Status


@register("health_probe", "ffmpeg")
class FFmpegProbe:
    """Checks for an ffmpeg binary and reports its version."""

    name = "ffmpeg"

    def check(self) -> ProbeResult:
        binary = shutil.which("ffmpeg")
        if binary is None:
            # DEGRADED, not DOWN: nothing before M5 needs ffmpeg, so this must
            # not stop the studio from running today.
            return ProbeResult(self.name, Status.DEGRADED, "not on PATH; required from M5")

        try:
            out = subprocess.run(
                [binary, "-version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return ProbeResult(self.name, Status.DEGRADED, f"could not run: {exc}")

        first_line = out.stdout.splitlines()[0] if out.stdout else "unknown version"
        return ProbeResult(self.name, Status.OK, first_line)
