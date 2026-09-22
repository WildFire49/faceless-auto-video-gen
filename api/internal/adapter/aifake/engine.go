// Package aifake is an in-memory implementation of domain.AIEngine.
//
// LAYER 4 (adapter) of SPEC.md 14.1, and the Null Object / Fake pattern of
// 14.3. It exists so that:
//
//  1. `go test ./...` passes with the Python worker stopped, on CI with no GPU.
//  2. `rewind-api --fake-ai` runs the dashboard for UI work without Python.
//
// It is a real implementation, not a mock framework: behaviour is set on the
// struct, so tests read as data rather than as expectation scripts.
package aifake

import (
	"context"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
)

// Engine implements domain.AIEngine with canned answers.
type Engine struct {
	// Health is returned by CheckHealth. The zero value is deliberately not
	// useful -- call NewHealthy() rather than relying on it -- so a test that
	// forgets to set up its fake fails loudly instead of silently passing.
	Health domain.ComponentHealth
	// Err, when set, is returned instead of Health. Use it to exercise the
	// caller's error path.
	Err error
	// DeepCalls records the `deep` argument of every CheckHealth call, so a
	// test can assert the flag was forwarded rather than dropped.
	DeepCalls []bool
}

// NewHealthy returns a fake worker that reports itself fully operational.
func NewHealthy() *Engine {
	return &Engine{
		Health: domain.ComponentHealth{
			Status:  domain.StatusOK,
			Version: "fake",
		},
	}
}

// NewDown returns a fake worker that reports itself unreachable, which is what
// the real adapter does when the Python process is not running.
func NewDown(detail string) *Engine {
	return &Engine{
		Health: domain.ComponentHealth{
			Status: domain.StatusDown,
			Detail: detail,
		},
	}
}

// CheckHealth implements domain.AIEngine.
func (e *Engine) CheckHealth(ctx context.Context, deep bool) (domain.ComponentHealth, error) {
	e.DeepCalls = append(e.DeepCalls, deep)
	if e.Err != nil {
		return domain.ComponentHealth{}, e.Err
	}
	// Respect cancellation even in the fake, so tests of context handling are
	// meaningful rather than accidentally passing.
	if err := ctx.Err(); err != nil {
		return domain.ComponentHealth{}, err
	}
	return e.Health, nil
}
