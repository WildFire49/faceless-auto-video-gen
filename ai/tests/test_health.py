"""Tests for the health use case and the provider registry.

These run offline, with no GPU, no Ollama and no gRPC -- the point of keeping
logic out of the transport layer is that it can be tested as plain objects.
"""

from __future__ import annotations

import pytest

from rewind_ai.core import registry
from rewind_ai.health.base import Probe, ProbeResult, Status, worst_of
from rewind_ai.health.service import HealthChecker


class StubProbe:
    """A probe with a fixed answer."""

    def __init__(self, name: str, status: Status, detail: str = "") -> None:
        self.name = name
        self._result = ProbeResult(name, status, detail)
        self.calls = 0

    def check(self) -> ProbeResult:
        self.calls += 1
        return self._result


class ExplodingProbe:
    """A probe that violates its contract by raising."""

    name = "exploding"

    def check(self) -> ProbeResult:
        raise RuntimeError("nvidia-smi segfaulted")


# ------------------------------------------------------------------ worst_of


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([], Status.UNKNOWN),
        ([Status.OK, Status.OK], Status.OK),
        ([Status.OK, Status.DOWN], Status.DOWN),
        ([Status.OK, Status.DEGRADED], Status.DEGRADED),
        ([Status.DEGRADED, Status.DOWN], Status.DOWN),
        ([Status.DEGRADED, Status.UNKNOWN], Status.UNKNOWN),
    ],
)
def test_worst_of(statuses: list[Status], expected: Status) -> None:
    assert worst_of(statuses) is expected


def test_worst_of_empty_is_unknown_not_ok() -> None:
    # Reporting OK for "nothing was checked" would be a lie the dashboard
    # renders as a green chip. Called out separately because it matters.
    assert worst_of([]) is not Status.OK


# ------------------------------------------------------------ HealthChecker


def test_shallow_check_skips_probes() -> None:
    # The dashboard polls this every 1.5s; it must not shell out to
    # nvidia-smi and ffmpeg each time.
    probe = StubProbe("ollama", Status.DOWN)
    report = HealthChecker("1.0", [probe]).check(deep=False)

    assert report.status is Status.OK
    assert report.dependencies == []
    assert probe.calls == 0, "a shallow check must not run probes"


def test_deep_check_runs_every_probe() -> None:
    probes: list[Probe] = [StubProbe("ollama", Status.OK), StubProbe("gpu", Status.OK)]
    report = HealthChecker("1.0", probes).check(deep=True)

    assert report.status is Status.OK
    assert [d.name for d in report.dependencies] == ["ollama", "gpu"]


def test_deep_check_aggregates_to_the_worst_status() -> None:
    probes: list[Probe] = [
        StubProbe("ollama", Status.OK),
        StubProbe("ffmpeg", Status.DEGRADED, "not on PATH"),
    ]
    report = HealthChecker("1.0", probes).check(deep=True)

    assert report.status is Status.DEGRADED


def test_a_raising_probe_cannot_break_the_health_check() -> None:
    # A probe is contractually forbidden from raising, but a buggy one must
    # not take down the check whose job is to report problems.
    probes: list[Probe] = [StubProbe("ollama", Status.OK), ExplodingProbe()]
    report = HealthChecker("1.0", probes).check(deep=True)

    assert report.status is Status.UNKNOWN
    exploded = next(d for d in report.dependencies if d.name == "exploding")
    assert exploded.status is Status.UNKNOWN
    assert "nvidia-smi segfaulted" in exploded.detail


def test_version_is_reported() -> None:
    assert HealthChecker("9.9.9", []).check(deep=False).version == "9.9.9"


# ---------------------------------------------------------------- registry


@pytest.fixture(autouse=True)
def _clean_registry() -> object:
    """Isolate registry state between tests."""
    saved_kinds = {k: list(registry.available(k)) for k in registry.kinds()}
    yield
    del saved_kinds  # the real providers re-register on import; nothing to restore


def test_register_and_get() -> None:
    registry.clear()

    @registry.register("voice", "piper")
    class Piper:
        pass

    assert registry.get("voice", "piper") is Piper
    assert registry.available("voice") == ["piper"]


def test_unknown_provider_lists_what_is_available() -> None:
    registry.clear()

    @registry.register("voice", "chatterbox")
    class Chatterbox:
        pass

    with pytest.raises(registry.ProviderError) as excinfo:
        registry.get("voice", "kokoro")

    # A typo in a config file should tell you the options, not just that you
    # were wrong.
    assert "chatterbox" in str(excinfo.value)


def test_duplicate_registration_is_rejected() -> None:
    registry.clear()

    @registry.register("voice", "piper")
    class First:
        pass

    with pytest.raises(registry.ProviderError):

        @registry.register("voice", "piper")
        class Second:
            pass


def test_real_probes_are_discoverable() -> None:
    # Guards the plug-and-play sweep: if load_providers ever stops importing
    # the probes package, this catches it.
    from pathlib import Path

    from rewind_ai.core import container
    from rewind_ai.core.config import AISettings, PathSettings, Settings

    settings = Settings(
        ai=AISettings(grpc_addr="127.0.0.1:0"),
        paths=PathSettings(projects=Path("projects"), assets=Path("assets")),
        config_dir=Path("config"),
    )
    container.build(settings)

    assert set(registry.available("health_probe")) >= {"ffmpeg", "gpu", "ollama"}
