"""The health use case.

LAYER 2 (service) of SPEC.md 14.1. Depends on the Probe protocol, never on a
concrete probe -- which is why ``tests`` can inject fake probes and why adding
a real one requires no change here.
"""

from __future__ import annotations

from dataclasses import dataclass

from rewind_ai.core.logging import get_logger
from rewind_ai.health.base import Probe, ProbeResult, Status, worst_of

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class HealthReport:
    """The worker's overall health."""

    status: Status
    version: str
    dependencies: list[ProbeResult]


class HealthChecker:
    """Runs the registered probes and aggregates their results."""

    def __init__(self, version: str, probes: list[Probe]) -> None:
        self._version = version
        self._probes = probes

    def check(self, *, deep: bool) -> HealthReport:
        """Report health.

        A shallow check answers "is this process alive?" and is what the
        dashboard polls -- it must stay cheap. Only ``rewind doctor`` asks for
        the deep check, which actually probes Ollama, the GPU and ffmpeg.
        """
        if not deep:
            return HealthReport(status=Status.OK, version=self._version, dependencies=[])

        results: list[ProbeResult] = []
        for probe in self._probes:
            results.append(self._run(probe))

        return HealthReport(
            status=worst_of([r.status for r in results]),
            version=self._version,
            dependencies=results,
        )

    def _run(self, probe: Probe) -> ProbeResult:
        """Run one probe, containing any failure.

        A probe is contractually not allowed to raise, but a buggy one must
        still not take down the health check whose whole job is to report
        problems. So the contract is enforced here rather than trusted.
        """
        try:
            return probe.check()
        except Exception as exc:  # noqa: BLE001 - contract enforced, see docstring
            log.warning("probe raised", probe=probe.name, error=str(exc))
            return ProbeResult(
                name=probe.name,
                status=Status.UNKNOWN,
                detail=f"probe failed: {exc}",
            )
