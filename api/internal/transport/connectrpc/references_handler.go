package connectrpc

import (
	"context"

	"connectrpc.com/connect"

	rewindv1 "github.com/WildFire49/faceless-auto-video-gen/api/gen/rewind/v1"
	"github.com/WildFire49/faceless-auto-video-gen/api/gen/rewind/v1/rewindv1connect"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/service"
)

// ReferencesHandler serves rewind.v1.ReferencesService -- the Gate B surface.
type ReferencesHandler struct {
	refs *service.ReferencesService
}

// NewReferencesHandler wires the handler to its use case.
func NewReferencesHandler(refs *service.ReferencesService) *ReferencesHandler {
	return &ReferencesHandler{refs: refs}
}

func (h *ReferencesHandler) GetReferences(
	ctx context.Context,
	req *connect.Request[rewindv1.GetReferencesRequest],
) (*connect.Response[rewindv1.GetReferencesResponse], error) {
	view, err := h.refs.GetReferences(ctx, req.Msg.GetVideoId())
	if err != nil {
		return nil, toConnectError(err)
	}
	return connect.NewResponse(&rewindv1.GetReferencesResponse{View: toProtoRefsView(view)}), nil
}

func (h *ReferencesHandler) SelectProposal(
	ctx context.Context,
	req *connect.Request[rewindv1.SelectProposalRequest],
) (*connect.Response[rewindv1.SelectProposalResponse], error) {
	view, err := h.refs.Select(ctx,
		req.Msg.GetVideoId(), req.Msg.GetProposalId(), req.Msg.GetSelected())
	if err != nil {
		return nil, toConnectError(err)
	}
	return connect.NewResponse(&rewindv1.SelectProposalResponse{View: toProtoRefsView(view)}), nil
}

func (h *ReferencesHandler) UpdateProposal(
	ctx context.Context,
	req *connect.Request[rewindv1.UpdateProposalRequest],
) (*connect.Response[rewindv1.UpdateProposalResponse], error) {
	view, err := h.refs.UpdateProposal(ctx,
		req.Msg.GetVideoId(),
		req.Msg.GetProposalId(),
		req.Msg.GetComparison(),
		req.Msg.GetWhyFunny(),
		req.Msg.GetLinkedFactId(),
	)
	if err != nil {
		return nil, toConnectError(err)
	}
	return connect.NewResponse(&rewindv1.UpdateProposalResponse{View: toProtoRefsView(view)}), nil
}

func (h *ReferencesHandler) DeleteProposal(
	ctx context.Context,
	req *connect.Request[rewindv1.DeleteProposalRequest],
) (*connect.Response[rewindv1.DeleteProposalResponse], error) {
	view, err := h.refs.DeleteProposal(ctx,
		req.Msg.GetVideoId(), req.Msg.GetProposalId(), req.Msg.GetReason())
	if err != nil {
		return nil, toConnectError(err)
	}
	return connect.NewResponse(&rewindv1.DeleteProposalResponse{View: toProtoRefsView(view)}), nil
}

func (h *ReferencesHandler) AddProposal(
	ctx context.Context,
	req *connect.Request[rewindv1.AddProposalRequest],
) (*connect.Response[rewindv1.AddProposalResponse], error) {
	view, err := h.refs.AddProposal(ctx,
		req.Msg.GetVideoId(),
		req.Msg.GetReference(),
		req.Msg.GetComparison(),
		req.Msg.GetWhyFunny(),
		req.Msg.GetLinkedFactId(),
	)
	if err != nil {
		return nil, toConnectError(err)
	}
	return connect.NewResponse(&rewindv1.AddProposalResponse{View: toProtoRefsView(view)}), nil
}

var kindToProto = map[domain.ReferenceKind]rewindv1.ReferenceKind{
	domain.KindEvergreen: rewindv1.ReferenceKind_REFERENCE_KIND_EVERGREEN,
	domain.KindHot:       rewindv1.ReferenceKind_REFERENCE_KIND_HOT,
	domain.KindManual:    rewindv1.ReferenceKind_REFERENCE_KIND_MANUAL,
}

func toProtoRefsView(view *service.ReferencesView) *rewindv1.ReferencesView {
	if view == nil || !view.Exists {
		return &rewindv1.ReferencesView{Exists: false}
	}

	sheet := &rewindv1.ReferenceSheet{
		Topic:               view.Sheet.Topic,
		ReferencesJsonPath:  view.Sheet.Path,
		MaxSelectable:       int32(view.Sheet.MaxSelectable),
		TrendSources:        view.Sheet.TrendSources,
		TrendsFetchedAt:     view.Sheet.TrendsFetchedAt,
		CandidatesGenerated: int32(view.Sheet.CandidatesGenerated),
		CandidatesRejected:  int32(view.Sheet.CandidatesRejected),
		Rejections:          view.Sheet.Rejections,
	}

	for _, p := range view.Sheet.Proposals {
		kind, ok := kindToProto[p.Kind]
		if !ok {
			kind = rewindv1.ReferenceKind_REFERENCE_KIND_UNSPECIFIED
		}

		out := &rewindv1.Proposal{
			Id:           p.ID,
			Reference:    p.Reference,
			Kind:         kind,
			LinkedFactId: p.LinkedFactID,
			Comparison:   p.Comparison,
			WhyFunny:     p.WhyFunny,
			AccuracyNote: p.AccuracyNote,
			Source:       p.Source,
			Selected:     p.Selected,
		}
		if !p.FreshUntil.IsZero() {
			out.FreshUntil = p.FreshUntil.Format("2006-01-02")
		}
		sheet.Proposals = append(sheet.Proposals, out)
	}

	return &rewindv1.ReferencesView{
		Exists:            true,
		Sheet:             sheet,
		CanApprove:        view.Readiness.CanApprove,
		ApprovalBlocker:   view.Readiness.Blocker,
		SelectedCount:     int32(view.Readiness.Selected),
		MaxSelectable:     int32(view.Readiness.MaxSelectable),
		StaleReferenceIds: view.Readiness.StaleIDs,
	}
}

var _ rewindv1connect.ReferencesServiceHandler = (*ReferencesHandler)(nil)
