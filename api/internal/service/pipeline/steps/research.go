// Package steps holds one file per pipeline step.
//
// Each file is self-contained: it declares which status it starts from, which
// it moves to, and how to do the work. Adding a step never requires editing
// the runner, the registry, the CLI or the dashboard (SPEC.md 14.2).
package steps

import (
	"context"
	"fmt"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/service/pipeline"
)

// Research is Module 2: build a sourced fact sheet (SPEC.md 5.2).
//
// queued -> researching -> facts_ready, then Gate A.
//
// It picks up a freshly queued video, holds it in `researching` while it
// works, and leaves it in `facts_ready` for a human.
//
// Note what this step does NOT do: it does not decide the video's status, it
// does not touch the database, and it cannot approve Gate A. It calls the
// worker and returns. Everything else is the runner's job.
type Research struct {
	ai       domain.AIEngine
	minFacts int
}

// NewResearch wires the step.
func NewResearch(ai domain.AIEngine, minFacts int) *Research {
	return &Research{ai: ai, minFacts: minFacts}
}

// From implements pipeline.Step.
func (s *Research) From() domain.Status { return domain.StatusQueued }

// Running implements pipeline.Step.
func (s *Research) Running() domain.Status { return domain.StatusResearching }

// To implements pipeline.Step.
func (s *Research) To() domain.Status { return domain.StatusFactsReady }

// Run implements pipeline.Step.
func (s *Research) Run(ctx context.Context, v *domain.Video, report pipeline.ProgressFn) error {
	result, err := s.ai.BuildFactSheet(ctx, domain.FactSheetRequest{
		VideoID:   v.ID,
		Topic:     v.Topic,
		ExtraURLs: extractURLs(v.Notes),
		MinFacts:  s.minFacts,
	}, func(p domain.Progress) {
		report(pipeline.Progress{
			Stage:   p.Stage,
			Percent: p.Percent,
			Current: p.Current,
			Total:   p.Total,
		})
	})
	if err != nil {
		return fmt.Errorf("research: %w", err)
	}

	report(pipeline.Progress{
		Stage:   fmt.Sprintf("%d facts ready for review", result.FactCount),
		Percent: 1,
	})
	return nil
}

// extractURLs pulls any http(s) URLs out of the video's notes, so a source
// pasted into `rewind add --notes` is fetched alongside Wikipedia (SPEC.md 5.2).
func extractURLs(notes string) []string {
	var urls []string
	for _, field := range splitFields(notes) {
		trimmed := trimPunctuation(field)
		if len(trimmed) > 8 && (hasPrefix(trimmed, "https://") || hasPrefix(trimmed, "http://")) {
			urls = append(urls, trimmed)
		}
	}
	return urls
}

// The helpers below avoid importing strings for four one-line calls, and keep
// the URL rules visible in one place rather than scattered through the parser.

func splitFields(s string) []string {
	var out []string
	current := ""
	for _, r := range s {
		if r == ' ' || r == '\n' || r == '\t' || r == '\r' || r == ',' || r == ';' {
			if current != "" {
				out = append(out, current)
				current = ""
			}
			continue
		}
		current += string(r)
	}
	if current != "" {
		out = append(out, current)
	}
	return out
}

func trimPunctuation(s string) string {
	for len(s) > 0 {
		last := s[len(s)-1]
		if last == '.' || last == ')' || last == ']' || last == '"' || last == '\'' {
			s = s[:len(s)-1]
			continue
		}
		break
	}
	return s
}

func hasPrefix(s, prefix string) bool {
	return len(s) >= len(prefix) && s[:len(prefix)] == prefix
}

var _ pipeline.Step = (*Research)(nil)
