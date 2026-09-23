package steps

import (
	"context"
	"fmt"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/service"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/service/pipeline"
)

// Relevance is Module 3: propose modern comparisons (SPEC.md 5.3).
//
// facts_approved -> finding_refs -> refs_ready, then Gate B.
//
// The whole file is this size because the step does one thing: read the facts
// a human approved, hand them to the worker, and report. Everything else --
// the state change, the job record, the error handling -- belongs to the
// runner (SPEC.md 14.3, Template Method).
type Relevance struct {
	ai           domain.AIEngine
	facts        domain.FactStore
	maxProposals int
}

// NewRelevance wires the step.
func NewRelevance(ai domain.AIEngine, facts domain.FactStore, maxProposals int) *Relevance {
	return &Relevance{ai: ai, facts: facts, maxProposals: maxProposals}
}

// From implements pipeline.Step.
func (s *Relevance) From() domain.Status { return domain.StatusFactsApproved }

// Running implements pipeline.Step.
func (s *Relevance) Running() domain.Status { return domain.StatusFindingRefs }

// To implements pipeline.Step.
func (s *Relevance) To() domain.Status { return domain.StatusRefsReady }

// Run implements pipeline.Step.
func (s *Relevance) Run(ctx context.Context, v *domain.Video, report pipeline.ProgressFn) error {
	sheet, exists, err := s.facts.Load(v.ID)
	if err != nil {
		return fmt.Errorf("relevance: loading facts: %w", err)
	}
	if !exists {
		// Cannot normally happen -- the state machine only reaches this step
		// after Gate A -- but a hand-deleted file should say so plainly.
		return fmt.Errorf("relevance: no fact sheet for %q", v.ID)
	}

	approved := service.ApprovedFactsFor(sheet)
	if len(approved) == 0 {
		return fmt.Errorf("relevance: no approved facts for %q", v.ID)
	}

	result, err := s.ai.ProposeReferences(ctx, domain.ReferencesRequest{
		VideoID:      v.ID,
		Topic:        v.Topic,
		Facts:        approved,
		MaxProposals: s.maxProposals,
	}, func(p domain.Progress) {
		report(pipeline.Progress{
			Stage:   p.Stage,
			Percent: p.Percent,
			Current: p.Current,
			Total:   p.Total,
		})
	})
	if err != nil {
		return fmt.Errorf("relevance: %w", err)
	}

	report(pipeline.Progress{
		Stage:   fmt.Sprintf("%d comparisons ready for review", result.ProposalCount),
		Percent: 1,
	})
	return nil
}

var _ pipeline.Step = (*Relevance)(nil)
