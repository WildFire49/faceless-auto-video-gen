// Package reviewmirror writes the review log out as projects/<id>/review_log.json.
//
// LAYER 4 (adapter) of SPEC.md 14.1, using the Decorator pattern (14.3): it
// wraps another domain.ReviewLog and adds a side effect, so neither the
// service layer nor the SQLite repository knows this file exists.
//
// Why a mirror rather than a second store: SPEC.md 8.4 requires the log to
// live beside the video as review_log.json, and SPEC.md 13.3 requires a state
// change and its log entry to commit atomically. A file cannot join a database
// transaction, so the database stays canonical and the file is regenerated
// from it after each successful commit. There is exactly one source of truth,
// and the artifact the spec asks for still exists on disk.
package reviewmirror

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"time"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/platform/logging"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/platform/validate"
)

// Mirror decorates a ReviewLog with a JSON file export.
type Mirror struct {
	inner       domain.ReviewLog
	projectsDir string
	log         *slog.Logger
}

// New wraps inner, writing files under projectsDir.
func New(inner domain.ReviewLog, projectsDir string, log *slog.Logger) *Mirror {
	return &Mirror{inner: inner, projectsDir: projectsDir, log: log}
}

// entryJSON is the on-disk shape. It is deliberately separate from
// domain.ReviewEntry: this file is an artifact a human reads and an auditor
// may keep, so its field names should not change just because an internal
// struct was refactored.
type entryJSON struct {
	ID         int64     `json:"id"`
	At         time.Time `json:"at"`
	Gate       string    `json:"gate,omitempty"`
	GateLabel  string    `json:"gate_label,omitempty"`
	Action     string    `json:"action"`
	FromStatus string    `json:"from_status"`
	ToStatus   string    `json:"to_status"`
	Note       string    `json:"note,omitempty"`
	Diff       string    `json:"diff,omitempty"`
}

type fileJSON struct {
	VideoID   string      `json:"video_id"`
	UpdatedAt time.Time   `json:"updated_at"`
	Note      string      `json:"_note"`
	Entries   []entryJSON `json:"entries"`
}

// Append delegates, then refreshes the JSON file.
//
// A failure to write the file is logged but NOT returned: the decision is
// already committed to the database, which is canonical, and failing the
// operator's approval because a mirror file could not be written would be
// worse than a stale mirror. `rewind doctor` will be able to report drift.
func (m *Mirror) Append(ctx context.Context, e *domain.ReviewEntry) error {
	if err := m.inner.Append(ctx, e); err != nil {
		return err
	}
	if err := m.write(ctx, e.VideoID); err != nil {
		logging.FromContext(ctx, m.log).Error("could not write review_log.json",
			slog.String("video_id", e.VideoID),
			slog.Any("error", err),
		)
	}
	return nil
}

// List delegates unchanged.
func (m *Mirror) List(ctx context.Context, videoID string) ([]*domain.ReviewEntry, error) {
	return m.inner.List(ctx, videoID)
}

// write regenerates the file from the canonical log.
func (m *Mirror) write(ctx context.Context, videoID string) error {
	// The id becomes a directory name, so it is validated here too rather
	// than trusted from upstream (SPEC.md 13.5, defence in depth).
	if err := validate.VideoID(videoID); err != nil {
		return err
	}

	entries, err := m.inner.List(ctx, videoID)
	if err != nil {
		return fmt.Errorf("reading review log: %w", err)
	}

	payload := fileJSON{
		VideoID:   videoID,
		UpdatedAt: time.Now().UTC(),
		Note:      "Generated from the database. Edit nothing here; this file is evidence of human review.",
		Entries:   make([]entryJSON, 0, len(entries)),
	}
	for _, e := range entries {
		payload.Entries = append(payload.Entries, entryJSON{
			ID:         e.ID,
			At:         e.At,
			Gate:       string(e.Gate),
			GateLabel:  gateLabel(e.Gate),
			Action:     string(e.Action),
			FromStatus: string(e.FromStatus),
			ToStatus:   string(e.ToStatus),
			Note:       e.Note,
			Diff:       e.Diff,
		})
	}

	data, err := json.MarshalIndent(payload, "", "  ")
	if err != nil {
		return fmt.Errorf("encoding review log: %w", err)
	}

	dir := filepath.Join(m.projectsDir, videoID)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return fmt.Errorf("creating %s: %w", dir, err)
	}
	return writeFileAtomic(filepath.Join(dir, "review_log.json"), append(data, '\n'))
}

func gateLabel(g domain.Gate) string {
	if g == domain.GateNone {
		return ""
	}
	return g.Label()
}

// writeFileAtomic writes to a temporary file and renames it into place, so a
// crash mid-write leaves the previous file intact rather than a truncated one.
func writeFileAtomic(path string, data []byte) error {
	tmp, err := os.CreateTemp(filepath.Dir(path), ".review_log-*.tmp")
	if err != nil {
		return fmt.Errorf("creating temp file for %s: %w", path, err)
	}
	tmpName := tmp.Name()

	// Best-effort cleanup if anything below fails; a successful rename makes
	// this a no-op.
	defer func() { _ = os.Remove(tmpName) }()

	if _, err := tmp.Write(data); err != nil {
		_ = tmp.Close()
		return fmt.Errorf("writing %s: %w", tmpName, err)
	}
	if err := tmp.Close(); err != nil {
		return fmt.Errorf("closing %s: %w", tmpName, err)
	}
	if err := os.Rename(tmpName, path); err != nil {
		return fmt.Errorf("renaming %s to %s: %w", tmpName, path, err)
	}
	return nil
}

var _ domain.ReviewLog = (*Mirror)(nil)
