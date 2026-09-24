package domain

import (
	"strings"
	"testing"
)

// What the script writer may see, and when Gate C may open.
//
// The ways this can go wrong, written before the code:
//
//  1. an unapproved fact reaches the script writer    -> it could be narrated
//     although no human ever accepted it
//  2. an unselected comparison reaches it              -> the Gate B choice is
//     ignored
//  3. a selected comparison whose fact is not approved -> a joke about nothing
//     approved; dropped
//  4. no reference sheet at all                        -> a straight history
//     video, not a crash
//  5. Gate C opens with rules still broken             -> refused, naming them
//  6. Gate C opens with no title chosen                -> refused
//  7. a clean script with a title                      -> opens
func TestScriptInputsOnlyCarryWhatAHumanApproved(t *testing.T) {
	facts := &FactSheet{Facts: []Fact{
		{ID: "f1", Label: "1774", Claim: "a", Evidence: "In 1774 ...", Approved: true},
		{ID: "f2", Label: "1902", Claim: "b", Evidence: "In 1902 ...", Approved: false},
		{ID: "f3", Label: "1962", Claim: "c", Evidence: "By 1962 ...", Approved: true},
	}}
	refs := &ReferenceSheet{Proposals: []Proposal{
		{ID: "r1", Reference: "Crocs", LinkedFactID: "f1", Selected: true},
		{ID: "r2", Reference: "Stanley cup", LinkedFactID: "f3", Selected: false},
		{ID: "r3", Reference: "limited drop", LinkedFactID: "f2", Selected: true},
	}}

	gotFacts, gotRefs := ScriptInputs(facts, refs)

	if ids := factIDs(gotFacts); ids != "f1,f3" {
		t.Errorf("facts = %s, want f1,f3 -- f2 was never approved (case 1)", ids)
	}
	if len(gotRefs) != 1 || gotRefs[0].ID != "r1" {
		t.Errorf("refs = %+v, want only r1 (r2 unselected: case 2; r3's fact unapproved: case 3)", gotRefs)
	}
}

func TestScriptInputsWithNoReferenceSheet(t *testing.T) {
	facts := &FactSheet{Facts: []Fact{{ID: "f1", Approved: true}}}

	gotFacts, gotRefs := ScriptInputs(facts, nil)

	if len(gotFacts) != 1 || len(gotRefs) != 0 {
		t.Fatalf("got %d facts and %d refs, want 1 and 0 (case 4)", len(gotFacts), len(gotRefs))
	}
}

func TestCheckGateC(t *testing.T) {
	broken := []Violation{
		{Rule: "UNGROUNDED_NUMBER", Beat: 4, Message: "says 1775"},
		{Rule: "NO_LOOP", Beat: 9, Message: "no echo"},
	}

	tests := []struct {
		name    string
		script  *Script
		open    bool
		blocker string
	}{
		{"5 rules broken", &Script{ChosenTitle: "T", Violations: broken}, false, "2 rules broken"},
		{"6 no title", &Script{}, false, "choose a title"},
		{"7 clean with a title", &Script{ChosenTitle: "Roman Soldiers Wore Spiked Sandals"}, true, ""},
		{"a blank title is no title", &Script{ChosenTitle: "   "}, false, "choose a title"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := CheckGateC(tt.script)
			if got.CanApprove != tt.open {
				t.Fatalf("CanApprove = %v, want %v (%s)", got.CanApprove, tt.open, got.Blocker)
			}
			if !strings.Contains(got.Blocker, tt.blocker) {
				t.Fatalf("Blocker = %q, want it to mention %q", got.Blocker, tt.blocker)
			}
		})
	}
}

func factIDs(facts []ScriptFact) string {
	ids := make([]string, 0, len(facts))
	for _, f := range facts {
		ids = append(ids, f.ID)
	}
	return strings.Join(ids, ",")
}
