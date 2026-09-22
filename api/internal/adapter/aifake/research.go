package aifake

import (
	"context"
	"fmt"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
)

// BuildFactSheet implements domain.AIEngine with a canned result, so Go tests
// and `rewind-api --fake-ai` exercise the whole orchestration path with no
// Python, no Ollama and no network.
func (e *Engine) BuildFactSheet(
	ctx context.Context,
	req domain.FactSheetRequest,
	report func(domain.Progress),
) (*domain.FactSheetResult, error) {
	e.ResearchCalls = append(e.ResearchCalls, req)

	if err := ctx.Err(); err != nil {
		return nil, err
	}
	if e.ResearchErr != nil {
		return nil, e.ResearchErr
	}

	// Emit the same progress shape the real worker does, so a UI built
	// against the fake behaves the same against the real one.
	if report != nil {
		for _, stage := range []struct {
			name    string
			percent float64
		}{
			{"fetching wikipedia", 0.2},
			{"reading sources", 0.5},
			{"verifying evidence", 0.8},
		} {
			report(domain.Progress{Stage: stage.name, Percent: stage.percent})
		}
	}

	if e.ResearchResult != nil {
		return e.ResearchResult, nil
	}

	return &domain.FactSheetResult{
		Topic:               req.Topic,
		FactCount:           max(req.MinFacts, 8),
		FactsJSONPath:       fmt.Sprintf("projects/%s/facts.json", req.VideoID),
		CandidatesExtracted: 12,
		CandidatesRejected:  2,
	}, nil
}
