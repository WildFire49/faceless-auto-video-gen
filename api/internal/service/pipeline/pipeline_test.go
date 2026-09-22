package pipeline_test

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"path/filepath"
	"testing"
	"time"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/adapter/aifake"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/adapter/sqlite"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/platform/clock"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/service/pipeline"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/service/pipeline/steps"
)

// These run the real orchestration against a real database with a fake AI
// worker: no Python, no Ollama, no network. That is the whole point of the
// adapter boundary (SPEC.md 14.1).

func quietLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(io.Discard, nil))
}

type harness struct {
	videos *sqlite.VideoRepo
	jobs   *sqlite.JobRepo
	runner *pipeline.Runner
	ai     *aifake.Engine
}

func newHarness(t *testing.T, steps ...pipeline.Step) *harness {
	t.Helper()

	db, err := sqlite.Open(context.Background(), filepath.Join(t.TempDir(), "pipeline.db"))
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	t.Cleanup(func() { _ = db.Close() })

	registry := pipeline.NewRegistry()
	for _, s := range steps {
		if err := registry.Register(s); err != nil {
			t.Fatalf("Register: %v", err)
		}
	}

	videos := sqlite.NewVideoRepo(db)
	jobs := sqlite.NewJobRepo(db)

	counter := 0
	ids := func() string {
		counter++
		return "job-" + string(rune('a'+counter-1))
	}

	return &harness{
		videos: videos,
		jobs:   jobs,
		runner: pipeline.NewRunner(registry, videos, jobs, db, clock.New(), ids, quietLogger()),
	}
}

func (h *harness) addVideo(t *testing.T, id string, status domain.Status) *domain.Video {
	t.Helper()

	now := time.Now().UTC()
	v := &domain.Video{
		ID: id, Topic: id, Status: status,
		Priority: domain.PriorityDefault, CreatedAt: now, UpdatedAt: now,
	}
	if err := h.videos.Create(context.Background(), v); err != nil {
		t.Fatalf("Create: %v", err)
	}
	return v
}

// waitForJob polls until the job finishes, because Start returns immediately
// and the work runs in a goroutine.
func (h *harness) waitForJob(t *testing.T, jobID string) *domain.Job {
	t.Helper()

	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		job, err := h.jobs.Get(context.Background(), jobID)
		if err != nil {
			t.Fatalf("Get job: %v", err)
		}
		if job.IsFinished() {
			return job
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatalf("job %s did not finish within 5s", jobID)
	return nil
}

// ------------------------------------------------------------ the registry

// TestRegistryRefusesGateCrossingSteps is the structural guarantee, checked at
// registration time: a step that tried to approve a gate could not even be
// wired in, let alone run.
func TestRegistryRefusesGateCrossingSteps(t *testing.T) {
	t.Parallel()

	registry := pipeline.NewRegistry()
	err := registry.Register(&fakeStep{
		from:    domain.StatusFactsReady, // waiting at Gate A
		running: domain.StatusFactsReady,
		to:      domain.StatusFactsApproved, // the approval
	})

	if err == nil {
		t.Fatal("a gate-crossing step was accepted by the registry")
	}
	if got := err.Error(); !contains(got, "never approve a gate") {
		t.Errorf("error = %q, want it to explain that a step cannot approve a gate", got)
	}
}

func TestRegistryRefusesIllegalTransitions(t *testing.T) {
	t.Parallel()

	registry := pipeline.NewRegistry()
	err := registry.Register(&fakeStep{
		from:    domain.StatusQueued,
		running: domain.StatusResearching,
		to:      domain.StatusRendering, // skips most of the pipeline
	})
	if err == nil {
		t.Fatal("a step declaring an impossible transition was accepted")
	}
}

func TestRegistryRefusesDuplicateHandlers(t *testing.T) {
	t.Parallel()

	registry := pipeline.NewRegistry()
	step := &fakeStep{from: domain.StatusQueued, running: domain.StatusResearching, to: domain.StatusFactsReady}

	if err := registry.Register(step); err != nil {
		t.Fatalf("first Register: %v", err)
	}
	if err := registry.Register(step); err == nil {
		t.Error("two steps claimed the same status without complaint")
	}
}

// -------------------------------------------------------------- the runner

func TestSuccessfulStepAdvancesTheVideo(t *testing.T) {
	t.Parallel()

	step := &fakeStep{from: domain.StatusQueued, running: domain.StatusResearching, to: domain.StatusFactsReady}
	h := newHarness(t, step)
	h.addVideo(t, "iron", domain.StatusQueued)

	result, err := h.runner.Start(context.Background(), "iron")
	if err != nil {
		t.Fatalf("Start: %v", err)
	}
	if !result.Started {
		t.Fatalf("did not start: %s", result.Reason)
	}

	job := h.waitForJob(t, result.Job.ID)
	if job.State != domain.JobSucceeded {
		t.Errorf("job state = %q, want succeeded (error: %s)", job.State, job.Error)
	}
	if job.Percent != 1 {
		t.Errorf("percent = %v, want 1 on success", job.Percent)
	}

	video, err := h.videos.Get(context.Background(), "iron")
	if err != nil {
		t.Fatalf("Get: %v", err)
	}
	if video.Status != domain.StatusFactsReady {
		t.Errorf("status = %q, want %q", video.Status, domain.StatusFactsReady)
	}
}

func TestFailedStepMarksTheVideoWithAResumePoint(t *testing.T) {
	t.Parallel()

	step := &fakeStep{
		from:    domain.StatusQueued,
		running: domain.StatusResearching,
		to:      domain.StatusFactsReady,
		err:     errors.New("wikipedia is on fire"),
	}
	h := newHarness(t, step)
	h.addVideo(t, "iron", domain.StatusQueued)

	result, err := h.runner.Start(context.Background(), "iron")
	if err != nil {
		t.Fatalf("Start: %v", err)
	}

	job := h.waitForJob(t, result.Job.ID)
	if job.State != domain.JobFailed {
		t.Errorf("job state = %q, want failed", job.State)
	}
	if !contains(job.Error, "wikipedia is on fire") {
		t.Errorf("job error = %q, want the step's message", job.Error)
	}

	video, err := h.videos.Get(context.Background(), "iron")
	if err != nil {
		t.Fatalf("Get: %v", err)
	}
	if video.Status != domain.StatusError {
		t.Errorf("status = %q, want %q", video.Status, domain.StatusError)
	}
	// The resume point is what makes `rewind retry` re-run the step that
	// failed rather than starting over.
	// The video was claimed into `researching` before the work began, so that
	// is where a retry picks up -- re-running the step that failed.
	if video.RetryFrom != domain.StatusResearching {
		t.Errorf("RetryFrom = %q, want %q", video.RetryFrom, domain.StatusResearching)
	}
}

func TestPanickingStepDoesNotTakeDownTheServer(t *testing.T) {
	t.Parallel()

	step := &fakeStep{from: domain.StatusQueued, running: domain.StatusResearching, to: domain.StatusFactsReady, panics: true}
	h := newHarness(t, step)
	h.addVideo(t, "iron", domain.StatusQueued)

	result, err := h.runner.Start(context.Background(), "iron")
	if err != nil {
		t.Fatalf("Start: %v", err)
	}

	// The job must be recorded as failed rather than left running forever.
	job := h.waitForJob(t, result.Job.ID)
	if job.State != domain.JobFailed {
		t.Errorf("job state = %q, want failed after a panic", job.State)
	}
}

func TestProgressIsRecorded(t *testing.T) {
	t.Parallel()

	step := &fakeStep{
		from:    domain.StatusQueued,
		running: domain.StatusResearching,
		to:      domain.StatusFactsReady,
		progress: []pipeline.Progress{
			{Stage: "fetching wikipedia", Percent: 0.3},
			{Stage: "verifying evidence", Percent: 0.8},
		},
		hold: 60 * time.Millisecond,
	}
	h := newHarness(t, step)
	h.addVideo(t, "iron", domain.StatusQueued)

	result, err := h.runner.Start(context.Background(), "iron")
	if err != nil {
		t.Fatalf("Start: %v", err)
	}

	// Observe mid-flight: this is what the dashboard's progress bar reads.
	sawProgress := false
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		job, err := h.jobs.Get(context.Background(), result.Job.ID)
		if err != nil {
			t.Fatalf("Get job: %v", err)
		}
		if job.Stage != "" && job.Stage != "queued" {
			sawProgress = true
			break
		}
		time.Sleep(5 * time.Millisecond)
	}
	if !sawProgress {
		t.Error("no progress was ever visible; the dashboard would show a dead bar")
	}

	h.waitForJob(t, result.Job.ID)
}

func TestStartRefusesWhenAwaitingAGate(t *testing.T) {
	t.Parallel()

	h := newHarness(t)
	h.addVideo(t, "iron", domain.StatusFactsReady)

	result, err := h.runner.Start(context.Background(), "iron")
	if err != nil {
		t.Fatalf("Start: %v", err)
	}
	if result.Started {
		t.Fatal("started a step for a video that is waiting on a human")
	}
	if !contains(result.Reason, "Gate A") {
		t.Errorf("reason = %q, want it to name Gate A", result.Reason)
	}
}

func TestStartRefusesASecondConcurrentJob(t *testing.T) {
	t.Parallel()

	// Two steps writing the same project folder would corrupt each other.
	step := &fakeStep{from: domain.StatusQueued, running: domain.StatusResearching, to: domain.StatusFactsReady, hold: 300 * time.Millisecond}
	h := newHarness(t, step)
	h.addVideo(t, "iron", domain.StatusQueued)

	first, err := h.runner.Start(context.Background(), "iron")
	if err != nil {
		t.Fatalf("first Start: %v", err)
	}

	second, err := h.runner.Start(context.Background(), "iron")
	if err != nil {
		t.Fatalf("second Start: %v", err)
	}
	if second.Started {
		t.Error("a second job was started while the first was still running")
	}

	h.waitForJob(t, first.Job.ID)
}

// ------------------------------------------------------------ the real step

// TestResearchStepUsesTheAIEngine exercises the actual research step against
// the fake worker, so the wiring from step to engine is covered.
func TestResearchStepUsesTheAIEngine(t *testing.T) {
	t.Parallel()

	ai := aifake.NewHealthy()
	h := newHarness(t, steps.NewResearch(ai, 8))
	h.addVideo(t, "iron", domain.StatusQueued)

	result, err := h.runner.Start(context.Background(), "iron")
	if err != nil {
		t.Fatalf("Start: %v", err)
	}
	job := h.waitForJob(t, result.Job.ID)

	if job.State != domain.JobSucceeded {
		t.Fatalf("job failed: %s", job.Error)
	}
	if len(ai.ResearchCalls) != 1 {
		t.Fatalf("AI engine called %d times, want 1", len(ai.ResearchCalls))
	}
	if got := ai.ResearchCalls[0]; got.Topic != "iron" || got.MinFacts != 8 {
		t.Errorf("request = %+v, want topic=iron minFacts=8", got)
	}

	video, err := h.videos.Get(context.Background(), "iron")
	if err != nil {
		t.Fatalf("Get: %v", err)
	}
	if video.Status != domain.StatusFactsReady {
		t.Errorf("status = %q, want %q — the video should now be at Gate A",
			video.Status, domain.StatusFactsReady)
	}
}

func TestResearchStepForwardsURLsFromNotes(t *testing.T) {
	t.Parallel()

	ai := aifake.NewHealthy()
	h := newHarness(t, steps.NewResearch(ai, 8))

	v := h.addVideo(t, "iron", domain.StatusQueued)
	v.Notes = "see https://example.com/history-of-irons and also http://example.org/b."
	if err := h.videos.Update(context.Background(), v); err != nil {
		t.Fatalf("Update: %v", err)
	}

	result, err := h.runner.Start(context.Background(), "iron")
	if err != nil {
		t.Fatalf("Start: %v", err)
	}
	h.waitForJob(t, result.Job.ID)

	got := ai.ResearchCalls[0].ExtraURLs
	if len(got) != 2 {
		t.Fatalf("extracted %d URLs from notes (%v), want 2", len(got), got)
	}
	// The trailing full stop must not end up in the URL.
	if got[1] != "http://example.org/b" {
		t.Errorf("second URL = %q, want the trailing period trimmed", got[1])
	}
}

// -------------------------------------------------------- crash recovery

func TestRecoverInterruptedRescuesStuckWork(t *testing.T) {
	t.Parallel()

	h := newHarness(t, &fakeStep{
		from: domain.StatusQueued, running: domain.StatusResearching, to: domain.StatusFactsReady,
	})

	// A video and job left behind by a crash mid-research.
	h.addVideo(t, "iron", domain.StatusResearching)
	stuck := &domain.Job{
		ID: "stuck", VideoID: "iron", Step: "facts_ready",
		State: domain.JobRunning, StartedAt: time.Now().UTC(),
	}
	if err := h.jobs.Create(context.Background(), stuck); err != nil {
		t.Fatalf("Create job: %v", err)
	}

	if err := h.runner.RecoverInterrupted(context.Background()); err != nil {
		t.Fatalf("RecoverInterrupted: %v", err)
	}

	job, err := h.jobs.Get(context.Background(), "stuck")
	if err != nil {
		t.Fatalf("Get job: %v", err)
	}
	if job.State != domain.JobInterrupted {
		t.Errorf("job state = %q, want interrupted", job.State)
	}

	video, err := h.videos.Get(context.Background(), "iron")
	if err != nil {
		t.Fatalf("Get video: %v", err)
	}
	if video.Status != domain.StatusError {
		t.Errorf("status = %q, want %q so it is recoverable", video.Status, domain.StatusError)
	}
	if !contains(video.Error, "rewind retry") {
		t.Errorf("error = %q, want it to tell the operator what to do", video.Error)
	}
}

// ----------------------------------------------------------------- helpers

type fakeStep struct {
	from     domain.Status
	running  domain.Status
	to       domain.Status
	err      error
	panics   bool
	hold     time.Duration
	progress []pipeline.Progress
}

func (s *fakeStep) From() domain.Status { return s.from }
func (s *fakeStep) To() domain.Status   { return s.to }

// Running defaults to `from` when a test does not care about the middle leg,
// which only works for steps whose From is itself an in-progress status.
func (s *fakeStep) Running() domain.Status {
	if s.running != "" {
		return s.running
	}
	return s.from
}

func (s *fakeStep) Run(ctx context.Context, v *domain.Video, report pipeline.ProgressFn) error {
	for _, p := range s.progress {
		report(p)
	}
	if s.hold > 0 {
		time.Sleep(s.hold)
	}
	if s.panics {
		panic("the step exploded")
	}
	return s.err
}

func contains(haystack, needle string) bool {
	return len(haystack) >= len(needle) && indexOf(haystack, needle) >= 0
}

func indexOf(haystack, needle string) int {
	for i := 0; i+len(needle) <= len(haystack); i++ {
		if haystack[i:i+len(needle)] == needle {
			return i
		}
	}
	return -1
}
