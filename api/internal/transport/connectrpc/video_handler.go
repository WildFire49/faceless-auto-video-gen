package connectrpc

import (
	"context"

	"connectrpc.com/connect"

	rewindv1 "github.com/WildFire49/faceless-auto-video-gen/api/gen/rewind/v1"
	"github.com/WildFire49/faceless-auto-video-gen/api/gen/rewind/v1/rewindv1connect"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/service"
)

// VideoHandler serves rewind.v1.VideoService.
//
// LAYER 5 (transport). Every method here does the same three things and
// nothing else: unwrap the request, call one service method, wrap the result.
// The rules live in domain/ and the workflow in service/.
type VideoHandler struct {
	videos *service.VideoService
	gates  *service.GateService
}

// NewVideoHandler wires the handler to its use cases.
func NewVideoHandler(videos *service.VideoService, gates *service.GateService) *VideoHandler {
	return &VideoHandler{videos: videos, gates: gates}
}

func (h *VideoHandler) AddVideo(
	ctx context.Context,
	req *connect.Request[rewindv1.AddVideoRequest],
) (*connect.Response[rewindv1.AddVideoResponse], error) {
	v, err := h.videos.AddVideo(ctx,
		req.Msg.GetTopic(),
		domain.Priority(req.Msg.GetPriority()),
		req.Msg.GetNotes(),
	)
	if err != nil {
		return nil, toConnectError(err)
	}
	return connect.NewResponse(&rewindv1.AddVideoResponse{Video: toProtoVideo(v)}), nil
}

func (h *VideoHandler) ListVideos(
	ctx context.Context,
	req *connect.Request[rewindv1.ListVideosRequest],
) (*connect.Response[rewindv1.ListVideosResponse], error) {
	filter := domain.VideoFilter{AwaitingReview: req.Msg.GetNeedsReviewOnly()}
	for _, s := range req.Msg.GetStatuses() {
		filter.Statuses = append(filter.Statuses, fromProtoStatus(s))
	}

	videos, err := h.videos.ListVideos(ctx, filter)
	if err != nil {
		return nil, toConnectError(err)
	}

	out := make([]*rewindv1.Video, 0, len(videos))
	for _, v := range videos {
		out = append(out, toProtoVideo(v))
	}
	return connect.NewResponse(&rewindv1.ListVideosResponse{Videos: out}), nil
}

func (h *VideoHandler) GetVideo(
	ctx context.Context,
	req *connect.Request[rewindv1.GetVideoRequest],
) (*connect.Response[rewindv1.GetVideoResponse], error) {
	v, err := h.videos.GetVideo(ctx, req.Msg.GetVideoId())
	if err != nil {
		return nil, toConnectError(err)
	}
	return connect.NewResponse(&rewindv1.GetVideoResponse{Video: toProtoVideo(v)}), nil
}

func (h *VideoHandler) ApproveGate(
	ctx context.Context,
	req *connect.Request[rewindv1.ApproveGateRequest],
) (*connect.Response[rewindv1.ApproveGateResponse], error) {
	v, err := h.gates.Approve(ctx,
		req.Msg.GetVideoId(),
		fromProtoGate(req.Msg.GetGate()),
		req.Msg.GetNote(),
	)
	if err != nil {
		return nil, toConnectError(err)
	}
	return connect.NewResponse(&rewindv1.ApproveGateResponse{Video: toProtoVideo(v)}), nil
}

func (h *VideoHandler) RejectGate(
	ctx context.Context,
	req *connect.Request[rewindv1.RejectGateRequest],
) (*connect.Response[rewindv1.RejectGateResponse], error) {
	v, err := h.gates.Reject(ctx,
		req.Msg.GetVideoId(),
		fromProtoGate(req.Msg.GetGate()),
		fromProtoStatus(req.Msg.GetBackTo()),
		req.Msg.GetNote(),
	)
	if err != nil {
		return nil, toConnectError(err)
	}
	return connect.NewResponse(&rewindv1.RejectGateResponse{Video: toProtoVideo(v)}), nil
}

func (h *VideoHandler) RetryVideo(
	ctx context.Context,
	req *connect.Request[rewindv1.RetryVideoRequest],
) (*connect.Response[rewindv1.RetryVideoResponse], error) {
	v, err := h.videos.RetryVideo(ctx, req.Msg.GetVideoId())
	if err != nil {
		return nil, toConnectError(err)
	}
	return connect.NewResponse(&rewindv1.RetryVideoResponse{Video: toProtoVideo(v)}), nil
}

func (h *VideoHandler) ListReviewLog(
	ctx context.Context,
	req *connect.Request[rewindv1.ListReviewLogRequest],
) (*connect.Response[rewindv1.ListReviewLogResponse], error) {
	entries, err := h.videos.ListReviewLog(ctx, req.Msg.GetVideoId())
	if err != nil {
		return nil, toConnectError(err)
	}

	out := make([]*rewindv1.ReviewLogEntry, 0, len(entries))
	for _, e := range entries {
		out = append(out, &rewindv1.ReviewLogEntry{
			Id:         e.ID,
			VideoId:    e.VideoID,
			At:         formatTime(e.At),
			Gate:       toProtoGate(e.Gate),
			Action:     string(e.Action),
			FromStatus: toProtoVideoStatus(e.FromStatus),
			ToStatus:   toProtoVideoStatus(e.ToStatus),
			Note:       e.Note,
			Diff:       e.Diff,
		})
	}
	return connect.NewResponse(&rewindv1.ListReviewLogResponse{Entries: out}), nil
}

var _ rewindv1connect.VideoServiceHandler = (*VideoHandler)(nil)
