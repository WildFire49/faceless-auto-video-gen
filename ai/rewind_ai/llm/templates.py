"""Render prompt templates from llm/prompts/*.jinja.

Prompts are files, not string literals in code (CLAUDE.md): a prompt is
edited far more often than the code around it, and a diff of a template is
readable where a diff of an f-string buried in a function is not.

StrictUndefined, so a template that names a variable nobody passed fails
loudly at render time instead of quietly sending the model an empty slot.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

PROMPTS_DIR = Path(__file__).parent / "prompts"


class Templates:
    """Loads and renders prompt templates."""

    def __init__(self, directory: Path = PROMPTS_DIR) -> None:
        self._env = Environment(
            loader=FileSystemLoader(str(directory)),
            undefined=StrictUndefined,
            # Prompts are plain text for a model, not HTML: escaping would
            # turn a quote mark into &#34; in front of the model.
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
        )

    def render(self, name: str, **variables: Any) -> str:
        return self._env.get_template(name).render(**variables)
