"""The REWIND AI worker: a gRPC server that does one job when asked.

Run it with::

    rewind-ai                 # or: python -m rewind_ai.server

This process owns NO state (SPEC.md 2.4). It never touches SQLite and never
decides a video's status. It receives a request, does the work, writes its
output into ``projects/<video_id>/``, returns a result, and forgets everything.
Go decides what any of it means.
"""

from __future__ import annotations

import argparse
import signal
import sys
from concurrent import futures
from pathlib import Path
from types import FrameType

import grpc

from rewind.v1 import health_pb2_grpc
from rewind_ai.core import config, container
from rewind_ai.core.logging import configure, get_logger

log = get_logger(__name__)

#: Bounded pool. Image and video work is heavy, so unbounded concurrency would
#: exhaust VRAM rather than go faster. Raised per-service when it is warranted.
MAX_WORKERS = 8

#: How long to let in-flight RPCs finish on shutdown before dropping them.
SHUTDOWN_GRACE_SECONDS = 20.0


def build_server(settings: config.Settings, *, llm_model: str = "") -> tuple[grpc.Server, str]:
    """Construct the gRPC server. Returns the server and the bound address.

    Separated from ``main`` so tests can build a real server on an ephemeral
    port without going through argument parsing.
    """
    deps = container.build(settings, llm_model=llm_model)

    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=MAX_WORKERS),
        options=[
            ("grpc.max_send_message_length", settings.ai.max_message_bytes),
            ("grpc.max_receive_message_length", settings.ai.max_message_bytes),
        ],
    )

    # Import here rather than at module scope: handlers pull in the generated
    # stubs, and keeping that off the import path until the server is actually
    # being built keeps `python -c "import rewind_ai"` fast and side-effect free.
    from rewind_ai.handlers.health import HealthHandler

    health_pb2_grpc.add_HealthServiceServicer_to_server(HealthHandler(deps.health), server)

    # Insecure is correct ONLY because this binds loopback and the Go API is on
    # the same machine (SPEC.md 13.5). If either end ever moves off this box,
    # this becomes server.add_secure_port with real credentials.
    bound_port = server.add_insecure_port(settings.ai.grpc_addr)
    if bound_port == 0:
        raise config.ConfigError(f"could not bind {settings.ai.grpc_addr}; is it already in use?")

    host = settings.ai.host
    return server, f"{host}:{bound_port}"


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns a process exit code."""
    parser = argparse.ArgumentParser(prog="rewind-ai", description=__doc__)
    parser.add_argument("--config", type=Path, default=None, help="path to config/")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--json-logs", action="store_true", help="emit JSON instead of text")
    parser.add_argument(
        "--llm-model",
        default="",
        help="model the health probe should verify is pulled, e.g. qwen2.5:14b",
    )
    args = parser.parse_args(argv)

    configure(level=args.log_level, json_output=args.json_logs)

    try:
        settings = config.load(args.config)
        server, address = build_server(settings, llm_model=args.llm_model)
    except config.ConfigError as exc:
        # A misconfigured worker refuses to start rather than failing later,
        # halfway through a render, where the cause is much harder to see.
        log.error("startup failed", error=str(exc))
        return 1

    server.start()
    log.info("rewind-ai listening", address=address, version=container.VERSION)

    # Graceful shutdown: let in-flight work finish rather than dropping it, so
    # Ctrl-C mid-job never leaves a half-written file behind (SPEC.md 13.3).
    def handle_signal(signum: int, _frame: FrameType | None) -> None:
        log.info("shutdown signal received, draining", signal=signum)
        server.stop(SHUTDOWN_GRACE_SECONDS)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    server.wait_for_termination()
    log.info("rewind-ai stopped cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
