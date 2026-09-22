"""Structured logging, sharing a trace id with the Go API.

LAYER 1 (core) of SPEC.md 14.1; the requirement is SPEC.md 13.4.

Go generates a trace id per request and forwards it as gRPC metadata. Both
services log it under the same field name, so one grep reconstructs a whole
job across both processes -- which is the only practical way to debug a
pipeline that spans two languages.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

#: Must match logging.TraceIDKey in the Go service.
TRACE_ID_KEY = "x-rewind-trace-id"


def configure(*, level: str = "INFO", json_output: bool = False) -> None:
    """Configure structlog once, at startup.

    Text output is easier to read while developing; JSON is what you want when
    logs are being collected.
    """
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())

    renderer: Any = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=False)
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> Any:
    """Return a bound logger."""
    return structlog.get_logger(name)


def bind_trace_id(trace_id: str | None) -> None:
    """Bind the inbound trace id for the current context.

    Uses contextvars, so every log line emitted while handling this request
    carries the id without any call site having to remember to add it.
    """
    structlog.contextvars.clear_contextvars()
    if trace_id:
        structlog.contextvars.bind_contextvars(trace_id=trace_id)


def trace_id_from_metadata(metadata: Any) -> str | None:
    """Extract the trace id from gRPC invocation metadata."""
    if not metadata:
        return None
    for key, value in metadata:
        if key.lower() == TRACE_ID_KEY:
            return str(value)
    return None
