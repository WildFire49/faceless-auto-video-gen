// Package sqlite implements the storage ports on top of SQLite.
//
// LAYER 4 (adapter) of SPEC.md 14.1. This is the only package in the Go
// service that contains SQL. Everything above it depends on domain.VideoRepo
// and domain.ReviewLog, which is why the whole tree can be tested against an
// in-memory database -- or a fake -- with no schema in sight.
//
// The driver is modernc.org/sqlite: a pure-Go translation of SQLite with no
// cgo, so the project builds on Windows without a C compiler. Do not swap it
// for mattn/go-sqlite3 (SPEC.md 3.1).
package sqlite

import (
	"context"
	"database/sql"
	"embed"
	"fmt"
	"path/filepath"

	"github.com/pressly/goose/v3"
	_ "modernc.org/sqlite" // registers the "sqlite" driver

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
)

//go:embed migrations/*.sql
var migrationsFS embed.FS

// DB owns the connection pool and implements domain.TxManager.
type DB struct {
	db *sql.DB
}

// Open connects to the database at path, applies migrations, and returns a
// ready DB. Use ":memory:" for tests.
func Open(ctx context.Context, path string) (*DB, error) {
	dsn, err := buildDSN(path)
	if err != nil {
		return nil, err
	}

	pool, err := sql.Open("sqlite", dsn)
	if err != nil {
		return nil, fmt.Errorf("opening sqlite at %s: %w", path, err)
	}

	// SQLite permits one writer at a time. Serialising through a single
	// connection turns "database is locked" -- which surfaces as a random
	// failure under concurrency -- into ordinary queueing (SPEC.md 13.3).
	pool.SetMaxOpenConns(1)
	pool.SetMaxIdleConns(1)

	if err := pool.PingContext(ctx); err != nil {
		_ = pool.Close()
		return nil, fmt.Errorf("connecting to sqlite at %s: %w", path, err)
	}

	d := &DB{db: pool}
	if err := d.migrate(ctx); err != nil {
		_ = pool.Close()
		return nil, err
	}
	return d, nil
}

// buildDSN assembles the connection string.
//
// The pragmas matter:
//   - WAL lets readers proceed while a write is in flight, so the dashboard
//     stays responsive during a state change.
//   - busy_timeout waits for a lock instead of failing instantly.
//   - foreign_keys is OFF by default in SQLite; without it the review log's
//     reference to videos would not be enforced at all.
func buildDSN(path string) (string, error) {
	const pragmas = "?_pragma=journal_mode(WAL)" +
		"&_pragma=busy_timeout(5000)" +
		"&_pragma=foreign_keys(ON)" +
		"&_pragma=synchronous(NORMAL)"

	if path == ":memory:" {
		return "file::memory:" + pragmas + "&cache=shared", nil
	}
	abs, err := filepath.Abs(path)
	if err != nil {
		return "", fmt.Errorf("resolving db path %q: %w", path, err)
	}
	return "file:" + filepath.ToSlash(abs) + pragmas, nil
}

// migrate applies any pending migrations.
//
// Migrations are embedded in the binary, so a deployed `rewind` needs no
// files alongside it and can never run against a half-known schema.
func (d *DB) migrate(ctx context.Context) error {
	goose.SetBaseFS(migrationsFS)
	goose.SetLogger(goose.NopLogger())

	if err := goose.SetDialect("sqlite3"); err != nil {
		return fmt.Errorf("setting goose dialect: %w", err)
	}
	if err := goose.UpContext(ctx, d.db, "migrations"); err != nil {
		return fmt.Errorf("applying migrations: %w", err)
	}
	return nil
}

// Close releases the pool.
func (d *DB) Close() error {
	if err := d.db.Close(); err != nil {
		return fmt.Errorf("closing sqlite: %w", err)
	}
	return nil
}

// --- transactions ---------------------------------------------------------

type txKey struct{}

// WithTx runs fn inside a transaction, committing on success and rolling back
// on any error or panic.
//
// The transaction is carried on the context, so repositories pick it up
// without the caller threading a *sql.Tx through every signature. Nested
// calls join the existing transaction rather than deadlocking against it --
// which they would, given the single connection.
func (d *DB) WithTx(ctx context.Context, fn func(ctx context.Context) error) error {
	if _, already := ctx.Value(txKey{}).(*sql.Tx); already {
		return fn(ctx)
	}

	tx, err := d.db.BeginTx(ctx, nil)
	if err != nil {
		return fmt.Errorf("beginning transaction: %w", err)
	}

	// A panic must not leave the transaction open holding the only
	// connection, which would wedge every later request.
	defer func() {
		if p := recover(); p != nil {
			_ = tx.Rollback()
			panic(p)
		}
	}()

	if err := fn(context.WithValue(ctx, txKey{}, tx)); err != nil {
		if rbErr := tx.Rollback(); rbErr != nil {
			return fmt.Errorf("%w (rollback also failed: %v)", err, rbErr)
		}
		return err
	}

	if err := tx.Commit(); err != nil {
		return fmt.Errorf("committing transaction: %w", err)
	}
	return nil
}

// querier is the subset of *sql.DB and *sql.Tx that repositories use, so the
// same query code runs inside and outside a transaction.
type querier interface {
	ExecContext(ctx context.Context, query string, args ...any) (sql.Result, error)
	QueryContext(ctx context.Context, query string, args ...any) (*sql.Rows, error)
	QueryRowContext(ctx context.Context, query string, args ...any) *sql.Row
}

// conn returns the transaction on the context if there is one, otherwise the
// pool. This is what makes WithTx transparent to repositories.
func (d *DB) conn(ctx context.Context) querier {
	if tx, ok := ctx.Value(txKey{}).(*sql.Tx); ok {
		return tx
	}
	return d.db
}

var _ domain.TxManager = (*DB)(nil)
