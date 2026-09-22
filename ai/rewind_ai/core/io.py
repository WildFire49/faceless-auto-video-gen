"""Atomic file writes.

LAYER 1 (core) of SPEC.md 14.1.

Everything the worker produces lands in ``projects/<video_id>/``, and Go reads
those files to serve the review gates. A half-written facts.json read
mid-render would be worse than no file at all, so every write goes to a
temporary file and is renamed into place -- rename is atomic on both NTFS and
POSIX, so a reader sees either the old file or the new one, never a torn one.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def write_bytes_atomic(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` atomically, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)

    # The temporary file must share a filesystem with the destination, or the
    # rename becomes a copy and loses atomicity.
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            # Durability: without this the rename can land before the contents
            # reach disk, so a crash leaves an empty file with a valid name.
            os.fsync(handle.fileno())

        # os.replace, not Path.replace: same call, but the name makes the
        # atomic-overwrite guarantee explicit at the point it matters.
        os.replace(tmp_name, path)  # noqa: PTH105
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def write_json_atomic(path: Path, payload: Any) -> None:
    """Write ``payload`` as indented UTF-8 JSON, atomically.

    Indented and with ensure_ascii off because these files are meant to be
    opened and read by a person -- escaped unicode in a historical claim would
    be unreadable.
    """
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    write_bytes_atomic(path, text.encode("utf-8"))


def read_json(path: Path) -> Any:
    """Read a JSON file."""
    return json.loads(path.read_text(encoding="utf-8"))
