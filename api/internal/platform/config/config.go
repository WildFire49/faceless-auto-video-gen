// Package config loads config/*.yaml into typed structs.
//
// LAYER 6 (platform) of SPEC.md 14.1. Only the composition root
// (cmd/rewind-api/main.go) reads config; it then passes concrete values into
// constructors. No package reaches for configuration on its own, because a
// component that fetches its own settings cannot be tested with different ones.
package config

import (
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/knadh/koanf/parsers/yaml"
	"github.com/knadh/koanf/providers/file"
	"github.com/knadh/koanf/v2"
)

// Services mirrors config/services.yaml.
type Services struct {
	API struct {
		HTTPAddr             string   `koanf:"http_addr"`
		DBPath               string   `koanf:"db_path"`
		CORSOrigins          []string `koanf:"cors_origins"`
		ShutdownGraceSeconds int      `koanf:"shutdown_grace_seconds"`
	} `koanf:"api"`

	AI struct {
		GRPCAddr        string         `koanf:"grpc_addr"`
		MaxMessageBytes int            `koanf:"max_message_bytes"`
		TimeoutsSeconds map[string]int `koanf:"timeouts_seconds"`
	} `koanf:"ai"`

	Web struct {
		APIBaseURL string `koanf:"api_base_url"`
	} `koanf:"web"`

	Paths struct {
		Projects string `koanf:"projects"`
		Assets   string `koanf:"assets"`
	} `koanf:"paths"`
}

// Timeout returns the deadline for a named RPC group, or fallback when the key
// is absent. An unknown key is not fatal: a missing timeout must never stop the
// studio from starting, it just uses a sane default.
func (s Services) Timeout(name string, fallback time.Duration) time.Duration {
	secs, ok := s.AI.TimeoutsSeconds[name]
	if !ok || secs <= 0 {
		return fallback
	}
	return time.Duration(secs) * time.Second
}

// ShutdownGrace returns how long to spend draining work on shutdown.
func (s Services) ShutdownGrace() time.Duration {
	if s.API.ShutdownGraceSeconds <= 0 {
		return 20 * time.Second
	}
	return time.Duration(s.API.ShutdownGraceSeconds) * time.Second
}

// LoadServices reads services.yaml from the given config directory.
//
// Note the error handling: every failure is wrapped with what was being
// attempted, so a misconfigured deployment produces a message that names the
// file rather than a bare "unexpected EOF" (SPEC.md Appendix A.1, point 2).
func LoadServices(configDir string) (Services, error) {
	path := filepath.Join(configDir, "services.yaml")

	if _, err := os.Stat(path); err != nil {
		return Services{}, fmt.Errorf("reading %s: %w", path, err)
	}

	k := koanf.New(".")
	if err := k.Load(file.Provider(path), yaml.Parser()); err != nil {
		return Services{}, fmt.Errorf("parsing %s: %w", path, err)
	}

	var cfg Services
	if err := k.Unmarshal("", &cfg); err != nil {
		return Services{}, fmt.Errorf("decoding %s: %w", path, err)
	}

	if err := cfg.validate(); err != nil {
		return Services{}, fmt.Errorf("validating %s: %w", path, err)
	}
	return cfg, nil
}

// validate fails fast on configuration that would only break later, at the
// first request, when the cause is much harder to see.
func (s Services) validate() error {
	if s.API.HTTPAddr == "" {
		return fmt.Errorf("api.http_addr is required")
	}
	if s.AI.GRPCAddr == "" {
		return fmt.Errorf("ai.grpc_addr is required")
	}
	if s.Paths.Projects == "" {
		return fmt.Errorf("paths.projects is required")
	}
	return nil
}

// FindDir locates the repository's config/ directory by walking up from the
// working directory. It means `go run ./cmd/rewind-api` works from anywhere in
// the repo, which matters more than it sounds like during development.
func FindDir(start string) (string, error) {
	dir, err := filepath.Abs(start)
	if err != nil {
		return "", fmt.Errorf("resolving %q: %w", start, err)
	}
	for {
		candidate := filepath.Join(dir, "config", "services.yaml")
		if _, err := os.Stat(candidate); err == nil {
			return filepath.Join(dir, "config"), nil
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return "", fmt.Errorf("no config/services.yaml found above %q", start)
		}
		dir = parent
	}
}
