// Package idgen turns a topic into a unique, path-safe video id.
//
// LAYER 6 (platform) of SPEC.md 14.1. It implements domain.IDGen.
package idgen

import (
	"context"
	"fmt"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
)

// maxAttempts bounds the suffix search. Twenty "iron" episodes is already
// implausible; failing loudly beats looping forever.
const maxAttempts = 20

// Slug generates ids by slugifying the topic and adding a numeric suffix on
// collision: "iron", then "iron-2", "iron-3".
//
// Readable ids matter here because the id is also the folder name under
// projects/, which you will be opening by hand constantly.
type Slug struct{}

// New returns the generator.
func New() Slug { return Slug{} }

// NewID implements domain.IDGen.
func (Slug) NewID(
	ctx context.Context,
	topic string,
	exists func(context.Context, string) (bool, error),
) (string, error) {
	base := domain.Slugify(topic)
	if base == "" {
		// Every usable character was stripped -- an emoji-only topic, say.
		// Better to refuse than to invent a meaningless id.
		return "", fmt.Errorf("%w: topic %q has no letters or digits to build an id from",
			domain.ErrValidation, topic)
	}

	for attempt := 1; attempt <= maxAttempts; attempt++ {
		candidate := base
		if attempt > 1 {
			candidate = fmt.Sprintf("%s-%d", base, attempt)
			// The suffix must not push the id past the 64-character limit.
			if len(candidate) > 64 {
				trimmed := base[:64-len(fmt.Sprintf("-%d", attempt))]
				candidate = fmt.Sprintf("%s-%d", trimmed, attempt)
			}
		}

		taken, err := exists(ctx, candidate)
		if err != nil {
			return "", fmt.Errorf("checking whether id %q is free: %w", candidate, err)
		}
		if !taken {
			return candidate, nil
		}
	}

	return "", fmt.Errorf("%w: could not find a free id for topic %q after %d attempts",
		domain.ErrValidation, topic, maxAttempts)
}

var _ domain.IDGen = Slug{}
