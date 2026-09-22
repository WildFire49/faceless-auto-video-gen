package service_test

import (
	"context"
	"errors"
	"path/filepath"
	"testing"
	"time"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/adapter/sqlite"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/platform/clock"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/platform/idgen"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/service"
)

// These exercise the real services against a real database, because the
// behaviour worth proving -- that an approval and its audit entry commit
// together, and that gates cannot be skipped through the service layer -- only
// exists once the pieces are wired up.

type harness struct {
	videos *service.VideoService
	gates  *service.GateService
	repo   *sqlite.VideoRepo
	log    *sqlite.ReviewLog
}

func newHarness(t *testing.T) *harness {
	t.Helper()

	db, err := sqlite.Open(context.Background(), filepath.Join(t.TempDir(), "svc.db"))
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	t.Cleanup(func() { _ = db.Close() })

	repo := sqlite.NewVideoRepo(db)
	log := sqlite.NewReviewLog(db)
	clk := clock.New()

	return &harness{
		videos: service.NewVideoService(repo, log, db, clk, idgen.New()),
		gates:  service.NewGateService(repo, log, db, clk, nil),
		repo:   repo,
		log:    log,
	}
}

// forceStatus moves a video directly, bypassing the state machine.
//
// Test-only scaffolding: without pipeline steps (M2) there is no legitimate
// way to park a video at a gate. It writes through the repository rather than
// through a service, so it cannot accidentally become a production shortcut
// for skipping a gate.
func (h *harness) forceStatus(t *testing.T, id string, s domain.Status) {
	t.Helper()

	v, err := h.repo.Get(context.Background(), id)
	if err != nil {
		t.Fatalf("forceStatus Get: %v", err)
	}
	v.Status = s
	v.UpdatedAt = time.Now().UTC()
	if err := h.repo.Update(context.Background(), v); err != nil {
		t.Fatalf("forceStatus Update: %v", err)
	}
}

// ------------------------------------------------------------------- adding

func TestAddVideo(t *testing.T) {
	t.Parallel()

	ctx := context.Background()
	h := newHarness(t)

	v, err := h.videos.AddVideo(ctx, "computer mouse", 0, "compare to a gaming mouse")
	if err != nil {
		t.Fatalf("AddVideo: %v", err)
	}

	if v.ID != "computer-mouse" {
		t.Errorf("id = %q, want %q", v.ID, "computer-mouse")
	}
	if v.Status != domain.StatusQueued {
		t.Errorf("status = %q, want %q", v.Status, domain.StatusQueued)
	}
	if v.Priority != domain.PriorityDefault {
		t.Errorf("priority = %d, want the default %d", v.Priority, domain.PriorityDefault)
	}

	// Creating a video is itself a logged event, so the review log is a
	// complete history rather than starting at the first approval.
	entries, err := h.log.List(ctx, v.ID)
	if err != nil {
		t.Fatalf("List: %v", err)
	}
	if len(entries) != 1 || entries[0].Action != domain.ActionCreate {
		t.Errorf("got %d entries, want 1 create entry", len(entries))
	}
}

func TestAddVideoGeneratesUniqueIDs(t *testing.T) {
	t.Parallel()

	ctx := context.Background()
	h := newHarness(t)

	first, err := h.videos.AddVideo(ctx, "iron", 0, "")
	if err != nil {
		t.Fatalf("first AddVideo: %v", err)
	}
	second, err := h.videos.AddVideo(ctx, "iron", 0, "")
	if err != nil {
		t.Fatalf("second AddVideo: %v", err)
	}

	if first.ID != "iron" || second.ID != "iron-2" {
		t.Errorf("ids = %q, %q; want iron, iron-2", first.ID, second.ID)
	}
}

func TestAddVideoRejectsBadInput(t *testing.T) {
	t.Parallel()

	ctx := context.Background()
	h := newHarness(t)

	tests := []struct {
		name     string
		topic    string
		priority domain.Priority
	}{
		{"empty topic", "", 0},
		{"topic with nothing usable", "🙂🙂🙂", 0},
		{"priority too low", "iron", 99},
		{"negative priority", "iron", -1},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			if _, err := h.videos.AddVideo(ctx, tc.topic, tc.priority, ""); err == nil {
				t.Errorf("AddVideo(%q, %d) = nil, want an error", tc.topic, tc.priority)
			}
		})
	}
}

// -------------------------------------------------------------------- gates

// TestFullGateWalkThroughTheServices is the service-level counterpart to the
// domain test: six approvals, each persisted and each logged.
func TestFullGateWalkThroughTheServices(t *testing.T) {
	t.Parallel()

	ctx := context.Background()
	h := newHarness(t)

	v, err := h.videos.AddVideo(ctx, "iron", 0, "")
	if err != nil {
		t.Fatalf("AddVideo: %v", err)
	}

	for _, g := range domain.AllGates() {
		waiting, ok := domain.GateWaitingStatus(g)
		if !ok {
			t.Fatalf("no waiting status for %s", g)
		}
		h.forceStatus(t, v.ID, waiting)

		got, err := h.gates.Approve(ctx, v.ID, g, "looks right")
		if err != nil {
			t.Fatalf("Approve(%s): %v", g, err)
		}
		if want := domain.GateApprovalTarget(g); got.Status != want {
			t.Errorf("after %s: status = %q, want %q", g, got.Status, want)
		}
	}

	entries, err := h.videos.ListReviewLog(ctx, v.ID)
	if err != nil {
		t.Fatalf("ListReviewLog: %v", err)
	}
	// 1 create + 6 approvals.
	if len(entries) != 7 {
		t.Fatalf("got %d review entries, want 7 (1 create + 6 approvals)", len(entries))
	}

	approvals := 0
	for _, e := range entries {
		if e.Action == domain.ActionApprove {
			approvals++
			if e.Note != "looks right" {
				t.Errorf("approval note = %q, want it recorded", e.Note)
			}
		}
	}
	if approvals != 6 {
		t.Errorf("logged %d approvals, want 6", approvals)
	}
}

func TestApproveTheWrongGateChangesNothing(t *testing.T) {
	t.Parallel()

	ctx := context.Background()
	h := newHarness(t)

	v, err := h.videos.AddVideo(ctx, "iron", 0, "")
	if err != nil {
		t.Fatalf("AddVideo: %v", err)
	}
	h.forceStatus(t, v.ID, domain.StatusScriptReady)

	if _, err := h.gates.Approve(ctx, v.ID, domain.GateA, ""); !errors.Is(err, domain.ErrIllegalTransition) {
		t.Fatalf("Approve(wrong gate) = %v, want ErrIllegalTransition", err)
	}

	// The transaction must have rolled back: no status change AND no log entry.
	after, err := h.videos.GetVideo(ctx, v.ID)
	if err != nil {
		t.Fatalf("GetVideo: %v", err)
	}
	if after.Status != domain.StatusScriptReady {
		t.Errorf("status = %q, want it unchanged", after.Status)
	}

	entries, err := h.videos.ListReviewLog(ctx, v.ID)
	if err != nil {
		t.Fatalf("ListReviewLog: %v", err)
	}
	if len(entries) != 1 { // just the create
		t.Errorf("got %d entries, want only the create entry; a refused approval must not be logged as one", len(entries))
	}
}

// TestRejectSendsVideoBackAndRecordsWhy covers the `rejected_to` acceptance
// criterion for M1.
func TestRejectSendsVideoBackAndRecordsWhy(t *testing.T) {
	t.Parallel()

	ctx := context.Background()
	h := newHarness(t)

	v, err := h.videos.AddVideo(ctx, "iron", 0, "")
	if err != nil {
		t.Fatalf("AddVideo: %v", err)
	}
	h.forceStatus(t, v.ID, domain.StatusScriptReady)

	const reason = "the 1882 date contradicts the source"
	got, err := h.gates.Reject(ctx, v.ID, domain.GateC, domain.StatusResearching, reason)
	if err != nil {
		t.Fatalf("Reject: %v", err)
	}

	if got.Status != domain.StatusResearching {
		t.Errorf("status = %q, want %q", got.Status, domain.StatusResearching)
	}
	if got.RejectedTo != domain.StatusResearching {
		t.Errorf("RejectedTo = %q, want %q", got.RejectedTo, domain.StatusResearching)
	}
	if got.RejectNote != reason {
		t.Errorf("RejectNote = %q, want %q", got.RejectNote, reason)
	}

	// It must survive a reload, not just live in the returned struct.
	reloaded, err := h.videos.GetVideo(ctx, v.ID)
	if err != nil {
		t.Fatalf("GetVideo: %v", err)
	}
	if reloaded.RejectedTo != domain.StatusResearching || reloaded.RejectNote != reason {
		t.Errorf("rejection did not persist: RejectedTo=%q RejectNote=%q",
			reloaded.RejectedTo, reloaded.RejectNote)
	}

	entries, err := h.videos.ListReviewLog(ctx, v.ID)
	if err != nil {
		t.Fatalf("ListReviewLog: %v", err)
	}
	last := entries[len(entries)-1]
	if last.Action != domain.ActionReject || last.Note != reason {
		t.Errorf("last log entry = %+v, want a reject carrying the reason", last)
	}
	if last.ToStatus != domain.StatusResearching {
		t.Errorf("logged to_status = %q, want %q", last.ToStatus, domain.StatusResearching)
	}
}

// --------------------------------------------------------------------- misc

func TestRetryRestoresTheFailedStep(t *testing.T) {
	t.Parallel()

	ctx := context.Background()
	h := newHarness(t)

	v, err := h.videos.AddVideo(ctx, "iron", 0, "")
	if err != nil {
		t.Fatalf("AddVideo: %v", err)
	}

	// Simulate a failed voicing step.
	stored, err := h.repo.Get(ctx, v.ID)
	if err != nil {
		t.Fatalf("Get: %v", err)
	}
	stored.Status = domain.StatusVoicing
	domain.Fail(stored, "out of VRAM")
	if err := h.repo.Update(ctx, stored); err != nil {
		t.Fatalf("Update: %v", err)
	}

	got, err := h.videos.RetryVideo(ctx, v.ID)
	if err != nil {
		t.Fatalf("RetryVideo: %v", err)
	}
	if got.Status != domain.StatusVoicing {
		t.Errorf("status = %q, want to resume at %q", got.Status, domain.StatusVoicing)
	}
	if got.Error != "" {
		t.Errorf("Error = %q, want it cleared", got.Error)
	}
}

func TestPlanNextExplainsWhatWouldHappen(t *testing.T) {
	t.Parallel()

	ctx := context.Background()
	h := newHarness(t)

	v, err := h.videos.AddVideo(ctx, "iron", 0, "")
	if err != nil {
		t.Fatalf("AddVideo: %v", err)
	}

	step, err := h.videos.PlanNext(ctx, v.ID)
	if err != nil {
		t.Fatalf("PlanNext: %v", err)
	}
	if step.NextStatus != domain.StatusResearching {
		t.Errorf("NextStatus = %q, want %q", step.NextStatus, domain.StatusResearching)
	}

	// At a gate, the plan is "a human needs to look at this".
	h.forceStatus(t, v.ID, domain.StatusFactsReady)
	step, err = h.videos.PlanNext(ctx, v.ID)
	if err != nil {
		t.Fatalf("PlanNext: %v", err)
	}
	if step.AwaitingGate != domain.GateA {
		t.Errorf("AwaitingGate = %q, want %q", step.AwaitingGate, domain.GateA)
	}
	if step.NextStatus != "" {
		t.Errorf("NextStatus = %q, want empty while waiting on a human", step.NextStatus)
	}
}

func TestListVideosAwaitingReview(t *testing.T) {
	t.Parallel()

	ctx := context.Background()
	h := newHarness(t)

	waiting, err := h.videos.AddVideo(ctx, "iron", 0, "")
	if err != nil {
		t.Fatalf("AddVideo: %v", err)
	}
	if _, err := h.videos.AddVideo(ctx, "sandals", 0, ""); err != nil {
		t.Fatalf("AddVideo: %v", err)
	}
	h.forceStatus(t, waiting.ID, domain.StatusRenderReady)

	got, err := h.videos.ListVideos(ctx, domain.VideoFilter{AwaitingReview: true})
	if err != nil {
		t.Fatalf("ListVideos: %v", err)
	}
	if len(got) != 1 || got[0].ID != waiting.ID {
		t.Errorf("got %d videos, want just %q", len(got), waiting.ID)
	}
}
