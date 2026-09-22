"""Builds the configured LLM provider.

The factory half of Registry + Factory (SPEC.md 14.3). Importing the providers
package runs every @register decorator in it, so adding a provider never means
editing this file.
"""

from __future__ import annotations

from rewind_ai.core import registry
from rewind_ai.llm import providers as provider_package
from rewind_ai.llm.base import LLM, LLMConfig


def build(config: LLMConfig) -> LLM:
    """Return the provider named by ``config.provider``."""
    registry.load_providers(provider_package)
    cls = registry.get("llm", config.provider)
    instance = cls(config)

    if not isinstance(instance, LLM):
        raise registry.ProviderError(
            f"llm provider {config.provider!r} does not implement the LLM protocol"
        )
    return instance
