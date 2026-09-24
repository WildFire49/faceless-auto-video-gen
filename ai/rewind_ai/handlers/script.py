"""gRPC servicer for rewind.v1.ScriptService.

LAYER 3 (transport) of SPEC.md 14.1: unwrap, call one service method, wrap
the result. All the real work is in ``script.service``; all the rules are in
``script.rules``.
"""

from __future__ import annotations

from collections.abc import Iterator

import grpc

from rewind.v1 import common_pb2, script_pb2, script_pb2_grpc
from rewind_ai.core.logging import bind_trace_id, get_logger, trace_id_from_metadata
from rewind_ai.handlers.stream_bridge import stream
from rewind_ai.script.base import Beat, Script, ScriptFact, ScriptReference, Violation
from rewind_ai.script.service import ScriptService

log = get_logger(__name__)


class ScriptHandler(script_pb2_grpc.ScriptServiceServicer):
    """Serves GenerateScript and ValidateScript."""

    def __init__(self, service: ScriptService) -> None:
        self._service = service

    def GenerateScript(
        self,
        request: script_pb2.GenerateScriptRequest,
        context: grpc.ServicerContext,
    ) -> Iterator[script_pb2.GenerateScriptResponse]:
        trace_id = trace_id_from_metadata(context.invocation_metadata())
        bind_trace_id(trace_id)
        log.info(
            "script requested",
            video_id=request.video_id,
            topic=request.topic,
            facts=len(request.facts),
            references=len(request.references),
            has_angle=bool(request.angle.strip()),
        )

        facts = [_fact(f) for f in request.facts]
        references = [_reference(r) for r in request.references]

        yield from stream(
            name=f"script-{request.video_id}",
            trace_id=trace_id,
            context=context,
            work=lambda progress: self._service.generate(
                video_id=request.video_id,
                topic=request.topic,
                angle=request.angle,
                facts=facts,
                references=references,
                progress=progress,
            ),
            on_progress=lambda stage, pct: script_pb2.GenerateScriptResponse(
                progress=common_pb2.Progress(stage=stage, percent=pct)
            ),
            on_result=lambda script: script_pb2.GenerateScriptResponse(
                result=to_proto(script, request.video_id)
            ),
            on_failure=lambda code, message, retryable: script_pb2.GenerateScriptResponse(
                failure=common_pb2.Failure(code=code, message=message, retryable=retryable)
            ),
        )

    def ValidateScript(
        self,
        request: script_pb2.ValidateScriptRequest,
        context: grpc.ServicerContext,
    ) -> script_pb2.ValidateScriptResponse:
        bind_trace_id(trace_id_from_metadata(context.invocation_metadata()))
        violations = self._service.check(
            from_proto(request.script),
            [_fact(f) for f in request.facts],
            [_reference(r) for r in request.references],
        )
        return script_pb2.ValidateScriptResponse(violations=[_violation(v) for v in violations])


# --------------------------------------------------------------- mapping


def to_proto(script: Script, video_id: str) -> script_pb2.Script:
    return script_pb2.Script(
        title_options=script.title_options,
        chosen_title=script.chosen_title,
        description=script.description,
        hashtags=script.hashtags,
        beats=[
            script_pb2.Beat(
                n=b.n,
                role=b.role,
                year_stamp=b.year_stamp,
                voice=b.voice,
                on_screen_text=b.on_screen_text,
                visual_prompts=b.visual_prompts,
                sfx=b.sfx,
                motion=b.motion,
                emphasis_words=b.emphasis_words,
                fact_ids=b.fact_ids,
                ref_ids=b.ref_ids,
                is_punch=b.is_punch,
            )
            for b in script.beats
        ],
        sources=script.sources,
        script_json_path=f"projects/{video_id}/script.json",
        attempts=script.attempts,
        violations=[_violation(v) for v in script.violations],
    )


def from_proto(message: script_pb2.Script) -> Script:
    return Script(
        beats=[
            Beat(
                n=b.n,
                role=b.role,
                voice=b.voice,
                year_stamp=b.year_stamp,
                on_screen_text=b.on_screen_text,
                visual_prompts=list(b.visual_prompts),
                sfx=b.sfx,
                motion=b.motion,
                emphasis_words=list(b.emphasis_words),
                fact_ids=list(b.fact_ids),
                ref_ids=list(b.ref_ids),
                is_punch=b.is_punch,
            )
            for b in message.beats
        ],
        title_options=list(message.title_options),
        chosen_title=message.chosen_title,
        description=message.description,
        hashtags=list(message.hashtags),
        sources=list(message.sources),
        attempts=message.attempts,
    )


def _fact(f: script_pb2.ScriptFact) -> ScriptFact:
    return ScriptFact(
        id=f.id,
        label=f.label,
        claim=f.claim,
        evidence=f.evidence,
        context=f.context,
        source_url=f.source_url,
        group=f.group,
    )


def _reference(r: script_pb2.ScriptReference) -> ScriptReference:
    return ScriptReference(
        id=r.id, reference=r.reference, comparison=r.comparison, linked_fact_id=r.linked_fact_id
    )


def _violation(v: Violation) -> script_pb2.Violation:
    return script_pb2.Violation(rule=v.rule, beat=v.beat, message=v.message)
