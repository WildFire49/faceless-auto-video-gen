"""The content format contract.

LAYER 2 (module base) of SPEC.md 14.1.

A CONTENT FORMAT is what kind of video this is. "History of an everyday object"
is one format, not the product. The product is: **every claim on screen is
traceable to a source a human approved**, and that is true whether the video is
a timeline, a ranked list or a myth-buster.

So everything format-specific lives behind this Protocol:

    - what "an item" means, and the JSON schema the model must return
    - the prompts that ask for it
    - which items are implausible for this format
    - how items are grouped, for the variety check at Gate A
    - the gate thresholds, and the NOUN to use when explaining them

What deliberately does NOT live here: the evidence verifier. Checking that a
quoted sentence really appears in the source is format-agnostic, and it is the
one thing that must never vary by content type (CLAUDE.md).

Adding a format is one new file under ``providers/`` with one ``@register``
line and one config value (SPEC.md 14.2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class GateRules:
    """What a fact sheet must contain before its gate can be approved."""

    #: Minimum approved items.
    min_items: int
    #: Minimum distinct groups those items must span, so a video is not eight
    #: variations on one idea.
    min_groups: int
    #: What a group IS called, for messages: "era", "domain", "category".
    #: Singular; the caller pluralises.
    group_noun: str


@dataclass(frozen=True, slots=True)
class BeatSlot:
    """What one position in a script is for (SPEC.md 5.4)."""

    #: Short stable name, written into script.json: "hook", "era", "rehook".
    role: str
    #: What the beat must do, in words the script writer is given.
    brief: str
    #: Must cite at least one approved fact. A beat that states something
    #: without citing a fact cannot have its numbers checked.
    needs_fact: bool
    #: Must carry an on-screen date.
    needs_year_stamp: bool


@dataclass(frozen=True, slots=True)
class ScriptShape:
    """How a format lays out a script: one slot per beat, in order.

    Owned by the format because the Rewind formula (era stops, year stamps)
    presumes a timeline. What is NOT the format's to vary lives in
    script/rules.py and applies to every shape: the word limit, grounded
    numbers, at most three references, and the loop back to the opening.
    """

    slots: tuple[BeatSlot, ...]


def opening_body_close(
    beats: int, *, opening: BeatSlot, body: BeatSlot, rehook: BeatSlot, close: BeatSlot
) -> ScriptShape:
    """The shape most formats share: an opening, a body with a rehook at its
    midpoint to hold attention, and a close that loops back to the opening.
    """
    if beats < 4:
        raise ValueError(f"a script needs at least 4 beats for this shape, got {beats}")
    middle = beats // 2  # 0-based index; beat 5 of 9
    slots = [opening]
    for index in range(1, beats - 1):
        slots.append(rehook if index == middle else body)
    slots.append(close)
    return ScriptShape(slots=tuple(slots))


@dataclass(frozen=True, slots=True)
class RawItem:
    """One object as the model returned it, before any checking.

    Deliberately loose: the format decides what the fields mean. ``sort_key``
    is a year for a timeline and a rank for a list; ``label`` is what a
    narrator says either way.
    """

    label: str
    sort_key: int
    context: str
    claim: str
    evidence: str
    #: Anything else the format asked for, kept so a provider can use fields
    #: the generic pipeline knows nothing about.
    extra: dict[str, Any]


@runtime_checkable
class ContentFormat(Protocol):
    """One kind of video."""

    #: Stable identifier, used in config and written into facts.json.
    name: str

    #: One line shown in the dashboard, e.g. "A timeline from the oldest
    #: known version to today."
    description: str

    def system_prompt(self) -> str:
        """The instruction that governs extraction.

        Every format's prompt must forbid the model from using anything it
        knows, and must require a verbatim ``evidence`` sentence. That rule is
        not the format's to relax (CLAUDE.md).
        """
        ...

    def user_prompt(self, *, topic: str, source_title: str, chunk: str, max_items: int) -> str:
        """The per-chunk request."""
        ...

    def item_schema(self) -> dict[str, Any]:
        """JSON schema for the model's response.

        Must produce an object with an ``items`` array. ``evidence`` must be a
        required property of each item -- without it there is nothing to
        verify, and an unverifiable claim is what this project must never
        produce.
        """
        ...

    def parse_item(self, raw: dict[str, Any]) -> RawItem | None:
        """Turn one raw object into a RawItem, or None if unusable."""
        ...

    def implausible_reason(self, item: RawItem) -> str:
        """Why this item is unusable for this format, or "" if it is fine.

        Separate from evidence verification because it fails differently: the
        claim may be true and perfectly sourced and still be no use here -- a
        date of 4.6 billion years ago in a series about everyday objects, or a
        rank of zero in a top-ten list.
        """
        ...

    def group_of(self, item: RawItem) -> str:
        """Which bucket this item falls in, for the variety check.

        A timeline groups by era; a myth-buster groups by subject domain. The
        pipeline only ever counts distinct values, so the strings are the
        format's own business.
        """
        ...

    def gate_rules(self) -> GateRules:
        """Thresholds for this format's first review gate."""
        ...

    def script_shape(self, beats: int) -> ScriptShape:
        """What each of ``beats`` positions in the script is for."""
        ...
