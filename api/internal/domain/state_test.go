package domain_test

import (
	"errors"
	"strings"
	"testing"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
)

func videoAt(s domain.Status) *domain.Video {
	return &domain.Video{ID: "iron", Topic: "iron", Status: s}
}

// ---------------------------------------------------------------- the happy path

// TestFullPipelineRequiresEveryGate walks a video from queued to published and
// asserts that it is impossible to get there without six human approvals.
//
// This is the single most important test in the project: it is the executable
// form of "human review gates can never be skipped" (CLAUDE.md).
func TestFullPipelineRequiresEveryGate(t *testing.T) {
	t.Parallel()

	v := videoAt(domain.StatusQueued)
	gatesPassed := 0

	for range 100 { // generous bound; the loop exits on its own
		if g, waiting := domain.GateFor(v.Status); waiting {
			// A pipeline step must NOT be able to move past this point.
			target := domain.GateApprovalTarget(g)
			if err := domain.Transition(v, target); err == nil {
				t.Fatalf("a pipeline step advanced %s past %s without approval", v.Status, g)
			} else if !strings.Contains(err.Error(), "human approval") {
				t.Errorf("error for skipping %s = %q, want it to mention human approval", g, err)
			}

			// Only an explicit human approval moves it on.
			if err := domain.ApproveGate(v, g); err != nil {
				t.Fatalf("ApproveGate(%s): %v", g, err)
			}
			gatesPassed++
			continue
		}

		next, ok := domain.NextAutomatic(v.Status)
		if !ok {
			break // terminal, or waiting on something outside the machine
		}
		if err := domain.Transition(v, next); err != nil {
			t.Fatalf("Transition(%s -> %s): %v", v.Status, next, err)
		}
	}

	if gatesPassed != 6 {
		t.Errorf("passed %d gates, want 6", gatesPassed)
	}
	// The machine stops at uploaded_private: a human publishes on YouTube.
	if v.Status != domain.StatusUploadedPrivate {
		t.Errorf("final status = %q, want %q", v.Status, domain.StatusUploadedPrivate)
	}
}

// ------------------------------------------------------------ illegal transitions

func TestTransitionRejectsIllegalMoves(t *testing.T) {
	t.Parallel()

	tests := []struct {
		name string
		from domain.Status
		to   domain.Status
	}{
		{"skipping research entirely", domain.StatusQueued, domain.StatusScripting},
		{"jumping to the end", domain.StatusQueued, domain.StatusPublished},
		{"moving backwards", domain.StatusScripting, domain.StatusResearching},
		{"unknown target", domain.StatusQueued, domain.Status("nonsense")},
		{"empty target", domain.StatusQueued, domain.Status("")},
		{"approving a gate as a step", domain.StatusFactsReady, domain.StatusFactsApproved},
		{"stepping from a gate to somewhere else", domain.StatusRenderReady, domain.StatusUploading},
		{"publishing without a human", domain.StatusUploadedPrivate, domain.StatusPublished},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			t.Parallel()
			v := videoAt(tc.from)
			err := domain.Transition(v, tc.to)
			if err == nil {
				t.Fatalf("Transition(%s -> %s) = nil, want an error", tc.from, tc.to)
			}
			if !errors.Is(err, domain.ErrIllegalTransition) {
				t.Errorf("error = %v, want it to wrap ErrIllegalTransition", err)
			}
			if v.Status != tc.from {
				t.Errorf("status changed to %q on a failed transition; it must not move", v.Status)
			}
		})
	}
}

// TestEveryGateRefusesAutomaticCrossing is the exhaustive version: for all six
// gates, a pipeline step may never perform the approval.
func TestEveryGateRefusesAutomaticCrossing(t *testing.T) {
	t.Parallel()

	for _, g := range domain.AllGates() {
		t.Run(string(g), func(t *testing.T) {
			t.Parallel()
			from, ok := domain.GateWaitingStatus(g)
			if !ok {
				t.Fatalf("no waiting status for %s", g)
			}
			v := videoAt(from)
			if err := domain.Transition(v, domain.GateApprovalTarget(g)); err == nil {
				t.Fatalf("%s was crossed by a pipeline step", g)
			}
			if v.Status != from {
				t.Errorf("status = %q after a refused crossing, want %q", v.Status, from)
			}
		})
	}
}

// ------------------------------------------------------------------- approvals

func TestApproveGateRejectsTheWrongGate(t *testing.T) {
	t.Parallel()

	// A stale browser tab showing Gate A must not be able to approve a video
	// that has since moved on to Gate C.
	v := videoAt(domain.StatusScriptReady)
	err := domain.ApproveGate(v, domain.GateA)
	if err == nil {
		t.Fatal("approving the wrong gate succeeded")
	}
	if !errors.Is(err, domain.ErrIllegalTransition) {
		t.Errorf("error = %v, want ErrIllegalTransition", err)
	}
	if v.Status != domain.StatusScriptReady {
		t.Errorf("status = %q, want it unchanged", v.Status)
	}
}

func TestApproveGateRejectsVideosNotAwaitingReview(t *testing.T) {
	t.Parallel()

	v := videoAt(domain.StatusRendering) // mid-step, not waiting on a human
	if err := domain.ApproveGate(v, domain.GateF); err == nil {
		t.Fatal("approved a gate for a video that is not awaiting one")
	}
}

// --------------------------------------------------------------------- rejection

func TestRejectGateSendsVideoBack(t *testing.T) {
	t.Parallel()

	// Gate C: the script is wrong because the facts were wrong, so send it all
	// the way back to Gate A's input.
	v := videoAt(domain.StatusScriptReady)
	if err := domain.RejectGate(v, domain.GateC, domain.StatusResearching, "date on beat 4 looks wrong"); err != nil {
		t.Fatalf("RejectGate: %v", err)
	}

	if v.Status != domain.StatusResearching {
		t.Errorf("status = %q, want %q", v.Status, domain.StatusResearching)
	}
	if v.RejectedTo != domain.StatusResearching {
		t.Errorf("RejectedTo = %q, want %q", v.RejectedTo, domain.StatusResearching)
	}
	if v.RejectNote == "" {
		t.Error("RejectNote is empty; the reason must be kept")
	}
}

func TestRejectGateRules(t *testing.T) {
	t.Parallel()

	tests := []struct {
		name   string
		status domain.Status
		gate   domain.Gate
		backTo domain.Status
		note   string
	}{
		{"forwards is not a rejection", domain.StatusFactsReady, domain.GateA, domain.StatusRendering, "nope"},
		{"sideways to itself", domain.StatusFactsReady, domain.GateA, domain.StatusFactsReady, "nope"},
		{"no note given", domain.StatusFactsReady, domain.GateA, domain.StatusQueued, ""},
		{"back to the error state", domain.StatusFactsReady, domain.GateA, domain.StatusError, "nope"},
		{"unknown status", domain.StatusFactsReady, domain.GateA, domain.Status("nowhere"), "nope"},
		{"wrong gate named", domain.StatusFactsReady, domain.GateD, domain.StatusQueued, "nope"},
		{"not at a gate at all", domain.StatusResearching, domain.GateA, domain.StatusQueued, "nope"},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			t.Parallel()
			v := videoAt(tc.status)
			if err := domain.RejectGate(v, tc.gate, tc.backTo, tc.note); err == nil {
				t.Fatalf("RejectGate(%s, %s, %q) = nil, want an error", tc.gate, tc.backTo, tc.note)
			}
			if v.Status != tc.status {
				t.Errorf("status = %q after a refused rejection, want %q", v.Status, tc.status)
			}
		})
	}
}

func TestMovingForwardClearsAPreviousRejection(t *testing.T) {
	t.Parallel()

	v := videoAt(domain.StatusScriptReady)
	if err := domain.RejectGate(v, domain.GateC, domain.StatusResearching, "wrong date"); err != nil {
		t.Fatalf("RejectGate: %v", err)
	}
	if err := domain.Transition(v, domain.StatusFactsReady); err != nil {
		t.Fatalf("Transition: %v", err)
	}

	// The rejection has been acted on; leaving it set would make the dashboard
	// keep showing a stale warning.
	if v.RejectedTo != "" || v.RejectNote != "" {
		t.Errorf("RejectedTo=%q RejectNote=%q, want both cleared once the video moves on",
			v.RejectedTo, v.RejectNote)
	}
}

// --------------------------------------------------------------- errors and retry

func TestFailAndRetryResumeTheFailedStep(t *testing.T) {
	t.Parallel()

	v := videoAt(domain.StatusVoicing)
	domain.Fail(v, "chatterbox ran out of VRAM")

	if v.Status != domain.StatusError {
		t.Fatalf("status = %q, want %q", v.Status, domain.StatusError)
	}
	if v.RetryFrom != domain.StatusVoicing {
		t.Errorf("RetryFrom = %q, want %q", v.RetryFrom, domain.StatusVoicing)
	}

	if err := domain.Retry(v); err != nil {
		t.Fatalf("Retry: %v", err)
	}
	if v.Status != domain.StatusVoicing {
		t.Errorf("status = %q, want to resume at %q", v.Status, domain.StatusVoicing)
	}
	if v.Error != "" || v.RetryFrom != "" {
		t.Errorf("Error=%q RetryFrom=%q, want both cleared after a retry", v.Error, v.RetryFrom)
	}
}

func TestFailTwiceKeepsTheOriginalResumePoint(t *testing.T) {
	t.Parallel()

	// Failing an already-failed video must not set RetryFrom to "error",
	// which would make the video unrecoverable.
	v := videoAt(domain.StatusRendering)
	domain.Fail(v, "first failure")
	domain.Fail(v, "second failure")

	if v.RetryFrom != domain.StatusRendering {
		t.Errorf("RetryFrom = %q, want %q", v.RetryFrom, domain.StatusRendering)
	}
}

func TestRetryOnAHealthyVideoIsRejected(t *testing.T) {
	t.Parallel()

	v := videoAt(domain.StatusScripting)
	if err := domain.Retry(v); !errors.Is(err, domain.ErrIllegalTransition) {
		t.Errorf("Retry on a non-failed video = %v, want ErrIllegalTransition", err)
	}
}

func TestRetryWithoutAResumePointFallsBackToQueued(t *testing.T) {
	t.Parallel()

	// A row that predates RetryFrom, or one corrupted by hand, must still be
	// recoverable rather than stuck in error forever.
	v := &domain.Video{ID: "iron", Status: domain.StatusError, Error: "legacy"}
	if err := domain.Retry(v); err != nil {
		t.Fatalf("Retry: %v", err)
	}
	if v.Status != domain.StatusQueued {
		t.Errorf("status = %q, want %q", v.Status, domain.StatusQueued)
	}
}

// --------------------------------------------------------------------- helpers

func TestIsTerminal(t *testing.T) {
	t.Parallel()

	terminal := []domain.Status{
		domain.StatusFactsReady, // waiting on Gate A
		domain.StatusRenderReady,
		domain.StatusError,
		domain.StatusUploadedPrivate, // waiting on a human to publish
		domain.StatusAnalyticsCollected,
	}
	for _, s := range terminal {
		if !domain.IsTerminal(s) {
			t.Errorf("IsTerminal(%q) = false, want true", s)
		}
	}

	running := []domain.Status{
		domain.StatusQueued, domain.StatusResearching,
		domain.StatusFactsApproved, domain.StatusRendering,
	}
	for _, s := range running {
		if domain.IsTerminal(s) {
			t.Errorf("IsTerminal(%q) = true, want false", s)
		}
	}
}

func TestSlugify(t *testing.T) {
	t.Parallel()

	tests := map[string]string{
		"iron":                     "iron",
		"computer mouse":           "computer-mouse",
		"Computer Mouse!":          "computer-mouse",
		"  sandals  ":              "sandals",
		"the washing-machine":      "the-washing-machine",
		"café":                     "caf",
		"a/b":                      "a-b",
		"multiple   spaces":        "multiple-spaces",
		"--leading and trailing--": "leading-and-trailing",
		"":                         "",
		"!!!":                      "",
	}

	for in, want := range tests {
		t.Run(in, func(t *testing.T) {
			t.Parallel()
			if got := domain.Slugify(in); got != want {
				t.Errorf("Slugify(%q) = %q, want %q", in, got, want)
			}
		})
	}
}

func TestSlugifyOutputAlwaysPassesThePathGuard(t *testing.T) {
	t.Parallel()

	// Slugify feeds directly into a directory name, so its output must always
	// be safe -- including for inputs that are actively trying to escape.
	hostile := []string{
		"../../etc/passwd", `..\..\windows`, "a/../../b", "C:\\Windows",
		"topic\x00null", "with spaces and !@#$%^&*()",
	}
	for _, in := range hostile {
		got := domain.Slugify(in)
		if got == "" {
			continue // rejected entirely, which is fine
		}
		for _, r := range got {
			isLower := r >= 'a' && r <= 'z'
			isDigit := r >= '0' && r <= '9'
			if !isLower && !isDigit && r != '-' {
				t.Errorf("Slugify(%q) = %q, which contains the unsafe rune %q", in, got, r)
			}
		}
		if strings.Contains(got, "..") {
			t.Errorf("Slugify(%q) = %q, which contains a traversal sequence", in, got)
		}
	}
}
