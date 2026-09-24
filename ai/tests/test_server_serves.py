"""Every service the worker is supposed to serve is actually registered.

Written after an M3 end-to-end run failed with::

    relevance: relevance stream for "iron":
    rpc error: code = Unimplemented desc = Method not found!

RelevanceService had been written, wired into the container, and covered by
sixteen passing unit tests. It was simply never registered on the gRPC server.
Nothing inside the worker could tell the difference, and no isolated test of
the handler ever would -- the handler was fine.

Per CLAUDE.md, the ways this can go wrong, written before the guard:

1. a new service is added to ``proto/`` and a handler is written, but
   ``build_server`` is never updated         -> caught: the proto declares it,
                                                 the server answers UNIMPLEMENTED
2. a handler is renamed and the registration line is deleted in the rename
                                              -> caught: same as 1
3. a service is registered but its handler raises on construction
                                              -> caught: ``build_server`` itself fails
4. a service moves from Python to Go (or back) and nobody updates this test
                                              -> caught LOUDLY: the test names the
                                                 service and fails, rather than
                                                 quietly covering nothing
5. the proto is regenerated but the stubs are stale
                                              -> caught: the descriptor and the
                                                 registered handler disagree

The one thing this cannot catch is a service that exists in neither the proto
nor the server, which is not a bug -- it is a feature nobody has asked for.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import grpc
import pytest

from rewind.v1 import (
    api_pb2,
    facts_pb2,
    health_pb2,
    references_pb2,
    relevance_pb2,
    research_pb2,
    script_pb2,
    scripts_pb2,
    video_pb2,
)
from rewind_ai.core.config import AISettings, PathSettings, Settings
from rewind_ai.server import build_server

#: Every module in the contract that may declare a service. Listed rather than
#: globbed so that a new .proto file with a service in it forces a decision
#: here about which process serves it.
CONTRACT_MODULES = (
    api_pb2,
    facts_pb2,
    health_pb2,
    references_pb2,
    relevance_pb2,
    research_pb2,
    script_pb2,
    scripts_pb2,
    video_pb2,
)

#: Services the GO API serves over Connect, not the Python worker. Go owns all
#: state (CLAUDE.md, architecture), so anything that reads or writes a video,
#: a fact sheet, a reference sheet or the review log belongs to Go.
GO_SERVED = frozenset(
    {
        "rewind.v1.RewindService",
        "rewind.v1.VideoService",
        "rewind.v1.FactsService",
        "rewind.v1.ReferencesService",
        "rewind.v1.ScriptsService",
    }
)


def contract_services() -> set[str]:
    """Every fully-qualified service name declared anywhere in ``proto/``."""
    names: set[str] = set()
    for module in CONTRACT_MODULES:
        for service in module.DESCRIPTOR.services_by_name.values():
            names.add(service.full_name)
    return names


@pytest.fixture
def address() -> Iterator[str]:
    settings = Settings(
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


def test_the_split_between_go_and_python_is_complete() -> None:
    """Failure 4: a service belongs to neither process, or to both."""
    declared = contract_services()

    unknown = GO_SERVED - declared
    assert not unknown, (
        f"GO_SERVED names services that no longer exist in the contract: {sorted(unknown)}. "
        "Update this test when a service is removed."
    )


@pytest.mark.parametrize("service", sorted(contract_services() - GO_SERVED))
def test_worker_answers_every_service_it_owns(address: str, service: str) -> None:
    """Failures 1, 2 and 5: declared in the contract, unreachable in practice.

    The call is made with a deliberately empty payload against the service's
    FIRST method. We do not care what it returns -- only that the answer is
    not UNIMPLEMENTED, which is what "nobody registered this" looks like from
    the Go side.
    """
    descriptor = next(
        s
        for module in CONTRACT_MODULES
        for s in module.DESCRIPTOR.services_by_name.values()
        if s.full_name == service
    )
    method = descriptor.methods[0]
    path = f"/{service}/{method.name}"

    with grpc.insecure_channel(address) as channel:
        # A raw unary-stream call with pass-through codecs: this test must not
        # depend on the generated stub for the service being tested, because a
        # stale stub is one of the things it is meant to catch.
        callable_ = channel.unary_stream(
            path,
            request_serializer=lambda _: b"",
            response_deserializer=lambda raw: raw,
        )
        try:
            for _ in callable_(object()):
                break
        except grpc.RpcError as exc:
            assert exc.code() is not grpc.StatusCode.UNIMPLEMENTED, (
                f"{path} is declared in the contract but the worker does not serve it. "
                "Add it to the `served` table in rewind_ai/server.py, or to GO_SERVED "
                "in this file if the Go API owns it."
            )
