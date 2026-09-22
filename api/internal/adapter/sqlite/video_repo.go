package sqlite

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
)

// VideoRepo implements domain.VideoRepo.
type VideoRepo struct {
	db *DB
}

// NewVideoRepo wires the repository to a database.
func NewVideoRepo(db *DB) *VideoRepo { return &VideoRepo{db: db} }

// videoColumns keeps SELECT and scan in step. Listing columns explicitly
// rather than using SELECT * means adding a column cannot silently break
// scanning.
const videoColumns = `id, topic, status, priority, notes, created_at, updated_at,
	rejected_to, reject_note, error, retry_from, yt_video_id, published_at`

// Create stores a new video.
func (r *VideoRepo) Create(ctx context.Context, v *domain.Video) error {
	const q = `INSERT INTO videos (` + videoColumns + `)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`

	_, err := r.db.conn(ctx).ExecContext(ctx, q,
		v.ID, v.Topic, string(v.Status), int(v.Priority), v.Notes,
		formatTime(v.CreatedAt), formatTime(v.UpdatedAt),
		string(v.RejectedTo), v.RejectNote,
		v.Error, string(v.RetryFrom),
		v.YTVideoID, formatNullableTime(v.PublishedAt),
	)
	if err != nil {
		if isUniqueViolation(err) {
			return fmt.Errorf("%w: video %q", domain.ErrAlreadyExists, v.ID)
		}
		return fmt.Errorf("inserting video %q: %w", v.ID, err)
	}
	return nil
}

// Get returns one video.
func (r *VideoRepo) Get(ctx context.Context, id string) (*domain.Video, error) {
	const q = `SELECT ` + videoColumns + ` FROM videos WHERE id = ?`

	v, err := scanVideo(r.db.conn(ctx).QueryRowContext(ctx, q, id))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, fmt.Errorf("%w: video %q", domain.ErrNotFound, id)
	}
	if err != nil {
		return nil, fmt.Errorf("loading video %q: %w", id, err)
	}
	return v, nil
}

// List returns videos matching the filter.
//
// Ordering is the queue order a human wants: highest priority first, then
// oldest first, so nothing starves at the bottom of the list.
func (r *VideoRepo) List(ctx context.Context, f domain.VideoFilter) ([]*domain.Video, error) {
	var (
		where []string
		args  []any
	)

	if len(f.Statuses) > 0 {
		placeholders := make([]string, len(f.Statuses))
		for i, s := range f.Statuses {
			placeholders[i] = "?"
			args = append(args, string(s))
		}
		where = append(where, "status IN ("+strings.Join(placeholders, ", ")+")")
	}

	if f.AwaitingReview {
		// Derived from the domain rather than hard-coded here, so adding a
		// gate in state.go automatically includes it in this query.
		gateStatuses := awaitingReviewStatuses()
		placeholders := make([]string, len(gateStatuses))
		for i, s := range gateStatuses {
			placeholders[i] = "?"
			args = append(args, string(s))
		}
		where = append(where, "status IN ("+strings.Join(placeholders, ", ")+")")
	}

	q := `SELECT ` + videoColumns + ` FROM videos`
	if len(where) > 0 {
		q += " WHERE " + strings.Join(where, " AND ")
	}
	q += " ORDER BY priority ASC, created_at ASC"

	rows, err := r.db.conn(ctx).QueryContext(ctx, q, args...)
	if err != nil {
		return nil, fmt.Errorf("listing videos: %w", err)
	}
	defer func() { _ = rows.Close() }()

	var out []*domain.Video
	for rows.Next() {
		v, err := scanVideo(rows)
		if err != nil {
			return nil, fmt.Errorf("scanning video row: %w", err)
		}
		out = append(out, v)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterating videos: %w", err)
	}
	return out, nil
}

// Update writes a video back.
func (r *VideoRepo) Update(ctx context.Context, v *domain.Video) error {
	const q = `UPDATE videos SET
		topic = ?, status = ?, priority = ?, notes = ?, updated_at = ?,
		rejected_to = ?, reject_note = ?, error = ?, retry_from = ?,
		yt_video_id = ?, published_at = ?
		WHERE id = ?`

	res, err := r.db.conn(ctx).ExecContext(ctx, q,
		v.Topic, string(v.Status), int(v.Priority), v.Notes, formatTime(v.UpdatedAt),
		string(v.RejectedTo), v.RejectNote, v.Error, string(v.RetryFrom),
		v.YTVideoID, formatNullableTime(v.PublishedAt),
		v.ID,
	)
	if err != nil {
		return fmt.Errorf("updating video %q: %w", v.ID, err)
	}

	n, err := res.RowsAffected()
	if err != nil {
		return fmt.Errorf("checking update of video %q: %w", v.ID, err)
	}
	if n == 0 {
		return fmt.Errorf("%w: video %q", domain.ErrNotFound, v.ID)
	}
	return nil
}

// awaitingReviewStatuses lists the statuses that sit at a gate.
func awaitingReviewStatuses() []domain.Status {
	gates := domain.AllGates()
	out := make([]domain.Status, 0, len(gates))
	for _, g := range gates {
		if s, ok := domain.GateWaitingStatus(g); ok {
			out = append(out, s)
		}
	}
	return out
}

// rowScanner covers both *sql.Row and *sql.Rows.
type rowScanner interface {
	Scan(dest ...any) error
}

func scanVideo(row rowScanner) (*domain.Video, error) {
	var (
		v            domain.Video
		status       string
		priority     int
		createdAt    string
		updatedAt    string
		rejectedTo   string
		retryFrom    string
		publishedAt  sql.NullString
		topic, notes string
	)

	if err := row.Scan(
		&v.ID, &topic, &status, &priority, &notes,
		&createdAt, &updatedAt,
		&rejectedTo, &v.RejectNote,
		&v.Error, &retryFrom,
		&v.YTVideoID, &publishedAt,
	); err != nil {
		return nil, err
	}

	v.Topic = topic
	v.Notes = notes
	v.Status = domain.Status(status)
	v.Priority = domain.Priority(priority)
	v.RejectedTo = domain.Status(rejectedTo)
	v.RetryFrom = domain.Status(retryFrom)

	var err error
	if v.CreatedAt, err = parseTime(createdAt); err != nil {
		return nil, fmt.Errorf("video %q created_at: %w", v.ID, err)
	}
	if v.UpdatedAt, err = parseTime(updatedAt); err != nil {
		return nil, fmt.Errorf("video %q updated_at: %w", v.ID, err)
	}
	if publishedAt.Valid && publishedAt.String != "" {
		t, err := parseTime(publishedAt.String)
		if err != nil {
			return nil, fmt.Errorf("video %q published_at: %w", v.ID, err)
		}
		v.PublishedAt = &t
	}

	return &v, nil
}

// Times are stored as RFC 3339 in UTC. Text rather than an integer so the
// database is readable with any SQLite browser, which matters for a local
// tool you will inspect by hand.
func formatTime(t time.Time) string { return t.UTC().Format(time.RFC3339Nano) }

func formatNullableTime(t *time.Time) any {
	if t == nil {
		return nil
	}
	return formatTime(*t)
}

func parseTime(s string) (time.Time, error) {
	t, err := time.Parse(time.RFC3339Nano, s)
	if err != nil {
		return time.Time{}, fmt.Errorf("parsing time %q: %w", s, err)
	}
	return t.UTC(), nil
}

// isUniqueViolation reports whether err is a primary-key collision.
//
// modernc.org/sqlite does not export a typed error for this, so the message is
// matched. Narrow and documented, rather than treating every insert failure as
// a duplicate.
func isUniqueViolation(err error) bool {
	msg := strings.ToLower(err.Error())
	return strings.Contains(msg, "unique constraint failed") ||
		strings.Contains(msg, "constraint failed: unique")
}

var _ domain.VideoRepo = (*VideoRepo)(nil)
