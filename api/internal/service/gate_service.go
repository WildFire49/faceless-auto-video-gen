package service

import (
	"context"
	"errors"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/platform/validate"
)

// GateService performs the six human review decisions.
//
// Every method here writes a review-log entry in the SAME transaction as the
// state change. An approval that moved a video but lost its audit entry would
// destroy the evidence the log exists to provide (SPEC.md 7, 13.3), so the two
// succeed together or neither happens.
type GateService struct {
	videos domain.VideoRepo
	log    domain.ReviewLog
	tx     domain.TxManager
	clock  domain.Clock
}

// NewGateService wires the service.
func NewGateService(
	videos domain.VideoRepo,
	log domain.ReviewLog,
	tx domain.TxManager,
	clock domain.Clock,
) *GateService {
	return &GateService{videos: videos, log: log, tx: tx, clock: clock}
}

// Approve records a human approval and advances the video past the gate.
func (s *GateService) Approve(ctx context.Context, id string, gate domain.Gate, note string) (*domain.Video, error) {
	return s.decide(ctx, id, func(v *domain.Video) (*domain.ReviewEntry, error) {
		from := v.Status
		if err := domain.ApproveGate(v, gate); err != nil {
			return nil, err
		}
		return &domain.ReviewEntry{
			VideoID:    v.ID,
			Gate:       gate,
			Action:     domain.ActionApprove,
			FromStatus: from,
			ToStatus:   v.Status,
			Note:       note,
		}, nil
	})
}

// Reject sends a video back to an earlier state with a required note.
func (s *GateService) Reject(ctx context.Context, id string, gate domain.Gate, backTo domain.Status, note string) (*domain.Video, error) {
	return s.decide(ctx, id, func(v *domain.Video) (*domain.ReviewEntry, error) {
		from := v.Status
		if err := domain.RejectGate(v, gate, backTo, note); err != nil {
			return nil, err
		}
		return &domain.ReviewEntry{
			VideoID:    v.ID,
			Gate:       gate,
			Action:     domain.ActionReject,
			FromStatus: from,
			ToStatus:   v.Status,
			Note:       note,
		}, nil
	})
}

// decide is the shared shape of every gate decision: load, apply the domain
// rule, persist, and log -- all inside one transaction.
//
// Approve and Reject differ only in the rule they apply, so the transaction
// and logging boilerplate lives here once rather than in each of them.
func (s *GateService) decide(
	ctx context.Context,
	id string,
	apply func(*domain.Video) (*domain.ReviewEntry, error),
) (*domain.Video, error) {
	if err := validate.VideoID(id); err != nil {
		return nil, err
	}

	var updated *domain.Video
	err := s.tx.WithTx(ctx, func(ctx context.Context) error {
		v, err := s.videos.Get(ctx, id)
		if err != nil {
			return err
		}

		entry, err := apply(v)
		if err != nil {
			return err
		}

		now := s.clock.Now()
		v.UpdatedAt = now
		entry.At = now

		if err := s.videos.Update(ctx, v); err != nil {
			return err
		}
		if err := s.log.Append(ctx, entry); err != nil {
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

// errorsIs is a tiny indirection so this package does not import errors in
// several files for one call.
func errorsIs(err, target error) bool { return errors.Is(err, target) }
