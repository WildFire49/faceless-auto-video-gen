package domain

import (
	"fmt"
	"strings"
	"time"
)

// ReferenceKind says where a comparison came from.
type ReferenceKind string

const (
	// KindEvergreen is curated in config/reference_bank.yaml. No expiry.
	KindEvergreen ReferenceKind = "evergreen"
	// KindHot came from a live trend source and goes stale.
	KindHot ReferenceKind = "hot"
	// KindManual was typed in by the human at Gate B.
	KindManual ReferenceKind = "manual"
)

// Proposal is one suggested modern comparison (SPEC.md 5.3).
//
// The pairing that matters: Comparison is what a narrator says, LinkedFactID
// is the approved fact it attaches to. A comparison floating free of a fact
// has nothing to be funny about, and would smuggle unapproved material into
// the script.
type Proposal struct {
	ID        string
	Reference string
	Kind      ReferenceKind

	LinkedFactID string
	Comparison   string
	WhyFunny     string
	// AccuracyNote states what is being compared -- look, price, hype,
	// behaviour -- so a reviewer can confirm it is not a claim about the brand.
	AccuracyNote string

	// FreshUntil is when a HOT reference stops being current. Zero for
	// evergreen ones, which never expire.
	FreshUntil time.Time
	Source     string
	Selected   bool
}

// IsStale reports whether a hot reference has passed its date.
func (p *Proposal) IsStale(now time.Time) bool {
	return !p.FreshUntil.IsZero() && p.FreshUntil.Before(now)
}

// ReferenceSheet is a video's proposed comparisons.
//
// Like the fact sheet, it carries its own gate rule -- MaxSelectable -- so the
// gate machinery enforces the limit without a second source of truth.
type ReferenceSheet struct {
	Topic     string
	Proposals []Proposal
	Path      string

	// MaxSelectable is the hard ceiling on selections (SPEC.md 5.3).
	MaxSelectable int

	TrendSources    []string
	TrendsFetchedAt string

	// CandidatesGenerated and CandidatesRejected measure how much of what the
	// model wrote was unusable, the same signal the fact sheet carries.
	CandidatesGenerated int
	CandidatesRejected  int
	Rejections          []string
}

// ReferenceStore reads and writes reference sheets.
type ReferenceStore interface {
	Load(videoID string) (*ReferenceSheet, bool, error)
	Save(videoID string, sheet *ReferenceSheet) error
}

// Find returns a proposal by id.
func (s *ReferenceSheet) Find(id string) (*Proposal, bool) {
	for i := range s.Proposals {
		if s.Proposals[i].ID == id {
			return &s.Proposals[i], true
		}
	}
	return nil, false
}

// SelectedCount is how many comparisons the human has ticked.
func (s *ReferenceSheet) SelectedCount() int {
	n := 0
	for _, p := range s.Proposals {
		if p.Selected {
			n++
		}
	}
	return n
}

// StaleSelected lists selected hot references that have expired.
//
// Not fatal at Gate B -- you may still want one -- but Gate F warns, so it is
// better to know now (SPEC.md 5.3).
func (s *ReferenceSheet) StaleSelected(now time.Time) []string {
	var ids []string
	for i := range s.Proposals {
		if s.Proposals[i].Selected && s.Proposals[i].IsStale(now) {
			ids = append(ids, s.Proposals[i].ID)
		}
	}
	return ids
}

// NextProposalID returns an unused id for a human-written comparison.
func (s *ReferenceSheet) NextProposalID() string {
	highest := 0
	for _, p := range s.Proposals {
		var n int
		if _, err := fmt.Sscanf(p.ID, "r%d", &n); err == nil && n > highest {
			highest = n
		}
	}
	return fmt.Sprintf("r%d", highest+1)
}

// GateBReadiness reports whether Gate B can be approved, and why not.
type GateBReadiness struct {
	CanApprove    bool
	Blocker       string
	Selected      int
	MaxSelectable int
	StaleIDs      []string
}

// CheckGateB applies the Gate B rules (SPEC.md 5.3).
//
// The limit comes from the SHEET, which carries the rule the worker's config
// declared, so there is one source of truth for "how many is too many".
func CheckGateB(sheet *ReferenceSheet, now time.Time) GateBReadiness {
	if sheet == nil {
		return GateBReadiness{Blocker: "no comparisons yet — run the relevance step first"}
	}

	limit := sheet.MaxSelectable
	if limit <= 0 {
		limit = DefaultMaxReferences
	}

	selected := sheet.SelectedCount()
	readiness := GateBReadiness{
		Selected:      selected,
		MaxSelectable: limit,
		StaleIDs:      sheet.StaleSelected(now),
	}

	switch {
	case selected > limit:
		// Cannot normally happen -- SelectProposal refuses -- but a
		// hand-edited file must not slip past the limit.
		readiness.Blocker = fmt.Sprintf("%d selected, the limit is %d", selected, limit)
	default:
		// Zero selected IS allowed. A video with no modern comparisons is a
		// straight history video, which is a legitimate episode; SPEC.md 5.3
		// caps how many you may have, never requires one.
		readiness.CanApprove = true
	}
	return readiness
}

// DefaultMaxReferences is the fallback when a sheet does not declare one
// (SPEC.md 5.3: max 3 modern references per video).
const DefaultMaxReferences = 3

// ErrTooManyReferences is returned when a selection would exceed the limit.
//
// A distinct sentinel rather than plain ErrValidation, because the dashboard
// shows it differently: the fix is to untick something, not to correct input.
var ErrTooManyReferences = fmt.Errorf("%w: too many references selected", ErrValidation)

// SelectProposal ticks or unticks a comparison, enforcing the limit.
//
// Refusing rather than silently dropping one: three is a deliberate ceiling on
// how much of a video can be "basically a modern brand" before it stops being
// history, and quietly rearranging the human's choices would hide that.
func SelectProposal(sheet *ReferenceSheet, id string, selected bool) error {
	proposal, found := sheet.Find(id)
	if !found {
		return fmt.Errorf("%w: proposal %q", ErrNotFound, id)
	}

	limit := sheet.MaxSelectable
	if limit <= 0 {
		limit = DefaultMaxReferences
	}

	if selected && !proposal.Selected && sheet.SelectedCount() >= limit {
		return fmt.Errorf("%w: %d already selected, the limit is %d — untick one first",
			ErrTooManyReferences, sheet.SelectedCount(), limit)
	}

	proposal.Selected = selected
	return nil
}

// ValidateHumanProposal checks a comparison a person wrote at Gate B.
//
// A human-written comparison skips the model's safety rules -- the person
// typing it IS the judgement those rules approximate -- but it still must
// attach to an approved fact, because that constraint is about the script's
// integrity rather than about taste.
func ValidateHumanProposal(p Proposal, approvedFactIDs map[string]struct{}) error {
	if strings.TrimSpace(p.Comparison) == "" {
		return fmt.Errorf("%w: a comparison is required", ErrValidation)
	}
	if strings.TrimSpace(p.Reference) == "" {
		return fmt.Errorf("%w: name the modern thing being compared to", ErrValidation)
	}

	factID := strings.TrimSpace(p.LinkedFactID)
	if factID == "" {
		return fmt.Errorf("%w: a comparison must attach to an approved fact", ErrValidation)
	}
	if _, ok := approvedFactIDs[factID]; !ok {
		return fmt.Errorf("%w: %q is not an approved fact", ErrValidation, factID)
	}
	return nil
}
