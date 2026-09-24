"""What every validator rule is given, besides the script itself."""

from __future__ import annotations

from dataclasses import dataclass

from rewind_ai.formats.base import ScriptShape
from rewind_ai.script.base import ScriptFact, ScriptReference


@dataclass(frozen=True, slots=True)
class Limits:
    """The numbers from config/channel.yaml the rules enforce."""

    beats: int
    max_words_per_beat: int
    max_sfx_per_beat: int
    max_references: int
    loop_min_shared_words: int


@dataclass(frozen=True, slots=True)
class RuleContext:
    """Everything a rule may consult. Rules read it; none may change it."""

    #: The content format's layout: what each beat position is for.
    shape: ScriptShape
    #: APPROVED facts only, by id.
    facts: dict[str, ScriptFact]
    #: References SELECTED at Gate B only, by id.
    references: dict[str, ScriptReference]
    limits: Limits
