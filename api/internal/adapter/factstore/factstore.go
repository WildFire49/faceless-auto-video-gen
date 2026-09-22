// Package factstore reads and writes projects/<video_id>/facts.json.
//
// LAYER 4 (adapter) of SPEC.md 14.1.
//
// Division of labour: the Python worker WRITES this file once, when research
// finishes. From then on Go owns it, because every subsequent change is a
// human decision at Gate A -- ticking a fact, correcting a claim, deleting
// one -- and Go owns all state (SPEC.md 2.4).
package factstore

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/platform/validate"
)

// Store reads and writes fact sheets on disk.
type Store struct {
	projectsDir string
}

// New wires the store to the projects directory.
func New(projectsDir string) *Store { return &Store{projectsDir: projectsDir} }

// factJSON is the on-disk shape, shared with the Python worker.
//
// Deliberately separate from domain.Fact: this file is a contract between two
// languages and a human reader, so its field names must not change just
// because an internal struct was refactored.
type factJSON struct {
	ID          string  `json:"id"`
	Label       string  `json:"label"`
	SortKey     int64   `json:"sort_key"`
	Context     string  `json:"context"`
	Group       string  `json:"group"`
	Claim       string  `json:"claim"`
	Evidence    string  `json:"evidence"`
	SourceURL   string  `json:"source_url"`
	SourceTitle string  `json:"source_title"`
	Confidence  string  `json:"confidence"`
	Conflict    bool    `json:"conflict"`
	Approved    bool    `json:"approved"`
	MatchScore  float64 `json:"match_score"`
	// AddedByHuman marks facts a person supplied at Gate A. They skip the
	// evidence verifier -- a human citing a book is the authority the
	// verifier exists to substitute for -- so it matters that they are
	// distinguishable afterwards.
	AddedByHuman bool `json:"added_by_human,omitempty"`
}

type sourceJSON struct {
	URL       string `json:"url"`
	Title     string `json:"title"`
	Fetcher   string `json:"fetcher"`
	CharCount int    `json:"char_count"`
}

type sheetJSON struct {
	Topic string `json:"topic"`

	// The format and its gate rules travel with the sheet, so Go can enforce
	// a format's thresholds without knowing which formats exist.
	Format    string `json:"format"`
	GroupNoun string `json:"group_noun"`
	MinItems  int    `json:"min_items"`
	MinGroups int    `json:"min_groups"`

	// How much the model invented. These used to be computed by the worker
	// and then discarded, which silently broke the one objective measure of
	// model quality on this task.
	CandidatesExtracted int      `json:"candidates_extracted"`
	CandidatesRejected  int      `json:"candidates_rejected"`
	Rejections          []string `json:"rejections,omitempty"`

	Facts   []factJSON   `json:"facts"`
	Sources []sourceJSON `json:"sources"`
}

// Load reads a video's fact sheet.
//
// Returns exists=false rather than an error when the file is absent: a video
// that has not been researched yet simply has no facts, which the Gate A page
// renders as an empty state.
func (s *Store) Load(videoID string) (*domain.FactSheet, bool, error) {
	path, err := s.path(videoID)
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

	var raw sheetJSON
	if err := json.Unmarshal(data, &raw); err != nil {
		return nil, false, fmt.Errorf("parsing %s: %w", path, err)
	}

	sheet := &domain.FactSheet{
		Topic:               raw.Topic,
		Path:                path,
		Format:              raw.Format,
		GroupNoun:           raw.GroupNoun,
		MinItems:            raw.MinItems,
		MinGroups:           raw.MinGroups,
		CandidatesExtracted: raw.CandidatesExtracted,
		CandidatesRejected:  raw.CandidatesRejected,
		Rejections:          raw.Rejections,
	}
	for _, f := range raw.Facts {
		sheet.Facts = append(sheet.Facts, domain.Fact{
			ID:           f.ID,
			Label:        f.Label,
			SortKey:      f.SortKey,
			Context:      f.Context,
			Group:        f.Group,
			Claim:        f.Claim,
			Evidence:     f.Evidence,
			SourceURL:    f.SourceURL,
			SourceTitle:  f.SourceTitle,
			Confidence:   f.Confidence,
			Conflict:     f.Conflict,
			Approved:     f.Approved,
			MatchScore:   f.MatchScore,
			AddedByHuman: f.AddedByHuman,
		})
	}
	for _, src := range raw.Sources {
		sheet.Sources = append(sheet.Sources, domain.FactSource{
			URL:       src.URL,
			Title:     src.Title,
			Fetcher:   src.Fetcher,
			CharCount: src.CharCount,
		})
	}

	return sheet, true, nil
}

// Save writes a fact sheet back, atomically.
func (s *Store) Save(videoID string, sheet *domain.FactSheet) error {
	path, err := s.path(videoID)
	if err != nil {
		return err
	}

	// Keep the file in the format's own order however facts were edited or
	// added, so it always reads the way the video will play.
	sorted := make([]domain.Fact, len(sheet.Facts))
	copy(sorted, sheet.Facts)
	sort.SliceStable(sorted, func(i, j int) bool { return sorted[i].SortKey < sorted[j].SortKey })

	raw := sheetJSON{
		Topic:               sheet.Topic,
		Format:              sheet.Format,
		GroupNoun:           sheet.GroupNoun,
		MinItems:            sheet.MinItems,
		MinGroups:           sheet.MinGroups,
		CandidatesExtracted: sheet.CandidatesExtracted,
		CandidatesRejected:  sheet.CandidatesRejected,
		Rejections:          sheet.Rejections,
	}
	for _, f := range sorted {
		raw.Facts = append(raw.Facts, factJSON{
			ID:           f.ID,
			Label:        f.Label,
			SortKey:      f.SortKey,
			Context:      f.Context,
			Group:        f.Group,
			Claim:        f.Claim,
			Evidence:     f.Evidence,
			SourceURL:    f.SourceURL,
			SourceTitle:  f.SourceTitle,
			Confidence:   f.Confidence,
			Conflict:     f.Conflict,
			Approved:     f.Approved,
			MatchScore:   f.MatchScore,
			AddedByHuman: f.AddedByHuman,
		})
	}
	for _, src := range sheet.Sources {
		raw.Sources = append(raw.Sources, sourceJSON{
			URL:       src.URL,
			Title:     src.Title,
			Fetcher:   src.Fetcher,
			CharCount: src.CharCount,
		})
	}

	encoded, err := json.MarshalIndent(raw, "", "  ")
	if err != nil {
		return fmt.Errorf("encoding facts for %q: %w", videoID, err)
	}

	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return fmt.Errorf("creating project folder for %q: %w", videoID, err)
	}
	return writeAtomic(path, append(encoded, '\n'))
}

// path validates the id and builds the file path.
//
// The id becomes a directory name, so it is checked here as well as at the
// service boundary -- defence in depth for the one guard that stops a crafted
// id escaping projects/ (SPEC.md 13.5).
func (s *Store) path(videoID string) (string, error) {
	if err := validate.VideoID(videoID); err != nil {
		return "", err
	}
	return filepath.Join(s.projectsDir, videoID, "facts.json"), nil
}

// writeAtomic writes via a temporary file and renames it into place, so a
// crash mid-write leaves the previous file intact rather than a truncated one.
func writeAtomic(path string, data []byte) error {
	tmp, err := os.CreateTemp(filepath.Dir(path), ".facts-*.tmp")
	if err != nil {
		return fmt.Errorf("creating temp file for %s: %w", path, err)
	}
	tmpName := tmp.Name()
	defer func() { _ = os.Remove(tmpName) }()

	if _, err := tmp.Write(data); err != nil {
		_ = tmp.Close()
		return fmt.Errorf("writing %s: %w", tmpName, err)
	}
	if err := tmp.Sync(); err != nil {
		_ = tmp.Close()
		return fmt.Errorf("syncing %s: %w", tmpName, err)
	}
	if err := tmp.Close(); err != nil {
		return fmt.Errorf("closing %s: %w", tmpName, err)
	}
	if err := os.Rename(tmpName, path); err != nil {
		return fmt.Errorf("renaming %s to %s: %w", tmpName, path, err)
	}
	return nil
}

var _ domain.FactStore = (*Store)(nil)
