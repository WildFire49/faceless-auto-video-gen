// Package pipeline holds the Strategy + Registry that drives the pipeline
// (SPEC.md 14.3).
//
// LAYER 2 (service) of SPEC.md 14.1.
//
// Each module from M2 onward contributes ONE file under steps/ that registers
// itself. Adding the voice step in M5 means writing steps/voice.go and nothing
// else: the runner, the orchestrator, the CLI and the dashboard are untouched
// (SPEC.md 14.2).
//
// THE INVARIANT: a Step declares the status it moves a video INTO, and that
// status is always reached through domain.Transition. Transition cannot
// perform a gate crossing, so no step -- however buggy -- can approve a gate.
package pipeline

import (
	"context"
	"fmt"
	"sort"
	"sync"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
)

// Progress is reported by a step while it works.
type Progress struct {
	Stage   string
	Percent float64
	Current int
	Total   int
}

// ProgressFn receives progress events. Steps call it; the runner forwards to
// the job record, which the dashboard polls.
type ProgressFn func(Progress)

// Step is one unit of pipeline work.
//
// Small on purpose (SPEC.md 14.4): a step knows what it needs and how to do
// its job, and nothing about state, gates, jobs or transactions.
//
// A step spans THREE statuses, mirroring how SPEC.md 2.3 is written:
//
//	queued  --From-->  researching  --Running-->  facts_ready  --To
//	(resting)          (working)                  (ready for a human)
//
// The runner moves the video From -> Running before starting, so the queue
// shows work in progress, and Running -> To when it succeeds. Declaring all
// three means a crash mid-step is recognisable: a video sitting in a Running
// status with nothing running is precisely what crash recovery looks for.
type Step interface {
	// From is the resting status a video must be in for this step to pick up.
	From() domain.Status
	// Running is the in-progress status held while the step works.
	Running() domain.Status
	// To is the status a successful run finishes in.
	To() domain.Status
	// Run does the work. It must be idempotent: a video whose output already
	// exists should return quickly rather than redo it (SPEC.md 13.3).
	Run(ctx context.Context, v *domain.Video, report ProgressFn) error
}

// Registry maps a starting status to the step that handles it.
type Registry struct {
	mu    sync.RWMutex
	steps map[domain.Status]Step
}

// NewRegistry returns an empty registry.
func NewRegistry() *Registry {
	return &Registry{steps: make(map[domain.Status]Step)}
}

// Register adds a step.
//
// Returns an error rather than panicking, and validates the declared
// transition: a step claiming a move the state machine forbids is a bug that
// should surface at startup, when it is one line to fix, not mid-render.
func (r *Registry) Register(s Step) error {
	if s == nil {
		return fmt.Errorf("pipeline: cannot register a nil step")
	}

	from, running, to := s.From(), s.Running(), s.To()

	// Both legs must be legal automatic transitions. Checking at registration
	// means a bad step fails at startup, when it is one line to fix, rather
	// than halfway through a render.
	for _, leg := range [][2]domain.Status{{from, running}, {running, to}} {
		if domain.CanTransition(leg[0], leg[1]) {
			continue
		}
		// The likeliest cause is a step trying to cross a gate, which is
		// exactly what must never be possible.
		if g, waiting := domain.GateFor(leg[0]); waiting {
			return fmt.Errorf(
				"pipeline: step %s -> %s crosses %s; a step can never approve a gate",
				leg[0], leg[1], g)
		}
		return fmt.Errorf("pipeline: step declares an illegal transition %s -> %s", leg[0], leg[1])
	}

	r.mu.Lock()
	defer r.mu.Unlock()

	if existing, taken := r.steps[from]; taken {
		return fmt.Errorf("pipeline: %s is already handled by %T", from, existing)
	}
	r.steps[from] = s
	return nil
}

// MustRegister is Register for composition roots, where a failure means the
// binary is misbuilt and should not start.
func (r *Registry) MustRegister(s Step) {
	if err := r.Register(s); err != nil {
		panic(err)
	}
}

// For returns the step that handles a status.
func (r *Registry) For(status domain.Status) (Step, bool) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	s, ok := r.steps[status]
	return s, ok
}

// RunningStatuses lists the in-progress statuses of every registered step.
//
// Crash recovery uses this: a video in one of these statuses when the process
// starts was interrupted, because nothing survives a restart (SPEC.md 13.3).
// Derived from the registered steps rather than hard-coded, so it can never
// fall out of step with what the pipeline can actually do.
func (r *Registry) RunningStatuses() []domain.Status {
	r.mu.RLock()
	defer r.mu.RUnlock()

	out := make([]domain.Status, 0, len(r.steps))
	for _, s := range r.steps {
		out = append(out, s.Running())
	}
	sort.Slice(out, func(i, j int) bool { return out[i] < out[j] })
	return out
}

// Handled lists the statuses this registry can act on, sorted for stable
// output in logs and diagnostics.
func (r *Registry) Handled() []domain.Status {
	r.mu.RLock()
	defer r.mu.RUnlock()

	out := make([]domain.Status, 0, len(r.steps))
	for status := range r.steps {
		out = append(out, status)
	}
	sort.Slice(out, func(i, j int) bool { return out[i] < out[j] })
	return out
}
