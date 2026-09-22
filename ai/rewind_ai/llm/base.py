"""The LLM contract.

LAYER 2 (module base) of SPEC.md 14.1. Imports nothing but ``core``.

Swapping model backends is one new file under ``providers/`` plus one config
value (SPEC.md 14.2). Nothing outside this package knows Ollama exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class LLMConfig:
    """Everything a provider needs, from ``config/channel.yaml``."""

    provider: str
    model: str
    temperature: float = 0.1
    request_timeout_seconds: int = 120
    max_chunk_chars: int = 6000
    #: Where the daemon lives. Providers that need no endpoint ignore it.
    base_url: str = "http://127.0.0.1:11434"


@runtime_checkable
class LLM(Protocol):
    """A local language model that can return structured JSON.

    Only one method, because only one thing is ever asked of it in this
    project: read some text, return JSON matching a schema. There is
    deliberately no free-text ``complete`` -- every use here is extraction,
    and a general escape hatch would invite the LLM to become the source of a
    fact (CLAUDE.md).
    """

    def complete_json(
        self,
        *,
        system: str,
        prompt: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        """Return a JSON object matching ``schema``.

        Implementations must raise on unparseable output rather than returning
        a partial or guessed result: a malformed response is a real failure and
        should surface, not be papered over.
        """
        ...
