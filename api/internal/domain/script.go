package domain

import (
	"context"
	"fmt"
	"strings"
)

// Beat is one ~5 second unit of the video (SPEC.md 5.4).
type Beat struct {
	N             int
	Role          string
	YearStamp     string
	Voice         string
	OnScreenText  string
	VisualPrompts []string
	SFX           string
	Motion        string
	EmphasisWords []string
	FactIDs       []string
	RefIDs        []string
	IsPunch       bool
}

// Violation is one broken script rule. The rules themselves live in ONE place,
// the Python worker (script/rules.py); Go only ever asks it and records the
// answer, so the two services cannot disagree about what is valid.
type Violation struct {
	Rule    string
	Beat    int // 1-based; 0 for the script as a whole
	Message string
}

// Script is script.json.
type Script struct {
	TitleOptions []string
	ChosenTitle  string
	Description  string
	Hashtags     []string
	Beats        []Beat
	Sources      []string
	Path         string
	Attempts     int
	Violations   []Violation
}

// Beat returns beat n (1-based).
func (s *Script) Beat(n int) (*Beat, bool) {
	for i := range s.Beats {
		if s.Beats[i].N == n {
			return &s.Beats[i], true
		}
	}
	return nil, false
}

// ScriptStore persists script.json. The worker writes it once; Go owns it
// from then on, because every later change is a human decision at Gate C.
type ScriptStore interface {
	Load(videoID string) (*Script, bool, error)
	Save(videoID string, script *Script) error
}

// ScriptFact is an approved fact as the script writer sees it -- with its
// evidence, because a beat may use a number the quote has and the one-line
// claim left out.
type ScriptFact struct {
	ID, Label, Claim, Evidence, Context, SourceURL, Group string
}

// ScriptReference is a comparison selected at Gate B.
type ScriptReference struct {
	ID, Reference, Comparison, LinkedFactID string
}

// ScriptRequest is what the worker needs to write a script.
type ScriptRequest struct {
	VideoID string
	Topic   string
	// Angle steers tone and emphasis only; it is never a source of facts.
	Angle      string
	Facts      []ScriptFact
	References []ScriptReference
}

// ScriptResult summarises what the script step produced.
type ScriptResult struct {
	BeatCount      int
	Attempts       int
	ViolationCount int
	ScriptJSONPath string
}

// ScriptWriter is the worker's script port. Separate from AIEngine so each
// interface stays small (SPEC.md 14.4): a service that only validates never
// sees research.
type ScriptWriter interface {
	GenerateScript(ctx context.Context, req ScriptRequest, report func(Progress)) (*ScriptResult, error)
	// ValidateScript returns every rule the script breaks. No model runs.
	ValidateScript(ctx context.Context, script *Script, facts []ScriptFact, refs []ScriptReference) ([]Violation, error)
}

// ScriptInputs selects what the script writer may see: facts a human
// APPROVED at Gate A, and comparisons SELECTED at Gate B whose fact is among
// them. Anything else reaching the writer could be narrated without a human
// ever having accepted it.
func ScriptInputs(facts *FactSheet, refs *ReferenceSheet) ([]ScriptFact, []ScriptReference) {
	approved := map[string]bool{}
	var outFacts []ScriptFact
	for _, f := range facts.Facts {
		if !f.Approved {
			continue
		}
		approved[f.ID] = true
		outFacts = append(outFacts, ScriptFact{
			ID: f.ID, Label: f.Label, Claim: f.Claim, Evidence: f.Evidence,
			Context: f.Context, SourceURL: f.SourceURL, Group: f.Group,
		})
	}

	var outRefs []ScriptReference
	if refs != nil {
		for _, p := range refs.Proposals {
			if p.Selected && approved[p.LinkedFactID] {
				outRefs = append(outRefs, ScriptReference{
					ID: p.ID, Reference: p.Reference, Comparison: p.Comparison, LinkedFactID: p.LinkedFactID,
				})
			}
		}
	}
	return outFacts, outRefs
}

// GateCReadiness says whether Gate C may be approved, and if not, why.
type GateCReadiness struct {
	CanApprove bool
	Blocker    string
}

// CheckGateC: a script opens its gate only with no rule broken and a title
// chosen. The violations are the worker's latest verdict, refreshed after
// every edit, so this never trusts a stale answer.
func CheckGateC(s *Script) GateCReadiness {
	if n := len(s.Violations); n > 0 {
		first := s.Violations[0]
		where := "the script"
		if first.Beat > 0 {
			where = fmt.Sprintf("beat %d", first.Beat)
		}
		plural := "s"
		if n == 1 {
			plural = ""
		}
		return GateCReadiness{Blocker: fmt.Sprintf(
			"%d rule%s broken -- first, %s %s", n, plural, where, first.Message)}
	}
	if strings.TrimSpace(s.ChosenTitle) == "" {
		return GateCReadiness{Blocker: "choose a title"}
	}
	return GateCReadiness{CanApprove: true}
}
