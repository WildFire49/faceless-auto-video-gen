"""The Accelerator contract.

LAYER 2 (module base) of SPEC.md 14.1 -- imports nothing from this project.

Which GPU the models run on is a swap, not an assumption: an Apple Silicon Mac
runs them on Metal ("mps"), an NVIDIA box on CUDA ("cuda"). Everything that
loads a model (voice at M5, images at M6) asks the configured accelerator for
its ``device`` instead of naming one, so changing machines is one config value.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable


class Readiness(StrEnum):
    """Whether model work can run on this accelerator.

    Three states, not a bool: a GPU below the memory target still works, it
    just forces smaller models -- that is different from having no GPU.
    """

    READY = "ready"
    LIMITED = "limited"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class HardwareReport:
    """What an accelerator found when it looked at the machine."""

    readiness: Readiness
    #: Operator-facing, shown in the dashboard: "Apple M4, 16 GB unified memory".
    detail: str


@runtime_checkable
class Accelerator(Protocol):
    """One kind of GPU that model work can run on."""

    name: str
    #: The torch device string models are loaded onto: "mps", "cuda".
    device: str

    def inspect(self) -> HardwareReport:
        """Look at this machine. Must not raise for missing hardware."""
        ...
