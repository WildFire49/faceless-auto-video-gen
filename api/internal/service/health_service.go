// Package service holds the use cases: the workflows the application performs.
//
// LAYER 2 of SPEC.md 14.1. It depends on domain/ and on nothing else in the
// project. It never imports a driver -- no SQL, no gRPC, no HTTP. Everything
// it needs arrives through a domain interface, injected by the constructor.
//
// That is what makes this package testable with fakes and no running services.
package service

import (
	"context"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
)

// HealthService answers "is the system working?".
//
// It is a Facade (SPEC.md 14.3): the transport layer calls one method and gets
// a finished answer. Transport never orchestrates the pieces itself.
type HealthService struct {
	ai    domain.AIEngine
	clock domain.Clock
	build domain.BuildInfo
}

// NewHealthService wires the service. Constructor injection, no globals: every
// dependency is visible in this signature, which is what lets a test pass
// fakes in. The only place that chooses real implementations is
// cmd/rewind-api/main.go (SPEC.md 14.1, rule 3).
func NewHealthService(ai domain.AIEngine, clock domain.Clock, build domain.BuildInfo) *HealthService {
	return &HealthService{ai: ai, clock: clock, build: build}
}

// GetSystemHealth reports the health of every component.
//
// A stopped AI worker is a normal, expected condition -- it yields a DOWN
// component, not an error. The dashboard must stay usable when the worker is
// not running, so the only error returned here is one the caller caused, such
// as cancelling the context.
func (s *HealthService) GetSystemHealth(ctx context.Context, deep bool) (domain.SystemHealth, error) {
	api := domain.ComponentHealth{
		Name:    "api",
		Status:  domain.StatusOK, // reached this code, so it is up by definition
		Version: s.build.Version(),
	}

	start := s.clock.Now()
	ai, err := s.ai.CheckHealth(ctx, deep)
	if err != nil {
		return domain.SystemHealth{}, err
	}
	ai.Name = "ai"
	ai.Latency = s.clock.Since(start)

	return domain.SystemHealth{
		Status: domain.WorstOf(api.Status, ai.Status),
		API:    api,
		AI:     ai,
	}, nil
}
