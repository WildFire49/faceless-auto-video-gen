package sqlite

import (
	"context"
	"fmt"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
)

// ReviewLog implements domain.ReviewLog.
//
// Append-only by construction: there is no Update and no Delete, because this
// table is the project's evidence that a human made the creative decisions
// (SPEC.md 7, 8.4). Rows are removed only by cascade when a video is deleted.
type ReviewLog struct {
	db *DB
}

// NewReviewLog wires the log to a database.
func NewReviewLog(db *DB) *ReviewLog { return &ReviewLog{db: db} }

// Append records one decision. The entry's ID is filled in on success.
func (l *ReviewLog) Append(ctx context.Context, e *domain.ReviewEntry) error {
	const q = `INSERT INTO review_log
		(video_id, at, gate, action, from_status, to_status, note, diff)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?)`

	res, err := l.db.conn(ctx).ExecContext(ctx, q,
		e.VideoID, formatTime(e.At), string(e.Gate), string(e.Action),
		string(e.FromStatus), string(e.ToStatus), e.Note, e.Diff,
	)
	if err != nil {
		return fmt.Errorf("appending review log for %q: %w", e.VideoID, err)
	}

	id, err := res.LastInsertId()
	if err != nil {
		return fmt.Errorf("reading review log id for %q: %w", e.VideoID, err)
	}
	e.ID = id
	return nil
}

// List returns one video's decisions, oldest first, which is how a human
// reads a history.
func (l *ReviewLog) List(ctx context.Context, videoID string) ([]*domain.ReviewEntry, error) {
	const q = `SELECT id, video_id, at, gate, action, from_status, to_status, note, diff
		FROM review_log WHERE video_id = ? ORDER BY at ASC, id ASC`

	rows, err := l.db.conn(ctx).QueryContext(ctx, q, videoID)
	if err != nil {
		return nil, fmt.Errorf("listing review log for %q: %w", videoID, err)
	}
	defer func() { _ = rows.Close() }()

	var out []*domain.ReviewEntry
	for rows.Next() {
		var (
			e                              domain.ReviewEntry
			at, gate, action, fromSt, toSt string
		)
		if err := rows.Scan(&e.ID, &e.VideoID, &at, &gate, &action,
			&fromSt, &toSt, &e.Note, &e.Diff); err != nil {
			return nil, fmt.Errorf("scanning review log row: %w", err)
		}

		t, err := parseTime(at)
		if err != nil {
			return nil, fmt.Errorf("review log %d: %w", e.ID, err)
		}
		e.At = t
		e.Gate = domain.Gate(gate)
		e.Action = domain.ReviewAction(action)
		e.FromStatus = domain.Status(fromSt)
		e.ToStatus = domain.Status(toSt)

		out = append(out, &e)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterating review log: %w", err)
	}
	return out, nil
}

var _ domain.ReviewLog = (*ReviewLog)(nil)
