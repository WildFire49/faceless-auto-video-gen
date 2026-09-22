package sqlite

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"time"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
)

// JobRepo implements domain.JobRepo.
type JobRepo struct {
	db *DB
}

// NewJobRepo wires the repository to a database.
func NewJobRepo(db *DB) *JobRepo { return &JobRepo{db: db} }

const jobColumns = `id, video_id, step, state, stage, percent, current_item,
	total_items, error, started_at, finished_at`

// Create stores a new job.
func (r *JobRepo) Create(ctx context.Context, j *domain.Job) error {
	const q = `INSERT INTO jobs (` + jobColumns + `)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`

	_, err := r.db.conn(ctx).ExecContext(ctx, q,
		j.ID, j.VideoID, j.Step, string(j.State),
		j.Stage, j.Percent, j.Current, j.Total,
		j.Error, formatTime(j.StartedAt), formatNullableTime(j.FinishedAt),
	)
	if err != nil {
		return fmt.Errorf("inserting job %q: %w", j.ID, err)
	}
	return nil
}

// Get returns one job.
func (r *JobRepo) Get(ctx context.Context, id string) (*domain.Job, error) {
	const q = `SELECT ` + jobColumns + ` FROM jobs WHERE id = ?`

	j, err := scanJob(r.db.conn(ctx).QueryRowContext(ctx, q, id))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, fmt.Errorf("%w: job %q", domain.ErrNotFound, id)
	}
	if err != nil {
		return nil, fmt.Errorf("loading job %q: %w", id, err)
	}
	return j, nil
}

// Latest returns the most recent job for a video, or nil when there is none.
//
// Absence is not an error here: a video that has never run simply has no job,
// and making the caller distinguish ErrNotFound from a real failure for such
// an ordinary case would be noise.
func (r *JobRepo) Latest(ctx context.Context, videoID string) (*domain.Job, error) {
	const q = `SELECT ` + jobColumns + ` FROM jobs
		WHERE video_id = ? ORDER BY started_at DESC, rowid DESC LIMIT 1`

	j, err := scanJob(r.db.conn(ctx).QueryRowContext(ctx, q, videoID))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil //nolint:nilnil // "no job yet" is a normal state
	}
	if err != nil {
		return nil, fmt.Errorf("loading latest job for %q: %w", videoID, err)
	}
	return j, nil
}

// UpdateProgress writes only the progress fields.
//
// Narrow on purpose: this runs many times per job, and rewriting the whole row
// would risk clobbering a concurrent Finish with stale values.
func (r *JobRepo) UpdateProgress(
	ctx context.Context,
	id string,
	stage string,
	percent float64,
	current, total int,
) error {
	const q = `UPDATE jobs SET stage = ?, percent = ?, current_item = ?, total_items = ?
		WHERE id = ? AND state = 'running'`

	if _, err := r.db.conn(ctx).ExecContext(ctx, q, stage, percent, current, total, id); err != nil {
		return fmt.Errorf("updating progress for job %q: %w", id, err)
	}
	return nil
}

// Finish marks a job succeeded or failed.
func (r *JobRepo) Finish(
	ctx context.Context,
	id string,
	state domain.JobState,
	errMessage string,
	at time.Time,
) error {
	const q = `UPDATE jobs SET state = ?, error = ?, finished_at = ?,
		percent = CASE WHEN ? = 'succeeded' THEN 1.0 ELSE percent END
		WHERE id = ?`

	res, err := r.db.conn(ctx).ExecContext(ctx, q,
		string(state), errMessage, formatTime(at), string(state), id)
	if err != nil {
		return fmt.Errorf("finishing job %q: %w", id, err)
	}

	n, err := res.RowsAffected()
	if err != nil {
		return fmt.Errorf("checking finish of job %q: %w", id, err)
	}
	if n == 0 {
		return fmt.Errorf("%w: job %q", domain.ErrNotFound, id)
	}
	return nil
}

// MarkRunningAsInterrupted is called at startup (SPEC.md 13.3).
//
// Any job still marked running when the process starts was cut short, because
// nothing survives a restart. Leaving it as "running" would show the operator
// a progress bar that never moves.
func (r *JobRepo) MarkRunningAsInterrupted(ctx context.Context, at time.Time) (int, error) {
	const q = `UPDATE jobs SET state = 'interrupted', finished_at = ?,
		error = 'interrupted by a restart'
		WHERE state = 'running'`

	res, err := r.db.conn(ctx).ExecContext(ctx, q, formatTime(at))
	if err != nil {
		return 0, fmt.Errorf("marking interrupted jobs: %w", err)
	}

	n, err := res.RowsAffected()
	if err != nil {
		return 0, fmt.Errorf("counting interrupted jobs: %w", err)
	}
	return int(n), nil
}

func scanJob(row rowScanner) (*domain.Job, error) {
	var (
		j          domain.Job
		state      string
		startedAt  string
		finishedAt sql.NullString
	)

	if err := row.Scan(
		&j.ID, &j.VideoID, &j.Step, &state,
		&j.Stage, &j.Percent, &j.Current, &j.Total,
		&j.Error, &startedAt, &finishedAt,
	); err != nil {
		return nil, err
	}

	j.State = domain.JobState(state)

	var err error
	if j.StartedAt, err = parseTime(startedAt); err != nil {
		return nil, fmt.Errorf("job %q started_at: %w", j.ID, err)
	}
	if finishedAt.Valid && finishedAt.String != "" {
		t, err := parseTime(finishedAt.String)
		if err != nil {
			return nil, fmt.Errorf("job %q finished_at: %w", j.ID, err)
		}
		j.FinishedAt = &t
	}

	return &j, nil
}

var _ domain.JobRepo = (*JobRepo)(nil)
