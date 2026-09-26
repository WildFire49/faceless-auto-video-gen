"""NVIDIA GPU via CUDA (torch device "cuda").

Reads nvidia-smi rather than importing torch: this must stay fast and work
before the heavy ML dependencies arrive at M5.
"""

from __future__ import annotations

import shutil
import subprocess

from rewind_ai.compute.base import HardwareReport, Readiness
from rewind_ai.core.registry import register

#: SPEC.md 1.2 targets a GPU with "at least 8 GB VRAM". The threshold is set
#: below a nominal 8 GB on purpose: cards report slightly less than their
#: marketing figure once firmware reserves its share -- an RTX 4060 8 GB
#: reports 8188 MB -- so testing against a round 8192 would fail every card it
#: is meant to accept. Below this, the fallback path applies (Kokoro on CPU,
#: smaller LLM, remote image generation).
MIN_VRAM_MB = 7600


@register("accelerator", "nvidia_cuda")
class NvidiaCUDA:
    """Runs model work on an NVIDIA GPU."""

    name = "nvidia_cuda"
    device = "cuda"

    def inspect(self) -> HardwareReport:
        binary = shutil.which("nvidia-smi")
        if binary is None:
            return HardwareReport(
                Readiness.UNAVAILABLE,
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
            return HardwareReport(Readiness.UNAVAILABLE, f"could not run nvidia-smi: {exc}")
        return assess_nvidia_smi(out.stdout)


def assess_nvidia_smi(output: str) -> HardwareReport:
    """Decide from nvidia-smi's CSV output whether model work can run here."""
    line = output.strip().splitlines()[0] if output.strip() else ""
    if not line:
        return HardwareReport(Readiness.UNAVAILABLE, "nvidia-smi reported no GPU")

    name, _, vram_raw = line.partition(",")
    try:
        vram_mb = int(vram_raw.strip())
    except ValueError:
        return HardwareReport(Readiness.READY, f"{name.strip()} (VRAM unknown)")

    detail = f"{name.strip()}, {vram_mb} MB VRAM"
    if vram_mb < MIN_VRAM_MB:
        return HardwareReport(
            Readiness.LIMITED,
            f"{detail}; below the {MIN_VRAM_MB} MB target, expect CPU fallbacks",
        )
    return HardwareReport(Readiness.READY, detail)
