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

// HealthStatus describes how healthy a component is. It is deliberately a small
// closed set rather than a bool, because "running but missing the model you
// will need at M5" is genuinely different from both OK and DOWN.
type HealthStatus string

const (
	// HealthUnknown means the check has not run yet.
	HealthUnknown HealthStatus = "unknown"
	// HealthOK means everything needed is present and working.
	HealthOK HealthStatus = "ok"
	// HealthDegraded means usable now, but something is missing that will
	// matter later -- e.g. Ollama is up but the model is not pulled.
	HealthDegraded HealthStatus = "degraded"
	// HealthDown means the component cannot do useful work.
	HealthDown HealthStatus = "down"
)

// severity orders statuses from best to worst so they can be aggregated.
// Unknown counts as worse than degraded: never report health you do not have.
var severity = map[HealthStatus]int{
	HealthOK:       0,
	HealthDegraded: 1,
	HealthUnknown:  2,
	HealthDown:     3,
}

// WorstOf returns the least healthy of the given statuses, which is how a
// system-wide status is derived from its parts. Zero arguments yields
// HealthUnknown rather than a misleading OK.
func WorstOf(statuses ...HealthStatus) HealthStatus {
	worst := HealthUnknown
	for i, s := range statuses {
		if _, known := severity[s]; !known {
			s = HealthUnknown
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
	Status HealthStatus
	Detail string
}

// ComponentHealth is the health of one service in the system.
type ComponentHealth struct {
	Name    string
	Status  HealthStatus
	Version string
	// Detail carries the failure reason when Status is not OK. It is shown to
	// the operator in the dashboard, so it must not contain secrets.
	Detail       string
	Latency      time.Duration
	Dependencies []Dependency
}

// SystemHealth is the health of every component, plus the aggregate.
type SystemHealth struct {
	Status HealthStatus
	API    ComponentHealth
	AI     ComponentHealth
}
