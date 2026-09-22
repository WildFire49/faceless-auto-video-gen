-- +goose Up
-- The video queue and the human review log (SPEC.md 5.1, 8.4).

CREATE TABLE videos (
    -- Slug, and also the folder name under projects/. Validated against
    -- ^[a-z0-9-]{1,64}$ before ever being used to build a path.
    id            TEXT PRIMARY KEY,
    topic         TEXT NOT NULL,
    status        TEXT NOT NULL,

    -- 1 highest, 5 lowest.
    priority      INTEGER NOT NULL DEFAULT 3,
    notes         TEXT NOT NULL DEFAULT '',

    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,

    -- Set when a gate sent this video back; cleared when it moves forward.
    rejected_to   TEXT NOT NULL DEFAULT '',
    reject_note   TEXT NOT NULL DEFAULT '',

    -- Set together when a step fails. retry_from is where to resume.
    error         TEXT NOT NULL DEFAULT '',
    retry_from    TEXT NOT NULL DEFAULT '',

    yt_video_id   TEXT NOT NULL DEFAULT '',
    published_at  TEXT,

    CHECK (priority BETWEEN 1 AND 5),
    CHECK (length(id) BETWEEN 1 AND 64)
);

-- The dashboard's two main queries: "everything, queue order" and
-- "just what needs my review".
CREATE INDEX idx_videos_status ON videos (status);
CREATE INDEX idx_videos_queue ON videos (priority ASC, created_at ASC);

CREATE TABLE review_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id    TEXT NOT NULL REFERENCES videos (id) ON DELETE CASCADE,
    at          TEXT NOT NULL,

    -- Empty for non-gate actions such as create and retry.
    gate        TEXT NOT NULL DEFAULT '',
    action      TEXT NOT NULL,

    from_status TEXT NOT NULL,
    to_status   TEXT NOT NULL,

    note        TEXT NOT NULL DEFAULT '',
    -- JSON describing what a human changed, for edit actions.
    diff        TEXT NOT NULL DEFAULT ''
);

CREATE INDEX idx_review_log_video ON review_log (video_id, at);

-- +goose Down
DROP TABLE review_log;
DROP TABLE videos;
