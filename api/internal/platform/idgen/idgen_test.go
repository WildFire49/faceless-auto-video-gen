package idgen

import (
	"context"
	"errors"
	"fmt"
	"testing"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
)

// Found by the M4 end-to-end run: after twenty test videos about "iron", the
// twenty-first could not be queued at all -- "could not find a free id for
// topic "iron" after 20 attempts". Twenty is not implausible for a channel
// that remakes, sends back and re-runs episodes; it is a Tuesday.
//
// The ways this can go wrong, written before the fix:
//
//  1. the Nth video of a topic cannot be created     -> ids keep counting up
//  2. the search never ends when everything is taken -> it still stops, loudly
//  3. a gap in the numbering is skipped               -> the first free id wins
func takenUpTo(n int) func(context.Context, string) (bool, error) {
	taken := map[string]bool{"iron": true}
	for i := 2; i <= n; i++ {
		taken[fmt.Sprintf("iron-%d", i)] = true
	}
	return func(_ context.Context, id string) (bool, error) { return taken[id], nil }
}

func TestTheTwentyFirstVideoOfATopicGetsAnID(t *testing.T) {
	id, err := New().NewID(context.Background(), "iron", takenUpTo(20))
	if err != nil {
		t.Fatalf("case 1: %v", err)
	}
	if id != "iron-21" {
		t.Fatalf("id = %q, want iron-21", id)
	}
}

func TestAHundredVideosOfATopicStillGetIDs(t *testing.T) {
	id, err := New().NewID(context.Background(), "iron", takenUpTo(150))
	if err != nil || id != "iron-151" {
		t.Fatalf("id = %q, err = %v; want iron-151 (case 1)", id, err)
	}
}

func TestTheSearchStillStopsWhenEverythingIsTaken(t *testing.T) {
	always := func(context.Context, string) (bool, error) { return true, nil }

	_, err := New().NewID(context.Background(), "iron", always)

	if !errors.Is(err, domain.ErrValidation) {
		t.Fatalf("err = %v, want a loud failure rather than an endless loop (case 2)", err)
	}
}

func TestAGapIsFilledFirst(t *testing.T) {
	taken := map[string]bool{"iron": true, "iron-2": true, "iron-4": true}
	exists := func(_ context.Context, id string) (bool, error) { return taken[id], nil }

	id, err := New().NewID(context.Background(), "iron", exists)
	if err != nil || id != "iron-3" {
		t.Fatalf("id = %q, err = %v; want iron-3 (case 3)", id, err)
	}
}
