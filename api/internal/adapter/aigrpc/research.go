package aigrpc

import (
	"context"
	"errors"
	"fmt"
	"io"

	rewindv1 "github.com/WildFire49/faceless-auto-video-gen/api/gen/rewind/v1"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
)

// BuildFactSheet implements domain.AIEngine by consuming the worker's
// server-streaming BuildFactSheet RPC.
//
// The shape here is the template every later long-running call follows: read
// events until the stream ends, forward Progress to the caller, and treat the
// single terminal result-or-failure as the outcome.
func (e *Engine) BuildFactSheet(
	ctx context.Context,
	req domain.FactSheetRequest,
	report func(domain.Progress),
) (*domain.FactSheetResult, error) {
	ctx, cancel := context.WithTimeout(ctx, e.researchTimeout)
	defer cancel()
	ctx = e.withTrace(ctx)
	e.nudgeReconnect()

	stream, err := e.research.BuildFactSheet(ctx, &rewindv1.BuildFactSheetRequest{
		VideoId:   req.VideoID,
		Topic:     req.Topic,
		ExtraUrls: req.ExtraURLs,
		MinFacts:  int32(req.MinFacts),
	})
	if err != nil {
		return nil, fmt.Errorf("starting research for %q: %w", req.Topic, err)
	}

	var result *domain.FactSheetResult

	for {
		event, err := stream.Recv()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			return nil, fmt.Errorf("research stream for %q: %w", req.Topic, err)
		}

		switch payload := event.GetEvent().(type) {
		case *rewindv1.BuildFactSheetResponse_Progress:
			if report != nil {
				report(domain.Progress{
					Stage:   payload.Progress.GetStage(),
					Percent: payload.Progress.GetPercent(),
					Current: int(payload.Progress.GetCurrent()),
					Total:   int(payload.Progress.GetTotal()),
				})
			}

		case *rewindv1.BuildFactSheetResponse_Failure:
			// The worker reports WHAT went wrong; turning it into a video
			// status is the runner's decision, not ours.
			f := payload.Failure
			return nil, fmt.Errorf("%s: %s", f.GetCode(), f.GetMessage())

		case *rewindv1.BuildFactSheetResponse_Result:
			sheet := payload.Result
			result = &domain.FactSheetResult{
				Topic:               sheet.GetTopic(),
				FactCount:           len(sheet.GetFacts()),
				FactsJSONPath:       sheet.GetFactsJsonPath(),
				CandidatesExtracted: int(sheet.GetCandidatesExtracted()),
				CandidatesRejected:  int(sheet.GetCandidatesRejected()),
			}
		}
	}

	if result == nil {
		// The stream ended without a terminal event. That is a contract
		// violation by the worker, and silently succeeding would leave the
		// video marked ready with no facts behind it.
		return nil, fmt.Errorf("research for %q ended without a result", req.Topic)
	}
	return result, nil
}
