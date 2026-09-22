// Package aigrpc implements domain.AIEngine by calling the Python AI worker
// over gRPC.
//
// LAYER 4 (adapter) of SPEC.md 14.1. This is the ONLY package in the Go API
// that knows gRPC exists on the worker side. Everything above it depends on
// the domain.AIEngine interface, which is why aifake can stand in for this
// package without any caller noticing.
package aigrpc

import (
	"context"
	"fmt"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"

	rewindv1 "github.com/WildFire49/faceless-auto-video-gen/api/gen/rewind/v1"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/platform/logging"
)

// Engine is a gRPC-backed AI worker client.
type Engine struct {
	conn          *grpc.ClientConn
	health        rewindv1.HealthServiceClient
	healthTimeout time.Duration
}

// Options configure the client. Everything here comes from
// config/services.yaml; nothing is hard-coded (SPEC.md 14.4).
type Options struct {
	// Addr is the worker's gRPC address, e.g. "127.0.0.1:50051".
	Addr string
	// MaxMessageBytes caps message size. We pass paths rather than media, so
	// a large message means a bug, and failing loudly is the right response.
	MaxMessageBytes int
	// HealthTimeout bounds the Check RPC.
	HealthTimeout time.Duration
}

// New creates the client.
//
// It does NOT connect eagerly: grpc.NewClient is lazy, so the API starts fine
// with the worker stopped and recovers on its own when the worker appears.
// That is deliberate -- the dashboard must be usable before Python is running.
func New(opts Options) (*Engine, error) {
	if opts.Addr == "" {
		return nil, fmt.Errorf("aigrpc: Addr is required")
	}
	if opts.MaxMessageBytes <= 0 {
		opts.MaxMessageBytes = 4 << 20
	}
	if opts.HealthTimeout <= 0 {
		opts.HealthTimeout = 5 * time.Second
	}

	conn, err := grpc.NewClient(
		opts.Addr,
		// Insecure is correct ONLY because both ends are on loopback and the
		// servers bind 127.0.0.1 (SPEC.md 13.5). If either end ever moves off
		// this machine, this line must become real TLS credentials.
		grpc.WithTransportCredentials(insecure.NewCredentials()),
		grpc.WithDefaultCallOptions(
			grpc.MaxCallRecvMsgSize(opts.MaxMessageBytes),
			grpc.MaxCallSendMsgSize(opts.MaxMessageBytes),
		),
	)
	if err != nil {
		return nil, fmt.Errorf("aigrpc: creating client for %s: %w", opts.Addr, err)
	}

	return &Engine{
		conn:          conn,
		health:        rewindv1.NewHealthServiceClient(conn),
		healthTimeout: opts.HealthTimeout,
	}, nil
}

// Close releases the connection. Called during graceful shutdown.
func (e *Engine) Close() error {
	if err := e.conn.Close(); err != nil {
		return fmt.Errorf("aigrpc: closing connection: %w", err)
	}
	return nil
}

// CheckHealth implements domain.AIEngine.
//
// A worker that is not running is reported as StatusDown, not as an error:
// "Python is stopped" is an expected state of this system, and the dashboard
// renders it rather than failing (SPEC.md 11, "Go treats AI service down as a
// normal retryable error").
func (e *Engine) CheckHealth(ctx context.Context, deep bool) (domain.ComponentHealth, error) {
	ctx, cancel := context.WithTimeout(ctx, e.healthTimeout)
	defer cancel()
	ctx = e.withTrace(ctx)

	resp, err := e.health.Check(ctx, &rewindv1.CheckRequest{Deep: deep})
	if err != nil {
		return domain.ComponentHealth{
			Status: domain.StatusDown,
			Detail: err.Error(),
		}, nil
	}

	return domain.ComponentHealth{
		Status:       fromProtoStatus(resp.GetStatus()),
		Version:      resp.GetVersion(),
		Dependencies: fromProtoDependencies(resp.GetDependencies()),
	}, nil
}

// withTrace forwards the request's trace id to Python as gRPC metadata, so one
// job's log lines can be grepped across both services (SPEC.md 13.4).
func (e *Engine) withTrace(ctx context.Context) context.Context {
	id := logging.TraceID(ctx)
	if id == "" {
		return ctx
	}
	return metadata.AppendToOutgoingContext(ctx, logging.TraceIDKey, id)
}

// fromProtoStatus maps the wire enum to the domain type. Translation lives in
// the adapter so that domain/ never imports protobuf (SPEC.md 14.1, rule 1).
func fromProtoStatus(s rewindv1.HealthStatus) domain.Status {
	switch s {
	case rewindv1.HealthStatus_HEALTH_STATUS_OK:
		return domain.StatusOK
	case rewindv1.HealthStatus_HEALTH_STATUS_DEGRADED:
		return domain.StatusDegraded
	case rewindv1.HealthStatus_HEALTH_STATUS_DOWN:
		return domain.StatusDown
	default:
		return domain.StatusUnknown
	}
}

func fromProtoDependencies(in []*rewindv1.Dependency) []domain.Dependency {
	if len(in) == 0 {
		return nil
	}
	out := make([]domain.Dependency, 0, len(in))
	for _, d := range in {
		out = append(out, domain.Dependency{
			Name:   d.GetName(),
			Status: fromProtoStatus(d.GetStatus()),
			Detail: d.GetDetail(),
		})
	}
	return out
}

var _ domain.AIEngine = (*Engine)(nil)
