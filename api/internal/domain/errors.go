package domain

import "errors"

// Sentinel errors for conditions the core itself can detect. Callers compare
// with errors.Is, and the transport layer maps them to wire codes in exactly
// one place (transport/connectrpc/errors.go) -- never at each call site.
//
// Go has no exceptions: errors are values that are returned and wrapped with
// %w as they travel up. See SPEC.md Appendix A.1.
var (
	// ErrInvalidVideoID means an id failed the ^[a-z0-9-]{1,64}$ guard. It is
	// checked before an id is ever used to build a filesystem path
	// (SPEC.md 13.5, path traversal).
	ErrInvalidVideoID = errors.New("invalid video id")

	// ErrNotFound means the requested entity does not exist.
	ErrNotFound = errors.New("not found")

	// ErrIllegalTransition means a state change was attempted that the video
	// state machine does not permit -- for example approving Gate C before
	// Gate B. This is the error that makes gate-skipping impossible.
	ErrIllegalTransition = errors.New("illegal state transition")
)
