package connectrpc

import (
	"time"

	rewindv1 "github.com/WildFire49/faceless-auto-video-gen/api/gen/rewind/v1"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
)

// Wire <-> domain translation.
//
// All of it lives in this one file, at the transport edge, so that domain/
// never imports protobuf (SPEC.md 14.1, rule 1). The cost is a mapping table;
// the benefit is that the state machine can be read, tested and changed
// without any generated code in sight.

// statusToProto is the single mapping between the domain status and the wire
// enum. A table rather than a switch, so the inverse can be derived from it
// and the two can never disagree.
var statusToProto = map[domain.Status]rewindv1.VideoStatus{
	domain.StatusQueued:             rewindv1.VideoStatus_VIDEO_STATUS_QUEUED,
	domain.StatusResearching:        rewindv1.VideoStatus_VIDEO_STATUS_RESEARCHING,
	domain.StatusFactsReady:         rewindv1.VideoStatus_VIDEO_STATUS_FACTS_READY,
	domain.StatusFactsApproved:      rewindv1.VideoStatus_VIDEO_STATUS_FACTS_APPROVED,
	domain.StatusFindingRefs:        rewindv1.VideoStatus_VIDEO_STATUS_FINDING_REFS,
	domain.StatusRefsReady:          rewindv1.VideoStatus_VIDEO_STATUS_REFS_READY,
	domain.StatusRefsApproved:       rewindv1.VideoStatus_VIDEO_STATUS_REFS_APPROVED,
	domain.StatusScripting:          rewindv1.VideoStatus_VIDEO_STATUS_SCRIPTING,
	domain.StatusScriptReady:        rewindv1.VideoStatus_VIDEO_STATUS_SCRIPT_READY,
	domain.StatusScriptApproved:     rewindv1.VideoStatus_VIDEO_STATUS_SCRIPT_APPROVED,
	domain.StatusVoicing:            rewindv1.VideoStatus_VIDEO_STATUS_VOICING,
	domain.StatusVoiceReady:         rewindv1.VideoStatus_VIDEO_STATUS_VOICE_READY,
	domain.StatusVoiceApproved:      rewindv1.VideoStatus_VIDEO_STATUS_VOICE_APPROVED,
	domain.StatusImaging:            rewindv1.VideoStatus_VIDEO_STATUS_IMAGING,
	domain.StatusStoryboardReady:    rewindv1.VideoStatus_VIDEO_STATUS_STORYBOARD_READY,
	domain.StatusStoryboardApproved: rewindv1.VideoStatus_VIDEO_STATUS_STORYBOARD_APPROVED,
	domain.StatusRendering:          rewindv1.VideoStatus_VIDEO_STATUS_RENDERING,
	domain.StatusRenderReady:        rewindv1.VideoStatus_VIDEO_STATUS_RENDER_READY,
	domain.StatusFinalApproved:      rewindv1.VideoStatus_VIDEO_STATUS_FINAL_APPROVED,
	domain.StatusUploading:          rewindv1.VideoStatus_VIDEO_STATUS_UPLOADING,
	domain.StatusUploadedPrivate:    rewindv1.VideoStatus_VIDEO_STATUS_UPLOADED_PRIVATE,
	domain.StatusPublished:          rewindv1.VideoStatus_VIDEO_STATUS_PUBLISHED,
	domain.StatusAnalyticsCollected: rewindv1.VideoStatus_VIDEO_STATUS_ANALYTICS_COLLECTED,
	domain.StatusError:              rewindv1.VideoStatus_VIDEO_STATUS_ERROR,
}

// statusFromProto is derived from statusToProto at init, so adding a status
// means editing one table rather than two that can drift apart.
var statusFromProto = func() map[rewindv1.VideoStatus]domain.Status {
	m := make(map[rewindv1.VideoStatus]domain.Status, len(statusToProto))
	for d, p := range statusToProto {
		m[p] = d
	}
	return m
}()

func toProtoVideoStatus(s domain.Status) rewindv1.VideoStatus {
	if p, ok := statusToProto[s]; ok {
		return p
	}
	return rewindv1.VideoStatus_VIDEO_STATUS_UNSPECIFIED
}

// fromProtoStatus maps a wire status back.
//
// An unrecognised value yields the empty status, which every domain rule
// rejects. That is deliberate: a client sending a status this build does not
// know should fail cleanly rather than be silently coerced to something
// plausible.
func fromProtoStatus(p rewindv1.VideoStatus) domain.Status {
	return statusFromProto[p]
}

var gateToProto = map[domain.Gate]rewindv1.Gate{
	domain.GateA: rewindv1.Gate_GATE_A_FACTS,
	domain.GateB: rewindv1.Gate_GATE_B_REFERENCES,
	domain.GateC: rewindv1.Gate_GATE_C_SCRIPT,
	domain.GateD: rewindv1.Gate_GATE_D_VOICE,
	domain.GateE: rewindv1.Gate_GATE_E_STORYBOARD,
	domain.GateF: rewindv1.Gate_GATE_F_FINAL,
}

var gateFromProto = func() map[rewindv1.Gate]domain.Gate {
	m := make(map[rewindv1.Gate]domain.Gate, len(gateToProto))
	for d, p := range gateToProto {
		m[p] = d
	}
	return m
}()

func toProtoGate(g domain.Gate) rewindv1.Gate {
	if p, ok := gateToProto[g]; ok {
		return p
	}
	return rewindv1.Gate_GATE_UNSPECIFIED
}

func fromProtoGate(p rewindv1.Gate) domain.Gate {
	return gateFromProto[p]
}

// toProtoVideo converts a video for the wire.
//
// awaiting_gate and is_terminal are computed here rather than left to each
// client. Two clients deriving the same thing separately is how a CLI and a
// dashboard end up disagreeing about whether something needs review.
func toProtoVideo(v *domain.Video) *rewindv1.Video {
	if v == nil {
		return nil
	}

	gate := domain.GateNone
	if g, waiting := domain.GateFor(v.Status); waiting {
		gate = g
	}

	out := &rewindv1.Video{
		Id:           v.ID,
		Topic:        v.Topic,
		Status:       toProtoVideoStatus(v.Status),
		Priority:     int32(v.Priority),
		Notes:        v.Notes,
		CreatedAt:    formatTime(v.CreatedAt),
		UpdatedAt:    formatTime(v.UpdatedAt),
		RejectedTo:   toProtoVideoStatus(v.RejectedTo),
		RejectNote:   v.RejectNote,
		Error:        v.Error,
		RetryFrom:    toProtoVideoStatus(v.RetryFrom),
		YtVideoId:    v.YTVideoID,
		AwaitingGate: toProtoGate(gate),
		IsTerminal:   domain.IsTerminal(v.Status),
	}
	if v.PublishedAt != nil {
		out.PublishedAt = formatTime(*v.PublishedAt)
	}
	return out
}

// formatTime renders a timestamp as RFC 3339, which every language's date
// parser handles -- including JavaScript's `new Date(...)`.
func formatTime(t time.Time) string {
	if t.IsZero() {
		return ""
	}
	return t.UTC().Format(time.RFC3339)
}
