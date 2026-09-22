// Command rewind-api serves the REWIND dashboard API.
//
// This file is the COMPOSITION ROOT (SPEC.md 14.1, rule 3): the only place in
// the Go service allowed to name a concrete implementation. Everything below
// it receives its dependencies through an interface. That is what makes the
// whole tree testable, and it is why --fake-ai below is three lines rather
// than a parallel code path.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"
	"time"

	"golang.org/x/net/http2"
	"golang.org/x/net/http2/h2c"

	"github.com/WildFire49/faceless-auto-video-gen/api/gen/rewind/v1/rewindv1connect"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/adapter/aifake"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/adapter/aigrpc"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/adapter/reviewmirror"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/adapter/sqlite"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/platform/buildinfo"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/platform/clock"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/platform/config"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/platform/idgen"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/platform/logging"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/service"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/transport/connectrpc"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/transport/middleware"
)

func main() {
	// main() does nothing but call run() and report. Keeping the real work in
	// a function that returns an error means every failure path is uniform and
	// deferred cleanup actually runs -- os.Exit skips defers.
	if err := run(); err != nil {
		fmt.Fprintf(os.Stderr, "rewind-api: %v\n", err)
		os.Exit(1)
	}
}

func run() error {
	var (
		configDir = flag.String("config", "", "path to config/ (default: found by walking up)")
		fakeAI    = flag.Bool("fake-ai", false, "use the in-memory AI worker; runs the dashboard without Python")
		jsonLogs  = flag.Bool("json-logs", false, "emit JSON logs instead of text")
		debug     = flag.Bool("debug", false, "enable debug logging")
	)
	flag.Parse()

	level := slog.LevelInfo
	if *debug {
		level = slog.LevelDebug
	}
	log := logging.New(level, *jsonLogs)

	// ---- configuration -----------------------------------------------------
	dir := *configDir
	if dir == "" {
		found, err := config.FindDir(".")
		if err != nil {
			return fmt.Errorf("locating config directory: %w", err)
		}
		dir = found
	}
	cfg, err := config.LoadServices(dir)
	if err != nil {
		return fmt.Errorf("loading config: %w", err)
	}

	// ---- storage -----------------------------------------------------------
	// Paths in config are relative to the repository root, the parent of
	// config/, so the server works from any working directory.
	repoRoot := filepath.Dir(dir)
	db, err := sqlite.Open(context.Background(), filepath.Join(repoRoot, cfg.API.DBPath))
	if err != nil {
		return err
	}
	defer func() {
		if err := db.Close(); err != nil {
			log.Error("closing database", slog.Any("error", err))
		}
	}()

	// ---- adapters (the only place concrete types are chosen) ---------------
	var ai domain.AIEngine
	if *fakeAI {
		ai = aifake.NewHealthy()
		log.Warn("using the FAKE AI worker; no Python process will be contacted")
	} else {
		engine, err := aigrpc.New(aigrpc.Options{
			Addr:            cfg.AI.GRPCAddr,
			MaxMessageBytes: cfg.AI.MaxMessageBytes,
			HealthTimeout:   cfg.Timeout("health", 5*time.Second),
		})
		if err != nil {
			return fmt.Errorf("creating AI client: %w", err)
		}
		defer func() {
			if err := engine.Close(); err != nil {
				log.Error("closing AI client", slog.Any("error", err))
			}
		}()
		ai = engine
	}

	// ---- use cases ---------------------------------------------------------
	videoRepo := sqlite.NewVideoRepo(db)
	reviewLog := reviewmirror.New(sqlite.NewReviewLog(db), filepath.Join(repoRoot, cfg.Paths.Projects), log)

	healthService := service.NewHealthService(ai, clock.New(), buildinfo.New())
	videoService := service.NewVideoService(videoRepo, reviewLog, db, clock.New(), idgen.New())
	gateService := service.NewGateService(videoRepo, reviewLog, db, clock.New())

	// ---- transport ---------------------------------------------------------
	mux := http.NewServeMux()

	healthPath, healthHandler := rewindv1connect.NewRewindServiceHandler(
		connectrpc.NewHealthHandler(healthService))
	mux.Handle(healthPath, healthHandler)

	videoPath, videoHandler := rewindv1connect.NewVideoServiceHandler(
		connectrpc.NewVideoHandler(videoService, gateService))
	mux.Handle(videoPath, videoHandler)

	// A plain liveness endpoint, so `curl` and container probes do not need to
	// speak Connect to find out whether the process is up.
	mux.HandleFunc("GET /livez", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok\n"))
	})

	root := middleware.Chain(mux,
		middleware.Recover(log),
		middleware.TraceID,
		middleware.Logging(log),
		middleware.CORS(cfg.API.CORSOrigins),
	)

	srv := &http.Server{
		Addr: cfg.API.HTTPAddr,
		// h2c serves HTTP/2 without TLS, which Connect clients can use over
		// loopback. Safe here only because we bind 127.0.0.1 (SPEC.md 13.5).
		Handler:           h2c.NewHandler(root, &http2.Server{}),
		ReadHeaderTimeout: 10 * time.Second,
	}

	// ---- run until interrupted --------------------------------------------
	// NotifyContext cancels ctx on Ctrl-C. One cancelled context unwinds every
	// in-flight request cleanly, which is how a SIGINT mid-job avoids leaving
	// a video stuck in a running state (SPEC.md 13.3).
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	errCh := make(chan error, 1)
	go func() {
		log.Info("rewind-api listening",
			slog.String("addr", cfg.API.HTTPAddr),
			slog.String("ai_addr", cfg.AI.GRPCAddr),
			slog.Bool("fake_ai", *fakeAI),
			slog.String("version", buildinfo.New().Version()),
		)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			errCh <- fmt.Errorf("serving http: %w", err)
			return
		}
		errCh <- nil
	}()

	select {
	case err := <-errCh:
		return err
	case <-ctx.Done():
		log.Info("shutdown signal received, draining", slog.Duration("grace", cfg.ShutdownGrace()))
	}

	shutdownCtx, cancel := context.WithTimeout(context.Background(), cfg.ShutdownGrace())
	defer cancel()
	if err := srv.Shutdown(shutdownCtx); err != nil {
		return fmt.Errorf("graceful shutdown: %w", err)
	}
	log.Info("rewind-api stopped cleanly")
	return nil
}
