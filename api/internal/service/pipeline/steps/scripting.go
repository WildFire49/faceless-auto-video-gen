package steps

import (
	"context"
	"fmt"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/service"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/service/pipeline"
)

// Scripting is Module 4: write the beat script (SPEC.md 5.4).
//
// refs_approved -> scripting -> script_ready, then Gate C.
//
// Hands the worker only what humans approved (domain.ScriptInputs) plus the
// video's angle, and reports. The worker validates and writes script.json; a
// script that is still invalid after its attempts arrives at Gate C with its
// violations, and the gate stays shut until they are fixed.
type Scripting struct {
	writer domain.ScriptWriter
	facts  domain.FactStore
	refs   domain.ReferenceStore
}

// NewScripting wires the step.
func NewScripting(writer domain.ScriptWriter, facts domain.FactStore, refs domain.ReferenceStore) *Scripting {
	return &Scripting{writer: writer, facts: facts, refs: refs}
}

// From implements pipeline.Step.
func (s *Scripting) From() domain.Status { return domain.StatusRefsApproved }

// Running implements pipeline.Step.
func (s *Scripting) Running() domain.Status { return domain.StatusScripting }

// To implements pipeline.Step.
func (s *Scripting) To() domain.Status { return domain.StatusScriptReady }

// Run implements pipeline.Step.
func (s *Scripting) Run(ctx context.Context, v *domain.Video, report pipeline.ProgressFn) error {
	facts, refs, err := service.LoadScriptInputs(s.facts, s.refs, v.ID)
	if err != nil {
		return fmt.Errorf("script: %w", err)
	}
	if len(facts) == 0 {
		return fmt.Errorf("script: no approved facts for %q", v.ID)
	}

	result, err := s.writer.GenerateScript(ctx, domain.ScriptRequest{
		VideoID:    v.ID,
		Topic:      v.Topic,
		Angle:      v.Notes,
		Facts:      facts,
		References: refs,
	}, func(p domain.Progress) {
		report(pipeline.Progress{Stage: p.Stage, Percent: p.Percent, Current: p.Current, Total: p.Total})
	})
	if err != nil {
		return fmt.Errorf("script: %w", err)
	}

	stage := fmt.Sprintf("script ready: %d beats", result.BeatCount)
	if result.ViolationCount > 0 {
		stage = fmt.Sprintf("script ready with %d rules to fix", result.ViolationCount)
	}
	report(pipeline.Progress{Stage: stage, Percent: 1})
	return nil
}

var _ pipeline.Step = (*Scripting)(nil)
