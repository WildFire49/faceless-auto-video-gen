"""Builds the configured content format.

The factory half of Registry + Factory (SPEC.md 14.3). Importing the providers
package runs every @register decorator in it, so adding a format never means
editing this file.
"""

from __future__ import annotations

from rewind_ai.core import registry
from rewind_ai.formats import providers as provider_package
from rewind_ai.formats.base import ContentFormat


def build(name: str) -> ContentFormat:
    """Return the format named by ``content.format`` in config."""
    registry.load_providers(provider_package)
    cls = registry.get("content_format", name)
    instance = cls()

    if not isinstance(instance, ContentFormat):
        raise registry.ProviderError(
            f"content format {name!r} does not implement the ContentFormat protocol"
        )
    return instance


def available() -> list[str]:
    """Every registered format name, for diagnostics and the dashboard."""
    registry.load_providers(provider_package)
    return registry.available("content_format")
