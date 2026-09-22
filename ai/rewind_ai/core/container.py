"""The composition root: the one place that turns config into objects.

LAYER 1 (core) of SPEC.md 14.1, rule 3.

This is the ONLY module in the worker allowed to decide which concrete
provider is used. Everything else receives what it needs through its
constructor and depends on a Protocol, which is what makes the tree testable
and what makes SPEC.md 14.2's one-file-one-line-one-value promise real.
"""

from __future__ import annotations

from dataclasses import dataclass

from rewind_ai.core import registry
from rewind_ai.core.config import Settings
from rewind_ai.core.logging import get_logger
from rewind_ai.health import probes as probe_package
from rewind_ai.health.base import Probe
from rewind_ai.health.service import HealthChecker

log = get_logger(__name__)

#: Reported to the dashboard footer and in bug reports.
VERSION = "0.1.0"


@dataclass(frozen=True, slots=True)
class Container:
    """Everything the server needs, already wired."""

    settings: Settings
    health: HealthChecker


def build(settings: Settings, *, llm_model: str = "") -> Container:
    """Construct the object graph from configuration.

    Args:
        settings: parsed ``config/services.yaml``.
        llm_model: the model the pipeline will need, so the Ollama probe can
            report it as missing before M2 depends on it.
    """
    # Importing the providers package runs every @register decorator in it.
    # Sweeping the package rather than listing imports is what lets a new
    # provider be added without editing this file.
    registry.load_providers(probe_package)

    probes = _build_probes(llm_model=llm_model)
    log.info("providers registered", health_probes=registry.available("health_probe"))

    return Container(
        settings=settings,
        health=HealthChecker(version=VERSION, probes=probes),
    )


def _build_probes(*, llm_model: str) -> list[Probe]:
    """Instantiate every registered health probe.

    Probes differ in their constructor arguments, so this function knows how
    to supply them. It is the one seam where a provider's specific needs are
    expressed -- and note it degrades rather than crashes when a probe cannot
    be built, because a broken probe must never stop the worker from starting.
    """
    built: list[Probe] = []
    for name in registry.available("health_probe"):
        cls = registry.get("health_probe", name)
        try:
            built.append(cls(model=llm_model) if name == "ollama" else cls())
        except Exception as exc:
            log.warning("could not construct probe", probe=name, error=str(exc))
    return built
