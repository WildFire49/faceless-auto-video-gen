// Package logging configures structured logging and carries the trace id that
// ties one job's lines together across Go and Python (SPEC.md 13.4).
//
// LAYER 6 (platform) of SPEC.md 14.1.
package logging

import (
	"context"
	"log/slog"
	"os"
)

// TraceIDKey is the metadata key used to pass the trace id to the Python
// worker over gRPC. Both sides log under the same field name, so one grep
// across both services reconstructs a whole job.
const TraceIDKey = "x-rewind-trace-id"

type ctxKey struct{}

// New returns a logger. Text output is easier to read while developing;
// JSON is what you want when logs are being collected.
func New(level slog.Level, jsonOutput bool) *slog.Logger {
	opts := &slog.HandlerOptions{Level: level}
	var h slog.Handler
	if jsonOutput {
		h = slog.NewJSONHandler(os.Stdout, opts)
	} else {
		h = slog.NewTextHandler(os.Stdout, opts)
	}
	return slog.New(h)
}

// WithTraceID returns a context carrying the trace id.
func WithTraceID(ctx context.Context, id string) context.Context {
	return context.WithValue(ctx, ctxKey{}, id)
}

// TraceID reads the trace id from the context, or "" when absent.
func TraceID(ctx context.Context) string {
	id, _ := ctx.Value(ctxKey{}).(string)
	return id
}

// FromContext returns a logger pre-tagged with the context's trace id, so call
// sites never have to remember to add it.
func FromContext(ctx context.Context, base *slog.Logger) *slog.Logger {
	if id := TraceID(ctx); id != "" {
		return base.With(slog.String("trace_id", id))
	}
	return base
}
