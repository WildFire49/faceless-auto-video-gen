-- +goose Up
-- Pipeline step executions, so the dashboard can show live progress and an
-- interrupted run is visible rather than silent (SPEC.md 8.3, 13.3).

CREATE TABLE jobs (
    id           TEXT PRIMARY KEY,
    video_id     TEXT NOT NULL REFERENCES videos (id) ON DELETE CASCADE,
    -- The status the video moves INTO on success, e.g. "facts_ready".
    step         TEXT NOT NULL,
    state        TEXT NOT NULL,

    -- Latest progress reported by the worker.
    stage        TEXT NOT NULL DEFAULT '',
    percent      REAL NOT NULL DEFAULT 0,
    current_item INTEGER NOT NULL DEFAULT 0,
    total_items  INTEGER NOT NULL DEFAULT 0,

    error        TEXT NOT NULL DEFAULT '',
    started_at   TEXT NOT NULL,
    finished_at  TEXT,

    CHECK (state IN ('running', 'succeeded', 'failed', 'interrupted'))
);

-- "the latest job for this video", which every progress poll asks for.
CREATE INDEX idx_jobs_video_recent ON jobs (video_id, started_at DESC);

-- Startup crash recovery scans for jobs still marked running.
CREATE INDEX idx_jobs_state ON jobs (state);

-- +goose Down
DROP TABLE jobs;
