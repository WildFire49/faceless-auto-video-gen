package domain

import (
	"strings"
	"time"
	"unicode"
)

// Status is where a video sits in the pipeline (SPEC.md 2.3).
//
// A string rather than an int: it is what appears in the database, the CLI and
// the dashboard, and a readable value in all three is worth more than the
// bytes saved. The wire enum is mapped at the transport edge.
type Status string

const (
	StatusQueued Status = "queued"

	// Module 2 -- research, then Gate A
	StatusResearching   Status = "researching"
	StatusFactsReady    Status = "facts_ready"
	StatusFactsApproved Status = "facts_approved"

	// Module 3 -- relevance, then Gate B
	StatusFindingRefs  Status = "finding_refs"
	StatusRefsReady    Status = "refs_ready"
	StatusRefsApproved Status = "refs_approved"

	// Module 4 -- script, then Gate C
	StatusScripting      Status = "scripting"
	StatusScriptReady    Status = "script_ready"
	StatusScriptApproved Status = "script_approved"

	// Module 5 -- voice, then Gate D
	StatusVoicing       Status = "voicing"
	StatusVoiceReady    Status = "voice_ready"
	StatusVoiceApproved Status = "voice_approved"

	// Module 6 -- visuals, then Gate E
	StatusImaging            Status = "imaging"
	StatusStoryboardReady    Status = "storyboard_ready"
	StatusStoryboardApproved Status = "storyboard_approved"

	// Module 9 -- render, then Gate F
	StatusRendering     Status = "rendering"
	StatusRenderReady   Status = "render_ready"
	StatusFinalApproved Status = "final_approved"

	// Module 10 -- publish. Always private; a human publishes manually.
	StatusUploading       Status = "uploading"
	StatusUploadedPrivate Status = "uploaded_private"
	StatusPublished       Status = "published"

	// Module 11
	StatusAnalyticsCollected Status = "analytics_collected"

	// A step failed.
	StatusError Status = "error"
)

// Priority orders the queue. 1 is highest, 5 lowest.
type Priority int

const (
	PriorityHighest Priority = 1
	PriorityDefault Priority = 3
	PriorityLowest  Priority = 5
)

// Valid reports whether p is in range.
func (p Priority) Valid() bool { return p >= PriorityHighest && p <= PriorityLowest }

// Video is one episode moving through the pipeline.
type Video struct {
	// ID is the slug, and also the name of the folder under projects/. It is
	// validated against ^[a-z0-9-]{1,64}$ before ever being used as a path.
	ID     string
	Topic  string
	Status Status

	Priority Priority
	Notes    string

	CreatedAt time.Time
	UpdatedAt time.Time

	// RejectedTo records where a gate sent this video back to. It is cleared
	// once the video moves forward again, so it always describes the most
	// recent rejection that is still relevant.
	RejectedTo Status
	RejectNote string

	// Error and RetryFrom are set together when a step fails. RetryFrom is the
	// status to resume from, so a retry re-runs the failed step rather than
	// guessing where to restart.
	Error     string
	RetryFrom Status

	YTVideoID   string
	PublishedAt *time.Time
}

// Slugify turns a topic into a safe, readable id: "Computer Mouse!" becomes
// "computer-mouse".
//
// Deliberately lossy and conservative. It produces only characters that pass
// the path guard, so an id can never be crafted to escape projects/.
func Slugify(topic string) string {
	var b strings.Builder
	lastDash := true // avoids a leading dash

	for _, r := range strings.ToLower(strings.TrimSpace(topic)) {
		switch {
		case r >= 'a' && r <= 'z', unicode.IsDigit(r):
			b.WriteRune(r)
			lastDash = false
		case r == ' ' || r == '-' || r == '_' || r == '/':
			if !lastDash {
				b.WriteByte('-')
				lastDash = true
			}
		default:
			// Accented letters, punctuation and anything non-ASCII are
			// dropped rather than transliterated: a wrong transliteration
			// would be a worse id than a shorter one.
		}
	}

	slug := strings.Trim(b.String(), "-")
	if len(slug) > 64 {
		slug = strings.Trim(slug[:64], "-")
	}
	return slug
}
