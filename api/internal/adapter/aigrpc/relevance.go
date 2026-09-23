package aigrpc

import (
	"context"
	"errors"
	"fmt"
	"io"

	rewindv1 "github.com/WildFire49/faceless-auto-video-gen/api/gen/rewind/v1"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
)

// ProposeReferences implements domain.AIEngine over the worker's
// server-streaming ProposeReferences RPC.
//
// Same shape as BuildFactSheet: drain events, forward progress, treat the one
// terminal result-or-failure as the outcome.
func (e *Engine) ProposeReferences(
	ctx context.Context,
	req domain.ReferencesRequest,
	report func(domain.Progress),
) (*domain.ReferencesResult, error) {
	ctx, cancel := context.WithTimeout(ctx, e.relevanceTimeout)
	defer cancel()
	ctx = e.withTrace(ctx)
	e.nudgeReconnect()

	facts := make([]*rewindv1.ApprovedFact, 0, len(req.Facts))
	for _, f := range req.Facts {
		facts = append(facts, &rewindv1.ApprovedFact{
			Id: f.ID, Label: f.Label, Claim: f.Claim, Group: f.Group,
		})
	}

	stream, err := e.relevance.ProposeReferences(ctx, &rewindv1.ProposeReferencesRequest{
		VideoId:      req.VideoID,
		Topic:        req.Topic,
		Facts:        facts,
		MaxProposals: int32(req.MaxProposals),
	})
	if err != nil {
		return nil, fmt.Errorf("starting relevance for %q: %w", req.Topic, err)
	}

	var result *domain.ReferencesResult

	for {
		event, err := stream.Recv()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			return nil, fmt.Errorf("relevance stream for %q: %w", req.Topic, err)
		}

		switch payload := event.GetEvent().(type) {
		case *rewindv1.ProposeReferencesResponse_Progress:
			if report != nil {
				report(domain.Progress{
					Stage:   payload.Progress.GetStage(),
					Percent: payload.Progress.GetPercent(),
					Current: int(payload.Progress.GetCurrent()),
					Total:   int(payload.Progress.GetTotal()),
				})
			}

		case *rewindv1.ProposeReferencesResponse_Failure:
			f := payload.Failure
			return nil, fmt.Errorf("%s: %s", f.GetCode(), f.GetMessage())

		case *rewindv1.ProposeReferencesResponse_Result:
			sheet := payload.Result
			result = &domain.ReferencesResult{
				Topic:              sheet.GetTopic(),
				ProposalCount:      len(sheet.GetProposals()),
				ReferencesJSONPath: sheet.GetReferencesJsonPath(),
				Generated:          int(sheet.GetCandidatesGenerated()),
				Rejected:           int(sheet.GetCandidatesRejected()),
			}
		}
	}

	if result == nil {
		// The stream ended with no terminal event -- a contract violation by
		// the worker. Succeeding silently would leave the video marked ready
		// with no comparisons behind it.
		return nil, fmt.Errorf("relevance for %q ended without a result", req.Topic)
	}
	return result, nil
}
