"""Probe: is Ollama running, and is the configured model pulled?

One file, one @register line, zero edits elsewhere -- SPEC.md 14.2.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from rewind_ai.core.registry import register
from rewind_ai.health.base import ProbeResult, Status


@register("health_probe", "ollama")
class OllamaProbe:
    """Checks the local Ollama daemon and the model the pipeline will need."""

    name = "ollama"

    def __init__(self, *, base_url: str = "http://127.0.0.1:11434", model: str = "") -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model

    def check(self) -> ProbeResult:
        try:
            with urllib.request.urlopen(f"{self._base_url}/api/tags", timeout=2) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return ProbeResult(self.name, Status.DOWN, f"not reachable at {self._base_url}: {exc}")
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            return ProbeResult(self.name, Status.DEGRADED, f"unexpected response: {exc}")

        models = {m.get("name", "") for m in payload.get("models", [])}
        if not self._model:
            return ProbeResult(self.name, Status.OK, f"{len(models)} model(s) available")

        # DEGRADED rather than DOWN: Ollama is up, so the studio starts fine.
        # The model only becomes load-bearing at M2.
        if self._model not in models:
            return ProbeResult(
                self.name,
                Status.DEGRADED,
                f"model {self._model!r} not pulled; run: ollama pull {self._model}",
            )
        return ProbeResult(self.name, Status.OK, f"model {self._model!r} ready")
