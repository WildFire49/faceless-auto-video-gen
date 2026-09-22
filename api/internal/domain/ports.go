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
	// implementations return a ComponentHealth with HealthDown rather than a
	// non-nil error when the connection simply fails. An error is reserved for
	// the caller's own mistakes, such as a cancelled context.
	CheckHealth(ctx context.Context, deep bool) (ComponentHealth, error)

	// BuildFactSheet researches a topic and writes facts.json into the
	// video's project folder.
	//
	// The worker streams progress while it works; `report` is called for each
	// event. A research failure is returned as an error -- unlike a health
	// check, a step that cannot do its job IS a failure, and Go turns it into
	// status=error with a resume point.
	BuildFactSheet(ctx context.Context, req FactSheetRequest, report func(Progress)) (*FactSheetResult, error)
}

// Progress is one update from a long-running worker call.
type Progress struct {
	Stage   string
	Percent float64
	Current int
	Total   int
}

// FactSheetRequest is what the worker needs to research a topic.
type FactSheetRequest struct {
	VideoID   string
	Topic     string
	ExtraURLs []string
	MinFacts  int
}

// FactSheetResult summarises what research produced.
//
// It carries counts and a path, not the facts themselves: the fact sheet is a
// file in the project folder, and passing it through gRPC as well would mean
// two copies that can disagree (SPEC.md 2.5, "paths, not bytes").
type FactSheetResult struct {
	Topic               string
	FactCount           int
	FactsJSONPath       string
	CandidatesExtracted int
	CandidatesRejected  int
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

// VideoRepo stores videos. All SQL lives behind this interface; nothing above
// the adapter layer ever sees a query.
type VideoRepo interface {
	// Create stores a new video. Returns ErrAlreadyExists if the id is taken.
	Create(ctx context.Context, v *Video) error
	// Get returns one video, or ErrNotFound.
	Get(ctx context.Context, id string) (*Video, error)
	// List returns videos matching the filter, ordered for the queue view.
	List(ctx context.Context, f VideoFilter) ([]*Video, error)
	// Update writes a video back. Returns ErrNotFound if it has vanished.
	Update(ctx context.Context, v *Video) error
}

// VideoFilter narrows a List. The zero value means "everything".
type VideoFilter struct {
	// Statuses, when non-empty, restricts results to these statuses.
	Statuses []Status
	// AwaitingReview restricts results to videos sitting at a gate -- the
	// "needs my review" view that is the dashboard's default.
	AwaitingReview bool
}

// ReviewLog is the append-only record of human decisions. It is the project's
// evidence of human creative involvement (SPEC.md 8.4), so there is
// deliberately no Update and no Delete.
type ReviewLog interface {
	Append(ctx context.Context, e *ReviewEntry) error
	List(ctx context.Context, videoID string) ([]*ReviewEntry, error)
}

// TxManager runs work inside a database transaction.
//
// It exists so a state change and its review-log entry commit together or not
// at all (SPEC.md 13.3) -- an approval that moved a video but lost its audit
// entry would destroy the very evidence the log is for.
//
// The returned context carries the transaction; implementations of VideoRepo
// and ReviewLog pick it up automatically, so callers just use ctx as normal.
type TxManager interface {
	WithTx(ctx context.Context, fn func(ctx context.Context) error) error
}

// IDGen produces video ids from topics. A port so tests get deterministic ids
// and so collision handling can be exercised.
type IDGen interface {
	// NewID returns an id for the topic that does not collide with an
	// existing one, consulting exists to find out.
	NewID(ctx context.Context, topic string, exists func(context.Context, string) (bool, error)) (string, error)
}
