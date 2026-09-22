"""Provider registry: the mechanism behind the plug-and-play contract.

LAYER 1 (core) of SPEC.md 14.1.

This is the single piece of machinery that makes SPEC.md 14.2 true:

    Adding or replacing a provider = one new file + one registry line +
    one config value. No existing file may be edited.

A provider module declares itself::

    @register("voice", "piper")
    class PiperEngine(VoiceEngine):
        ...

and the container resolves it by the name in ``config/channel.yaml``. Nothing
imports ``PiperEngine`` directly, so nothing has to change when it appears or
disappears. There is no ``if provider == "..."`` anywhere in this codebase, by
construction.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable
from types import ModuleType
from typing import TypeVar

T = TypeVar("T")

# kind -> name -> implementation. "kind" is the extension point ("voice",
# "llm", "visuals"); "name" is the provider ("chatterbox", "kokoro").
_REGISTRY: dict[str, dict[str, type]] = {}


class ProviderError(LookupError):
    """Raised when a provider cannot be resolved.

    Subclasses LookupError so callers can catch it broadly, and carries a
    message that lists what IS available -- a misspelled provider name in a
    config file should tell you the options, not just that you were wrong.
    """


def register(kind: str, name: str) -> Callable[[type[T]], type[T]]:
    """Register a provider class under ``kind``/``name``.

    Returns the class unchanged, so the decorator is invisible to everything
    except the registry.

    Raises:
        ProviderError: if the same kind/name is registered twice. A silent
            overwrite would mean the provider you get depends on import order,
            which is the kind of bug that takes a day to find.
    """

    def decorate(cls: type[T]) -> type[T]:
        providers = _REGISTRY.setdefault(kind, {})
        if name in providers and providers[name] is not cls:
            raise ProviderError(
                f"provider {kind}/{name} is already registered by "
                f"{providers[name].__module__}.{providers[name].__qualname__}"
            )
        providers[name] = cls
        return cls

    return decorate


def get(kind: str, name: str) -> type:
    """Look up a registered provider class."""
    providers = _REGISTRY.get(kind, {})
    if name not in providers:
        available = ", ".join(sorted(providers)) or "none registered"
        raise ProviderError(f"unknown {kind} provider {name!r}; available: {available}")
    return providers[name]


def available(kind: str) -> list[str]:
    """List the registered provider names for a kind, for diagnostics and docs."""
    return sorted(_REGISTRY.get(kind, {}))


def kinds() -> list[str]:
    """List every registered extension point."""
    return sorted(_REGISTRY)


def load_providers(package: ModuleType) -> None:
    """Import every submodule of ``package`` so its decorators run.

    Registration is a side effect of import, so a provider that is never
    imported is invisible. Rather than maintain a hand-written import list --
    which would break the "no existing file may be edited" rule the moment you
    add a provider -- each ``providers/`` package is swept once at startup.
    """
    if not hasattr(package, "__path__"):
        return
    for module in pkgutil.iter_modules(package.__path__):
        if module.name.startswith("_"):
            continue
        importlib.import_module(f"{package.__name__}.{module.name}")


def clear() -> None:
    """Reset the registry. Test-only; never call this from application code."""
    _REGISTRY.clear()
