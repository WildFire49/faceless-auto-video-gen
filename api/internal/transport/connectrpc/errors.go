package connectrpc

import (
	"context"
	"errors"

	"connectrpc.com/connect"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
)

// toConnectError maps a domain error to a wire status code.
//
// This mapping exists in exactly ONE place. Doing it per call site is how
// codebases end up returning Internal for a validation failure in one handler
// and InvalidArgument in another (SPEC.md 14.1).
func toConnectError(err error) *connect.Error {
	switch {
	case err == nil:
		return nil
	case errors.Is(err, domain.ErrInvalidVideoID):
		return connect.NewError(connect.CodeInvalidArgument, err)
	case errors.Is(err, domain.ErrNotFound):
		return connect.NewError(connect.CodeNotFound, err)
	case errors.Is(err, domain.ErrIllegalTransition):
		// FailedPrecondition, not InvalidArgument: the request was well formed,
		// the system is simply not in a state where it can be honoured. This is
		// what a client sees when it tries to skip a review gate.
		return connect.NewError(connect.CodeFailedPrecondition, err)
	case errors.Is(err, context.Canceled):
		return connect.NewError(connect.CodeCanceled, err)
	case errors.Is(err, context.DeadlineExceeded):
		return connect.NewError(connect.CodeDeadlineExceeded, err)
	default:
		return connect.NewError(connect.CodeInternal, err)
	}
}
