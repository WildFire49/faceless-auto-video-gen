"""Probe: can model work run on the configured GPU?

Knows no vendor. It asks the accelerator chosen by ``compute.accelerator`` in
config (Apple Silicon or NVIDIA) to inspect the machine, so the dashboard
reports the GPU this machine actually uses.
"""

from __future__ import annotations

from rewind_ai.compute.base import Accelerator, Readiness
from rewind_ai.core.registry import register
from rewind_ai.health.base import ProbeResult, Status

_STATUS = {
    Readiness.READY: Status.OK,
    # Both still run -- on smaller models or CPU fallbacks -- so neither is DOWN.
    Readiness.LIMITED: Status.DEGRADED,
    Readiness.UNAVAILABLE: Status.DEGRADED,
}


@register("health_probe", "gpu")
class GPUProbe:
    """Reports the configured accelerator's view of this machine."""

    name = "gpu"

    def __init__(self, *, accelerator: Accelerator) -> None:
        self._accelerator = accelerator

    def check(self) -> ProbeResult:
        try:
            report = self._accelerator.inspect()
        except Exception as exc:  # noqa: BLE001 - a probe must never crash the worker
            return ProbeResult(
                self.name, Status.DEGRADED, f"{self._accelerator.name}: could not inspect: {exc}"
            )
        return ProbeResult(self.name, _STATUS[report.readiness], report.detail)
