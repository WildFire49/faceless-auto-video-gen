"""Builds the configured accelerator.

The factory half of Registry + Factory (SPEC.md 14.3). Importing the providers
package runs every @register decorator in it, so adding an accelerator never
means editing this file.
"""

from __future__ import annotations

from rewind_ai.compute import providers as provider_package
from rewind_ai.compute.base import Accelerator
from rewind_ai.core import registry


def build(name: str) -> Accelerator:
    """Return the accelerator named by ``compute.accelerator`` in config."""
    registry.load_providers(provider_package)
    cls = registry.get("accelerator", name)
    instance = cls()

    if not isinstance(instance, Accelerator):
        raise registry.ProviderError(
            f"accelerator {name!r} does not implement the Accelerator protocol"
        )
    return instance


def available() -> list[str]:
    """Every registered accelerator name, for diagnostics."""
    registry.load_providers(provider_package)
    return registry.available("accelerator")
