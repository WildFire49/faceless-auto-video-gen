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
class Settings:
    """Everything the AI worker needs to start."""

    ai: AISettings
    paths: PathSettings
    config_dir: Path


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
    """Load and validate ``services.yaml``."""
    directory = config_dir or find_config_dir()
    path = directory / "services.yaml"

    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"missing {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"parsing {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must contain a YAML mapping")

    ai_raw = _require_mapping(raw, "ai", path)
    paths_raw = _require_mapping(raw, "paths", path)

    grpc_addr = ai_raw.get("grpc_addr")
    if not isinstance(grpc_addr, str) or ":" not in grpc_addr:
        raise ConfigError(f"{path}: ai.grpc_addr must look like 'host:port'")

    repo_root = directory.parent
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
    )


def _require_mapping(raw: dict[str, Any], key: str, path: Path) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"{path}: '{key}' section is required and must be a mapping")
    return value
