"""Run blocking work on a thread and stream its progress as it happens.

M2 learned this the hard way: a handler that collects progress events and
yields them after the work finishes LOOKS identical and gives a dead progress
bar for the whole run. Progress must be yielded as it arrives, which means the
work runs on its own thread and the handler drains a queue.

The research and relevance handlers each carry their own copy of this loop;
new handlers use this one. (Folding the two older copies in is a refactor for
a milestone that is allowed to touch them.)
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable, Iterator
from typing import Any, TypeVar

import grpc

from rewind_ai.core.errors import RewindError
from rewind_ai.core.logging import bind_trace_id, get_logger

log = get_logger(__name__)

T = TypeVar("T")

#: How often to check whether the client has gone away while work runs.
POLL_SECONDS = 0.5

ProgressFn = Callable[[str, float], None]


def stream(
    *,
    name: str,
    trace_id: str | None,
    context: grpc.ServicerContext,
    work: Callable[[ProgressFn], Any],
    on_progress: Callable[[str, float], T],
    on_result: Callable[[Any], T],
    on_failure: Callable[[str, str, bool], T],
) -> Iterator[T]:
    """Yield progress, then exactly one result or failure message.

    `work` receives a progress callback and returns the result. A RewindError
    becomes a failure carrying its code; anything else becomes INTERNAL.
    """
    events: queue.Queue[tuple[str, Any]] = queue.Queue()

    def run() -> None:
        # contextvars do not cross a thread boundary; without this the work's
        # log lines lose their correlation id.
        bind_trace_id(trace_id)
        try:
            events.put(("result", work(lambda stage, pct: events.put(("progress", (stage, pct))))))
        except RewindError as exc:
            log.warning(f"{name} failed", code=exc.code)
            events.put(("failure", (exc.code, exc.message, exc.retryable)))
        except Exception as exc:
            log.exception(f"{name} crashed")
            events.put(("failure", ("INTERNAL", f"unexpected error in {name}: {exc}", False)))
        finally:
            events.put(("done", None))

    to_message: dict[str, Callable[[Any], T]] = {
        "progress": lambda p: on_progress(*p),
        "result": on_result,
        "failure": lambda p: on_failure(*p),
    }

    thread = threading.Thread(target=run, name=name)
    thread.start()
    yield on_progress("starting", 0.01)

    while True:
        try:
            kind, payload = events.get(timeout=POLL_SECONDS)
        except queue.Empty:
            if not context.is_active():
                log.warning(f"client cancelled {name}")
                return
            continue

        if kind == "done":
            break
        yield to_message[kind](payload)

    thread.join(timeout=5)
