# CLAUDE.md — Rules for building REWIND

You are building the project described in `SPEC.md`. Read it fully before any work.

## How we work
1. Build **one milestone at a time** (SPEC.md Section 9). Never start the next milestone
   without the user's explicit "approved, start M<n>".
2. At the start of a milestone: restate its deliverables and acceptance criteria, list the files
   you plan to create, and ask about any ☐ APPROVE items in SPEC.md that affect it.
3. At the end of a milestone: run the tests, show the exact demo commands, summarize what was
   built and anything that deviates from SPEC.md, then STOP.
4. If the spec is ambiguous or seems wrong, ask — don't silently improvise. Propose a spec edit.

## Non-negotiable product rules
- Human review gates (A–F) can never be skipped or auto-approved. No "--yes" flags that bypass them.
- Never upload with `privacyStatus` other than `private`. Never auto-publish.
- The LLM must never be the source of a fact. Facts come only from fetched sources and must pass
  the evidence verifier.
- No brand logos, product designs, or real identifiable people in generated images.
- Only use free/open-source tools and free API tiers. Ask before adding any dependency that
  costs money or needs a paid account.
- Voice cloning only from `assets/voice/reference.wav` (the user's own voice).

## Architecture (SPEC.md §2.4) — memorise this
Three services in one monorepo, talking over a generated contract:

    web/ (Next.js + MUI) --HTTP/JSON--> api/ (Go) --gRPC--> ai/ (Python)

- **`api/` (Go) owns ALL state.** SQLite, the video state machine, gates A–F, the job queue,
  `review_log.json`, and the YouTube upload. Go never runs a model.
- **`ai/` (Python) owns ALL model and media work and NO state.** It receives a request, does one
  job, writes files into `projects/<video_id>/`, returns a result, and forgets everything.
  It must never decide a status or write to SQLite.
- **`proto/` is the source of truth.** Change the proto first, run `make proto`, then implement
  both sides. Never hand-write a type that a generated one already covers.
- **Messages carry paths, not bytes.** Never stream media over gRPC.

## Engineering conventions

### Everywhere
- All config in `config/*.yaml`; no hard-coded paths, ports, model names, or limits.
- Steps must be idempotent and resumable; on failure set status `error` with a message.
- Secrets live in `.env` (gitignored). Provide `.env.example`. Never commit credentials.
- Every long-running RPC is server-streaming and emits `Progress` events.
- Write offline test fixtures (saved source text) so tests don't need the internet or a GPU.
- Conventional Commits; one milestone per branch/PR; all CI jobs green before merge.

### Go (`api/`)
- Go 1.23+, `gofmt`, `go vet`, `golangci-lint`. Errors wrapped with `%w` and context — never
  `_ = err`. `ctx context.Context` is the first parameter of anything that can block.
- Every state change goes through `internal/state`; no raw status UPDATE anywhere else.
  A state change and its review-log entry commit in the same transaction.
- SQLite via `modernc.org/sqlite` (pure Go — do not introduce a cgo driver).
- Table-driven tests; test the orchestrator against an in-process fake AI server, never live Python.

### Python (`ai/`)
- Python 3.11, type hints, `ruff` + `mypy` + `pytest`. Keep modules small and testable.
- Service handlers are thin: parse the request, call a plain function, yield typed events.
  All real logic lives in ordinary functions that tests can call without gRPC.

### TypeScript (`web/`)
- Next.js 15 App Router, strict TS. **MUI v6 only — never add Tailwind or shadcn/ui.**
- No hand-written API types: import the generated client from `lib/gen/`.
- All colours, radii, type scale and motion come from `web/theme/tokens.ts`. No magic values
  in page or component code. Every animation respects `prefers-reduced-motion`.

## Current milestone
M0 — Plumbing (proto + three services saying hello). Update this line as milestones are approved.
