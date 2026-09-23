"""gRPC servicer for rewind.v1.RelevanceService.

LAYER 3 (transport) of SPEC.md 14.1: unwrap, call one service method, wrap the
result. All the real work is in ``relevance.service``.

The streaming shape is the same thread-and-queue bridge as the research
handler, and for the same reason: collecting progress and yielding it after
the work finishes looks identical and gives a dead progress bar.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Iterator
from typing import Any

import grpc

from rewind.v1 import common_pb2, relevance_pb2, relevance_pb2_grpc
from rewind_ai.core.errors import RewindError
from rewind_ai.core.logging import bind_trace_id, get_logger, trace_id_from_metadata
from rewind_ai.relevance.bank import TrendCache
from rewind_ai.relevance.base import Kind, Proposal, RelevanceResult
from rewind_ai.relevance.service import ApprovedFact, RelevanceService

log = get_logger(__name__)

_POLL_SECONDS = 0.5

_KIND_TO_PROTO: dict[Kind, relevance_pb2.ReferenceKind.ValueType] = {
    Kind.EVERGREEN: relevance_pb2.REFERENCE_KIND_EVERGREEN,
    Kind.HOT: relevance_pb2.REFERENCE_KIND_HOT,
    Kind.MANUAL: relevance_pb2.REFERENCE_KIND_MANUAL,
}


class RelevanceHandler(relevance_pb2_grpc.RelevanceServiceServicer):
    """Serves ProposeReferences and ScanTrends."""

    def __init__(self, service: RelevanceService, trends: TrendCache) -> None:
        self._service = service
        self._trends = trends

    def ProposeReferences(
        self,
        request: relevance_pb2.ProposeReferencesRequest,
        context: grpc.ServicerContext,
    ) -> Iterator[relevance_pb2.ProposeReferencesResponse]:
        trace_id = trace_id_from_metadata(context.invocation_metadata())
        bind_trace_id(trace_id)
        log.info(
            "references requested",
            video_id=request.video_id,
            topic=request.topic,
            facts=len(request.facts),
        )

        facts = [
            ApprovedFact(id=f.id, label=f.label, claim=f.claim, group=f.group)
            for f in request.facts
        ]

        events: queue.Queue[tuple[str, Any]] = queue.Queue()

        def work() -> None:
            # contextvars do not cross a thread boundary, so without this the
            # worker's log lines lose their correlation id.
            bind_trace_id(trace_id)
            try:
                result = self._service.propose(
                    video_id=request.video_id,
                    topic=request.topic,
                    facts=facts,
                    max_proposals=request.max_proposals or None,
                    progress=lambda stage, pct: events.put(("progress", (stage, pct))),
                )
                events.put(("result", result))
            except RewindError as exc:
                events.put(("failure", exc))
            except Exception as exc:
                log.exception("relevance crashed", video_id=request.video_id)
                events.put(("crash", exc))
            finally:
                events.put(("done", None))

        thread = threading.Thread(target=work, name=f"relevance-{request.video_id}")
        thread.start()

        yield _progress("starting", 0.01)

        while True:
            try:
                kind, payload = events.get(timeout=_POLL_SECONDS)
            except queue.Empty:
                if not context.is_active():
                    log.warning("client cancelled relevance", video_id=request.video_id)
                    return
                continue

            if kind == "done":
                break

            message = _to_response(kind, payload)
            if message is not None:
                yield message

        thread.join(timeout=5)

    def ScanTrends(
        self,
        request: relevance_pb2.ScanTrendsRequest,
        context: grpc.ServicerContext,
    ) -> relevance_pb2.ScanTrendsResponse:
        bind_trace_id(trace_id_from_metadata(context.invocation_metadata()))

        before = self._trends.get() if not request.force else None
        cached = self._trends.get(force=request.force)

        return relevance_pb2.ScanTrendsResponse(
            term_count=len(cached.trends),
            sources=cached.sources,
            fetched_at=cached.fetched_at.isoformat(),
            from_cache=before is not None and before.fetched_at == cached.fetched_at,
        )


def _to_response(kind: str, payload: Any) -> relevance_pb2.ProposeReferencesResponse | None:
    """Map one worker event to a wire message."""
    if kind == "progress":
        stage, percent = payload
        return _progress(stage, percent)

    if kind == "result":
        return _result(payload)

    if kind == "failure":
        exc: RewindError = payload
        log.warning("relevance failed", code=exc.code)
        return relevance_pb2.ProposeReferencesResponse(
            failure=common_pb2.Failure(code=exc.code, message=exc.message, retryable=exc.retryable)
        )

    if kind == "crash":
        return relevance_pb2.ProposeReferencesResponse(
            failure=common_pb2.Failure(
                code="INTERNAL",
                message=f"unexpected error while proposing references: {payload}",
                retryable=False,
            )
        )

    return None


def _progress(stage: str, percent: float) -> relevance_pb2.ProposeReferencesResponse:
    return relevance_pb2.ProposeReferencesResponse(
        progress=common_pb2.Progress(stage=stage, percent=percent)
    )


def _result(result: RelevanceResult) -> relevance_pb2.ProposeReferencesResponse:
    return relevance_pb2.ProposeReferencesResponse(
        result=relevance_pb2.ReferenceSheet(
            topic=result.topic,
            proposals=[_to_proto(p) for p in result.proposals],
            references_json_path=result.references_json_path,
            candidates_generated=result.candidates_generated,
            candidates_rejected=result.candidates_rejected,
            rejections=result.rejections,
            max_selectable=result.max_selectable,
            trend_sources=result.trend_sources,
            trends_fetched_at=result.trends_fetched_at,
        )
    )


def _to_proto(proposal: Proposal) -> relevance_pb2.Proposal:
    return relevance_pb2.Proposal(
        id=proposal.id,
        reference=proposal.reference,
        kind=_KIND_TO_PROTO.get(proposal.kind, relevance_pb2.REFERENCE_KIND_UNSPECIFIED),
        linked_fact_id=proposal.linked_fact_id,
        comparison=proposal.comparison,
        why_funny=proposal.why_funny,
        accuracy_note=proposal.accuracy_note,
        fresh_until=proposal.fresh_until.isoformat() if proposal.fresh_until else "",
        source=proposal.source,
        selected=proposal.selected,
    )
