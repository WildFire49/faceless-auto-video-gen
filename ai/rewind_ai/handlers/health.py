"""gRPC servicer for rewind.v1.HealthService.

LAYER 3 (transport) of SPEC.md 14.1. Handlers here may only:

    read the request -> call one service method -> map the result back

No business logic lives in this package. All the real work is in
``health.service``, which is an ordinary class that tests call directly
without gRPC anywhere in sight (SPEC.md 14.4, "no logic in transport").
"""

from __future__ import annotations

import grpc

from rewind.v1 import health_pb2, health_pb2_grpc
from rewind_ai.core.logging import bind_trace_id, get_logger, trace_id_from_metadata
from rewind_ai.health.base import ProbeResult, Status
from rewind_ai.health.service import HealthChecker

log = get_logger(__name__)

#: Domain status -> wire enum. Translation lives at the edge so that the
#: health module never imports protobuf.
_STATUS_TO_PROTO: dict[Status, health_pb2.HealthStatus.ValueType] = {
    Status.UNKNOWN: health_pb2.HEALTH_STATUS_UNSPECIFIED,
    Status.OK: health_pb2.HEALTH_STATUS_OK,
    Status.DEGRADED: health_pb2.HEALTH_STATUS_DEGRADED,
    Status.DOWN: health_pb2.HEALTH_STATUS_DOWN,
}


class HealthHandler(health_pb2_grpc.HealthServiceServicer):
    """Serves Check by delegating to HealthChecker."""

    def __init__(self, checker: HealthChecker) -> None:
        # Constructor injection: the handler is handed its use case rather
        # than constructing one, so tests supply a checker with fake probes.
        self._checker = checker

    def Check(
        self,
        request: health_pb2.CheckRequest,
        context: grpc.ServicerContext,
    ) -> health_pb2.CheckResponse:
        """Report worker health.

        Deliberately does not catch exceptions: HealthChecker already contains
        per-probe failures, so anything escaping here is a genuine bug that
        should surface as a gRPC error rather than be reported as healthy.
        """
        bind_trace_id(trace_id_from_metadata(context.invocation_metadata()))

        report = self._checker.check(deep=request.deep)
        log.info("health check", deep=request.deep, status=report.status.value)

        return health_pb2.CheckResponse(
            status=_STATUS_TO_PROTO[report.status],
            version=report.version,
            dependencies=[_to_proto_dependency(d) for d in report.dependencies],
        )


def _to_proto_dependency(result: ProbeResult) -> health_pb2.Dependency:
    return health_pb2.Dependency(
        name=result.name,
        status=_STATUS_TO_PROTO[result.status],
        detail=result.detail,
    )
