package connectrpc

import (
	"context"

	"connectrpc.com/connect"

	rewindv1 "github.com/WildFire49/faceless-auto-video-gen/api/gen/rewind/v1"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
)

// RunStep starts the next pipeline step and returns immediately with a job id.
//
// Never blocks on the work: research takes minutes, and an HTTP request that
// waits for it would time out in the browser long before it finished
// (SPEC.md 8.3).
func (h *VideoHandler) RunStep(
	ctx context.Context,
	req *connect.Request[rewindv1.RunStepRequest],
) (*connect.Response[rewindv1.RunStepResponse], error) {
	result, err := h.videos.RunStep(ctx, req.Msg.GetVideoId())
	if err != nil {
		return nil, toConnectError(err)
	}

	return connect.NewResponse(&rewindv1.RunStepResponse{
		Job:     toProtoJob(result.Job),
		Started: result.Started,
		Reason:  result.Reason,
	}), nil
}

// GetJob reports a job's progress. Polled by the dashboard.
func (h *VideoHandler) GetJob(
	ctx context.Context,
	req *connect.Request[rewindv1.GetJobRequest],
) (*connect.Response[rewindv1.GetJobResponse], error) {
	job, err := h.videos.GetJob(ctx, req.Msg.GetJobId())
	if err != nil {
		return nil, toConnectError(err)
	}
	return connect.NewResponse(&rewindv1.GetJobResponse{
		Exists: job != nil,
		Job:    toProtoJob(job),
	}), nil
}

// GetLatestJob returns the most recent job for a video, so reloading the page
// reattaches to work that is already running instead of losing sight of it.
func (h *VideoHandler) GetLatestJob(
	ctx context.Context,
	req *connect.Request[rewindv1.GetLatestJobRequest],
) (*connect.Response[rewindv1.GetLatestJobResponse], error) {
	job, err := h.videos.GetLatestJob(ctx, req.Msg.GetVideoId())
	if err != nil {
		return nil, toConnectError(err)
	}
	return connect.NewResponse(&rewindv1.GetLatestJobResponse{
		Exists: job != nil,
		Job:    toProtoJob(job),
	}), nil
}

var jobStateToProto = map[domain.JobState]rewindv1.JobState{
	domain.JobRunning:     rewindv1.JobState_JOB_STATE_RUNNING,
	domain.JobSucceeded:   rewindv1.JobState_JOB_STATE_SUCCEEDED,
	domain.JobFailed:      rewindv1.JobState_JOB_STATE_FAILED,
	domain.JobInterrupted: rewindv1.JobState_JOB_STATE_INTERRUPTED,
}

func toProtoJob(j *domain.Job) *rewindv1.Job {
	if j == nil {
		return nil
	}

	state, ok := jobStateToProto[j.State]
	if !ok {
		state = rewindv1.JobState_JOB_STATE_UNSPECIFIED
	}

	out := &rewindv1.Job{
		Id:        j.ID,
		VideoId:   j.VideoID,
		Step:      j.Step,
		State:     state,
		Stage:     j.Stage,
		Percent:   j.Percent,
		Current:   int32(j.Current),
		Total:     int32(j.Total),
		Error:     j.Error,
		StartedAt: formatTime(j.StartedAt),
	}
	if j.FinishedAt != nil {
		out.FinishedAt = formatTime(*j.FinishedAt)
	}
	return out
}
