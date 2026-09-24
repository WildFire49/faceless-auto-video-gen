package connectrpc

import (
	"context"

	"connectrpc.com/connect"

	rewindv1 "github.com/WildFire49/faceless-auto-video-gen/api/gen/rewind/v1"
	"github.com/WildFire49/faceless-auto-video-gen/api/gen/rewind/v1/rewindv1connect"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/service"
)

// ScriptsHandler serves rewind.v1.ScriptsService -- the Gate C surface.
// Translation only; every rule is in the service and the worker.
type ScriptsHandler struct {
	scripts *service.ScriptService
}

// NewScriptsHandler wires the handler to its use case.
func NewScriptsHandler(scripts *service.ScriptService) *ScriptsHandler {
	return &ScriptsHandler{scripts: scripts}
}

func (h *ScriptsHandler) GetScript(
	ctx context.Context,
	req *connect.Request[rewindv1.GetScriptRequest],
) (*connect.Response[rewindv1.GetScriptResponse], error) {
	view, err := h.scripts.GetScript(ctx, req.Msg.GetVideoId())
	if err != nil {
		return nil, toConnectError(err)
	}
	return connect.NewResponse(&rewindv1.GetScriptResponse{View: toProtoScriptView(view)}), nil
}

func (h *ScriptsHandler) UpdateBeat(
	ctx context.Context,
	req *connect.Request[rewindv1.UpdateBeatRequest],
) (*connect.Response[rewindv1.UpdateBeatResponse], error) {
	view, err := h.scripts.UpdateBeat(ctx,
		req.Msg.GetVideoId(),
		int(req.Msg.GetN()),
		req.Msg.GetVoice(),
		req.Msg.GetOnScreenText(),
		req.Msg.GetYearStamp(),
		req.Msg.GetRefIds(),
	)
	if err != nil {
		return nil, toConnectError(err)
	}
	return connect.NewResponse(&rewindv1.UpdateBeatResponse{View: toProtoScriptView(view)}), nil
}

func (h *ScriptsHandler) ChooseTitle(
	ctx context.Context,
	req *connect.Request[rewindv1.ChooseTitleRequest],
) (*connect.Response[rewindv1.ChooseTitleResponse], error) {
	view, err := h.scripts.ChooseTitle(ctx, req.Msg.GetVideoId(), req.Msg.GetTitle())
	if err != nil {
		return nil, toConnectError(err)
	}
	return connect.NewResponse(&rewindv1.ChooseTitleResponse{View: toProtoScriptView(view)}), nil
}

func toProtoScriptView(view *service.ScriptView) *rewindv1.ScriptView {
	if view == nil || !view.Exists {
		return &rewindv1.ScriptView{Exists: false}
	}
	return &rewindv1.ScriptView{
		Exists:          true,
		Script:          toProtoScript(view.Script),
		CanApprove:      view.Readiness.CanApprove,
		ApprovalBlocker: view.Readiness.Blocker,
	}
}

func toProtoScript(s *domain.Script) *rewindv1.Script {
	out := &rewindv1.Script{
		TitleOptions:   s.TitleOptions,
		ChosenTitle:    s.ChosenTitle,
		Description:    s.Description,
		Hashtags:       s.Hashtags,
		Sources:        s.Sources,
		ScriptJsonPath: s.Path,
		Attempts:       int32(s.Attempts),
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
	for _, v := range s.Violations {
		out.Violations = append(out.Violations, &rewindv1.Violation{
			Rule: v.Rule, Beat: int32(v.Beat), Message: v.Message,
		})
	}
	return out
}

var _ rewindv1connect.ScriptsServiceHandler = (*ScriptsHandler)(nil)
