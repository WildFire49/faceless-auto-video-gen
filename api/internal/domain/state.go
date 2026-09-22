package domain

import "fmt"

// The state machine (SPEC.md 2.3).
//
// THE CENTRAL IDEA: transitions come in two kinds, and they are stored in two
// separate tables.
//
//   - automatic -- a pipeline step finished, e.g. researching -> facts_ready
//   - gate      -- a human approved, e.g. facts_ready -> facts_approved
//
// `Transition` can only perform automatic moves, and `ApproveGate` can only
// perform gate moves. A pipeline step therefore *cannot* produce a
// gate-crossing state change, however buggy it is: the transition it would
// need is not in the table it is allowed to consult.
//
// That is what makes "human review gates can never be skipped or
// auto-approved" (CLAUDE.md) a structural property rather than a rule someone
// has to remember.

// automatic maps each status to the statuses a pipeline step may move it to.
var automatic = map[Status][]Status{
	StatusQueued: {StatusResearching},

	StatusResearching:   {StatusFactsReady, StatusError},
	StatusFactsApproved: {StatusFindingRefs},

	StatusFindingRefs:  {StatusRefsReady, StatusError},
	StatusRefsApproved: {StatusScripting},

	StatusScripting:      {StatusScriptReady, StatusError},
	StatusScriptApproved: {StatusVoicing},

	StatusVoicing:       {StatusVoiceReady, StatusError},
	StatusVoiceApproved: {StatusImaging},

	StatusImaging:            {StatusStoryboardReady, StatusError},
	StatusStoryboardApproved: {StatusRendering},

	StatusRendering:     {StatusRenderReady, StatusError},
	StatusFinalApproved: {StatusUploading},

	StatusUploading: {StatusUploadedPrivate, StatusError},

	// uploaded_private -> published is NOT here. A human publishes on
	// YouTube; the machine only observes that it happened.
	StatusPublished: {StatusAnalyticsCollected},
}

// gateTransition describes one human review point.
type gateTransition struct {
	Gate Gate
	// From is the status that is waiting for this gate.
	From Status
	// To is where approval moves it.
	To Status
}

// gates are the six review points, in pipeline order (SPEC.md 2.2).
var gates = []gateTransition{
	{GateA, StatusFactsReady, StatusFactsApproved},
	{GateB, StatusRefsReady, StatusRefsApproved},
	{GateC, StatusScriptReady, StatusScriptApproved},
	{GateD, StatusVoiceReady, StatusVoiceApproved},
	{GateE, StatusStoryboardReady, StatusStoryboardApproved},
	{GateF, StatusRenderReady, StatusFinalApproved},
}

// pipelineOrder lists every status in forward order, so "is X earlier than Y"
// is answerable. Used to keep a rejection from sending a video *forwards*.
var pipelineOrder = []Status{
	StatusQueued,
	StatusResearching, StatusFactsReady, StatusFactsApproved,
	StatusFindingRefs, StatusRefsReady, StatusRefsApproved,
	StatusScripting, StatusScriptReady, StatusScriptApproved,
	StatusVoicing, StatusVoiceReady, StatusVoiceApproved,
	StatusImaging, StatusStoryboardReady, StatusStoryboardApproved,
	StatusRendering, StatusRenderReady, StatusFinalApproved,
	StatusUploading, StatusUploadedPrivate, StatusPublished,
	StatusAnalyticsCollected,
}

var orderIndex = func() map[Status]int {
	m := make(map[Status]int, len(pipelineOrder))
	for i, s := range pipelineOrder {
		m[s] = i
	}
	return m
}()

// KnownStatus reports whether s is a status this system understands.
func KnownStatus(s Status) bool {
	if s == StatusError {
		return true
	}
	_, ok := orderIndex[s]
	return ok
}

// CanTransition reports whether a pipeline step may move from -> to.
func CanTransition(from, to Status) bool {
	for _, allowed := range automatic[from] {
		if allowed == to {
			return true
		}
	}
	return false
}

// Transition performs an automatic (non-gate) state change.
//
// It returns ErrIllegalTransition for anything not in the automatic table,
// which includes every gate crossing. Approving a gate goes through
// ApproveGate instead.
func Transition(v *Video, to Status) error {
	if v == nil {
		return fmt.Errorf("%w: nil video", ErrIllegalTransition)
	}
	if !KnownStatus(to) {
		return fmt.Errorf("%w: unknown target status %q", ErrIllegalTransition, to)
	}
	if !CanTransition(v.Status, to) {
		if g, ok := GateFor(v.Status); ok && GateApprovalTarget(g) == to {
			return fmt.Errorf(
				"%w: %s -> %s crosses %s and needs human approval",
				ErrIllegalTransition, v.Status, to, g)
		}
		return fmt.Errorf("%w: %s -> %s", ErrIllegalTransition, v.Status, to)
	}

	v.Status = to

	// Moving forward clears a previous rejection: it describes the last
	// rejection that still matters, and this one has now been acted on.
	if to != StatusError {
		v.RejectedTo = ""
		v.RejectNote = ""
	}
	return nil
}

// NextAutomatic returns the status a successful pipeline step should move this
// video to, and whether such a step exists.
//
// It skips StatusError, which is a failure outcome rather than a destination
// anyone aims for.
func NextAutomatic(from Status) (Status, bool) {
	for _, to := range automatic[from] {
		if to != StatusError {
			return to, true
		}
	}
	return "", false
}

// IsEarlier reports whether a comes strictly before b in the pipeline.
func IsEarlier(a, b Status) bool {
	ia, oka := orderIndex[a]
	ib, okb := orderIndex[b]
	return oka && okb && ia < ib
}

// IsTerminal reports whether nothing further will happen to this video on its
// own -- either it is finished, or it is waiting on a human.
func IsTerminal(s Status) bool {
	if s == StatusError {
		return true
	}
	if _, waiting := GateFor(s); waiting {
		return true
	}
	// uploaded_private waits for a human to publish on YouTube.
	if s == StatusUploadedPrivate || s == StatusAnalyticsCollected {
		return true
	}
	_, hasNext := NextAutomatic(s)
	return !hasNext
}

// Fail moves a video to the error state, remembering where to resume from.
//
// Any status can fail, so this is not checked against the transition table.
// RetryFrom is the status the video was in when the step began, so a retry
// re-runs that step rather than guessing.
func Fail(v *Video, message string) {
	if v.Status != StatusError {
		v.RetryFrom = v.Status
	}
	v.Status = StatusError
	v.Error = message
}

// Retry resumes a failed video from where it left off.
func Retry(v *Video) error {
	if v.Status != StatusError {
		return fmt.Errorf("%w: video is %s, not %s", ErrIllegalTransition, v.Status, StatusError)
	}
	resume := v.RetryFrom
	if resume == "" || !KnownStatus(resume) {
		// An error with no usable resume point sends the video back to the
		// start rather than leaving it stuck forever.
		resume = StatusQueued
	}
	v.Status = resume
	v.Error = ""
	v.RetryFrom = ""
	return nil
}
