package service_test

import (
	"context"
	"errors"
	"testing"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/adapter/aifake"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/adapter/factstore"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/platform/clock"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/service"
)

// The Gate C edit path. The E2E proves edits re-validate against the live
// worker; this covers what it cannot reach, with the worker faked.
//
// The ways this can go wrong, written before the code:
//
//  1. an edit is saved without being re-checked        -> the old verdict
//     stays, and the gate could open on a script nobody validated
//  2. the worker is down during an edit                 -> the edit must be
//     REFUSED and the file left as it was, not saved on trust
//  3. a new violation from the worker                   -> it closes the gate
//  4. an edit to a beat that does not exist             -> not found, nothing
//     written
//  5. an edit once Gate C is approved                   -> gate closed
//  6. a comparison in a beat that does not cite its fact -> the reviewer can
//     take it out; a first live run left one no edit of the WORDS could fix
type scriptHarness struct {
	*harness
	scripts *factstore.ScriptStore
	ai      *aifake.Engine
	svc     *service.ScriptService
	id      string
}

func newScriptHarness(t *testing.T) *scriptHarness {
	t.Helper()
	h := newHarness(t)
	dir := t.TempDir()

	facts := factstore.New(dir)
	refs := factstore.NewRefStore(dir)
	scripts := factstore.NewScriptStore(dir)
	ai := aifake.NewHealthy()

	v, err := h.videos.AddVideo(context.Background(), "sandals", 3, "")
	if err != nil {
		t.Fatalf("AddVideo: %v", err)
	}
	h.forceStatus(t, v.ID, domain.StatusScriptReady)

	if err := facts.Save(v.ID, &domain.FactSheet{Facts: []domain.Fact{
		{ID: "f1", Label: "1774", Claim: "c", Evidence: "In 1774 ...", Approved: true},
	}}); err != nil {
		t.Fatalf("saving facts: %v", err)
	}
	if err := scripts.Save(v.ID, &domain.Script{
		ChosenTitle: "Sandals",
		Beats:       []domain.Beat{{N: 1, Role: "hook", Voice: "In 1774, sandals.", FactIDs: []string{"f1"}}},
	}); err != nil {
		t.Fatalf("saving script: %v", err)
	}

	return &scriptHarness{
		harness: h,
		scripts: scripts,
		ai:      ai,
		svc:     service.NewScriptService(scripts, facts, refs, h.repo, ai, h.log, clock.New()),
		id:      v.ID,
	}
}

func (s *scriptHarness) voice(t *testing.T) string {
	t.Helper()
	script, _, err := s.scripts.Load(s.id)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	return script.Beats[0].Voice
}

func TestAnEditIsRecheckedBeforeItIsSaved(t *testing.T) {
	s := newScriptHarness(t)
	s.ai.Violations = []domain.Violation{{Rule: "UNGROUNDED_NUMBER", Beat: 1, Message: "says 1775"}}

	view, err := s.svc.UpdateBeat(context.Background(), s.id, 1, "In 1775, sandals.", "", "", nil)
	if err != nil {
		t.Fatalf("UpdateBeat: %v", err)
	}

	if s.ai.ValidateCalls != 1 {
		t.Fatalf("ValidateCalls = %d, want 1 -- an edit must be re-checked (case 1)", s.ai.ValidateCalls)
	}
	if view.Readiness.CanApprove {
		t.Fatal("the worker reported a violation, but the gate would open (case 3)")
	}
	saved, _, _ := s.scripts.Load(s.id)
	if len(saved.Violations) != 1 {
		t.Fatalf("saved %d violations, want the worker's 1 -- Gate C reads them from disk", len(saved.Violations))
	}
}

func TestAnEditIsRefusedWhenTheWorkerCannotCheckIt(t *testing.T) {
	s := newScriptHarness(t)
	s.ai.ValidateErr = errors.New("connection refused")

	_, err := s.svc.UpdateBeat(context.Background(), s.id, 1, "In 1775, sandals.", "", "", nil)

	if err == nil {
		t.Fatal("the edit was accepted with nobody to check it (case 2)")
	}
	if got := s.voice(t); got != "In 1774, sandals." {
		t.Fatalf("the file changed to %q although the edit was refused (case 2)", got)
	}
}

func TestAnEditToAMissingBeatWritesNothing(t *testing.T) {
	s := newScriptHarness(t)

	_, err := s.svc.UpdateBeat(context.Background(), s.id, 7, "anything", "", "", nil)

	if !errors.Is(err, domain.ErrNotFound) {
		t.Fatalf("err = %v, want ErrNotFound (case 4)", err)
	}
	if s.ai.ValidateCalls != 0 {
		t.Fatal("a failed edit should not reach the worker")
	}
}

func TestAnApprovedScriptRefusesEdits(t *testing.T) {
	s := newScriptHarness(t)
	s.forceStatus(t, s.id, domain.StatusScriptApproved)

	_, err := s.svc.UpdateBeat(context.Background(), s.id, 1, "In 1774, new words.", "", "", nil)

	if !errors.Is(err, domain.ErrGateClosed) {
		t.Fatalf("err = %v, want ErrGateClosed (case 5)", err)
	}
}

func TestAComparisonCanBeTakenOutOfABeat(t *testing.T) {
	s := newScriptHarness(t)
	script, _, _ := s.scripts.Load(s.id)
	script.Beats[0].RefIDs = []string{"r1"}
	if err := s.scripts.Save(s.id, script); err != nil {
		t.Fatalf("Save: %v", err)
	}

	view, err := s.svc.UpdateBeat(context.Background(), s.id, 1, "In 1774, sandals.", "", "", []string{})
	if err != nil {
		t.Fatalf("UpdateBeat: %v", err)
	}
	if got := view.Script.Beats[0].RefIDs; len(got) != 0 {
		t.Fatalf("RefIDs = %v, want none -- the reviewer took r1 out (case 6)", got)
	}
	if s.ai.ValidateCalls != 1 {
		t.Fatal("removing a comparison is an edit like any other and must be re-checked")
	}
}
