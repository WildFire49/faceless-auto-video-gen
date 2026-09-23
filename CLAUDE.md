# CLAUDE.md — Rules for building REWIND

## Testing philosophy (read this first)

**Highly prefer E2E tests as the sole testing mechanism.** Use them to verify complex
features work. At the end of E2E tests, produce a verifiable and repeatable artifact.

- If you must test a system in isolation, FIRST write all the ways it could fail,
  THEN write the code.

What this means in practice here:
- `task e2e` is the real proof a milestone works. It drives the actual three-service
  stack over HTTP, exactly as a human would, and writes an artifact to `artifacts/e2e/`
  that can be read, diffed and re-run.
- A milestone is not "done" because unit tests pass. It is done when the E2E run
  produces an artifact showing the feature working end to end.
- Isolated tests are for components where the failure modes are the point — the
  evidence verifier is the example: its test file is organised as a list of ways it
  could let a falsified fact through, written before the matching code.

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

## Modularity rules (SPEC.md §14) — apply to every file you write

**The dependency rule.** Dependencies point inward only:
`transport/handlers/pages → service/use-cases → domain/core`, with adapters implementing
interfaces the domain declares. `domain/` (Go) and `*/base.py` (Python) import nothing from
this project. Business logic depends on interfaces, never on a driver.

**The plug-and-play contract.** For every swappable piece (LLM, voice engine, image backend,
research source, trend source, ASR, renderer, style preset, validator rule, storage, uploader):

> Adding or replacing a provider = **one new file + one registry line + one config value.**
> No existing file may be edited.

If a swap would require editing a caller, the abstraction is wrong — fix the abstraction, not
the caller. Before adding a second implementation of anything, extract the interface first.

**Wiring happens in exactly one place per service** — `cmd/rewind-api/main.go`,
`ai/rewind_ai/core/container.py`, `web/lib/api/client.ts`. Only those files may name a concrete
implementation. Nothing else constructs its own dependencies. No globals, no singletons.

**Patterns to use** (see §14.3 for where): Strategy, Registry+Factory, Ports & Adapters,
Repository, constructor DI, Template Method, Chain of Responsibility (validator rules),
Builder (prompts), Decorator/Middleware (retry, logging, trace id), Observer (progress events),
table-driven State, Null Object/Fake (offline tests), Facade (services).

**Patterns to avoid:** deep inheritance, singletons, service locators, global mutable state,
and grab-bag `utils.py` / `helpers.py` / `common.py` / `manager.go` / `misc/` packages. Shared
code goes in `platform/` (Go) or `core/` (Python) in a file named after its one job.

**Readability, enforced in review:** files ≤ 300 lines (> 500 needs a reason), functions ≤ 50
lines, cyclomatic complexity ≤ 10, one exported concept per file, interfaces of 1–3 methods,
no logic in transport handlers, prompts in `llm/prompts/*.jinja` not string literals, any
human-tunable number in `config/`. Comments explain *why*.

**At the start of each milestone:** state which layer each new file belongs to and which
interface it implements.

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
- Next.js 15 App Router, strict TS. **MUI v7 only — never add Tailwind or shadcn/ui.**
- No hand-written API types: import the generated client from `lib/gen/`.
- All colours, radii, type scale and motion come from `web/theme/tokens.ts`. No magic values
  in page or component code. Every animation respects `prefers-reduced-motion`.

## Current milestone
M3 — Relevance & Gate B: **COMPLETE**, awaiting review. Do not start M4 without an explicit
"approved, start M4" from the user.

### Invariant M3 established — do not weaken it
**A modern reference is a comparison, never a claim.** The channel researches history, not
brands, so nothing it says about a modern company has a source behind it. Two rules enforce
this and both are load-bearing:

1. `ai/rewind_ai/relevance/rules.py` rejects any proposal whose wording asserts something
   about the brand (founded, invented, patented, acquired, "the first company to…") or
   reaches for a subject the channel avoids. It is a Chain of Responsibility: add a rule,
   do not edit the existing ones.
2. Every proposal must link to a fact the reviewer **approved at Gate A**. An unattached
   comparison has nothing to be funny about and no fact to protect.

The cap of three (`config/channel.yaml: relevance.max_selectable`) is the point at which a
history video starts sounding like an advert. It is enforced in `domain.SelectProposal`, not
in the handler, so no transport can route around it. A zero there would mean "no limit", so
config loading treats `<= 0` as the default rather than as unlimited.

### Invariant M2b established — content format is configurable
**"History of an everyday object" is ONE format, not the product.** The product is
evidence-verified short-form video. A ContentFormat owns what an item is, the prompts
that extract it, which values are implausible, how items are grouped, and its gate
thresholds. Adding a format is one file in `ai/rewind_ai/formats/providers/` plus one
config value — **Go is never touched**, because each fact sheet carries the gate rules
its own format declared.

What is NOT the format's to vary: the evidence verifier, and the requirement that every
item carry a verbatim `evidence` string. `tests/test_formats.py` asserts both against
every registered format, so a new format cannot quietly opt out.

Field names are format-neutral: `label`, `sort_key`, `context`, `group`. Never
reintroduce `year_label` or `sort_year` — they presume a timeline.

### Invariant M2 established — do not weaken it
**The LLM is never the source of a fact.** `ai/rewind_ai/research/verifier.py` checks every
extracted sentence against the fetched source TWO ways, and both are load-bearing:

1. fuzzy prose match, so honest copies survive typographic drift
2. **exact number match**, because a falsified date scores 0.99 on prose similarity —
   changing "7000" to "3000" alters four characters in a hundred and eighty, and no prose
   threshold catches it

If you ever relax the number check, a falsified date reaches a human. Every later module
consumes these facts, so this is the foundation everything else stands on.

### Things the M3 E2E run caught that unit tests did not
- **a handler can be written, wired and unit tested and still never be SERVED.**
  `RelevanceService` had sixteen passing tests and was missing from `build_server`, so the
  first Gate B run died on `Unimplemented: Method not found!`. Registration is now a table,
  logged at startup and checked against the proto contract by `tests/test_server_serves.py`.
- **whatever a prompt lists as a heading, a model will answer with.** Grouping the bank as
  `home: Dyson, air fryer, …` produced proposals whose reference was `"home"`. The prompt
  and the accept-check are now built from ONE function (`_offered`), so the model can never
  break a rule it was not shown.
- **a count returned over gRPC but not written to disk is a count that is lost.** Go rebuilds
  the whole Gate B view from `references.json` on every request.
- **whichever check runs first is the one a human reads.** Safety rules therefore run before
  the mechanical ones: a tasteless comparison must be reported as tasteless, not as
  "that brand is not on the list".
- **a check that can pass without testing anything is worse than no check.** The max-3 check
  used to excuse itself when the model wrote fewer than four comparisons; it now adds its own
  through `AddProposal` so the cap is always actually hit.

### Things the M2 E2E run caught that unit tests did not
- **a cap on items must preserve variety.** Keeping the best-scoring 40 of 172 collapsed
  them into 2 eras and Gate A refused them. Selection is round-robin across groups.
  Fixing "too many to review" created "too narrow to use" -- watch for that shape.
- a trim must never go below what the gate requires
Kept here because each was invisible to isolated tests and would recur:
- a step must declare `From → Running → To`; a step that only knows its output status
  leaves freshly queued videos untouched
- `ErrValidation` must map to HTTP 400, not 500 — a user-fixable condition is not a
  server error
- a dependency failure (model not pulled) must propagate, not be swallowed per-chunk and
  reported as "0 facts survived verification"
- a streaming handler must yield progress AS IT ARRIVES, from a worker thread; collecting
  events and yielding them after the work finishes looks identical and gives a dead
  progress bar for the whole run

### Invariant M1 established — do not weaken it
Gate-crossing transitions live in a SEPARATE table from automatic ones
(`api/internal/domain/state.go`). `Transition` can only perform automatic moves;
`ApproveGate` can only perform gate moves. A pipeline step therefore cannot skip a gate
even if it tries, because the transition it would need is not in the table it consults.
When M2 adds pipeline steps, they call `Transition` — never `ApproveGate`.

## Commands (this repo uses go-task, not make)
- `task dev` — all three services · `task dev:nopython` — API with the fake AI adapter
- `task proto` — regenerate all stubs after ANY change to `proto/`
- `task test` — every suite · `task check` — everything CI runs
