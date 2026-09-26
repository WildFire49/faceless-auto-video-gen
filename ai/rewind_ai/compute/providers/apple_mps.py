"""Apple Silicon GPU via Metal Performance Shaders (torch device "mps").

Reads the hardware with sysctl rather than importing torch: this must stay
fast and work before the heavy ML dependencies arrive at M5.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass

from rewind_ai.compute.base import HardwareReport, Readiness
from rewind_ai.core.registry import register

#: A Mac has no separate VRAM: the GPU, the LLM and FLUX all draw on one
#: unified pool. 16 GB is the smallest that fits the 4.7 GB LLM alongside
#: image generation; below it, expect smaller models. Unified memory is
#: reported exactly (unlike VRAM), so a 16 GB machine reports 16384.
MIN_UNIFIED_MEMORY_MB = 16 * 1024


@dataclass(frozen=True, slots=True)
class MacFacts:
    """What the machine says about itself. Plain data, so tests need no Mac."""

    system: str
    #: The HARDWARE is arm64 -- true even when this process runs under Rosetta.
    apple_silicon: bool
    #: This process is x86_64 code translated by Rosetta.
    translated: bool
    chip: str
    memory_mb: int | None


@register("accelerator", "apple_mps")
class AppleMPS:
    """Runs model work on an Apple Silicon GPU."""

    name = "apple_mps"
    device = "mps"

    def inspect(self) -> HardwareReport:
        return assess_mac(_read_facts())


def assess_mac(facts: MacFacts) -> HardwareReport:
    """Decide whether model work can run on this Mac's GPU."""
    if facts.system != "Darwin":
        return HardwareReport(
            Readiness.UNAVAILABLE,
            f"not a Mac ({facts.system}); set compute.accelerator to nvidia_cuda",
        )
    if not facts.apple_silicon:
        return HardwareReport(
            Readiness.UNAVAILABLE, f"{facts.chip or 'Intel Mac'}: MPS needs Apple Silicon"
        )
    if facts.translated:
        # The x86_64 torch wheel a Rosetta Python installs has no MPS backend.
        return HardwareReport(
            Readiness.UNAVAILABLE,
            f"{facts.chip}, but Python runs under Rosetta; use an arm64 Python",
        )
    if facts.memory_mb is None:
        return HardwareReport(Readiness.LIMITED, f"{facts.chip}, unified memory unknown")

    detail = f"{facts.chip}, {facts.memory_mb // 1024} GB unified memory, Metal (mps)"
    if facts.memory_mb < MIN_UNIFIED_MEMORY_MB:
        return HardwareReport(
            Readiness.LIMITED,
            f"{detail}; below the {MIN_UNIFIED_MEMORY_MB // 1024} GB target, expect smaller models",
        )
    return HardwareReport(Readiness.READY, detail)


def _read_facts() -> MacFacts:
    memory = _sysctl("hw.memsize")
    return MacFacts(
        system=platform.system(),
        apple_silicon=_sysctl("hw.optional.arm64") == "1",
        translated=_sysctl("sysctl.proc_translated") == "1",
        chip=_sysctl("machdep.cpu.brand_string") or "",
        memory_mb=int(memory) // (1024 * 1024) if memory and memory.isdigit() else None,
    )


def _sysctl(key: str) -> str | None:
    """One sysctl value, or None when the key or the binary is missing."""
    binary = shutil.which("sysctl") or "/usr/sbin/sysctl"
    try:
        out = subprocess.run(
            [binary, "-n", key], capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = out.stdout.strip()
    return value if out.returncode == 0 and value else None
