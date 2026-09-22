package service_test

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/adapter/aifake"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/platform/buildinfo"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/platform/clock"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/service"
)

// These tests are the point of the whole layering exercise: they exercise the
// real use case with no gRPC connection, no Python process, no GPU and no
// network. The fake adapter is injected exactly where the real one goes.

var testTime = time.Date(2026, 9, 22, 12, 0, 0, 0, time.UTC)

func newService(ai domain.AIEngine) *service.HealthService {
	return service.NewHealthService(ai, clock.NewFake(testTime, 42*time.Millisecond), buildinfo.Static("test"))
}

func TestGetSystemHealth(t *testing.T) {
	t.Parallel()

	// Table-driven, as the Go convention and SPEC.md 10 require: one row per
	// behaviour, so adding a case means adding data rather than code.
	tests := []struct {
		name       string
		engine     *aifake.Engine
		wantSystem domain.HealthStatus
		wantAI     domain.HealthStatus
	}{
		{
			name:       "everything up",
			engine:     aifake.NewHealthy(),
			wantSystem: domain.HealthOK,
			wantAI:     domain.HealthOK,
		},
		{
			// The case that matters most: the dashboard must still render when
			// the Python worker is not running, so this is DOWN, not an error.
			name:       "ai worker stopped",
			engine:     aifake.NewDown("connection refused"),
			wantSystem: domain.HealthDown,
			wantAI:     domain.HealthDown,
		},
		{
			name: "ai worker degraded drags the system down to degraded",
			engine: &aifake.Engine{
				Health: domain.ComponentHealth{Status: domain.HealthDegraded, Detail: "model not pulled"},
			},
			wantSystem: domain.HealthDegraded,
			wantAI:     domain.HealthDegraded,
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			t.Parallel()

			got, err := newService(tc.engine).GetSystemHealth(context.Background(), false)
			if err != nil {
				t.Fatalf("GetSystemHealth() returned error: %v", err)
			}
			if got.Status != tc.wantSystem {
				t.Errorf("system status = %q, want %q", got.Status, tc.wantSystem)
			}
			if got.AI.Status != tc.wantAI {
				t.Errorf("ai status = %q, want %q", got.AI.Status, tc.wantAI)
			}
			if got.API.Status != domain.HealthOK {
				t.Errorf("api status = %q, want %q (we are running, so it is up)", got.API.Status, domain.HealthOK)
			}
			if got.API.Version != "test" {
				t.Errorf("api version = %q, want %q", got.API.Version, "test")
			}
			if got.AI.Name != "ai" {
				t.Errorf("ai component name = %q, want %q", got.AI.Name, "ai")
			}
			if got.AI.Latency != 42*time.Millisecond {
				t.Errorf("ai latency = %v, want 42ms from the fake clock", got.AI.Latency)
			}
		})
	}
}

func TestGetSystemHealthForwardsDeepFlag(t *testing.T) {
	t.Parallel()

	// A dashboard poll must stay cheap; only `rewind doctor` asks for the
	// expensive probe. Dropping this flag would be silent and slow, so it is
	// asserted explicitly.
	engine := aifake.NewHealthy()
	if _, err := newService(engine).GetSystemHealth(context.Background(), true); err != nil {
		t.Fatalf("GetSystemHealth() returned error: %v", err)
	}
	if want := []bool{true}; len(engine.DeepCalls) != 1 || engine.DeepCalls[0] != want[0] {
		t.Errorf("deep flag forwarded as %v, want %v", engine.DeepCalls, want)
	}
}

func TestGetSystemHealthPropagatesCallerErrors(t *testing.T) {
	t.Parallel()

	// An engine error is the caller's problem (cancelled context, bad wiring),
	// as distinct from a DOWN worker, which is a normal condition.
	sentinel := errors.New("context cancelled")
	_, err := newService(&aifake.Engine{Err: sentinel}).GetSystemHealth(context.Background(), false)
	if !errors.Is(err, sentinel) {
		t.Fatalf("error = %v, want it to wrap %v", err, sentinel)
	}
}

func TestWorstOf(t *testing.T) {
	t.Parallel()

	tests := []struct {
		name string
		in   []domain.HealthStatus
		want domain.HealthStatus
	}{
		{"no inputs is unknown, never a misleading ok", nil, domain.HealthUnknown},
		{"all ok", []domain.HealthStatus{domain.HealthOK, domain.HealthOK}, domain.HealthOK},
		{"down beats ok", []domain.HealthStatus{domain.HealthOK, domain.HealthDown}, domain.HealthDown},
		{"down beats degraded", []domain.HealthStatus{domain.HealthDegraded, domain.HealthDown}, domain.HealthDown},
		{"degraded beats ok", []domain.HealthStatus{domain.HealthOK, domain.HealthDegraded}, domain.HealthDegraded},
		{"unknown beats degraded", []domain.HealthStatus{domain.HealthDegraded, domain.HealthUnknown}, domain.HealthUnknown},
		{"unrecognised status is treated as unknown", []domain.HealthStatus{domain.HealthOK, domain.HealthStatus("bogus")}, domain.HealthUnknown},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			t.Parallel()
			if got := domain.WorstOf(tc.in...); got != tc.want {
				t.Errorf("WorstOf(%v) = %q, want %q", tc.in, got, tc.want)
			}
		})
	}
}
