"""End-to-end test of the gRPC surface.

Starts a real server on an ephemeral port and calls it with a real client, so
the wiring -- servicer registration, proto mapping, trace-id metadata -- is
exercised rather than assumed. Still needs no network, no GPU and no Ollama.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import grpc
import pytest

from rewind.v1 import health_pb2, health_pb2_grpc
from rewind_ai.core.config import AISettings, PathSettings, Settings
from rewind_ai.core.logging import TRACE_ID_KEY
from rewind_ai.server import build_server


@pytest.fixture
def address() -> Iterator[str]:
    """Run the worker on a free port for the duration of one test."""
    settings = Settings(
        # Port 0 asks the OS for any free port, so tests never collide with a
        # worker the developer already has running.
        ai=AISettings(grpc_addr="127.0.0.1:0"),
        paths=PathSettings(projects=Path("projects"), assets=Path("assets")),
        config_dir=Path("config"),
    )
    server, bound = build_server(settings)
    server.start()
    try:
        yield bound
    finally:
        server.stop(None).wait()


def test_shallow_check_reports_ok(address: str) -> None:
    with grpc.insecure_channel(address) as channel:
        client = health_pb2_grpc.HealthServiceStub(channel)
        resp = client.Check(health_pb2.CheckRequest(deep=False))

    assert resp.status == health_pb2.HEALTH_STATUS_OK
    assert resp.version
    assert list(resp.dependencies) == [], "a shallow check reports no dependencies"


def test_deep_check_reports_real_dependencies(address: str) -> None:
    with grpc.insecure_channel(address) as channel:
        client = health_pb2_grpc.HealthServiceStub(channel)
        resp = client.Check(health_pb2.CheckRequest(deep=True))

    names = {d.name for d in resp.dependencies}
    assert names >= {"ollama", "ffmpeg", "gpu"}

    # The status depends on what this machine actually has, so assert only
    # that every probe produced a real verdict rather than the zero value.
    for dep in resp.dependencies:
        assert dep.status != health_pb2.HEALTH_STATUS_UNSPECIFIED, dep.name


def test_trace_id_metadata_is_accepted(address: str) -> None:
    # Go sends this on every call so both services' logs can be correlated.
    # The worker must accept it rather than reject the unknown key.
    with grpc.insecure_channel(address) as channel:
        client = health_pb2_grpc.HealthServiceStub(channel)
        resp = client.Check(
            health_pb2.CheckRequest(deep=False),
            metadata=((TRACE_ID_KEY, "abc123"),),
        )

    assert resp.status == health_pb2.HEALTH_STATUS_OK
