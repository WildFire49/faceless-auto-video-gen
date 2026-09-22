package connectrpc

import (
	"context"

	"connectrpc.com/connect"

	rewindv1 "github.com/WildFire49/faceless-auto-video-gen/api/gen/rewind/v1"
	"github.com/WildFire49/faceless-auto-video-gen/api/gen/rewind/v1/rewindv1connect"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/service"
)

// FactsHandler serves rewind.v1.FactsService -- the Gate A surface.
type FactsHandler struct {
	facts *service.FactsService
}

// NewFactsHandler wires the handler to its use case.
func NewFactsHandler(facts *service.FactsService) *FactsHandler {
	return &FactsHandler{facts: facts}
}

func (h *FactsHandler) GetFacts(
	ctx context.Context,
	req *connect.Request[rewindv1.GetFactsRequest],
) (*connect.Response[rewindv1.GetFactsResponse], error) {
	view, err := h.facts.GetFacts(ctx, req.Msg.GetVideoId())
	if err != nil {
		return nil, toConnectError(err)
	}
	return connect.NewResponse(&rewindv1.GetFactsResponse{View: toProtoFactsView(view)}), nil
}

func (h *FactsHandler) SetFactApproval(
	ctx context.Context,
	req *connect.Request[rewindv1.SetFactApprovalRequest],
) (*connect.Response[rewindv1.SetFactApprovalResponse], error) {
	view, err := h.facts.SetApproval(ctx,
		req.Msg.GetVideoId(), req.Msg.GetFactId(), req.Msg.GetApproved())
	if err != nil {
		return nil, toConnectError(err)
	}
	return connect.NewResponse(&rewindv1.SetFactApprovalResponse{View: toProtoFactsView(view)}), nil
}

func (h *FactsHandler) ApproveAllFacts(
	ctx context.Context,
	req *connect.Request[rewindv1.ApproveAllFactsRequest],
) (*connect.Response[rewindv1.ApproveAllFactsResponse], error) {
	view, err := h.facts.ApproveAll(ctx, req.Msg.GetVideoId(), req.Msg.GetApproved())
	if err != nil {
		return nil, toConnectError(err)
	}
	return connect.NewResponse(&rewindv1.ApproveAllFactsResponse{View: toProtoFactsView(view)}), nil
}

func (h *FactsHandler) UpdateFact(
	ctx context.Context,
	req *connect.Request[rewindv1.UpdateFactRequest],
) (*connect.Response[rewindv1.UpdateFactResponse], error) {
	view, err := h.facts.UpdateFact(ctx,
		req.Msg.GetVideoId(),
		req.Msg.GetFactId(),
		req.Msg.GetYearLabel(),
		int(req.Msg.GetSortYear()),
		req.Msg.GetPlace(),
		req.Msg.GetClaim(),
	)
	if err != nil {
		return nil, toConnectError(err)
	}
	return connect.NewResponse(&rewindv1.UpdateFactResponse{View: toProtoFactsView(view)}), nil
}

func (h *FactsHandler) DeleteFact(
	ctx context.Context,
	req *connect.Request[rewindv1.DeleteFactRequest],
) (*connect.Response[rewindv1.DeleteFactResponse], error) {
	view, err := h.facts.DeleteFact(ctx,
		req.Msg.GetVideoId(), req.Msg.GetFactId(), req.Msg.GetReason())
	if err != nil {
		return nil, toConnectError(err)
	}
	return connect.NewResponse(&rewindv1.DeleteFactResponse{View: toProtoFactsView(view)}), nil
}

func (h *FactsHandler) AddFact(
	ctx context.Context,
	req *connect.Request[rewindv1.AddFactRequest],
) (*connect.Response[rewindv1.AddFactResponse], error) {
	view, err := h.facts.AddFact(ctx, req.Msg.GetVideoId(), domain.Fact{
		YearLabel: req.Msg.GetYearLabel(),
		SortYear:  int(req.Msg.GetSortYear()),
		Place:     req.Msg.GetPlace(),
		Claim:     req.Msg.GetClaim(),
		SourceURL: req.Msg.GetSourceUrl(),
		Evidence:  req.Msg.GetEvidence(),
	})
	if err != nil {
		return nil, toConnectError(err)
	}
	return connect.NewResponse(&rewindv1.AddFactResponse{View: toProtoFactsView(view)}), nil
}

func toProtoFactsView(view *service.FactsView) *rewindv1.FactsView {
	if view == nil || !view.Exists {
		return &rewindv1.FactsView{Exists: false}
	}

	sheet := &rewindv1.FactSheet{
		Topic:         view.Sheet.Topic,
		FactsJsonPath: view.Sheet.Path,
	}
	for _, f := range view.Sheet.Facts {
		sheet.Facts = append(sheet.Facts, &rewindv1.Fact{
			Id:          f.ID,
			YearLabel:   f.YearLabel,
			SortYear:    int32(f.SortYear),
			Place:       f.Place,
			Claim:       f.Claim,
			Evidence:    f.Evidence,
			SourceUrl:   f.SourceURL,
			SourceTitle: f.SourceTitle,
			Confidence:  f.Confidence,
			Conflict:    f.Conflict,
			Approved:    f.Approved,
			MatchScore:  f.MatchScore,
		})
	}
	for _, src := range view.Sheet.Sources {
		sheet.Sources = append(sheet.Sources, &rewindv1.SourceDocument{
			Url:       src.URL,
			Title:     src.Title,
			Fetcher:   src.Fetcher,
			CharCount: int32(src.CharCount),
		})
	}

	return &rewindv1.FactsView{
		Exists:          true,
		Sheet:           sheet,
		CanApprove:      view.Readiness.CanApprove,
		ApprovalBlocker: view.Readiness.Blocker,
		ApprovedCount:   int32(view.Readiness.Approved),
		EraCount:        int32(view.Readiness.Eras),
	}
}

var _ rewindv1connect.FactsServiceHandler = (*FactsHandler)(nil)
