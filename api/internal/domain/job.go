package domain

import (
	"context"
	"time"
)

// JobState is the lifecycle of one pipeline step execution.
type JobState string

const (
	JobRunning   JobState = "running"
	JobSucceeded JobState = "succeeded"
	JobFailed    JobState = "failed"
	// JobInterrupted means the process died while this job was running.
	// Detected at startup (SPEC.md 13.3, crash recovery) -- a job that is
	// still "running" when nothing is running is a lie the dashboard would
	// otherwise display forever.
	JobInterrupted JobState = "interrupted"
)

// Job records one execution of a pipeline step.
//
// Jobs exist so the dashboard can show a live progress bar instead of a
// spinner that hangs for four minutes (SPEC.md 8.3), and so an interrupted
// run is visible rather than silent.
type Job struct {
	ID      string
	VideoID string
	// Step is the status the video moves INTO on success, e.g. "researching".
	Step  string
	State JobState

	// Latest progress reported by the worker.
	Stage   string
	Percent float64
	Current int
	Total   int

	Error      string
	StartedAt  time.Time
	FinishedAt *time.Time
}

// IsFinished reports whether the job has stopped, for any reason.
func (j *Job) IsFinished() bool {
	return j.State != JobRunning
}

// JobRepo stores jobs.
type JobRepo interface {
	Create(ctx context.Context, j *Job) error
	Get(ctx context.Context, id string) (*Job, error)
	// Latest returns the most recent job for a video, so a page reload can
	// reattach to work already in flight.
	Latest(ctx context.Context, videoID string) (*Job, error)
	// UpdateProgress writes only the progress fields. Called often while a
	// step runs, so it deliberately does not rewrite the whole row.
	UpdateProgress(ctx context.Context, id string, stage string, percent float64, current, total int) error
	// Finish marks a job succeeded or failed.
	Finish(ctx context.Context, id string, state JobState, errMessage string, at time.Time) error
	// MarkRunningAsInterrupted is called at startup. Returns how many it
	// found, so the operator learns that something was cut short.
	MarkRunningAsInterrupted(ctx context.Context, at time.Time) (int, error)
}
