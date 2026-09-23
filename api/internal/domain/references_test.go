package domain_test

import (
	"errors"
	"testing"
	"time"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
)

// The rule this file exists to protect: at most three modern references per
// video (SPEC.md 5.3). It is a ceiling on how much of a history video can be
// "basically a modern brand" before it stops being history.
//
// Failure modes, written before the code:
//
//   - a fourth selection slips through
//   - the limit is silently enforced by dropping someone's earlier choice
//   - unticking then re-ticking miscounts
//   - a hand-edited file arrives already over the limit
//   - an expired hot reference is not flagged
//   - a comparison attaches to a fact nobody approved

func sheet(limit int, proposals ...domain.Proposal) *domain.ReferenceSheet {
	return &domain.ReferenceSheet{
		Topic:         "sandals",
		MaxSelectable: limit,
		Proposals:     proposals,
	}
}

func proposal(id string, selected bool) domain.Proposal {
	return domain.Proposal{
		ID:           id,
		Reference:    "Birkenstock-" + id,
		Kind:         domain.KindEvergreen,
		LinkedFactID: "f1",
		Comparison:   "Basically Birkenstocks with spikes.",
		Selected:     selected,
	}
}

func TestSelectingUpToTheLimitWorks(t *testing.T) {
	t.Parallel()

	s := sheet(3, proposal("r1", false), proposal("r2", false), proposal("r3", false))

	for _, id := range []string{"r1", "r2", "r3"} {
		if err := domain.SelectProposal(s, id, true); err != nil {
			t.Fatalf("SelectProposal(%s): %v", id, err)
		}
	}
	if s.SelectedCount() != 3 {
		t.Errorf("selected %d, want 3", s.SelectedCount())
	}
}

func TestTheFourthSelectionIsRefused(t *testing.T) {
	t.Parallel()

	s := sheet(3,
		proposal("r1", true), proposal("r2", true), proposal("r3", true),
		proposal("r4", false),
	)

	err := domain.SelectProposal(s, "r4", true)
	if !errors.Is(err, domain.ErrTooManyReferences) {
		t.Fatalf("selecting a fourth = %v, want ErrTooManyReferences", err)
	}

	// Refused, not silently rearranged: quietly dropping someone's earlier
	// choice would hide the limit rather than explain it.
	if s.SelectedCount() != 3 {
		t.Errorf("selected %d after a refused selection, want 3", s.SelectedCount())
	}
	if p, _ := s.Find("r4"); p.Selected {
		t.Error("r4 was selected despite the refusal")
	}
	if p, _ := s.Find("r1"); !p.Selected {
		t.Error("an earlier choice was dropped to make room")
	}
}

func TestUntickingFreesASlot(t *testing.T) {
	t.Parallel()

	s := sheet(3,
		proposal("r1", true), proposal("r2", true), proposal("r3", true),
		proposal("r4", false),
	)

	if err := domain.SelectProposal(s, "r2", false); err != nil {
		t.Fatalf("unticking: %v", err)
	}
	if err := domain.SelectProposal(s, "r4", true); err != nil {
		t.Fatalf("selecting after freeing a slot: %v", err)
	}
	if s.SelectedCount() != 3 {
		t.Errorf("selected %d, want 3", s.SelectedCount())
	}
}

func TestReSelectingAnAlreadySelectedProposalIsNotACountIncrease(t *testing.T) {
	t.Parallel()

	// A double-click, or two browser tabs, must not push the count over.
	s := sheet(3, proposal("r1", true), proposal("r2", true), proposal("r3", true))

	if err := domain.SelectProposal(s, "r1", true); err != nil {
		t.Fatalf("re-selecting: %v", err)
	}
	if s.SelectedCount() != 3 {
		t.Errorf("selected %d, want 3", s.SelectedCount())
	}
}

func TestASheetWithNoLimitFallsBackToTheSpecDefault(t *testing.T) {
	t.Parallel()

	// A sheet written by an older build, or edited by hand, must not become
	// unlimited.
	s := sheet(0,
		proposal("r1", true), proposal("r2", true), proposal("r3", true),
		proposal("r4", false),
	)

	if err := domain.SelectProposal(s, "r4", true); !errors.Is(err, domain.ErrTooManyReferences) {
		t.Errorf("a sheet with no declared limit accepted a fourth: %v", err)
	}
}

func TestGateBCatchesAHandEditedOverLimitSheet(t *testing.T) {
	t.Parallel()

	s := sheet(3,
		proposal("r1", true), proposal("r2", true),
		proposal("r3", true), proposal("r4", true),
	)

	readiness := domain.CheckGateB(s, time.Now())
	if readiness.CanApprove {
		t.Error("Gate B opened with 4 references selected")
	}
	if readiness.Blocker == "" {
		t.Error("no reason given for refusing")
	}
}

func TestGateBAllowsZeroReferences(t *testing.T) {
	t.Parallel()

	// A video with no modern comparisons is a straight history video, which
	// is a legitimate episode. SPEC.md 5.3 caps how many you may have; it
	// never requires one.
	s := sheet(3, proposal("r1", false), proposal("r2", false))

	if !domain.CheckGateB(s, time.Now()).CanApprove {
		t.Error("Gate B refused a video with no modern references")
	}
}

func TestStaleHotReferencesAreFlagged(t *testing.T) {
	t.Parallel()

	now := time.Date(2026, 9, 22, 0, 0, 0, 0, time.UTC)
	yesterday := now.AddDate(0, 0, -1)
	tomorrow := now.AddDate(0, 0, 1)

	expiredSelected := proposal("r1", true)
	expiredSelected.Kind = domain.KindHot
	expiredSelected.FreshUntil = yesterday

	expiredUnselected := proposal("r2", false)
	expiredUnselected.Kind = domain.KindHot
	expiredUnselected.FreshUntil = yesterday

	freshSelected := proposal("r3", true)
	freshSelected.Kind = domain.KindHot
	freshSelected.FreshUntil = tomorrow

	s := sheet(3, expiredSelected, expiredUnselected, freshSelected)
	readiness := domain.CheckGateB(s, now)

	// Only r1: selected AND expired. An unselected stale one is nobody's
	// problem, and a fresh one is fine.
	if len(readiness.StaleIDs) != 1 || readiness.StaleIDs[0] != "r1" {
		t.Errorf("stale = %v, want [r1]", readiness.StaleIDs)
	}
	// Staleness warns; it does not block. You may still want the reference.
	if !readiness.CanApprove {
		t.Error("a stale reference blocked the gate; it should only warn")
	}
}

func TestEvergreenReferencesNeverGoStale(t *testing.T) {
	t.Parallel()

	p := proposal("r1", true) // evergreen, zero FreshUntil
	if p.IsStale(time.Now().AddDate(10, 0, 0)) {
		t.Error("an evergreen reference expired")
	}
}

func TestHumanProposalsMustAttachToAnApprovedFact(t *testing.T) {
	t.Parallel()

	approved := map[string]struct{}{"f1": {}, "f2": {}}

	tests := []struct {
		name string
		p    domain.Proposal
	}{
		{"no comparison", domain.Proposal{Reference: "Crocs", LinkedFactID: "f1"}},
		{"no reference", domain.Proposal{Comparison: "Basically Crocs.", LinkedFactID: "f1"}},
		{"no fact", domain.Proposal{Reference: "Crocs", Comparison: "Basically Crocs."}},
		{
			"unapproved fact",
			domain.Proposal{Reference: "Crocs", Comparison: "Basically Crocs.", LinkedFactID: "f99"},
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			t.Parallel()
			if err := domain.ValidateHumanProposal(tc.p, approved); err == nil {
				t.Errorf("ValidateHumanProposal(%+v) = nil, want an error", tc.p)
			}
		})
	}
}

func TestAValidHumanProposalIsAccepted(t *testing.T) {
	t.Parallel()

	approved := map[string]struct{}{"f1": {}}
	p := domain.Proposal{
		Reference:    "Crocs",
		Comparison:   "The oldest shoes were basically bark Crocs.",
		LinkedFactID: "f1",
	}

	if err := domain.ValidateHumanProposal(p, approved); err != nil {
		t.Errorf("ValidateHumanProposal: %v", err)
	}
}

func TestNextProposalIDContinuesPastTheHighest(t *testing.T) {
	t.Parallel()

	s := sheet(3, proposal("r1", false), proposal("r7", false), proposal("r3", false))
	if got := s.NextProposalID(); got != "r8" {
		t.Errorf("NextProposalID() = %q, want r8 — ids must never be reused", got)
	}
}
