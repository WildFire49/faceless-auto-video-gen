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
	"syscall"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/adapter/aifake"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/platform/config"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/platform/logging"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/platform/wiring"
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

	channel, err := config.LoadChannel(configDir)
	if err != nil {
		return fmt.Errorf("loading channel config: %w", err)
	}

	// The CLI logs only real problems: its output is a human-readable report,
	// not a log stream, so anything below Error would be noise.
	log := logging.New(slog.LevelError, false)

	// The CLI never starts a pipeline step itself -- `rewind run` is served by
	// the API process, which owns the worker connection. A fake engine keeps
	// the object graph complete without opening a second gRPC client that
	// would sit unused.
	app, err := wiring.Build(ctx, cfg, channel, configDir, aifake.NewHealthy(), log)
	if err != nil {
		return err
	}
	defer func() { _ = app.Close() }()

	root := cli.NewRootCommand(cli.Deps{
		Videos: app.Videos,
		Gates:  app.Gates,
		Facts:  app.Facts,
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
