package domain

import (
	"context"
	"fmt"
	"strings"
)

// Fact is one verified item (SPEC.md 5.2).
//
// Format-neutral by design: for a timeline Label is a year and SortKey orders
// chronologically; for a myth-buster Label is the belief and SortKey is how
// surprising the correction is. Go never needs to know which -- it stores,
// counts and serves whatever the worker produced.
//
// The pairing that matters, and never varies: Claim is what a narrator says,
// Evidence is the sentence from the source that supports it. Evidence and
// SourceURL are never editable for an extracted fact, because they are the
// record of where the claim came from -- letting a human rewrite them would
// defeat the verifier that produced them.
type Fact struct {
	ID      string
	Label   string
	SortKey int64
	Context string
	Claim   string

	Evidence    string
	SourceURL   string
	SourceTitle string

	// Group is the variety bucket, computed by the format: "industrial" for a
	// timeline, "health" for a myth-buster. Go only ever counts distinct
	// values, so their meaning stays the format's business.
	Group string

	Confidence string
	Conflict   bool
	Approved   bool
	// MatchScore is how closely the evidence matched the source, 0..1.
	MatchScore float64
	// AddedByHuman marks facts a person supplied at Gate A. Those skip the
	// evidence verifier, so it matters that they stay distinguishable.
	AddedByHuman bool
}

// FactSource is a document the facts were drawn from.
type FactSource struct {
	URL       string
	Title     string
	Fetcher   string
	CharCount int
}

// FactSheet is a video's research output.
//
// It carries its own review thresholds. That is what lets the gate machinery
// enforce a format's rules without knowing which formats exist -- adding a
// format in Python never touches Go (SPEC.md 14.2).
type FactSheet struct {
	Topic   string
	Facts   []Fact
	Sources []FactSource
	// Path is where the sheet lives on disk, shown in the UI so you can open
	// the raw file.
	Path string

	// Format is the content format that produced this sheet.
	Format string
	// GroupNoun is what a group is called here: "era", "domain", "category".
	GroupNoun string
	// MinItems and MinGroups are this format's gate thresholds.
	MinItems  int
	MinGroups int

	// CandidatesExtracted and CandidatesRejected measure the MODEL: a large
	// gap means it invents on this task. Surfaced at Gate A.
	CandidatesExtracted int
	CandidatesRejected  int
	Rejections          []string
}

// FactStore reads and writes fact sheets.
type FactStore interface {
	// Load returns the sheet, and false when the video has not been
	// researched yet. Absence is not an error.
	Load(videoID string) (*FactSheet, bool, error)
	Save(videoID string, sheet *FactSheet) error
}

// Find returns a fact by id.
func (s *FactSheet) Find(id string) (*Fact, bool) {
	for i := range s.Facts {
		if s.Facts[i].ID == id {
			return &s.Facts[i], true
		}
	}
	return nil, false
}

// ApprovedCount is how many facts the human has ticked.
func (s *FactSheet) ApprovedCount() int {
	n := 0
	for _, f := range s.Facts {
		if f.Approved {
			n++
		}
	}
	return n
}

// GroupCount is how many distinct groups the APPROVED facts span.
//
// Gate A requires breadth as well as volume (SPEC.md 5.2): eight facts about
// the 1900s make a dull episode. What counts as a group is the format's
// decision, already recorded on each fact -- Go just counts them.
func (s *FactSheet) GroupCount() int {
	seen := make(map[string]struct{})
	for _, f := range s.Facts {
		if f.Approved && f.Group != "" {
			seen[f.Group] = struct{}{}
		}
	}
	return len(seen)
}

// NextFactID returns an unused fact id for a human-added fact.
//
// New ids continue past the highest existing number rather than filling gaps,
// so an id never silently refers to a different fact than it did yesterday --
// which matters because the script will reference these ids by name.
func (s *FactSheet) NextFactID() string {
	highest := 0
	for _, f := range s.Facts {
		var n int
		if _, err := fmt.Sscanf(f.ID, "f%d", &n); err == nil && n > highest {
			highest = n
		}
	}
	return fmt.Sprintf("f%d", highest+1)
}

// GateAReadiness reports whether Gate A can be approved, and why not.
type GateAReadiness struct {
	CanApprove bool
	Blocker    string
	Approved   int
	Groups     int
	GroupNoun  string
}

// CheckGateA applies the Gate A rules (SPEC.md 5.2).
//
// The thresholds come from the SHEET, which carries the rules its own format
// declared. That is what makes this function work unchanged for a format
// written after it.
//
// Deliberately in the domain rather than the UI: the CLI, the API and the
// dashboard must all agree about when a fact sheet is good enough, and a rule
// implemented in a React component is a rule only the browser enforces.
func CheckGateA(sheet *FactSheet) GateAReadiness {
	if sheet == nil {
		return GateAReadiness{Blocker: "no fact sheet yet — run the research step first"}
	}

	minItems, minGroups, noun := sheet.MinItems, sheet.MinGroups, sheet.GroupNoun

	// A sheet written by an older build, or edited by hand, must not become
	// approvable with nothing in it.
	if minItems <= 0 {
		minItems = 8
	}
	if minGroups <= 0 {
		minGroups = 4
	}
	if noun == "" {
		noun = "group"
	}

	approved := sheet.ApprovedCount()
	groups := sheet.GroupCount()

	readiness := GateAReadiness{Approved: approved, Groups: groups, GroupNoun: noun}

	switch {
	case approved < minItems:
		readiness.Blocker = fmt.Sprintf("%d of %d facts approved — tick at least %d",
			approved, len(sheet.Facts), minItems)
	case groups < minGroups:
		readiness.Blocker = fmt.Sprintf(
			"approved facts span only %d %s(s), need %d — approve a wider spread",
			groups, noun, minGroups)
	default:
		readiness.CanApprove = true
	}
	return readiness
}

// ValidateHumanFact checks a fact a person typed at Gate A.
//
// Human facts skip the evidence verifier -- a person citing a book is the
// authority the verifier substitutes for -- but a source is still required,
// because SPEC.md 5.2 permits no unsourced claim anywhere in the pipeline.
func ValidateHumanFact(f Fact) error {
	if strings.TrimSpace(f.Claim) == "" {
		return fmt.Errorf("%w: a claim is required", ErrValidation)
	}
	if strings.TrimSpace(f.Label) == "" {
		return fmt.Errorf("%w: a label is required", ErrValidation)
	}

	source := strings.TrimSpace(f.SourceURL)
	if source == "" {
		return fmt.Errorf("%w: a source URL is required — no unsourced facts", ErrValidation)
	}
	if !strings.HasPrefix(source, "http://") && !strings.HasPrefix(source, "https://") {
		return fmt.Errorf("%w: the source must be a URL starting with http:// or https://", ErrValidation)
	}
	return nil
}

// FactsService is implemented in the service layer; declared here so the
// transport layer depends on the core rather than on a concrete type.
type FactsReader interface {
	GetFacts(ctx context.Context, videoID string) (*FactSheet, GateAReadiness, bool, error)
}
