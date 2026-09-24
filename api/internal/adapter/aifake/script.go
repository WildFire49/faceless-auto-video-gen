package aifake

import (
	"context"
	"fmt"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
)

// ScriptFake holds the fake script writer's canned behaviour. Embedded in
// Engine so one fake serves every AI port.
type ScriptFake struct {
	// ScriptResult, when set, is returned by GenerateScript.
	ScriptResult *domain.ScriptResult
	// ScriptErr, when set, makes GenerateScript fail.
	ScriptErr error
	// ScriptCalls records every script request, so a test can assert that only
	// approved facts and selected comparisons were forwarded.
	ScriptCalls []domain.ScriptRequest

	// Violations is what ValidateScript returns. Nil means "valid".
	Violations []domain.Violation
	// ValidateErr, when set, makes ValidateScript fail.
	ValidateErr error
	// ValidateCalls counts validations, so a test can assert an edit was
	// re-checked rather than saved on trust.
	ValidateCalls int
}

// GenerateScript implements domain.ScriptWriter with a canned result. Like the
// other fakes it writes no file: it exercises orchestration, not content.
func (e *Engine) GenerateScript(
	ctx context.Context,
	req domain.ScriptRequest,
	report func(domain.Progress),
) (*domain.ScriptResult, error) {
	e.ScriptCalls = append(e.ScriptCalls, req)
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	if e.ScriptErr != nil {
		return nil, e.ScriptErr
	}
	if report != nil {
		report(domain.Progress{Stage: "writing the script (attempt 1 of 3)", Percent: 0.25})
		report(domain.Progress{Stage: "writing script.json", Percent: 0.97})
	}
	if e.ScriptResult != nil {
		return e.ScriptResult, nil
	}
	return &domain.ScriptResult{
		BeatCount:      9,
		Attempts:       1,
		ScriptJSONPath: fmt.Sprintf("projects/%s/script.json", req.VideoID),
	}, nil
}

// ValidateScript implements domain.ScriptWriter.
func (e *Engine) ValidateScript(
	ctx context.Context,
	_ *domain.Script,
	_ []domain.ScriptFact,
	_ []domain.ScriptReference,
) ([]domain.Violation, error) {
	e.ValidateCalls++
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	if e.ValidateErr != nil {
		return nil, e.ValidateErr
	}
	return e.Violations, nil
}

var _ domain.ScriptWriter = (*Engine)(nil)
