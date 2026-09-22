// Package validate holds the guards applied at the edge of the system, before
// untrusted input reaches anything that touches a filesystem path.
//
// LAYER 6 (platform) of SPEC.md 14.1; the rule it enforces is SPEC.md 13.5.
package validate

import (
	"fmt"
	"regexp"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
)

// videoIDPattern is deliberately strict. A video id becomes a directory name
// under projects/, so anything that could escape that directory -- "..", a
// slash, a backslash, a drive letter, a NUL -- must be impossible by
// construction rather than stripped after the fact.
var videoIDPattern = regexp.MustCompile(`^[a-z0-9-]{1,64}$`)

// VideoID returns nil when id is safe to use as a path segment.
//
// Errors wrap domain.ErrInvalidVideoID so callers can test with errors.Is
// while still getting a message that names the offending value.
func VideoID(id string) error {
	if !videoIDPattern.MatchString(id) {
		return fmt.Errorf("%w: %q must match %s", domain.ErrInvalidVideoID, id, videoIDPattern)
	}
	return nil
}
