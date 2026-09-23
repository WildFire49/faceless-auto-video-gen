package aifake

import (
	"context"
	"fmt"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
)

// ProposeReferences implements domain.AIEngine with a canned result, so Go
// tests and `rewind-api --fake-ai` exercise the whole orchestration path with
// no Python, no Ollama and no network.
func (e *Engine) ProposeReferences(
	ctx context.Context,
	req domain.ReferencesRequest,
	report func(domain.Progress),
) (*domain.ReferencesResult, error) {
	e.ReferenceCalls = append(e.ReferenceCalls, req)

	if err := ctx.Err(); err != nil {
		return nil, err
	}
	if e.ReferenceErr != nil {
		return nil, e.ReferenceErr
	}

	if report != nil {
		for _, stage := range []struct {
			name    string
			percent float64
		}{
			{"reading the reference bank", 0.1},
			{"checking today's trends", 0.25},
			{"writing comparisons", 0.5},
			{"checking them against the rules", 0.8},
		} {
			report(domain.Progress{Stage: stage.name, Percent: stage.percent})
		}
	}

	if e.ReferenceResult != nil {
		return e.ReferenceResult, nil
	}

	return &domain.ReferencesResult{
		Topic:              req.Topic,
		ProposalCount:      4,
		ReferencesJSONPath: fmt.Sprintf("projects/%s/references.json", req.VideoID),
		Generated:          6,
		Rejected:           2,
	}, nil
}
