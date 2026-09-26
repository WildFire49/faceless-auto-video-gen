"""The composition root: the one place that turns config into objects.

LAYER 1 (core) of SPEC.md 14.1, rule 3.

This is the ONLY module in the worker allowed to decide which concrete
provider is used. Everything else receives what it needs through its
constructor and depends on a Protocol, which is what makes the tree testable
and what makes SPEC.md 14.2's one-file-one-line-one-value promise real.
"""

from __future__ import annotations

from dataclasses import dataclass

from rewind_ai.compute import factory as accelerator_factory
from rewind_ai.compute.base import Accelerator
from rewind_ai.core import registry
from rewind_ai.core.config import Settings
from rewind_ai.core.logging import get_logger
from rewind_ai.formats import factory as format_factory
from rewind_ai.formats.base import ContentFormat
from rewind_ai.health import probes as probe_package
from rewind_ai.health.base import Probe
from rewind_ai.health.service import HealthChecker
from rewind_ai.llm import factory as llm_factory
from rewind_ai.llm.base import LLM, LLMConfig
from rewind_ai.research import sources as research_source_package
from rewind_ai.research.base import SourceFetcher
from rewind_ai.research.service import ResearchConfig, ResearchService

log = get_logger(__name__)

#: Reported to the dashboard footer and in bug reports.
VERSION = "0.2.0"


@dataclass(frozen=True, slots=True)
class Container:
    """Everything the server needs, already wired."""

    settings: Settings
    health: HealthChecker
    research: ResearchService
    llm: LLM
    content_format: ContentFormat
    #: The GPU model work runs on. M5/M6 load models onto ``accelerator.device``.
    accelerator: Accelerator


def build(settings: Settings) -> Container:
    """Construct the object graph from configuration."""
    # Importing each providers package runs every @register decorator in it.
    # Sweeping rather than listing imports is what lets a new provider be
    # added without editing this file (SPEC.md 14.2).
    registry.load_providers(probe_package)
    registry.load_providers(research_source_package)

    llm_config = LLMConfig(
        provider=settings.llm.provider,
        model=settings.llm.model,
        temperature=settings.llm.temperature,
        request_timeout_seconds=settings.llm.request_timeout_seconds,
        max_chunk_chars=settings.llm.max_chunk_chars,
        base_url=settings.llm.base_url,
    )
    llm = llm_factory.build(llm_config)

    content_format = format_factory.build(settings.content.format)
    accelerator = accelerator_factory.build(settings.compute.accelerator)
    fetchers = _build_fetchers(settings)
    probes = _build_probes(
        llm_model=settings.llm.model, base_url=settings.llm.base_url, accelerator=accelerator
    )

    log.info(
        "providers registered",
        content_format=content_format.name,
        available_formats=format_factory.available(),
        llm=settings.llm.provider,
        model=settings.llm.model,
        accelerator=accelerator.name,
        device=accelerator.device,
        research_sources=[f.name for f in fetchers],
        health_probes=registry.available("health_probe"),
    )

    return Container(
        settings=settings,
        health=HealthChecker(version=VERSION, probes=probes),
        llm=llm,
        content_format=content_format,
        accelerator=accelerator,
        research=ResearchService(
            fetchers=fetchers,
            llm=llm,
            content_format=content_format,
            config=ResearchConfig(
                evidence_match_threshold=settings.research.evidence_match_threshold,
                max_chunk_chars=settings.llm.max_chunk_chars,
                max_items=settings.research.max_items,
            ),
            projects_dir=settings.paths.projects,
        ),
    )


def _build_fetchers(settings: Settings) -> list[SourceFetcher]:
    """Instantiate the research sources named in config, in order.

    Order matters: earlier sources are fetched first and win on conflict.
    """
    built: list[SourceFetcher] = []

    for name in settings.research.sources:
        try:
            cls = registry.get("research_source", name)
        except registry.ProviderError:
            # A typo in config should not silently drop a source.
            log.error("unknown research source in config", source=name)
            raise

        if name == "wikipedia":
            built.append(
                cls(
                    max_articles=settings.research.max_articles,
                    search_pool=settings.research.search_pool,
                    offtopic_markers=settings.research.offtopic_markers,
                )
            )
        else:
            built.append(cls())

    return built


def _build_probes(*, llm_model: str, base_url: str, accelerator: Accelerator) -> list[Probe]:
    """Instantiate every registered health probe.

    Probes differ in their constructor arguments, so this function knows how
    to supply them. It degrades rather than crashes when a probe cannot be
    built, because a broken probe must never stop the worker from starting.
    """
    built: list[Probe] = []
    for name in registry.available("health_probe"):
        cls = registry.get("health_probe", name)
        try:
            if name == "ollama":
                built.append(cls(base_url=base_url, model=llm_model))
            elif name == "gpu":
                built.append(cls(accelerator=accelerator))
            else:
                built.append(cls())
        except Exception as exc:  # noqa: BLE001 - see docstring
            log.warning("could not construct probe", probe=name, error=str(exc))
    return built
