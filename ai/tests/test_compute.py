"""Tests for the compute accelerator swap.

The dashboard's GPU chip decides whether M5/M6 plan for the GPU or for CPU
fallbacks, so a wrong answer is expensive either way. Written as the ways it
could lie, before the providers existed:

* calls a Linux box, or an Intel Mac, an Apple GPU     -- MPS does not exist there
* calls Python-under-Rosetta ready                      -- the hardware is Apple
  Silicon, but an x86_64 interpreter gets an x86 torch with no MPS at all
* calls a machine below the memory target ready         -- FLUX and the LLM share
  one unified pool on a Mac
* calls unknown memory ready                            -- never report health
  you do not have
* crashes the worker when the hardware query fails
* silently falls back when config names an accelerator that does not exist
* leaves an accelerator without a device string models can load onto
"""

from __future__ import annotations

import pytest

from rewind_ai.compute import factory
from rewind_ai.compute.base import Accelerator, HardwareReport, Readiness
from rewind_ai.compute.providers.apple_mps import MIN_UNIFIED_MEMORY_MB, MacFacts, assess_mac
from rewind_ai.compute.providers.nvidia_cuda import assess_nvidia_smi
from rewind_ai.core import registry
from rewind_ai.health.base import Status
from rewind_ai.health.probes.gpu import GPUProbe

M4_16GB = MacFacts(
    system="Darwin",
    apple_silicon=True,
    translated=False,
    chip="Apple M4",
    memory_mb=16384,
)


def _with(**changes: object) -> MacFacts:
    fields = {
        "system": M4_16GB.system,
        "apple_silicon": M4_16GB.apple_silicon,
        "translated": M4_16GB.translated,
        "chip": M4_16GB.chip,
        "memory_mb": M4_16GB.memory_mb,
    }
    fields.update(changes)
    return MacFacts(**fields)  # type: ignore[arg-type]


# ------------------------------------------------------------ apple_mps ------


def test_an_m4_mac_is_ready_and_named() -> None:
    report = assess_mac(M4_16GB)
    assert report.readiness is Readiness.READY
    assert "Apple M4" in report.detail
    assert "16 GB" in report.detail


def test_linux_is_not_an_apple_gpu() -> None:
    report = assess_mac(_with(system="Linux", apple_silicon=False, chip=""))
    assert report.readiness is Readiness.UNAVAILABLE
    assert "nvidia_cuda" in report.detail  # tells the operator what to swap to


def test_an_intel_mac_is_not_an_apple_gpu() -> None:
    report = assess_mac(_with(apple_silicon=False, chip="Intel(R) Core(TM) i9"))
    assert report.readiness is Readiness.UNAVAILABLE


def test_python_under_rosetta_is_not_ready() -> None:
    report = assess_mac(_with(translated=True))
    assert report.readiness is Readiness.UNAVAILABLE
    assert "Rosetta" in report.detail


def test_below_the_memory_target_is_limited() -> None:
    report = assess_mac(_with(memory_mb=MIN_UNIFIED_MEMORY_MB - 1024))
    assert report.readiness is Readiness.LIMITED


def test_unknown_memory_is_not_ready() -> None:
    report = assess_mac(_with(memory_mb=None))
    assert report.readiness is Readiness.LIMITED
    assert "unknown" in report.detail


# ---------------------------------------------------------- nvidia_cuda ------


def test_no_nvidia_smi_output_is_unavailable() -> None:
    assert assess_nvidia_smi("").readiness is Readiness.UNAVAILABLE


def test_an_8gb_card_is_ready_despite_reporting_under_8192() -> None:
    # An RTX 4060 8 GB reports 8188 MB once firmware takes its share.
    report = assess_nvidia_smi("NVIDIA GeForce RTX 4060 Laptop GPU, 8188")
    assert report.readiness is Readiness.READY
    assert "8188 MB" in report.detail


def test_a_small_card_is_limited() -> None:
    assert assess_nvidia_smi("NVIDIA GeForce GTX 1050, 4096").readiness is Readiness.LIMITED


# ------------------------------------------------------------- factory -------


def test_the_configured_accelerator_is_built() -> None:
    assert factory.build("apple_mps").device == "mps"
    assert factory.build("nvidia_cuda").device == "cuda"


def test_an_unknown_accelerator_fails_loudly() -> None:
    with pytest.raises(registry.ProviderError):
        factory.build("tpu_v9")


@pytest.mark.parametrize("name", factory.available())
def test_every_accelerator_honours_the_contract(name: str) -> None:
    accelerator = factory.build(name)
    assert isinstance(accelerator, Accelerator)
    assert accelerator.device, "models need a device string to load onto"
    # Inspecting real hardware must never raise, on any machine.
    assert isinstance(accelerator.inspect(), HardwareReport)


# ------------------------------------------------------------ gpu probe ------


class _Fixed:
    name = "fixed"
    device = "mps"

    def __init__(self, readiness: Readiness) -> None:
        self._readiness = readiness

    def inspect(self) -> HardwareReport:
        return HardwareReport(self._readiness, "fixed hardware")


class _Broken:
    name = "broken"
    device = "mps"

    def inspect(self) -> HardwareReport:
        raise OSError("sysctl vanished")


@pytest.mark.parametrize(
    ("readiness", "status"),
    [
        (Readiness.READY, Status.OK),
        (Readiness.LIMITED, Status.DEGRADED),
        (Readiness.UNAVAILABLE, Status.DEGRADED),
    ],
)
def test_the_probe_reports_the_configured_accelerator(readiness: Readiness, status: Status) -> None:
    result = GPUProbe(accelerator=_Fixed(readiness)).check()
    assert result.status is status
    assert "fixed hardware" in result.detail


def test_a_failing_hardware_query_degrades_instead_of_crashing() -> None:
    result = GPUProbe(accelerator=_Broken()).check()
    assert result.status is Status.DEGRADED
    assert "sysctl vanished" in result.detail
