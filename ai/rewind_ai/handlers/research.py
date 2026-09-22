"""gRPC servicer for rewind.v1.ResearchService.

LAYER 3 (transport) of SPEC.md 14.1: unwrap, call one service method, wrap the
result. All the real work is in ``research.service``, which tests call directly.

This is the project's first server-streaming handler, and the shape every later
long-running step will copy (SPEC.md 2.5):

    yield Progress...        while working
    yield result OR failure  exactly once, at the end

Why a thread and a queue
------------------------
``ResearchService.build`` is ordinary synchronous code -- it cannot yield, and
rewriting the whole pipeline as a generator to suit gRPC would be the transport
layer dictating the shape of the domain.

So the work runs on a thread and reports progress into a queue, which this
generator drains AS EVENTS ARRIVE. The obvious alternative -- collecting
progress in a list and yielding it after ``build`` returns -- looks equivalent
and is not: every event then arrives at the end, so the dashboard shows a dead
progress bar for the entire multi-minute run. That bug was real, and it is the
reason this is written the harder way.

The worker reports WHAT happened. Go decides what it MEANS for the video's
status -- this handler never sets one.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Iterator
from typing import Any

import grpc

from rewind.v1 import common_pb2, research_pb2, research_pb2_grpc
from rewind_ai.core.errors import RewindError
from rewind_ai.core.logging import bind_trace_id, get_logger, trace_id_from_metadata
from rewind_ai.research.base import Document, Fact, ResearchResult
from rewind_ai.research.service import ResearchService

log = get_logger(__name__)

#: How long to wait on the queue before checking whether the client is still
#: there. Short enough that a cancelled request is noticed promptly, long
#: enough not to spin.
_POLL_SECONDS = 0.5


class ResearchHandler(research_pb2_grpc.ResearchServiceServicer):
    """Serves BuildFactSheet."""

    def __init__(self, service: ResearchService) -> None:
        self._service = service

    def BuildFactSheet(
        self,
        request: research_pb2.BuildFactSheetRequest,
        context: grpc.ServicerContext,
    ) -> Iterator[research_pb2.BuildFactSheetResponse]:
        trace_id = trace_id_from_metadata(context.invocation_metadata())
        bind_trace_id(trace_id)
        log.info("research requested", video_id=request.video_id, topic=request.topic)

        events: queue.Queue[tuple[str, Any]] = queue.Queue()
        done = object()

        def work() -> None:
            # Re-bind the trace id: contextvars do not cross a thread boundary,
            # so without this the worker's log lines lose their correlation id.
            bind_trace_id(trace_id)
            try:
                result = self._service.build(
                    video_id=request.video_id,
                    topic=request.topic,
                    extra_urls=list(request.extra_urls),
                    min_facts=request.min_facts,
                    progress=lambda stage, percent: events.put(("progress", (stage, percent))),
                )
                events.put(("result", result))
            except RewindError as exc:
                events.put(("failure", exc))
            except Exception as exc:
                log.exception("research crashed", video_id=request.video_id)
                events.put(("crash", exc))
            finally:
                events.put(("done", done))

        # Not a daemon thread: if the process is shutting down, letting an
        # in-flight research finish writing facts.json is better than leaving a
        # half-written file behind (SPEC.md 13.3).
        thread = threading.Thread(target=work, name=f"research-{request.video_id}")
        thread.start()

        yield _progress("starting", 0.01)

        while True:
            try:
                kind, payload = events.get(timeout=_POLL_SECONDS)
            except queue.Empty:
                # Nothing yet. If the caller has gone away there is no point
                # continuing to compute for it.
                if not context.is_active():
                    log.warning("client cancelled research", video_id=request.video_id)
                    return
                continue

            if kind == "done":
                break

            message = _to_response(kind, payload)
            if message is not None:
                yield message

        thread.join(timeout=5)


def _to_response(kind: str, payload: Any) -> research_pb2.BuildFactSheetResponse | None:
    """Map one worker event to a wire message.

    Split out from the loop so the streaming mechanics and the message shapes
    can each be read on their own (SPEC.md 14.4, complexity).
    """
    if kind == "progress":
        stage, percent = payload
        return _progress(stage, percent)

    if kind == "result":
        return _result(payload)

    if kind == "failure":
        exc: RewindError = payload
        log.warning("research failed", code=exc.code)
        return research_pb2.BuildFactSheetResponse(
            failure=common_pb2.Failure(
                code=exc.code,
                message=exc.message,
                retryable=exc.retryable,
            )
        )

    if kind == "crash":
        # An unexpected failure is still a Failure event rather than a gRPC
        # error: Go's job record should carry the reason, and a stream that
        # dies abruptly tells it nothing useful.
        return research_pb2.BuildFactSheetResponse(
            failure=common_pb2.Failure(
                code="INTERNAL",
                message=f"unexpected error during research: {payload}",
                retryable=False,
            )
        )

    return None


def _progress(stage: str, percent: float) -> research_pb2.BuildFactSheetResponse:
    return research_pb2.BuildFactSheetResponse(
        progress=common_pb2.Progress(stage=stage, percent=percent)
    )


def _result(result: ResearchResult) -> research_pb2.BuildFactSheetResponse:
    return research_pb2.BuildFactSheetResponse(
        result=research_pb2.FactSheet(
            topic=result.topic,
            facts=[_to_proto_fact(f) for f in result.facts],
            sources=[_to_proto_source(d) for d in result.documents],
            facts_json_path=result.facts_json_path,
            candidates_extracted=result.candidates_extracted,
            candidates_rejected=result.candidates_rejected,
            rejections=result.rejections,
            format=result.format_name,
            group_noun=result.group_noun,
            min_items=result.min_items,
            min_groups=result.min_groups,
        )
    )


def _to_proto_fact(fact: Fact) -> research_pb2.Fact:
    return research_pb2.Fact(
        id=fact.id,
        label=fact.label,
        sort_key=fact.sort_key,
        context=fact.context,
        group=fact.group,
        claim=fact.claim,
        evidence=fact.evidence,
        source_url=fact.source_url,
        source_title=fact.source_title,
        confidence=fact.confidence,
        conflict=fact.conflict,
        approved=fact.approved,
        match_score=fact.match_score,
    )


def _to_proto_source(document: Document) -> research_pb2.SourceDocument:
    return research_pb2.SourceDocument(
        url=document.url,
        title=document.title,
        fetcher=document.fetcher,
        char_count=document.char_count,
    )
