// Package clock provides the real and fake implementations of domain.Clock.
//
// LAYER 6 (platform / cross-cutting) of SPEC.md 14.1. Note the name: this is
// not a `utils` bucket. Every file under platform/ has one job and is named
// after it, so nothing ever becomes a grab-bag that everything imports.
package clock

import (
	"time"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
)

// System is the real clock, backed by the standard library.
type System struct{}

// New returns the real clock.
func New() System { return System{} }

// Now implements domain.Clock.
func (System) Now() time.Time { return time.Now() }

// Since implements domain.Clock.
func (System) Since(t time.Time) time.Duration { return time.Since(t) }

// Fake is a clock tests control, so latency assertions are deterministic
// instead of flaky. It advances only when told to.
type Fake struct {
	Current time.Time
	// Step is added to Current on every call to Since, which lets a test make
	// a measured duration exactly predictable.
	Step time.Duration
}

// NewFake returns a Fake pinned to a fixed instant, with each measurement
// reporting exactly step.
func NewFake(at time.Time, step time.Duration) *Fake {
	return &Fake{Current: at, Step: step}
}

// Now implements domain.Clock.
func (f *Fake) Now() time.Time { return f.Current }

// Since implements domain.Clock.
func (f *Fake) Since(time.Time) time.Duration { return f.Step }

// Compile-time proof that both types satisfy the port. Go interfaces are
// implicit, so this line is how you assert the contract without waiting for a
// call site to break (SPEC.md Appendix A.1, point 3).
var (
	_ domain.Clock = System{}
	_ domain.Clock = (*Fake)(nil)
)
