"""Typed settings loaded from ``config/*.yaml``.

LAYER 1 (core) of SPEC.md 14.1.

Only the composition root (``core.container``) reads configuration. Everything
else receives the values it needs through its constructor, because a component
that fetches its own settings cannot be tested with different ones.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ConfigError(RuntimeError):
    """Raised when configuration is missing or malformed.

    Configuration problems are detected at startup, never at the first request:
    a studio that will not work should refuse to start rather than fail
    halfway through a render.
    """


@dataclass(frozen=True, slots=True)
class AISettings:
    """The ``ai:`` block of ``config/services.yaml``."""

    grpc_addr: str
    max_message_bytes: int = 4 * 1024 * 1024
    timeouts_seconds: dict[str, int] = field(default_factory=dict)

    @property
    def host(self) -> str:
        return self.grpc_addr.rsplit(":", 1)[0]

    @property
    def port(self) -> int:
        return int(self.grpc_addr.rsplit(":", 1)[1])


@dataclass(frozen=True, slots=True)
class PathSettings:
    """Where project output and shared assets live."""

    projects: Path
    assets: Path


@dataclass(frozen=True, slots=True)
class LLMSettings:
    """The ``llm:`` block of ``config/channel.yaml``."""

    provider: str = "ollama"
    model: str = "qwen3:8b"
    temperature: float = 0.1
    request_timeout_seconds: int = 120
    max_chunk_chars: int = 6000
    base_url: str = "http://127.0.0.1:11434"


@dataclass(frozen=True, slots=True)
class ResearchSettings:
    """The ``research:`` block of ``config/channel.yaml``.

    Item counts and grouping are NOT here: they belong to the content format,
    because they differ by kind of video.
    """

    sources: list[str] = field(default_factory=lambda: ["wikipedia", "user_url"])
    evidence_match_threshold: float = 0.90
    max_articles: int = 3
    search_pool: int = 3
    offtopic_markers: list[str] = field(default_factory=list)
    max_items: int = 40


@dataclass(frozen=True, slots=True)
class ComputeSettings:
    """The ``compute:`` block of ``config/channel.yaml``.

    Which GPU model work runs on. A swap, so moving between an Apple Silicon
    Mac and an NVIDIA box is this one value.
    """

    accelerator: str = "apple_mps"


@dataclass(frozen=True, slots=True)
class ContentSettings:
    """The ``content:`` block of ``config/channel.yaml``.

    One line decides what kind of video this channel makes.
    """

    format: str = "history_timeline"


@dataclass(frozen=True, slots=True)
class Settings:
    """Everything the AI worker needs to start."""

    ai: AISettings
    paths: PathSettings
    config_dir: Path
    llm: LLMSettings = field(default_factory=LLMSettings)
    research: ResearchSettings = field(default_factory=ResearchSettings)
    content: ContentSettings = field(default_factory=ContentSettings)
    compute: ComputeSettings = field(default_factory=ComputeSettings)


def find_config_dir(start: Path | None = None) -> Path:
    """Walk up from ``start`` to the repository's ``config/`` directory.

    Lets the worker be launched from anywhere in the repo, which matters more
    than it sounds like during development.
    """
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "config" / "services.yaml").is_file():
            return candidate / "config"
    raise ConfigError(f"no config/services.yaml found at or above {current}")


def load(config_dir: Path | None = None) -> Settings:
    """Load and validate the configuration files."""
    directory = config_dir or find_config_dir()
    services = _load_yaml(directory / "services.yaml")

    ai_raw = _require_mapping(services, "ai", directory / "services.yaml")
    paths_raw = _require_mapping(services, "paths", directory / "services.yaml")

    grpc_addr = ai_raw.get("grpc_addr")
    if not isinstance(grpc_addr, str) or ":" not in grpc_addr:
        raise ConfigError(f"{directory / 'services.yaml'}: ai.grpc_addr must look like 'host:port'")

    repo_root = directory.parent

    # channel.yaml is optional at this layer: the worker can start and report
    # health without it, which matters when diagnosing a broken setup.
    channel_path = directory / "channel.yaml"
    channel = _load_yaml(channel_path) if channel_path.is_file() else {}

    return Settings(
        ai=AISettings(
            grpc_addr=grpc_addr,
            max_message_bytes=int(ai_raw.get("max_message_bytes", 4 * 1024 * 1024)),
            timeouts_seconds=dict(ai_raw.get("timeouts_seconds") or {}),
        ),
        paths=PathSettings(
            projects=repo_root / str(paths_raw.get("projects", "projects")),
            assets=repo_root / str(paths_raw.get("assets", "assets")),
        ),
        config_dir=directory,
        llm=_llm_settings(channel),
        research=_research_settings(channel),
        content=_content_settings(channel),
        compute=_compute_settings(channel),
    )


def _compute_settings(channel: dict[str, Any]) -> ComputeSettings:
    raw = channel.get("compute")
    if not isinstance(raw, dict):
        return ComputeSettings()
    return ComputeSettings(accelerator=str(raw.get("accelerator", ComputeSettings().accelerator)))


def _content_settings(channel: dict[str, Any]) -> ContentSettings:
    raw = channel.get("content")
    if not isinstance(raw, dict):
        return ContentSettings()
    return ContentSettings(format=str(raw.get("format", ContentSettings().format)))


def _llm_settings(channel: dict[str, Any]) -> LLMSettings:
    raw = channel.get("llm")
    if not isinstance(raw, dict):
        return LLMSettings()

    defaults = LLMSettings()
    return LLMSettings(
        provider=str(raw.get("provider", defaults.provider)),
        model=str(raw.get("model", defaults.model)),
        temperature=float(raw.get("temperature", defaults.temperature)),
        request_timeout_seconds=int(
            raw.get("request_timeout_seconds", defaults.request_timeout_seconds)
        ),
        max_chunk_chars=int(raw.get("max_chunk_chars", defaults.max_chunk_chars)),
        base_url=str(raw.get("base_url", defaults.base_url)),
    )


def _research_settings(channel: dict[str, Any]) -> ResearchSettings:
    raw = channel.get("research")
    if not isinstance(raw, dict):
        return ResearchSettings()

    defaults = ResearchSettings()
    sources = raw.get("sources")
    markers = raw.get("offtopic_markers")
    return ResearchSettings(
        sources=[str(s) for s in sources] if isinstance(sources, list) else defaults.sources,
        evidence_match_threshold=float(
            raw.get("evidence_match_threshold", defaults.evidence_match_threshold)
        ),
        max_articles=int(raw.get("max_articles", defaults.max_articles)),
        search_pool=int(raw.get("search_pool", defaults.search_pool)),
        offtopic_markers=[str(m) for m in markers]
        if isinstance(markers, list)
        else defaults.offtopic_markers,
        max_items=int(raw.get("max_items", defaults.max_items)),
    )


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"missing {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"parsing {path}: {exc}") from exc

    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must contain a YAML mapping")
    return raw


def _require_mapping(raw: dict[str, Any], key: str, path: Path) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"{path}: '{key}' section is required and must be a mapping")
    return value
