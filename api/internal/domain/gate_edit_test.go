package domain

import (
	"errors"
	"testing"
)

// A gate's sheet may be edited only while the video is waiting at that gate.
//
// Found by reviewing the dashboard: an approved gate still offered its edit
// controls, and the API honoured them. Approve Gate A, then untick a fact or
// add one, and relevance and the script would run on a sheet no human had
// approved in that form. The review log recorded an "edit" -- but the gate
// approval it followed no longer described what was downstream.
//
// The ways this can go wrong, written before the code:
//
//  1. editing at the gate                       -> allowed (the whole point)
//  2. editing after that gate was approved      -> refused
//  3. editing an earlier gate from a later one  -> refused
//  4. editing while the step that WRITES the sheet is still running
//     (researching, finding refs)               -> refused; the step is about
//     to overwrite it
//  5. editing a failed video                    -> refused; retry first
//  6. a later gate SENT IT BACK to this one     -> allowed again; that is what
//     sending back is for
//  7. an unknown gate                           -> a validation error, not a
//     silent yes
func TestRequireOpenGate(t *testing.T) {
	tests := []struct {
		name   string
		status Status
		gate   Gate
		open   bool
	}{
		{"1 at gate A", StatusFactsReady, GateA, true},
		{"1 at gate B", StatusRefsReady, GateB, true},
		{"2 A after approval", StatusFactsApproved, GateA, false},
		{"2 B after approval", StatusRefsApproved, GateB, false},
		{"3 A from gate B", StatusRefsReady, GateA, false},
		{"3 A from much later", StatusScriptReady, GateA, false},
		{"4 A while researching", StatusResearching, GateA, false},
		{"4 B while finding refs", StatusFindingRefs, GateB, false},
		{"4 B before it exists", StatusFactsReady, GateB, false},
		{"5 A on a failed video", StatusError, GateA, false},
		// 6 is case 1 reached a different way: a rejection moves the status
		// back to facts_ready, and the rule reads only the status.
		{"6 A after being sent back", StatusFactsReady, GateA, true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := RequireOpenGate(&Video{ID: "iron", Status: tt.status}, tt.gate)

			if tt.open && err != nil {
				t.Fatalf("status %s, gate %s: want editable, got %v", tt.status, tt.gate, err)
			}
			if !tt.open && !errors.Is(err, ErrGateClosed) {
				t.Fatalf("status %s, gate %s: want ErrGateClosed, got %v", tt.status, tt.gate, err)
			}
		})
	}
}

func TestRequireOpenGateUnknownGate(t *testing.T) {
	err := RequireOpenGate(&Video{ID: "iron", Status: StatusFactsReady}, Gate("Z"))

	if !errors.Is(err, ErrValidation) {
		t.Fatalf("unknown gate: want ErrValidation, got %v", err)
	}
	if errors.Is(err, ErrGateClosed) {
		t.Fatal("an unknown gate is a caller mistake, not a closed gate")
	}
}
