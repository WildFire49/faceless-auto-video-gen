// Package middleware holds cross-cutting HTTP concerns.
//
// LAYER 5 (transport) of SPEC.md 14.1, using the Decorator pattern (14.3):
// each function wraps an http.Handler and returns one, so behaviour is added
// by composition in main.go rather than by editing handlers.
package middleware

import (
	"crypto/rand"
	"encoding/hex"
	"log/slog"
	"net/http"
	"slices"
	"time"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/platform/logging"
)

// Chain applies middlewares so that the first listed is the outermost.
// Reading main.go top to bottom then matches the order a request travels.
func Chain(h http.Handler, mw ...func(http.Handler) http.Handler) http.Handler {
	for i := len(mw) - 1; i >= 0; i-- {
		h = mw[i](h)
	}
	return h
}

// TraceID attaches a request id to the context, reusing an inbound one when
// present so a trace survives across services.
func TraceID(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		id := r.Header.Get(logging.TraceIDKey)
		if id == "" {
			id = newTraceID()
		}
		w.Header().Set(logging.TraceIDKey, id)
		next.ServeHTTP(w, r.WithContext(logging.WithTraceID(r.Context(), id)))
	})
}

func newTraceID() string {
	var b [8]byte
	if _, err := rand.Read(b[:]); err != nil {
		// A trace id is diagnostic, never load-bearing: degrade rather than
		// fail a real request over it.
		return "trace-unavailable"
	}
	return hex.EncodeToString(b[:])
}

// statusRecorder captures the response code so it can be logged, since
// http.ResponseWriter does not expose it.
type statusRecorder struct {
	http.ResponseWriter
	status int
}

func (r *statusRecorder) WriteHeader(code int) {
	r.status = code
	r.ResponseWriter.WriteHeader(code)
}

// Logging records one structured line per request (SPEC.md 13.4).
func Logging(log *slog.Logger) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			start := time.Now()
			rec := &statusRecorder{ResponseWriter: w, status: http.StatusOK}
			next.ServeHTTP(rec, r)

			logging.FromContext(r.Context(), log).Info("http request",
				slog.String("method", r.Method),
				slog.String("path", r.URL.Path),
				slog.Int("status", rec.status),
				slog.Duration("duration", time.Since(start)),
			)
		})
	}
}

// Recover turns a panic into a 500 instead of killing the process. A crash
// during a render must not take down the studio (SPEC.md 13.3).
func Recover(log *slog.Logger) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			defer func() {
				if v := recover(); v != nil {
					logging.FromContext(r.Context(), log).Error("panic recovered",
						slog.Any("panic", v),
						slog.String("path", r.URL.Path),
					)
					http.Error(w, "internal error", http.StatusInternalServerError)
				}
			}()
			next.ServeHTTP(w, r)
		})
	}
}

// CORS permits the dashboard's dev server to call the API.
//
// The allow-list comes from config/services.yaml and contains localhost only.
// It is an allow-list rather than "*" even on loopback, because a wildcard
// here is a habit that becomes a vulnerability the day this moves off the
// machine (SPEC.md 13.5).
func CORS(origins []string) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			origin := r.Header.Get("Origin")
			if origin != "" && slices.Contains(origins, origin) {
				w.Header().Set("Access-Control-Allow-Origin", origin)
				w.Header().Set("Vary", "Origin")
				w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
				// Connect sends its own protocol headers; they must be allowed
				// through or every request fails preflight.
				w.Header().Set("Access-Control-Allow-Headers",
					"Content-Type, Connect-Protocol-Version, Connect-Timeout-Ms, "+logging.TraceIDKey)
				w.Header().Set("Access-Control-Expose-Headers", logging.TraceIDKey)
				w.Header().Set("Access-Control-Max-Age", "86400")
			}
			if r.Method == http.MethodOptions {
				w.WriteHeader(http.StatusNoContent)
				return
			}
			next.ServeHTTP(w, r)
		})
	}
}
