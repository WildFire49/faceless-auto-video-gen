"""Probe: is an NVIDIA GPU visible, and how much VRAM does it have?

Reads nvidia-smi rather than importing torch: this probe must stay fast and
must work before the heavy ML dependencies are installed (they arrive at M5).
"""

from __future__ import annotations

import shutil
import subprocess

from rewind_ai.core.registry import register
from rewind_ai.health.base import ProbeResult, Status

#: SPEC.md 1.2 targets a GPU with "at least 8 GB VRAM". The threshold is set
#: below a nominal 8 GB on purpose: cards report slightly less than their
#: marketing figure once firmware reserves its share -- an RTX 4060 8 GB
#: reports 8188 MB -- so testing against a round 8192 would fail every card it
#: is meant to accept. Below this, the fallback path applies (Kokoro on CPU,
#: smaller LLM, remote image generation).
MIN_VRAM_MB = 7600


@register("health_probe", "gpu")
class GPUProbe:
    """Reports GPU presence and VRAM via nvidia-smi."""

    name = "gpu"

    def check(self) -> ProbeResult:
        binary = shutil.which("nvidia-smi")
        if binary is None:
            return ProbeResult(
                self.name,
                Status.DEGRADED,
                "no nvidia-smi; CPU fallback applies (Kokoro voice, remote image gen)",
            )

        try:
            out = subprocess.run(
                [binary, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return ProbeResult(self.name, Status.DEGRADED, f"could not run nvidia-smi: {exc}")

        line = out.stdout.strip().splitlines()[0] if out.stdout.strip() else ""
        if not line:
            return ProbeResult(self.name, Status.DEGRADED, "nvidia-smi reported no GPU")

        name, _, vram_raw = line.partition(",")
        try:
            vram_mb = int(vram_raw.strip())
        except ValueError:
            return ProbeResult(self.name, Status.OK, f"{name.strip()} (VRAM unknown)")

        detail = f"{name.strip()}, {vram_mb} MB VRAM"
        if vram_mb < MIN_VRAM_MB:
            return ProbeResult(
                self.name,
                Status.DEGRADED,
                f"{detail}; below the {MIN_VRAM_MB} MB target, expect CPU fallbacks",
            )
        return ProbeResult(self.name, Status.OK, detail)
