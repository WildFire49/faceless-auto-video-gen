// Package buildinfo reports which build of the API is running.
//
// LAYER 6 (platform) of SPEC.md 14.1. It implements domain.BuildInfo, which is
// a port rather than a global constant so that tests get stable output instead
// of whatever the build machine stamped in.
package buildinfo

import (
	"runtime/debug"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
)

// Version is overridden at release time with:
//
//	go build -ldflags "-X ...buildinfo.Version=v0.1.0"
//
// It stays "dev" during development.
var Version = "dev"

// Real reports the linker-stamped version, falling back to the VCS revision
// that the Go toolchain embeds automatically.
type Real struct{}

// New returns the real build info.
func New() Real { return Real{} }

// Version implements domain.BuildInfo.
func (Real) Version() string {
	if Version != "dev" {
		return Version
	}
	info, ok := debug.ReadBuildInfo()
	if !ok {
		return Version
	}
	for _, s := range info.Settings {
		if s.Key == "vcs.revision" && len(s.Value) >= 7 {
			return "dev+" + s.Value[:7]
		}
	}
	return Version
}

// Static is a fixed version, for tests and for the fake AI mode.
type Static string

// Version implements domain.BuildInfo.
func (s Static) Version() string { return string(s) }

var (
	_ domain.BuildInfo = Real{}
	_ domain.BuildInfo = Static("")
)
