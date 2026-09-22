package sqlite_test

import (
	"context"
	"errors"
	"path/filepath"
	"testing"
	"time"

	"github.com/WildFire49/faceless-auto-video-gen/api/internal/adapter/sqlite"
	"github.com/WildFire49/faceless-auto-video-gen/api/internal/domain"
)

// These are integration tests against a real SQLite file, because the things
// worth testing here -- migrations, constraints, transaction rollback -- only
// exist in a real database. Each test gets its own file in t.TempDir(), so
// they stay isolated and need no cleanup.

func newDB(t *testing.T) *sqlite.DB {
	t.Helper()

	db, err := sqlite.Open(context.Background(), filepath.Join(t.TempDir(), "test.db"))
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	t.Cleanup(func() {
		if err := db.Close(); err != nil {
			t.Errorf("Close: %v", err)
		}
	})
	return db
}

func sampleVideo(id string) *domain.Video {
	now := time.Date(2026, 9, 22, 10, 0, 0, 0, time.UTC)
	return &domain.Video{
		ID:        id,
		Topic:     id,
		Status:    domain.StatusQueued,
		Priority:  domain.PriorityDefault,
		CreatedAt: now,
		UpdatedAt: now,
	}
}

func TestMigrationsRunOnOpen(t *testing.T) {
	t.Parallel()

	// Opening twice must be safe: goose should find nothing to do the second
	// time. A migration that is not idempotent breaks every restart.
	dir := t.TempDir()
	path := filepath.Join(dir, "twice.db")
	ctx := context.Background()

	db1, err := sqlite.Open(ctx, path)
	if err != nil {
		t.Fatalf("first Open: %v", err)
	}
	if err := db1.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}

	db2, err := sqlite.Open(ctx, path)
	if err != nil {
		t.Fatalf("second Open: %v", err)
	}
	if err := db2.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}
}

func TestCreateAndGet(t *testing.T) {
	t.Parallel()

	ctx := context.Background()
	repo := sqlite.NewVideoRepo(newDB(t))

	want := sampleVideo("iron")
	want.Notes = "compare to a modern steam iron"
	if err := repo.Create(ctx, want); err != nil {
		t.Fatalf("Create: %v", err)
	}

	got, err := repo.Get(ctx, "iron")
	if err != nil {
		t.Fatalf("Get: %v", err)
	}

	if got.ID != want.ID || got.Topic != want.Topic || got.Status != want.Status {
		t.Errorf("round trip mismatch: got %+v, want %+v", got, want)
	}
	if got.Notes != want.Notes {
		t.Errorf("notes = %q, want %q", got.Notes, want.Notes)
	}
	if !got.CreatedAt.Equal(want.CreatedAt) {
		t.Errorf("created_at = %v, want %v", got.CreatedAt, want.CreatedAt)
	}
	if got.PublishedAt != nil {
		t.Errorf("published_at = %v, want nil for a queued video", got.PublishedAt)
	}
}

func TestCreateRejectsDuplicateIDs(t *testing.T) {
	t.Parallel()

	ctx := context.Background()
	repo := sqlite.NewVideoRepo(newDB(t))

	if err := repo.Create(ctx, sampleVideo("iron")); err != nil {
		t.Fatalf("first Create: %v", err)
	}

	err := repo.Create(ctx, sampleVideo("iron"))
	if !errors.Is(err, domain.ErrAlreadyExists) {
		t.Errorf("duplicate Create = %v, want ErrAlreadyExists", err)
	}
}

func TestGetMissingReturnsNotFound(t *testing.T) {
	t.Parallel()

	repo := sqlite.NewVideoRepo(newDB(t))
	_, err := repo.Get(context.Background(), "nothing-here")
	if !errors.Is(err, domain.ErrNotFound) {
		t.Errorf("Get(missing) = %v, want ErrNotFound", err)
	}
}

func TestUpdateMissingReturnsNotFound(t *testing.T) {
	t.Parallel()

	repo := sqlite.NewVideoRepo(newDB(t))
	err := repo.Update(context.Background(), sampleVideo("ghost"))
	if !errors.Is(err, domain.ErrNotFound) {
		t.Errorf("Update(missing) = %v, want ErrNotFound", err)
	}
}

func TestListOrdersByPriorityThenAge(t *testing.T) {
	t.Parallel()

	ctx := context.Background()
	repo := sqlite.NewVideoRepo(newDB(t))
	base := time.Date(2026, 9, 22, 10, 0, 0, 0, time.UTC)

	// Inserted deliberately out of order.
	for _, tc := range []struct {
		id       string
		priority domain.Priority
		offset   time.Duration
	}{
		{"low-old", domain.PriorityLowest, 0},
		{"high-new", domain.PriorityHighest, 2 * time.Hour},
		{"high-old", domain.PriorityHighest, 1 * time.Hour},
		{"mid", domain.PriorityDefault, 0},
	} {
		v := sampleVideo(tc.id)
		v.Priority = tc.priority
		v.CreatedAt = base.Add(tc.offset)
		v.UpdatedAt = v.CreatedAt
		if err := repo.Create(ctx, v); err != nil {
			t.Fatalf("Create(%s): %v", tc.id, err)
		}
	}

	got, err := repo.List(ctx, domain.VideoFilter{})
	if err != nil {
		t.Fatalf("List: %v", err)
	}

	var ids []string
	for _, v := range got {
		ids = append(ids, v.ID)
	}
	want := []string{"high-old", "high-new", "mid", "low-old"}
	if len(ids) != len(want) {
		t.Fatalf("got %d videos %v, want %d", len(ids), ids, len(want))
	}
	for i := range want {
		if ids[i] != want[i] {
			t.Errorf("order = %v, want %v", ids, want)
			break
		}
	}
}

func TestListFilters(t *testing.T) {
	t.Parallel()

	ctx := context.Background()
	repo := sqlite.NewVideoRepo(newDB(t))

	statuses := map[string]domain.Status{
		"waiting-a":  domain.StatusFactsReady,  // at Gate A
		"waiting-f":  domain.StatusRenderReady, // at Gate F
		"busy":       domain.StatusRendering,   // mid-step
		"queued-one": domain.StatusQueued,
	}
	for id, st := range statuses {
		v := sampleVideo(id)
		v.Status = st
		if err := repo.Create(ctx, v); err != nil {
			t.Fatalf("Create(%s): %v", id, err)
		}
	}

	t.Run("awaiting review", func(t *testing.T) {
		got, err := repo.List(ctx, domain.VideoFilter{AwaitingReview: true})
		if err != nil {
			t.Fatalf("List: %v", err)
		}
		if len(got) != 2 {
			t.Fatalf("got %d videos awaiting review, want 2", len(got))
		}
		for _, v := range got {
			if _, waiting := domain.GateFor(v.Status); !waiting {
				t.Errorf("video %q with status %q is not actually at a gate", v.ID, v.Status)
			}
		}
	})

	t.Run("by status", func(t *testing.T) {
		got, err := repo.List(ctx, domain.VideoFilter{
			Statuses: []domain.Status{domain.StatusQueued},
		})
		if err != nil {
			t.Fatalf("List: %v", err)
		}
		if len(got) != 1 || got[0].ID != "queued-one" {
			t.Errorf("got %d videos, want just queued-one", len(got))
		}
	})
}

// --------------------------------------------------------------- transactions

func TestWithTxRollsBackOnError(t *testing.T) {
	t.Parallel()

	ctx := context.Background()
	db := newDB(t)
	repo := sqlite.NewVideoRepo(db)
	log := sqlite.NewReviewLog(db)

	sentinel := errors.New("something went wrong after the write")

	err := db.WithTx(ctx, func(ctx context.Context) error {
		if err := repo.Create(ctx, sampleVideo("doomed")); err != nil {
			return err
		}
		if err := log.Append(ctx, &domain.ReviewEntry{
			VideoID: "doomed", At: time.Now(), Action: domain.ActionCreate,
			ToStatus: domain.StatusQueued,
		}); err != nil {
			return err
		}
		return sentinel
	})
	if !errors.Is(err, sentinel) {
		t.Fatalf("WithTx error = %v, want the sentinel", err)
	}

	// This is the property SPEC.md 13.3 requires: neither the video nor its
	// log entry survives a failure partway through.
	if _, err := repo.Get(ctx, "doomed"); !errors.Is(err, domain.ErrNotFound) {
		t.Errorf("video survived a rolled-back transaction")
	}
	entries, err := log.List(ctx, "doomed")
	if err != nil {
		t.Fatalf("List: %v", err)
	}
	if len(entries) != 0 {
		t.Errorf("got %d log entries after rollback, want 0", len(entries))
	}
}

func TestWithTxCommitsBothWritesTogether(t *testing.T) {
	t.Parallel()

	ctx := context.Background()
	db := newDB(t)
	repo := sqlite.NewVideoRepo(db)
	log := sqlite.NewReviewLog(db)

	err := db.WithTx(ctx, func(ctx context.Context) error {
		if err := repo.Create(ctx, sampleVideo("iron")); err != nil {
			return err
		}
		return log.Append(ctx, &domain.ReviewEntry{
			VideoID: "iron", At: time.Now(), Action: domain.ActionCreate,
			ToStatus: domain.StatusQueued,
		})
	})
	if err != nil {
		t.Fatalf("WithTx: %v", err)
	}

	if _, err := repo.Get(ctx, "iron"); err != nil {
		t.Errorf("video missing after commit: %v", err)
	}
	entries, err := log.List(ctx, "iron")
	if err != nil {
		t.Fatalf("List: %v", err)
	}
	if len(entries) != 1 {
		t.Errorf("got %d log entries, want 1", len(entries))
	}
}

func TestNestedWithTxJoinsTheOuterTransaction(t *testing.T) {
	t.Parallel()

	// With a single connection, a nested BeginTx would deadlock against the
	// outer one. Joining is what keeps composed services safe.
	ctx := context.Background()
	db := newDB(t)
	repo := sqlite.NewVideoRepo(db)

	err := db.WithTx(ctx, func(ctx context.Context) error {
		return db.WithTx(ctx, func(ctx context.Context) error {
			return repo.Create(ctx, sampleVideo("nested"))
		})
	})
	if err != nil {
		t.Fatalf("nested WithTx: %v", err)
	}
	if _, err := repo.Get(ctx, "nested"); err != nil {
		t.Errorf("video missing after nested commit: %v", err)
	}
}

// ---------------------------------------------------------------- review log

func TestReviewLogIsOrderedAndScoped(t *testing.T) {
	t.Parallel()

	ctx := context.Background()
	db := newDB(t)
	repo := sqlite.NewVideoRepo(db)
	log := sqlite.NewReviewLog(db)

	for _, id := range []string{"iron", "mouse"} {
		if err := repo.Create(ctx, sampleVideo(id)); err != nil {
			t.Fatalf("Create(%s): %v", id, err)
		}
	}

	base := time.Date(2026, 9, 22, 10, 0, 0, 0, time.UTC)
	entries := []*domain.ReviewEntry{
		{VideoID: "iron", At: base.Add(2 * time.Hour), Gate: domain.GateB, Action: domain.ActionApprove,
			FromStatus: domain.StatusRefsReady, ToStatus: domain.StatusRefsApproved},
		{VideoID: "iron", At: base, Gate: domain.GateA, Action: domain.ActionApprove,
			FromStatus: domain.StatusFactsReady, ToStatus: domain.StatusFactsApproved, Note: "checked every source"},
		{VideoID: "mouse", At: base.Add(time.Hour), Gate: domain.GateA, Action: domain.ActionReject,
			FromStatus: domain.StatusFactsReady, ToStatus: domain.StatusResearching, Note: "1968 date is wrong"},
	}
	for _, e := range entries {
		if err := log.Append(ctx, e); err != nil {
			t.Fatalf("Append: %v", err)
		}
		if e.ID == 0 {
			t.Error("Append did not set the entry id")
		}
	}

	got, err := log.List(ctx, "iron")
	if err != nil {
		t.Fatalf("List: %v", err)
	}
	if len(got) != 2 {
		t.Fatalf("got %d entries for iron, want 2 (mouse must not leak in)", len(got))
	}
	// Oldest first, which is how a human reads a history.
	if got[0].Gate != domain.GateA || got[1].Gate != domain.GateB {
		t.Errorf("order = %s then %s, want A then B", got[0].Gate, got[1].Gate)
	}
	if got[0].Note != "checked every source" {
		t.Errorf("note = %q, want it preserved", got[0].Note)
	}
}

func TestReviewLogRequiresAnExistingVideo(t *testing.T) {
	t.Parallel()

	// The foreign key is only enforced because the DSN turns it on; SQLite
	// leaves foreign keys off by default. This test guards that pragma.
	db := newDB(t)
	log := sqlite.NewReviewLog(db)

	err := log.Append(context.Background(), &domain.ReviewEntry{
		VideoID: "does-not-exist", At: time.Now(), Action: domain.ActionApprove,
		FromStatus: domain.StatusFactsReady, ToStatus: domain.StatusFactsApproved,
	})
	if err == nil {
		t.Error("appended a log entry for a nonexistent video; the foreign key is not being enforced")
	}
}
