"""The script's data types.

LAYER 2 (module base) of SPEC.md 14.1. Imports nothing from this project.

Numbers in a beat are DIGITS ("9,000 years", "1709"). That was decided at M4
kickoff so the validator can check every one against the approved facts;
turning them into speech is Module 5's job.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ScriptFact:
    """An approved fact, as the script writer and validator see it."""

    id: str
    label: str
    claim: str
    evidence: str
    context: str = ""
    source_url: str = ""
    group: str = ""


@dataclass(frozen=True, slots=True)
class ScriptReference:
    """A modern comparison selected at Gate B."""

    id: str
    reference: str
    comparison: str
    linked_fact_id: str


@dataclass(frozen=True, slots=True)
class Beat:
    """One ~5 second unit of the video (SPEC.md 5.4)."""

    n: int
    role: str
    voice: str
    year_stamp: str = ""
    on_screen_text: str = ""
    visual_prompts: list[str] = field(default_factory=list)
    sfx: str = ""
    motion: str = ""
    emphasis_words: list[str] = field(default_factory=list)
    fact_ids: list[str] = field(default_factory=list)
    ref_ids: list[str] = field(default_factory=list)
    is_punch: bool = False


@dataclass(frozen=True, slots=True)
class Violation:
    """One broken rule. `rule` is a stable code; `message` is for a person."""

    rule: str
    #: 1-based; 0 for the script as a whole.
    beat: int
    message: str


@dataclass(frozen=True, slots=True)
class Script:
    """A whole script, as written to script.json."""

    beats: list[Beat]
    title_options: list[str] = field(default_factory=list)
    chosen_title: str = ""
    description: str = ""
    hashtags: list[str] = field(default_factory=list)
    #: Built from the cited facts' sources -- never written by the model.
    sources: list[str] = field(default_factory=list)
    attempts: int = 0
    violations: list[Violation] = field(default_factory=list)
