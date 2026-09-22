package domain

import (
	"context"
	"time"
)

// This file holds the PORTS: the interfaces the core declares and the outside
// world implements (SPEC.md 14.3, Ports & Adapters).
//
// These are the plug points. Every interface here has at least two
// implementations -- a real one in adapter/, and a fake one used by tests --
// which is what lets `go test ./...` pass with the Python worker stopped.
//
// Interfaces stay small (1-3 methods). A large interface here is a sign that a
// use case is doing too much.

// AIEngine is everything Go needs from the Python AI worker.
//
// In M0 it has one method. Each later milestone adds one more (BuildFactSheet,
// WriteScript, SynthesizeNarration...), and each is implemented twice: once in
// adapter/aigrpc over real gRPC, once in adapter/aifake in memory.
type AIEngine interface {
	// CheckHealth probes the worker. A worker that is not running is NOT an
	// error from the caller's point of view -- it is a DOWN component -- so
	// implementations return a ComponentHealth with StatusDown rather than a
	// non-nil error when the connection simply fails. An error is reserved for
	// the caller's own mistakes, such as a cancelled context.
	CheckHealth(ctx context.Context, deep bool) (ComponentHealth, error)
}

// Clock exists so time-dependent behaviour is testable without sleeping.
// The real implementation wraps time.Now; the fake one is controlled by tests.
type Clock interface {
	Now() time.Time
	// Since is a convenience for measuring latency without two Now calls at
	// the call site.
	Since(t time.Time) time.Duration
}

// BuildInfo describes the running binary, for the dashboard footer and for
// bug reports. It is a port rather than a constant so tests get stable output.
type BuildInfo interface {
	Version() string
}
