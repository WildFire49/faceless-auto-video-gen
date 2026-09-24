package aigrpc

import (
	"context"
	"errors"
	"fmt"
	"io"

	rewindv1 "github.com/WildFire49/faceless-auto-video-gen/api/gen/rewind/v1"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
)

// GenerateScript implements domain.ScriptWriter over the worker's
// server-streaming GenerateScript RPC. Same shape as the other long calls:
// drain events, forward progress, treat the one terminal event as the outcome.
func (e *Engine) GenerateScript(
	ctx context.Context,
	req domain.ScriptRequest,
	report func(domain.Progress),
) (*domain.ScriptResult, error) {
	ctx, cancel := context.WithTimeout(ctx, e.scriptTimeout)
	defer cancel()
	ctx = e.withTrace(ctx)
	e.nudgeReconnect()

	stream, err := e.script.GenerateScript(ctx, &rewindv1.GenerateScriptRequest{
		VideoId:    req.VideoID,
		Topic:      req.Topic,
		Angle:      req.Angle,
		Facts:      toProtoFacts(req.Facts),
		References: toProtoRefs(req.References),
	})
	if err != nil {
		return nil, fmt.Errorf("starting script for %q: %w", req.Topic, err)
	}

	for {
		event, err := stream.Recv()
		if errors.Is(err, io.EOF) {
			return nil, fmt.Errorf("script stream for %q ended without a result", req.Topic)
		}
		if err != nil {
			return nil, fmt.Errorf("script stream for %q: %w", req.Topic, err)
		}

		switch payload := event.GetEvent().(type) {
		case *rewindv1.GenerateScriptResponse_Progress:
			if report != nil {
				report(domain.Progress{
					Stage:   payload.Progress.GetStage(),
					Percent: payload.Progress.GetPercent(),
				})
			}
		case *rewindv1.GenerateScriptResponse_Failure:
			f := payload.Failure
			return nil, fmt.Errorf("%s: %s", f.GetCode(), f.GetMessage())
		case *rewindv1.GenerateScriptResponse_Result:
			s := payload.Result
			return &domain.ScriptResult{
				BeatCount:      len(s.GetBeats()),
				Attempts:       int(s.GetAttempts()),
				ViolationCount: len(s.GetViolations()),
				ScriptJSONPath: s.GetScriptJsonPath(),
			}, nil
		}
	}
}

// ValidateScript implements domain.ScriptWriter. Unary and model-free, so it
// runs after every inline edit at Gate C without a noticeable wait.
func (e *Engine) ValidateScript(
	ctx context.Context,
	script *domain.Script,
	facts []domain.ScriptFact,
	refs []domain.ScriptReference,
) ([]domain.Violation, error) {
	ctx, cancel := context.WithTimeout(ctx, e.validateTimeout)
	defer cancel()
	ctx = e.withTrace(ctx)
	e.nudgeReconnect()

	resp, err := e.script.ValidateScript(ctx, &rewindv1.ValidateScriptRequest{
		Script:     toProtoScript(script),
		Facts:      toProtoFacts(facts),
		References: toProtoRefs(refs),
	})
	if err != nil {
		return nil, fmt.Errorf("validating script: %w", err)
	}

	out := make([]domain.Violation, 0, len(resp.GetViolations()))
	for _, v := range resp.GetViolations() {
		out = append(out, domain.Violation{Rule: v.GetRule(), Beat: int(v.GetBeat()), Message: v.GetMessage()})
	}
	return out, nil
}

func toProtoScript(s *domain.Script) *rewindv1.Script {
	out := &rewindv1.Script{
		TitleOptions: s.TitleOptions,
		ChosenTitle:  s.ChosenTitle,
		Description:  s.Description,
		Hashtags:     s.Hashtags,
		Sources:      s.Sources,
		Attempts:     int32(s.Attempts),
	}
	for _, b := range s.Beats {
		out.Beats = append(out.Beats, &rewindv1.Beat{
			N:             int32(b.N),
			Role:          b.Role,
			YearStamp:     b.YearStamp,
			Voice:         b.Voice,
			OnScreenText:  b.OnScreenText,
			VisualPrompts: b.VisualPrompts,
			Sfx:           b.SFX,
			Motion:        b.Motion,
			EmphasisWords: b.EmphasisWords,
			FactIds:       b.FactIDs,
			RefIds:        b.RefIDs,
			IsPunch:       b.IsPunch,
		})
	}
	return out
}

func toProtoFacts(facts []domain.ScriptFact) []*rewindv1.ScriptFact {
	out := make([]*rewindv1.ScriptFact, 0, len(facts))
	for _, f := range facts {
		out = append(out, &rewindv1.ScriptFact{
			Id: f.ID, Label: f.Label, Claim: f.Claim, Evidence: f.Evidence,
			Context: f.Context, SourceUrl: f.SourceURL, Group: f.Group,
		})
	}
	return out
}

func toProtoRefs(refs []domain.ScriptReference) []*rewindv1.ScriptReference {
	out := make([]*rewindv1.ScriptReference, 0, len(refs))
	for _, r := range refs {
		out = append(out, &rewindv1.ScriptReference{
			Id: r.ID, Reference: r.Reference, Comparison: r.Comparison, LinkedFactId: r.LinkedFactID,
		})
	}
	return out
}

var _ domain.ScriptWriter = (*Engine)(nil)
