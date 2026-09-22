// Package domain holds the core types and rules of REWIND.
//
// LAYER 1 of SPEC.md 14.1. This package imports NOTHING from the rest of the
// project, and nothing outside the standard library. No SQL, no gRPC, no HTTP,
// no protobuf. Everything above it depends on it; it depends on nothing.
//
// If you find yourself wanting to import a driver here, the type you are
// writing belongs in adapter/ instead.
package domain

import "time"

// Status describes how healthy a component is. It is deliberately a small
// closed set rather than a bool, because "running but missing the model you
// will need at M5" is genuinely different from both OK and DOWN.
type Status string

const (
	// StatusUnknown means the check has not run yet.
	StatusUnknown Status = "unknown"
	// StatusOK means everything needed is present and working.
	StatusOK Status = "ok"
	// StatusDegraded means usable now, but something is missing that will
	// matter later -- e.g. Ollama is up but the model is not pulled.
	StatusDegraded Status = "degraded"
	// StatusDown means the component cannot do useful work.
	StatusDown Status = "down"
)

// severity orders statuses from best to worst so they can be aggregated.
// Unknown counts as worse than degraded: never report health you do not have.
var severity = map[Status]int{
	StatusOK:       0,
	StatusDegraded: 1,
	StatusUnknown:  2,
	StatusDown:     3,
}

// WorstOf returns the least healthy of the given statuses, which is how a
// system-wide status is derived from its parts. Zero arguments yields
// StatusUnknown rather than a misleading OK.
func WorstOf(statuses ...Status) Status {
	worst := StatusUnknown
	for i, s := range statuses {
		if _, known := severity[s]; !known {
			s = StatusUnknown
		}
		if i == 0 || severity[s] > severity[worst] {
			worst = s
		}
	}
	return worst
}

// Dependency is one probed prerequisite of a component, such as Ollama, the
// GPU, or ffmpeg on PATH.
type Dependency struct {
	Name   string
	Status Status
	Detail string
}

// ComponentHealth is the health of one service in the system.
type ComponentHealth struct {
	Name    string
	Status  Status
	Version string
	// Detail carries the failure reason when Status is not OK. It is shown to
	// the operator in the dashboard, so it must not contain secrets.
	Detail       string
	Latency      time.Duration
	Dependencies []Dependency
}

// SystemHealth is the health of every component, plus the aggregate.
type SystemHealth struct {
	Status Status
	API    ComponentHealth
	AI     ComponentHealth
}
