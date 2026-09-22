package service

import (
	"context"
	"fmt"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/platform/validate"
)

// VideoService is the use case layer for the queue.
//
// Both the CLI and the dashboard call these methods, so there is exactly one
// implementation of the rules. A second code path is how "gates can never be
// skipped" quietly stops being true.
type VideoService struct {
	videos domain.VideoRepo
	log    domain.ReviewLog
	tx     domain.TxManager
	clock  domain.Clock
	ids    domain.IDGen
}

// NewVideoService wires the service. Constructor injection, no globals.
func NewVideoService(
	videos domain.VideoRepo,
	log domain.ReviewLog,
	tx domain.TxManager,
	clock domain.Clock,
	ids domain.IDGen,
) *VideoService {
	return &VideoService{videos: videos, log: log, tx: tx, clock: clock, ids: ids}
}

// AddVideo queues a new topic.
func (s *VideoService) AddVideo(ctx context.Context, topic string, priority domain.Priority, notes string) (*domain.Video, error) {
	if topic == "" {
		return nil, fmt.Errorf("%w: a topic is required", domain.ErrValidation)
	}
	if priority == 0 {
		priority = domain.PriorityDefault
	}
	if !priority.Valid() {
		return nil, fmt.Errorf("%w: priority %d is outside 1..5", domain.ErrValidation, priority)
	}

	id, err := s.ids.NewID(ctx, topic, s.exists)
	if err != nil {
		return nil, err
	}
	// Defence in depth: the generator already produces safe ids, but this is
	// the last point before the value becomes a directory name.
	if err := validate.VideoID(id); err != nil {
		return nil, err
	}

	now := s.clock.Now()
	v := &domain.Video{
		ID:        id,
		Topic:     topic,
		Status:    domain.StatusQueued,
		Priority:  priority,
		Notes:     notes,
		CreatedAt: now,
		UpdatedAt: now,
	}

	err = s.tx.WithTx(ctx, func(ctx context.Context) error {
		if err := s.videos.Create(ctx, v); err != nil {
			return err
		}
		return s.log.Append(ctx, &domain.ReviewEntry{
			VideoID:    v.ID,
			At:         now,
			Gate:       domain.GateNone,
			Action:     domain.ActionCreate,
			FromStatus: "",
			ToStatus:   domain.StatusQueued,
			Note:       notes,
		})
	})
	if err != nil {
		return nil, err
	}
	return v, nil
}

// exists reports whether an id is taken, for the id generator.
func (s *VideoService) exists(ctx context.Context, id string) (bool, error) {
	_, err := s.videos.Get(ctx, id)
	switch {
	case err == nil:
		return true, nil
	case isNotFound(err):
		return false, nil
	default:
		return false, err
	}
}

// ListVideos returns the queue.
func (s *VideoService) ListVideos(ctx context.Context, f domain.VideoFilter) ([]*domain.Video, error) {
	return s.videos.List(ctx, f)
}

// GetVideo returns one video.
func (s *VideoService) GetVideo(ctx context.Context, id string) (*domain.Video, error) {
	if err := validate.VideoID(id); err != nil {
		return nil, err
	}
	return s.videos.Get(ctx, id)
}

// ListReviewLog returns a video's decision history.
func (s *VideoService) ListReviewLog(ctx context.Context, id string) ([]*domain.ReviewEntry, error) {
	if err := validate.VideoID(id); err != nil {
		return nil, err
	}
	return s.log.List(ctx, id)
}

// RetryVideo resumes a failed video from the step that failed.
func (s *VideoService) RetryVideo(ctx context.Context, id string) (*domain.Video, error) {
	if err := validate.VideoID(id); err != nil {
		return nil, err
	}

	var updated *domain.Video
	err := s.tx.WithTx(ctx, func(ctx context.Context) error {
		v, err := s.videos.Get(ctx, id)
		if err != nil {
			return err
		}

		from := v.Status
		if err := domain.Retry(v); err != nil {
			return err
		}
		v.UpdatedAt = s.clock.Now()

		if err := s.videos.Update(ctx, v); err != nil {
			return err
		}
		if err := s.log.Append(ctx, &domain.ReviewEntry{
			VideoID:    v.ID,
			At:         v.UpdatedAt,
			Gate:       domain.GateNone,
			Action:     domain.ActionRetry,
			FromStatus: from,
			ToStatus:   v.Status,
		}); err != nil {
			return err
		}

		updated = v
		return nil
	})
	if err != nil {
		return nil, err
	}
	return updated, nil
}

// NextStep describes what `rewind run` would do next with a video. It is
// returned rather than acted on, because no pipeline step exists before M2.
type NextStep struct {
	Video *domain.Video
	// AwaitingGate is set when the video needs a human before it can move.
	AwaitingGate domain.Gate
	// NextStatus is where a successful step would take it.
	NextStatus domain.Status
	// Reason explains why nothing will happen, when nothing will.
	Reason string
}

// PlanNext reports what would happen next for one video.
//
// M1 deliberately plans rather than executes: the orchestrator and the
// pipeline steps arrive in M2. Reporting the plan honestly is more useful than
// a `run` that silently does nothing.
func (s *VideoService) PlanNext(ctx context.Context, id string) (*NextStep, error) {
	v, err := s.GetVideo(ctx, id)
	if err != nil {
		return nil, err
	}

	step := &NextStep{Video: v}

	if g, waiting := domain.GateFor(v.Status); waiting {
		step.AwaitingGate = g
		step.Reason = fmt.Sprintf("waiting for your review at %s", g)
		return step, nil
	}
	if v.Status == domain.StatusError {
		step.Reason = fmt.Sprintf("failed: %s (run `rewind retry %s`)", v.Error, v.ID)
		return step, nil
	}

	next, ok := domain.NextAutomatic(v.Status)
	if !ok {
		step.Reason = fmt.Sprintf("nothing further happens automatically from %s", v.Status)
		return step, nil
	}

	step.NextStatus = next
	step.Reason = fmt.Sprintf("would run the %s step (not implemented until M2)", next)
	return step, nil
}

func isNotFound(err error) bool {
	return err != nil && errorsIs(err, domain.ErrNotFound)
}
