package pipeline

import (
	"context"
	"errors"
	"fmt"
	"log/slog"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/platform/logging"
)

// Runner executes steps and keeps the video and job records honest.
//
// This is the Template Method of SPEC.md 14.3: every step goes through the
// same sequence -- claim, run, record -- and therefore inherits progress
// reporting, error handling and state transitions without implementing any of
// them itself.
type Runner struct {
	registry *Registry
	videos   domain.VideoRepo
	jobs     domain.JobRepo
	tx       domain.TxManager
	clock    domain.Clock
	ids      func() string
	log      *slog.Logger
}

// NewRunner wires the runner.
func NewRunner(
	registry *Registry,
	videos domain.VideoRepo,
	jobs domain.JobRepo,
	tx domain.TxManager,
	clock domain.Clock,
	ids func() string,
	log *slog.Logger,
) *Runner {
	return &Runner{
		registry: registry,
		videos:   videos,
		jobs:     jobs,
		tx:       tx,
		clock:    clock,
		ids:      ids,
		log:      log,
	}
}

// StartResult describes what Start did.
type StartResult struct {
	Job     *domain.Job
	Started bool
	// Reason explains why nothing started, when nothing did.
	Reason string
}

// Start begins the next step for a video and returns immediately.
//
// The actual work runs in a goroutine, because research takes minutes and the
// HTTP request must not block on it (SPEC.md 8.3). The caller polls the
// returned job.
func (r *Runner) Start(ctx context.Context, videoID string) (*StartResult, error) {
	video, err := r.videos.Get(ctx, videoID)
	if err != nil {
		return nil, err
	}

	if g, waiting := domain.GateFor(video.Status); waiting {
		return &StartResult{Reason: fmt.Sprintf("waiting for your review at %s", g)}, nil
	}
	if video.Status == domain.StatusError {
		return &StartResult{
			Reason: fmt.Sprintf("failed: %s — run `rewind retry %s`", video.Error, video.ID),
		}, nil
	}

	step, found := r.registry.For(video.Status)
	if !found {
		if _, hasNext := domain.NextAutomatic(video.Status); hasNext {
			return &StartResult{
				Reason: fmt.Sprintf("the %s step is not implemented yet", video.Status),
			}, nil
		}
		return &StartResult{
			Reason: fmt.Sprintf("nothing further happens automatically from %s", video.Status),
		}, nil
	}

	// Refuse to start a second job for the same video. Two steps writing the
	// same project folder would corrupt each other's output.
	if latest, err := r.jobs.Latest(ctx, videoID); err == nil && latest != nil && !latest.IsFinished() {
		return &StartResult{Job: latest, Reason: "already running"}, nil
	}

	job := &domain.Job{
		ID:        r.ids(),
		VideoID:   video.ID,
		Step:      string(step.To()),
		State:     domain.JobRunning,
		Stage:     "starting",
		StartedAt: r.clock.Now(),
	}

	// Claim the work and create the job together. Without one transaction a
	// crash between them would leave a video marked "researching" with no job
	// tracking it -- invisible to both the dashboard and crash recovery.
	err = r.tx.WithTx(ctx, func(ctx context.Context) error {
		fresh, err := r.videos.Get(ctx, video.ID)
		if err != nil {
			return err
		}
		if err := domain.Transition(fresh, step.Running()); err != nil {
			return err
		}
		fresh.UpdatedAt = r.clock.Now()
		if err := r.videos.Update(ctx, fresh); err != nil {
			return err
		}
		return r.jobs.Create(ctx, job)
	})
	if err != nil {
		return nil, err
	}

	// Detached from the request context on purpose: the work must survive the
	// HTTP response returning. Cancellation comes from shutdown instead.
	go r.execute(context.WithoutCancel(ctx), step, video.ID, job.ID)

	return &StartResult{Job: job, Started: true}, nil
}

// execute runs one step to completion and records the outcome.
func (r *Runner) execute(ctx context.Context, step Step, videoID, jobID string) {
	log := logging.FromContext(ctx, r.log).With(
		slog.String("video_id", videoID),
		slog.String("job_id", jobID),
		slog.String("step", string(step.To())),
	)

	// Guard the goroutine: a panic in a step must not take down the server
	// and must not leave the job stuck in "running" forever.
	defer func() {
		if p := recover(); p != nil {
			log.Error("step panicked", slog.Any("panic", p))
			r.fail(ctx, videoID, jobID, fmt.Sprintf("internal error: %v", p))
		}
	}()

	video, err := r.videos.Get(ctx, videoID)
	if err != nil {
		log.Error("could not load video", slog.Any("error", err))
		r.fail(ctx, videoID, jobID, err.Error())
		return
	}

	report := func(p Progress) {
		if err := r.jobs.UpdateProgress(ctx, jobID, p.Stage, p.Percent, p.Current, p.Total); err != nil {
			// Losing a progress update is cosmetic; it must never abort the work.
			log.Warn("could not record progress", slog.Any("error", err))
		}
	}

	log.Info("step started")
	start := r.clock.Now()

	if err := step.Run(ctx, video, report); err != nil {
		log.Error("step failed", slog.Any("error", err), slog.Duration("took", r.clock.Since(start)))
		r.fail(ctx, videoID, jobID, err.Error())
		return
	}

	// Success: move the video on and close the job, atomically.
	err = r.tx.WithTx(ctx, func(ctx context.Context) error {
		fresh, err := r.videos.Get(ctx, videoID)
		if err != nil {
			return err
		}
		if err := domain.Transition(fresh, step.To()); err != nil {
			return err
		}
		fresh.UpdatedAt = r.clock.Now()
		if err := r.videos.Update(ctx, fresh); err != nil {
			return err
		}
		return r.jobs.Finish(ctx, jobID, domain.JobSucceeded, "", r.clock.Now())
	})
	if err != nil {
		log.Error("could not record success", slog.Any("error", err))
		r.fail(ctx, videoID, jobID, err.Error())
		return
	}

	log.Info("step finished", slog.Duration("took", r.clock.Since(start)))
}

// fail records a failed step: the video goes to error with a resume point,
// and the job records why.
func (r *Runner) fail(ctx context.Context, videoID, jobID, message string) {
	err := r.tx.WithTx(ctx, func(ctx context.Context) error {
		video, err := r.videos.Get(ctx, videoID)
		if err != nil {
			return err
		}
		domain.Fail(video, message)
		video.UpdatedAt = r.clock.Now()
		if err := r.videos.Update(ctx, video); err != nil {
			return err
		}
		return r.jobs.Finish(ctx, jobID, domain.JobFailed, message, r.clock.Now())
	})
	if err != nil && !errors.Is(err, context.Canceled) {
		// Nothing left to do but say so loudly: the video may now be stuck in
		// a running state, which `rewind doctor` should surface.
		logging.FromContext(ctx, r.log).Error("could not record failure",
			slog.String("video_id", videoID),
			slog.String("job_id", jobID),
			slog.Any("error", err),
		)
	}
}

// RecoverInterrupted is called at startup.
//
// A video left in a running state by a crash would sit there forever, because
// nothing is working on it any more. Marking it as an error with a clear
// message makes it recoverable with `rewind retry` (SPEC.md 13.3).
func (r *Runner) RecoverInterrupted(ctx context.Context) error {
	now := r.clock.Now()

	count, err := r.jobs.MarkRunningAsInterrupted(ctx, now)
	if err != nil {
		return fmt.Errorf("marking interrupted jobs: %w", err)
	}

	videos, err := r.videos.List(ctx, domain.VideoFilter{Statuses: r.registry.RunningStatuses()})
	if err != nil {
		return fmt.Errorf("listing in-progress videos: %w", err)
	}

	for _, video := range videos {
		domain.Fail(video, "interrupted by a restart; run `rewind retry "+video.ID+"`")
		video.UpdatedAt = now
		if err := r.videos.Update(ctx, video); err != nil {
			return fmt.Errorf("recovering video %q: %w", video.ID, err)
		}
	}

	if count > 0 || len(videos) > 0 {
		r.log.Warn("recovered from an interrupted run",
			slog.Int("jobs", count),
			slog.Int("videos", len(videos)),
		)
	}
	return nil
}
