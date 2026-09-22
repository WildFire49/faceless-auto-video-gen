package aigrpc_test

import (
	"context"
	"net"
	"testing"
	"time"

	"google.golang.org/grpc"

	rewindv1 "github.com/WildFire49/faceless-auto-video-gen/api/gen/rewind/v1"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/adapter/aigrpc"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
)

// stubWorker is a minimal in-process HealthService, so these tests exercise the
// real adapter over a real connection without needing the Python worker.
type stubWorker struct {
	rewindv1.UnimplementedHealthServiceServer
	status rewindv1.HealthStatus
}

func (s *stubWorker) Check(_ context.Context, _ *rewindv1.CheckRequest) (*rewindv1.CheckResponse, error) {
	return &rewindv1.CheckResponse{Status: s.status, Version: "stub"}, nil
}

// startWorker runs a stub worker on a free port and returns its address plus a
// stop function.
func startWorker(t *testing.T, addr string, status rewindv1.HealthStatus) (string, func()) {
	t.Helper()

	lis, err := net.Listen("tcp", addr)
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	srv := grpc.NewServer()
	rewindv1.RegisterHealthServiceServer(srv, &stubWorker{status: status})
	go func() { _ = srv.Serve(lis) }()

	return lis.Addr().String(), srv.Stop
}

func TestCheckHealthReportsDownWhenWorkerIsAbsent(t *testing.T) {
	t.Parallel()

	// Bind a port, then release it, so nothing is listening there.
	addr, stop := startWorker(t, "127.0.0.1:0", rewindv1.HealthStatus_HEALTH_STATUS_OK)
	stop()

	engine, err := aigrpc.New(aigrpc.Options{Addr: addr, HealthTimeout: 2 * time.Second})
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	defer func() { _ = engine.Close() }()

	got, err := engine.CheckHealth(context.Background(), false)
	// A stopped worker must NOT be an error: the dashboard has to stay usable
	// when Python is not running.
	if err != nil {
		t.Fatalf("CheckHealth returned an error for an absent worker: %v", err)
	}
	if got.Status != domain.StatusDown {
		t.Errorf("status = %q, want %q", got.Status, domain.StatusDown)
	}
	if got.Detail == "" {
		t.Error("expected a detail explaining why the worker is unreachable")
	}
}

// TestCheckHealthRecoversAfterWorkerRestart checks that a restarted worker is
// picked up again rather than being reported DOWN forever.
//
// SCOPE, honestly stated: this verifies that recovery happens and is prompt.
// It does NOT prove the reconnect nudge and backoff cap in the adapter are
// working, because reproducing gRPC's pathological backoff requires tens of
// seconds of continuous failure -- far too slow for a unit test. With the fix
// reverted, this test still passes (more slowly).
//
// The behaviour the fix addresses was found by running the real services:
// gRPC parks a failed channel in TransientFailure and retries on a backoff
// that grows towards two minutes, so a worker the operator had just restarted
// kept being reported DOWN and the dashboard chip stayed red long after Python
// was up. The remedy is grpc.WithConnectParams capping MaxDelay plus an
// explicit ClientConn.Connect when the channel is not usable; both live in
// engine.go and are covered by the smoke job in CI rather than here.
func TestCheckHealthRecoversAfterWorkerRestart(t *testing.T) {
	t.Parallel()

	addr, stop := startWorker(t, "127.0.0.1:0", rewindv1.HealthStatus_HEALTH_STATUS_OK)

	engine, err := aigrpc.New(aigrpc.Options{Addr: addr, HealthTimeout: 2 * time.Second})
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	defer func() { _ = engine.Close() }()

	ctx := context.Background()

	if got, _ := engine.CheckHealth(ctx, false); got.Status != domain.StatusOK {
		t.Fatalf("before restart: status = %q, want %q", got.Status, domain.StatusOK)
	}

	// Stop the worker, then poll repeatedly with pauses. Each failure grows
	// the reconnect backoff, which is the situation that used to strand the
	// channel. Enough iterations are needed to push the default backoff past
	// the recovery deadline below -- a handful of fast polls does not.
	stop()
	for range 12 {
		if got, _ := engine.CheckHealth(ctx, false); got.Status != domain.StatusDown {
			t.Fatalf("while stopped: status = %q, want %q", got.Status, domain.StatusDown)
		}
		time.Sleep(150 * time.Millisecond)
	}

	// Bring it back on the same address.
	_, stop2 := startWorker(t, addr, rewindv1.HealthStatus_HEALTH_STATUS_OK)
	defer stop2()

	// Recovery must happen within roughly one dashboard poll. This bound is
	// loose enough not to flake on a busy CI runner.
	const recoverWithin = 1500 * time.Millisecond

	start := time.Now()
	deadline := start.Add(recoverWithin)
	for time.Now().Before(deadline) {
		if got, _ := engine.CheckHealth(ctx, false); got.Status == domain.StatusOK {
			t.Logf("recovered in %v", time.Since(start))
			return
		}
		time.Sleep(50 * time.Millisecond)
	}
	t.Fatalf("worker restarted but the adapter did not recover within %v; "+
		"the reconnect nudge or the backoff cap is broken", recoverWithin)
}

func TestNewRejectsMissingAddress(t *testing.T) {
	t.Parallel()

	if _, err := aigrpc.New(aigrpc.Options{}); err == nil {
		t.Error("New with no Addr = nil error, want a configuration error")
	}
}
