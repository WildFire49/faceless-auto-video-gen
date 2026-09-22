package domain

import (
	"context"
	"fmt"
	"strings"
)

// Fact is one entry on the timeline (SPEC.md 5.2).
//
// The pairing that matters: Claim is what a narrator says, Evidence is the
// sentence from the source that supports it. Evidence and SourceURL are never
// editable for an extracted fact, because they are the record of where the
// claim came from -- letting a human rewrite them would defeat the verifier
// that produced them.
type Fact struct {
	ID        string
	YearLabel string
	SortYear  int
	Place     string
	Claim     string

	Evidence    string
	SourceURL   string
	SourceTitle string

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
type FactSheet struct {
	Topic   string
	Facts   []Fact
	Sources []FactSource
	// Path is where the sheet lives on disk, shown in the UI so you can open
	// the raw file.
	Path string
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

// EraCount is how many distinct eras the APPROVED facts span.
//
// Gate A requires breadth as well as volume (SPEC.md 5.2): eight facts about
// the 1900s make a dull episode, because the series premise is time travel
// across the whole life of an object.
func (s *FactSheet) EraCount() int {
	seen := make(map[string]struct{})
	for _, f := range s.Facts {
		if f.Approved {
			seen[eraOf(f.SortYear)] = struct{}{}
		}
	}
	return len(seen)
}

// eraOf buckets a year into a broad historical era.
//
// The buckets widen as they go back, because "7000 BC vs 6000 BC" is one era
// to a viewer while "1950 vs 1990" is clearly two. The aim is a rough measure
// of variety, not a historian's periodisation.
func eraOf(year int) string {
	switch {
	case year < -3000:
		return "prehistory"
	case year < -500:
		return "ancient"
	case year < 500:
		return "classical"
	case year < 1400:
		return "medieval"
	case year < 1750:
		return "early-modern"
	case year < 1900:
		return "industrial"
	case year < 1980:
		return "20th-century"
	default:
		return "modern"
	}
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
	Eras       int
}

// CheckGateA applies the Gate A rules (SPEC.md 5.2).
//
// Deliberately in the domain rather than the UI: the CLI, the API and the
// dashboard must all agree about when a fact sheet is good enough, and a rule
// implemented in a React component is a rule only the browser enforces.
func CheckGateA(sheet *FactSheet, minFacts, minEras int) GateAReadiness {
	if sheet == nil {
		return GateAReadiness{Blocker: "no fact sheet yet — run the research step first"}
	}

	approved := sheet.ApprovedCount()
	eras := sheet.EraCount()

	switch {
	case approved < minFacts:
		return GateAReadiness{
			Approved: approved,
			Eras:     eras,
			Blocker: fmt.Sprintf("%d of %d facts approved — tick at least %d",
				approved, len(sheet.Facts), minFacts),
		}
	case eras < minEras:
		return GateAReadiness{
			Approved: approved,
			Eras:     eras,
			Blocker: fmt.Sprintf("approved facts span only %d era(s), need %d — "+
				"approve some from further back or further forward", eras, minEras),
		}
	default:
		return GateAReadiness{CanApprove: true, Approved: approved, Eras: eras}
	}
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
	if strings.TrimSpace(f.YearLabel) == "" {
		return fmt.Errorf("%w: a year label is required", ErrValidation)
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
