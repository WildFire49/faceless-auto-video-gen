"""The Probe contract.

LAYER 2 (module base) of SPEC.md 14.1 -- this file imports nothing from the
project except ``core``, and knows nothing about gRPC.

Health probes are the first worked example of the plug-and-play contract
(SPEC.md 14.2) in this codebase. Adding a probe for a new dependency is one
new file under ``probes/`` with one ``@register`` line. ``HealthChecker``,
the handler, the Go orchestrator and the dashboard are untouched.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable


class Status(StrEnum):
    """How healthy something is.

    A closed set rather than a bool, because "running but missing the model
    you will need at M5" is genuinely different from both OK and DOWN. Mirrors
    domain.Status in the Go service and HealthStatus in the proto.
    """

    UNKNOWN = "unknown"
    OK = "ok"
    DEGRADED = "degraded"
    DOWN = "down"


#: Best to worst. UNKNOWN ranks worse than DEGRADED on purpose: never report
#: health you do not actually have.
_SEVERITY: dict[Status, int] = {
    Status.OK: 0,
    Status.DEGRADED: 1,
    Status.UNKNOWN: 2,
    Status.DOWN: 3,
}


def worst_of(statuses: list[Status]) -> Status:
    """Aggregate statuses to the least healthy one.

    Returns UNKNOWN for an empty list rather than a misleading OK.
    """
    if not statuses:
        return Status.UNKNOWN
    return max(statuses, key=lambda s: _SEVERITY.get(s, _SEVERITY[Status.UNKNOWN]))


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """The outcome of probing one dependency."""

    name: str
    status: Status
    #: Short operator-facing explanation, e.g. "model qwen2.5:14b not pulled".
    #: Shown in the dashboard, so it must never contain a secret.
    detail: str = ""


@runtime_checkable
class Probe(Protocol):
    """One checkable dependency.

    Implementations live in ``probes/`` and register themselves. Keep them
    small: a probe answers one question and never raises -- a probe that
    explodes would take down the health check that exists to report problems.
    """

    #: Stable identifier, e.g. "ollama". Appears in the dashboard.
    name: str

    def check(self) -> ProbeResult:
        """Probe the dependency. Must not raise."""
        ...
