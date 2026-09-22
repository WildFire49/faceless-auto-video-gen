"""Ollama provider.

One file, one @register line, one config value -- SPEC.md 14.2.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from rewind_ai.core.errors import DependencyUnavailableError, RewindError
from rewind_ai.core.logging import get_logger
from rewind_ai.core.registry import register
from rewind_ai.llm.base import LLMConfig

log = get_logger(__name__)


@register("llm", "ollama")
class OllamaLLM:
    """Talks to a local Ollama daemon over its HTTP API.

    Uses urllib rather than a client library: the API is two endpoints, and a
    dependency that exists to save ten lines is a dependency that will need
    upgrading later.
    """

    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        self._url = config.base_url.rstrip("/") + "/api/chat"

    def complete_json(
        self,
        *,
        system: str,
        prompt: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        payload = {
            "model": self._config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            # Ollama constrains generation to the schema, so the model cannot
            # return prose where an object is expected. This is far more
            # reliable than asking politely in the prompt and parsing later.
            "format": schema,
            "options": {
                "temperature": self._config.temperature,
                # Deterministic across runs, so a failing extraction can be
                # reproduced while debugging.
                "seed": 42,
            },
            # Reasoning models emit a visible thinking block by default. We
            # want terse JSON, so it is turned off where supported; daemons
            # that do not know this key ignore it.
            "think": False,
        }

        request = urllib.request.Request(
            self._url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(
                request, timeout=self._config.request_timeout_seconds
            ) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
            if exc.code == 404:
                raise DependencyUnavailableError(
                    f"model {self._config.model!r} is not pulled",
                    detail=f"run: ollama pull {self._config.model}",
                ) from exc
            raise DependencyUnavailableError(
                f"ollama returned HTTP {exc.code}", detail=detail
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise DependencyUnavailableError(
                f"cannot reach ollama at {self._config.base_url}",
                detail=str(exc),
            ) from exc

        content = body.get("message", {}).get("content", "")
        if not content:
            raise RewindError("ollama returned an empty response")

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            # Surface rather than guess: a model that cannot produce JSON
            # under a schema constraint is a real problem worth seeing.
            raise RewindError(
                "ollama returned output that is not valid JSON",
                detail=content[:400],
            ) from exc

        if not isinstance(parsed, dict):
            raise RewindError(f"expected a JSON object, got {type(parsed).__name__}")
        return parsed
