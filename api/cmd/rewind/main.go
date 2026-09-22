// Command rewind is the REWIND command-line interface.
//
// It is a second COMPOSITION ROOT (SPEC.md 14.1, rule 3), alongside
// cmd/rewind-api. Both wire the same service layer to the same adapters, so
// the CLI and the dashboard genuinely cannot enforce different rules.
package main

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/adapter/reviewmirror"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/adapter/sqlite"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/platform/clock"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/platform/config"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/platform/idgen"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/platform/logging"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/service"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/transport/cli"
)

func main() {
	if err := run(); err != nil {
		// Domain errors are the user's problem to fix, so they are printed
		// plainly. Anything else keeps its wrapped context for debugging.
		fmt.Fprintf(os.Stderr, "rewind: %s\n", userMessage(err))
		os.Exit(1)
	}
}

func run() error {
	// Ctrl-C cancels the context, which unwinds any in-flight database work
	// cleanly rather than leaving a transaction open.
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	configDir, err := config.FindDir(".")
	if err != nil {
		return fmt.Errorf("locating config directory: %w", err)
	}
	cfg, err := config.LoadServices(configDir)
	if err != nil {
		return fmt.Errorf("loading config: %w", err)
	}

	// Paths in config are relative to the repository root, which is the
	// parent of config/. Resolving them here means the CLI works from any
	// subdirectory.
	repoRoot := filepath.Dir(configDir)
	dbPath := filepath.Join(repoRoot, cfg.API.DBPath)
	projectsDir := filepath.Join(repoRoot, cfg.Paths.Projects)

	db, err := sqlite.Open(ctx, dbPath)
	if err != nil {
		return err
	}
	defer func() { _ = db.Close() }()

	// The CLI logs only real problems: its output is a human-readable report,
	// not a log stream, so anything below Error would be noise.
	log := logging.New(slog.LevelError, false)

	videoRepo := sqlite.NewVideoRepo(db)
	reviewLog := reviewmirror.New(sqlite.NewReviewLog(db), projectsDir, log)

	videoService := service.NewVideoService(videoRepo, reviewLog, db, clock.New(), idgen.New())
	gateService := service.NewGateService(videoRepo, reviewLog, db, clock.New())

	root := cli.NewRootCommand(cli.Deps{
		Videos: videoService,
		Gates:  gateService,
		Out:    os.Stdout,
	})
	return root.ExecuteContext(ctx)
}

// userMessage strips wrapping from errors that describe something the user
// did, so `rewind approve iron A` on the wrong gate prints one clear line
// instead of a chain of call sites.
func userMessage(err error) string {
	for _, sentinel := range []error{
		domain.ErrIllegalTransition,
		domain.ErrValidation,
		domain.ErrNotFound,
		domain.ErrAlreadyExists,
		domain.ErrInvalidVideoID,
	} {
		if errors.Is(err, sentinel) {
			return err.Error()
		}
	}
	return err.Error()
}
