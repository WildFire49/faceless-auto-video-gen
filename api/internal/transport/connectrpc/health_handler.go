// Package connectrpc exposes the API the Next.js dashboard calls.
//
// LAYER 5 (transport) of SPEC.md 14.1. Handlers here may only:
//
//	validate -> call one service method -> map the result back
//
// No business logic. If you find an `if` about gates, beats or history in this
// package, it belongs in service/ instead (SPEC.md 14.4).
package connectrpc

import (
	"context"

	"connectrpc.com/connect"

	rewindv1 "github.com/WildFire49/faceless-auto-video-gen/api/gen/rewind/v1"
	"github.com/WildFire49/faceless-auto-video-gen/api/gen/rewind/v1/rewindv1connect"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/service"
)

// HealthHandler serves rewind.v1.RewindService.
type HealthHandler struct {
	health *service.HealthService
}

// NewHealthHandler wires the handler to its use case.
func NewHealthHandler(health *service.HealthService) *HealthHandler {
	return &HealthHandler{health: health}
}

// GetSystemHealth implements rewindv1connect.RewindServiceHandler.
func (h *HealthHandler) GetSystemHealth(
	ctx context.Context,
	req *connect.Request[rewindv1.GetSystemHealthRequest],
) (*connect.Response[rewindv1.GetSystemHealthResponse], error) {
	sys, err := h.health.GetSystemHealth(ctx, req.Msg.GetDeep())
	if err != nil {
		return nil, toConnectError(err)
	}

	return connect.NewResponse(&rewindv1.GetSystemHealthResponse{
		Status: toProtoStatus(sys.Status),
		Api:    toProtoComponent(sys.API),
		Ai:     toProtoComponent(sys.AI),
	}), nil
}

// toProtoStatus maps the domain type to the wire enum. Translation lives here,
// at the edge, so domain/ never imports protobuf.
func toProtoStatus(s domain.HealthStatus) rewindv1.HealthStatus {
	switch s {
	case domain.HealthOK:
		return rewindv1.HealthStatus_HEALTH_STATUS_OK
	case domain.HealthDegraded:
		return rewindv1.HealthStatus_HEALTH_STATUS_DEGRADED
	case domain.HealthDown:
		return rewindv1.HealthStatus_HEALTH_STATUS_DOWN
	default:
		return rewindv1.HealthStatus_HEALTH_STATUS_UNSPECIFIED
	}
}

func toProtoComponent(c domain.ComponentHealth) *rewindv1.ComponentHealth {
	out := &rewindv1.ComponentHealth{
		Name:      c.Name,
		Status:    toProtoStatus(c.Status),
		Version:   c.Version,
		Detail:    c.Detail,
		LatencyMs: c.Latency.Milliseconds(),
	}
	for _, d := range c.Dependencies {
		out.Dependencies = append(out.Dependencies, &rewindv1.Dependency{
			Name:   d.Name,
			Status: toProtoStatus(d.Status),
			Detail: d.Detail,
		})
	}
	return out
}

var _ rewindv1connect.RewindServiceHandler = (*HealthHandler)(nil)
