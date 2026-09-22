"""The error hierarchy, and how it maps to gRPC status codes.

LAYER 1 (core) of SPEC.md 14.1.

The worker reports WHAT went wrong. Go decides what that MEANS for a video's
status -- the AI worker never sets a status itself (SPEC.md 2.4). So every
error carries two things Go needs in order to decide:

* ``code``      -- a stable machine-readable label, safe to branch on
* ``retryable`` -- whether trying again could plausibly help
"""

from __future__ import annotations


class RewindError(Exception):
    """Base class for every error this worker raises deliberately."""

    #: Stable identifier, e.g. "SOURCE_UNREACHABLE". Go may branch on this, so
    #: treat it as part of the contract: do not rename one casually.
    code: str = "INTERNAL"

    #: Whether Go should retry with backoff. Infrastructure hiccups are
    #: retryable; a script that fails validation will fail identically forever.
    retryable: bool = False

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


class ConfigurationError(RewindError):
    """Something is misconfigured. Retrying will not fix it."""

    code = "CONFIGURATION"
    retryable = False


class DependencyUnavailableError(RewindError):
    """A required service is not reachable -- Ollama down, model not pulled.

    Retryable: the operator may simply need to start it.
    """

    code = "DEPENDENCY_UNAVAILABLE"
    retryable = True


class SourceUnreachableError(RewindError):
    """A research source could not be fetched. Usually transient."""

    code = "SOURCE_UNREACHABLE"
    retryable = True


class ValidationFailedError(RewindError):
    """Generated output failed its rules. Deterministic, so never retried."""

    code = "VALIDATION_FAILED"
    retryable = False
