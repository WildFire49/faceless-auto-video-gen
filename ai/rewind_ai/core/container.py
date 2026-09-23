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
from rewind_ai.formats import factory as format_factory
from rewind_ai.formats.base import ContentFormat
from rewind_ai.health import probes as probe_package
from rewind_ai.health.base import Probe
from rewind_ai.health.service import HealthChecker
from rewind_ai.llm import factory as llm_factory
from rewind_ai.llm.base import LLM, LLMConfig
from rewind_ai.relevance import sources as trend_source_package
from rewind_ai.relevance.bank import TrendCache, load_bank
from rewind_ai.relevance.base import TrendSource
from rewind_ai.relevance.service import RelevanceConfig, RelevanceService
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
    relevance: RelevanceService
    trends: TrendCache
    llm: LLM
    content_format: ContentFormat


def build(settings: Settings) -> Container:
    """Construct the object graph from configuration."""
    # Importing each providers package runs every @register decorator in it.
    # Sweeping rather than listing imports is what lets a new provider be
    # added without editing this file (SPEC.md 14.2).
    registry.load_providers(probe_package)
    registry.load_providers(research_source_package)
    registry.load_providers(trend_source_package)

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
    fetchers = _build_fetchers(settings)
    trend_sources = _build_trend_sources(settings)

    # The cache lives beside the projects rather than inside one: it is shared
    # by every video made today (SPEC.md 5.3b).
    trends = TrendCache(settings.paths.projects.parent / "trends_cache.json", trend_sources)
    bank = load_bank(settings.config_dir)
    probes = _build_probes(llm_model=settings.llm.model, base_url=settings.llm.base_url)

    log.info(
        "providers registered",
        content_format=content_format.name,
        available_formats=format_factory.available(),
        llm=settings.llm.provider,
        model=settings.llm.model,
        research_sources=[f.name for f in fetchers],
        trend_sources=[t.name for t in trend_sources],
        reference_categories=sorted(bank.categories),
        health_probes=registry.available("health_probe"),
    )

    return Container(
        settings=settings,
        health=HealthChecker(version=VERSION, probes=probes),
        llm=llm,
        content_format=content_format,
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
        trends=trends,
        relevance=RelevanceService(
            llm=llm,
            bank=bank,
            trends=trends,
            config=RelevanceConfig(
                max_selectable=settings.relevance.max_selectable,
                max_proposals=settings.relevance.max_proposals,
            ),
            projects_dir=settings.paths.projects,
        ),
    )


def _build_trend_sources(settings: Settings) -> list[TrendSource]:
    """Instantiate the trend sources named in config.

    An unknown name is logged and skipped rather than fatal: trends are a
    garnish, and refusing to start the worker because one source was
    misspelled would be disproportionate.
    """
    built: list[TrendSource] = []

    for name in settings.relevance.sources:
        try:
            cls = registry.get("trend_source", name)
        except registry.ProviderError:
            log.error("unknown trend source in config", source=name)
            continue

        built.append(cls(geo=settings.relevance.geo) if name == "google_trends" else cls())

    return built


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
            built.append(cls(max_articles=settings.research.max_articles))
        else:
            built.append(cls())

    return built


def _build_probes(*, llm_model: str, base_url: str) -> list[Probe]:
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
            else:
                built.append(cls())
        except Exception as exc:  # noqa: BLE001 - see docstring
            log.warning("could not construct probe", probe=name, error=str(exc))
    return built
