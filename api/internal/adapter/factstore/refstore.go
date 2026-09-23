package factstore

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/platform/validate"
)

// RefStore reads and writes projects/<video_id>/references.json.
//
// Same division of labour as the fact sheet: the Python worker writes it once
// when the relevance step finishes, and Go owns it from then on, because every
// later change is a human decision at Gate B (SPEC.md 2.4).
type RefStore struct {
	projectsDir string
}

// NewRefStore wires the store to the projects directory.
func NewRefStore(projectsDir string) *RefStore { return &RefStore{projectsDir: projectsDir} }

type proposalJSON struct {
	ID           string `json:"id"`
	Reference    string `json:"reference"`
	Kind         string `json:"kind"`
	LinkedFactID string `json:"linked_fact_id"`
	Comparison   string `json:"comparison"`
	WhyFunny     string `json:"why_funny"`
	AccuracyNote string `json:"accuracy_note"`
	// A date, not a timestamp: freshness is a day-level judgement and a time
	// of day would imply precision nobody has.
	FreshUntil string `json:"fresh_until"`
	Source     string `json:"source"`
	Selected   bool   `json:"selected"`
}

type refSheetJSON struct {
	Topic         string `json:"topic"`
	MaxSelectable int    `json:"max_selectable"`

	TrendSources    []string `json:"trend_sources"`
	TrendsFetchedAt string   `json:"trends_fetched_at"`

	CandidatesGenerated int      `json:"candidates_generated"`
	CandidatesRejected  int      `json:"candidates_rejected"`
	Rejections          []string `json:"rejections,omitempty"`

	Proposals []proposalJSON `json:"proposals"`
}

const freshUntilLayout = "2006-01-02"

// Load reads a video's reference sheet.
func (s *RefStore) Load(videoID string) (*domain.ReferenceSheet, bool, error) {
	path, err := s.refPath(videoID)
	if err != nil {
		return nil, false, err
	}

	data, err := os.ReadFile(path) //nolint:gosec // path is validated above
	if os.IsNotExist(err) {
		return nil, false, nil
	}
	if err != nil {
		return nil, false, fmt.Errorf("reading %s: %w", path, err)
	}

	var raw refSheetJSON
	if err := json.Unmarshal(data, &raw); err != nil {
		return nil, false, fmt.Errorf("parsing %s: %w", path, err)
	}

	sheet := &domain.ReferenceSheet{
		Topic:               raw.Topic,
		Path:                path,
		MaxSelectable:       raw.MaxSelectable,
		TrendSources:        raw.TrendSources,
		TrendsFetchedAt:     raw.TrendsFetchedAt,
		CandidatesGenerated: raw.CandidatesGenerated,
		CandidatesRejected:  raw.CandidatesRejected,
		Rejections:          raw.Rejections,
	}

	for _, p := range raw.Proposals {
		proposal := domain.Proposal{
			ID:           p.ID,
			Reference:    p.Reference,
			Kind:         domain.ReferenceKind(p.Kind),
			LinkedFactID: p.LinkedFactID,
			Comparison:   p.Comparison,
			WhyFunny:     p.WhyFunny,
			AccuracyNote: p.AccuracyNote,
			Source:       p.Source,
			Selected:     p.Selected,
		}
		if p.FreshUntil != "" {
			// An unparseable date leaves FreshUntil zero, which reads as
			// "never expires". Better to under-warn than to refuse to load a
			// whole sheet over one malformed field.
			if t, err := time.Parse(freshUntilLayout, p.FreshUntil); err == nil {
				proposal.FreshUntil = t
			}
		}
		sheet.Proposals = append(sheet.Proposals, proposal)
	}

	return sheet, true, nil
}

// Save writes a reference sheet back, atomically.
func (s *RefStore) Save(videoID string, sheet *domain.ReferenceSheet) error {
	path, err := s.refPath(videoID)
	if err != nil {
		return err
	}

	raw := refSheetJSON{
		Topic:               sheet.Topic,
		MaxSelectable:       sheet.MaxSelectable,
		TrendSources:        sheet.TrendSources,
		TrendsFetchedAt:     sheet.TrendsFetchedAt,
		CandidatesGenerated: sheet.CandidatesGenerated,
		CandidatesRejected:  sheet.CandidatesRejected,
		Rejections:          sheet.Rejections,
	}

	for _, p := range sheet.Proposals {
		out := proposalJSON{
			ID:           p.ID,
			Reference:    p.Reference,
			Kind:         string(p.Kind),
			LinkedFactID: p.LinkedFactID,
			Comparison:   p.Comparison,
			WhyFunny:     p.WhyFunny,
			AccuracyNote: p.AccuracyNote,
			Source:       p.Source,
			Selected:     p.Selected,
		}
		if !p.FreshUntil.IsZero() {
			out.FreshUntil = p.FreshUntil.Format(freshUntilLayout)
		}
		raw.Proposals = append(raw.Proposals, out)
	}

	encoded, err := json.MarshalIndent(raw, "", "  ")
	if err != nil {
		return fmt.Errorf("encoding references for %q: %w", videoID, err)
	}

	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return fmt.Errorf("creating project folder for %q: %w", videoID, err)
	}
	return writeAtomic(path, append(encoded, '\n'))
}

// refPath validates the id and builds the file path.
//
// The id becomes a directory name, so it is checked here as well as at the
// service boundary -- defence in depth for the one guard that stops a crafted
// id escaping projects/ (SPEC.md 13.5).
func (s *RefStore) refPath(videoID string) (string, error) {
	if err := validate.VideoID(videoID); err != nil {
		return "", err
	}
	return filepath.Join(s.projectsDir, videoID, "references.json"), nil
}

var _ domain.ReferenceStore = (*RefStore)(nil)
