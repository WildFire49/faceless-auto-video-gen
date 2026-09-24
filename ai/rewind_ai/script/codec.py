"""Scripts to and from JSON: the model's output, and script.json on disk.

Separate from the service because it fails differently: this is about shape,
not truth. A model that returns a string where a list belongs is coerced
here; whether what it SAID is true is the validator's business.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from rewind_ai.script.base import Beat, Script, Violation

#: What the model must return. Beat numbers are not asked for -- they are
#: assigned by position, so a model cannot number beats 1, 2, 2, 4.
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title_options": {"type": "array", "items": {"type": "string"}},
        "description": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "beats": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "role": {"type": "string"},
                    "year_stamp": {"type": "string"},
                    # Two short parts rather than one line under a word budget:
                    # models cannot count to 14, but can write 9 words and 5.
                    "fact_line": {"type": "string"},
                    "punch": {"type": "string"},
                    "on_screen_text": {"type": "string"},
                    "visual_prompts": {"type": "array", "items": {"type": "string"}},
                    "sfx": {"type": "string"},
                    "motion": {"type": "string"},
                    "emphasis_words": {"type": "array", "items": {"type": "string"}},
                    "fact_ids": {"type": "array", "items": {"type": "string"}},
                    "ref_ids": {"type": "array", "items": {"type": "string"}},
                    "is_punch": {"type": "boolean"},
                },
                "required": ["role", "fact_line", "punch", "fact_ids"],
            },
        },
    },
    "required": ["title_options", "beats"],
}


def from_model(raw: dict[str, Any]) -> Script:
    """Build a Script from the model's JSON, numbering beats by position."""
    beats = [
        _beat(n, item)
        for n, item in enumerate(_list(raw.get("beats")), start=1)
        if isinstance(item, dict)
    ]
    return Script(
        beats=beats,
        title_options=_strings(raw.get("title_options")),
        description=_text(raw.get("description")),
        hashtags=_strings(raw.get("hashtags")),
    )


def to_json(script: Script) -> dict[str, Any]:
    """script.json, in the shape SPEC.md 5.4 shows."""
    return asdict(script)


def from_json(data: dict[str, Any]) -> Script:
    """Read script.json back."""
    return Script(
        beats=[
            _beat(int(b.get("n", i)), b)
            for i, b in enumerate(_list(data.get("beats")), start=1)
            if isinstance(b, dict)
        ],
        title_options=_strings(data.get("title_options")),
        chosen_title=_text(data.get("chosen_title")),
        description=_text(data.get("description")),
        hashtags=_strings(data.get("hashtags")),
        sources=_strings(data.get("sources")),
        attempts=int(data.get("attempts", 0) or 0),
        violations=[
            Violation(str(v.get("rule", "")), int(v.get("beat", 0) or 0), str(v.get("message", "")))
            for v in _list(data.get("violations"))
            if isinstance(v, dict)
        ],
    )


def narration(item: dict[str, Any]) -> str:
    """The spoken line: a fact line and a punch joined, or a whole `voice`."""
    parts = [_text(item.get("fact_line")), _text(item.get("punch"))]
    joined = " ".join(p for p in parts if p)
    return joined or _text(item.get("voice"))


def _beat(n: int, item: dict[str, Any]) -> Beat:
    return Beat(
        n=n,
        role=_text(item.get("role")),
        voice=narration(item),
        year_stamp=_text(item.get("year_stamp")),
        on_screen_text=_text(item.get("on_screen_text")),
        visual_prompts=_strings(item.get("visual_prompts")),
        sfx=_text(item.get("sfx")),
        motion=_text(item.get("motion")),
        emphasis_words=_strings(item.get("emphasis_words")),
        fact_ids=_strings(item.get("fact_ids")),
        ref_ids=_strings(item.get("ref_ids")),
        is_punch=bool(item.get("is_punch", False)),
    )


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _strings(value: Any) -> list[str]:
    # A model that answers "f3" where ["f3"] belongs meant a one-item list.
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return [s.strip() for s in _list(value) if isinstance(s, str) and s.strip()]
