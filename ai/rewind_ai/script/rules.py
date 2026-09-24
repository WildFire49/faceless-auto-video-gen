"""The script validator: every rule, in one chain (SPEC.md 5.4).

Two groups, kept in separate files so each stays readable:
structure_rules.py (shape: beat count, roles, word limit, loop) and
evidence_rules.py (truth: grounded numbers, references, brand claims).

This is the ONLY implementation of the rules. The worker runs it while
generating; Go calls it over gRPC after every inline edit at Gate C. Two
copies would eventually disagree about whether a script is valid.
"""

from __future__ import annotations

from rewind_ai.script.base import Script, Violation
from rewind_ai.script.context import Limits, RuleContext
from rewind_ai.script.evidence_rules import EVIDENCE_RULES
from rewind_ai.script.structure_rules import STRUCTURE_RULES, Rule

RULES: tuple[Rule, ...] = STRUCTURE_RULES + EVIDENCE_RULES


def validate(script: Script, ctx: RuleContext) -> list[Violation]:
    """Every violation, in beat order. Empty means the script is valid."""
    found = [violation for rule in RULES for violation in rule(script, ctx)]
    return sorted(found, key=lambda v: (v.beat, v.rule))


__all__ = ["RULES", "Limits", "RuleContext", "validate"]
