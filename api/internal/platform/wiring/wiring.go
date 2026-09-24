// Package wiring assembles the application from its adapters.
//
// LAYER 6 (platform) of SPEC.md 14.1, serving the composition roots.
//
// Both entry points -- cmd/rewind-api and cmd/rewind -- need the same object
// graph, and duplicating it would be the classic way for a CLI and a server to
// drift into enforcing different rules. So the graph is built once, here, and
// each root only decides which concrete AI engine to hand in.
package wiring

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"log/slog"
	"path/filepath"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/adapter/factstore"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/adapter/reviewmirror"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/adapter/sqlite"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/platform/clock"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/platform/config"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/platform/idgen"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/service"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/service/pipeline"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/service/pipeline/steps"
)

// App is the assembled application.
type App struct {
	DB       *sqlite.DB
	Videos   *service.VideoService
	Gates    *service.GateService
	Facts    *service.FactsService
	Refs     *service.ReferencesService
	Scripts  *service.ScriptService
	Runner   *pipeline.Runner
	Registry *pipeline.Registry
}

// Worker is everything the pipeline asks of the AI worker. Two ports rather
// than one wide interface (SPEC.md 14.4); the real gRPC engine and the fake
// both implement both.
type Worker interface {
	domain.AIEngine
	domain.ScriptWriter
}

// Close releases everything the app holds.
func (a *App) Close() error { return a.DB.Close() }

// Build assembles the application.
//
// ai is the only thing that varies between entry points and between real and
// fake runs, so it is a parameter rather than something chosen here.
func Build(
	ctx context.Context,
	cfg config.Services,
	channel config.Channel,
	configDir string,
	ai Worker,
	log *slog.Logger,
) (*App, error) {
	// Paths in config are relative to the repository root, the parent of
	// config/, so every entry point works from any working directory.
	repoRoot := filepath.Dir(configDir)
	projectsDir := filepath.Join(repoRoot, cfg.Paths.Projects)

	db, err := sqlite.Open(ctx, filepath.Join(repoRoot, cfg.API.DBPath))
	if err != nil {
		return nil, err
	}

	videoRepo := sqlite.NewVideoRepo(db)
	jobRepo := sqlite.NewJobRepo(db)
	reviewLog := reviewmirror.New(sqlite.NewReviewLog(db), projectsDir, log)
	factStore := factstore.New(projectsDir)
	refStore := factstore.NewRefStore(projectsDir)
	scriptStore := factstore.NewScriptStore(projectsDir)

	clk := clock.New()

	factsService := service.NewFactsService(factStore, videoRepo, reviewLog, clk)
	refsService := service.NewReferencesService(refStore, factStore, videoRepo, reviewLog, clk)
	scriptService := service.NewScriptService(scriptStore, factStore, refStore, videoRepo, ai, reviewLog, clk)

	// Gate A cannot be approved until the fact sheet meets its bar. The rule
	// itself lives in the domain; this just connects it to the gate.
	preconditions := map[domain.Gate]service.GatePrecondition{
		domain.GateA: func(ctx context.Context, videoID string) error {
			view, err := factsService.GetFacts(ctx, videoID)
			if err != nil {
				return err
			}
			if !view.Exists {
				return fmt.Errorf("%w: no fact sheet yet — run the research step first",
					domain.ErrValidation)
			}
			if !view.Readiness.CanApprove {
				return fmt.Errorf("%w: %s", domain.ErrValidation, view.Readiness.Blocker)
			}
			return nil
		},
		domain.GateB: func(ctx context.Context, videoID string) error {
			view, err := refsService.GetReferences(ctx, videoID)
			if err != nil {
				return err
			}
			if !view.Exists {
				return fmt.Errorf("%w: no comparisons yet — run the relevance step first",
					domain.ErrValidation)
			}
			if !view.Readiness.CanApprove {
				return fmt.Errorf("%w: %s", domain.ErrValidation, view.Readiness.Blocker)
			}
			return nil
		},
		domain.GateC: func(ctx context.Context, videoID string) error {
			view, err := scriptService.GetScript(ctx, videoID)
			if err != nil {
				return err
			}
			if !view.Exists {
				return fmt.Errorf("%w: no script yet — run the script step first", domain.ErrValidation)
			}
			if !view.Readiness.CanApprove {
				return fmt.Errorf("%w: %s", domain.ErrValidation, view.Readiness.Blocker)
			}
			return nil
		},
	}

	videoService := service.NewVideoService(videoRepo, reviewLog, db, clk, idgen.New())
	gateService := service.NewGateService(videoRepo, reviewLog, db, clk, preconditions)

	// The pipeline. Each milestone from here adds exactly one line.
	registry := pipeline.NewRegistry()
	// 0 means "use whatever the content format requires", which the worker
	// knows and Go does not need to.
	registry.MustRegister(steps.NewResearch(ai, channel.Research.MinFacts))
	registry.MustRegister(steps.NewRelevance(ai, factStore, channel.Relevance.MaxProposals))
	registry.MustRegister(steps.NewScripting(ai, factStore, refStore))

	runner := pipeline.NewRunner(registry, videoRepo, jobRepo, db, clk, newJobID, log)
	videoService.WithPipeline(jobRepo, runner)

	return &App{
		DB:       db,
		Videos:   videoService,
		Gates:    gateService,
		Facts:    factsService,
		Refs:     refsService,
		Scripts:  scriptService,
		Runner:   runner,
		Registry: registry,
	}, nil
}

// newJobID returns a random, URL-safe job id.
func newJobID() string {
	var b [12]byte
	if _, err := rand.Read(b[:]); err != nil {
		// Cannot happen on any supported platform, and a job without an id is
		// unusable, so this is one of the few places a panic is right.
		panic("wiring: cannot read random bytes for a job id: " + err.Error())
	}
	return hex.EncodeToString(b[:])
}
