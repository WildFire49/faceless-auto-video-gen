package validate_test

import (
	"errors"
	"testing"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/platform/validate"
)

func TestVideoID(t *testing.T) {
	t.Parallel()

	valid := []string{"iron", "computer-mouse", "sandals", "a", "a1-2-3"}
	for _, id := range valid {
		t.Run("valid/"+id, func(t *testing.T) {
			t.Parallel()
			if err := validate.VideoID(id); err != nil {
				t.Errorf("VideoID(%q) = %v, want nil", id, err)
			}
		})
	}

	// Each of these would become a directory name under projects/. The
	// traversal cases are the reason this guard exists (SPEC.md 13.5).
	invalid := map[string]string{
		"empty":              "",
		"parent traversal":   "..",
		"nested traversal":   "../../etc/passwd",
		"forward slash":      "iron/facts",
		"backslash":          `iron\facts`,
		"windows drive":      "c:iron",
		"uppercase":          "Iron",
		"space":              "computer mouse",
		"underscore":         "computer_mouse",
		"null byte":          "iron\x00",
		"leading dash is ok": "-iron", // documents that this IS allowed
	}
	for name, id := range invalid {
		if name == "leading dash is ok" {
			continue
		}
		t.Run("invalid/"+name, func(t *testing.T) {
			t.Parallel()
			err := validate.VideoID(id)
			if err == nil {
				t.Fatalf("VideoID(%q) = nil, want an error", id)
			}
			if !errors.Is(err, domain.ErrInvalidVideoID) {
				t.Errorf("VideoID(%q) error = %v, want it to wrap ErrInvalidVideoID", id, err)
			}
		})
	}
}

func TestVideoIDRejectsOverlongIDs(t *testing.T) {
	t.Parallel()

	id := ""
	for range 65 {
		id += "a"
	}
	if err := validate.VideoID(id); !errors.Is(err, domain.ErrInvalidVideoID) {
		t.Errorf("VideoID(65 chars) = %v, want ErrInvalidVideoID", err)
	}
}
