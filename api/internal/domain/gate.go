package domain

import "fmt"

// Gate is one of the six human review points (SPEC.md 2.2).
type Gate string

const (
	GateNone Gate = ""
	GateA    Gate = "A" // facts
	GateB    Gate = "B" // references
	GateC    Gate = "C" // script
	GateD    Gate = "D" // voice
	GateE    Gate = "E" // storyboard
	GateF    Gate = "F" // final video
)

// Label is the gate's human name, used in the CLI and the dashboard.
func (g Gate) Label() string {
	switch g {
	case GateA:
		return "A — Facts"
	case GateB:
		return "B — References"
	case GateC:
		return "C — Script"
	case GateD:
		return "D — Voice"
	case GateE:
		return "E — Storyboard"
	case GateF:
		return "F — Final video"
	default:
		return "—"
	}
}

func (g Gate) String() string {
	if g == GateNone {
		return "none"
	}
	return "Gate " + string(g)
}

// GateFor returns the gate a video in this status is waiting on.
//
// The bool is false for any status that is not awaiting review, which is most
// of them -- so callers cannot accidentally treat "mid-render" as "waiting for
// a human".
func GateFor(s Status) (Gate, bool) {
	for _, gt := range gates {
		if gt.From == s {
			return gt.Gate, true
		}
	}
	return GateNone, false
}

// GateApprovalTarget returns the status approving this gate moves a video to.
func GateApprovalTarget(g Gate) Status {
	for _, gt := range gates {
		if gt.Gate == g {
			return gt.To
		}
	}
	return ""
}

// ApproveGate records a human approval and advances the video.
//
// This is the only function that can perform a gate-crossing transition, and
// the only way a video ever passes a review point.
//
// The caller must name the gate it believes it is approving, and it must match
// the video's current state. That is not ceremony: it stops a stale browser
// tab, or a second operator, from approving a gate the human is not actually
// looking at.
func ApproveGate(v *Video, g Gate) error {
	if v == nil {
		return fmt.Errorf("%w: nil video", ErrIllegalTransition)
	}

	waiting, isWaiting := GateFor(v.Status)
	if !isWaiting {
		return fmt.Errorf("%w: video is %s and is not awaiting any gate",
			ErrIllegalTransition, v.Status)
	}
	if waiting != g {
		return fmt.Errorf("%w: video is awaiting %s, not %s",
			ErrIllegalTransition, waiting, g)
	}

	v.Status = GateApprovalTarget(g)
	v.RejectedTo = ""
	v.RejectNote = ""
	return nil
}

// RejectGate sends a video back to an earlier state with a note.
//
// Rules, all enforced here rather than in the handler:
//   - the video must actually be at the named gate
//   - backTo must be a real status, and strictly earlier in the pipeline
//   - the note is required; a rejection without a reason is useless to
//     whoever picks the video up later, including you next week
func RejectGate(v *Video, g Gate, backTo Status, note string) error {
	if v == nil {
		return fmt.Errorf("%w: nil video", ErrIllegalTransition)
	}

	waiting, isWaiting := GateFor(v.Status)
	if !isWaiting {
		return fmt.Errorf("%w: video is %s and is not awaiting any gate",
			ErrIllegalTransition, v.Status)
	}
	if waiting != g {
		return fmt.Errorf("%w: video is awaiting %s, not %s",
			ErrIllegalTransition, waiting, g)
	}
	if note == "" {
		return fmt.Errorf("%w: a rejection note is required", ErrValidation)
	}
	if !KnownStatus(backTo) || backTo == StatusError {
		return fmt.Errorf("%w: %q is not a status a video can be sent back to",
			ErrValidation, backTo)
	}
	if !IsEarlier(backTo, v.Status) {
		return fmt.Errorf("%w: %s is not earlier than %s; a rejection can only send a video back",
			ErrValidation, backTo, v.Status)
	}

	v.Status = backTo
	v.RejectedTo = backTo
	v.RejectNote = note
	return nil
}

// AllGates returns the six gates in pipeline order, for UI progress
// indicators and for the CLI.
func AllGates() []Gate {
	out := make([]Gate, 0, len(gates))
	for _, gt := range gates {
		out = append(out, gt.Gate)
	}
	return out
}

// GateWaitingStatus returns the status that waits on the given gate -- the
// inverse of GateFor. Used to offer sensible "send back to" options.
func GateWaitingStatus(g Gate) (Status, bool) {
	for _, gt := range gates {
		if gt.Gate == g {
			return gt.From, true
		}
	}
	return "", false
}
