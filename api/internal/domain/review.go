package domain

import "time"

// ReviewAction is what a human did at a gate.
type ReviewAction string

const (
	ActionApprove ReviewAction = "approve"
	ActionReject  ReviewAction = "reject"
	ActionEdit    ReviewAction = "edit"
	ActionRetry   ReviewAction = "retry"
	ActionCreate  ReviewAction = "create"
)

// ReviewEntry is one human decision, appended to the review log.
//
// This log is the project's proof that a person made the creative calls
// (SPEC.md 8.4, 7). It is append-only and never edited.
type ReviewEntry struct {
	ID      int64
	VideoID string
	At      time.Time

	// Gate is GateNone for actions that are not gate decisions, such as
	// creating a video or retrying a failed step.
	Gate   Gate
	Action ReviewAction

	FromStatus Status
	ToStatus   Status

	Note string
	// Diff is JSON describing what the human changed, for edit actions.
	// Empty for approvals and rejections.
	Diff string
}
