# REWIND

Faceless history shorts studio. Every episode takes an everyday object and time-travels from its
oldest version to today, one era every ~5 seconds — real, sourced history with dry humour.

**The machine does the busywork. A human approves every creative decision.** Nothing is ever
published without passing all six review gates.

See [`SPEC.md`](SPEC.md) for the full design and [`CLAUDE.md`](CLAUDE.md) for the build rules.

---

## Architecture

Three services in one repo, talking over a contract generated from `proto/`:

```
  web/   Next.js 15 + MUI     ──HTTP/JSON──▶   api/   Go        ──gRPC──▶   ai/   Python
  the review dashboard                        owns ALL state                owns ALL model work
  :3000                                       :8080                         :50051
```

The rule that keeps this simple:

> **Go owns the database. Python owns no state at all.**
> Python receives a request, does one job, writes files into `projects/<video_id>/`, returns a
> result, and forgets everything. Only Go writes to SQLite.

New to Go or gRPC? **[SPEC.md Appendix A](SPEC.md#appendix-a--crash-course-go-and-grpc-for-a-python-developer)**
is a crash course written for a Python developer.

---

## Get it running on Windows in 10 minutes

### 1. Prerequisites

| Tool | Version | Install |
|---|---|---|
| Go | 1.23+ | <https://go.dev/dl/> |
| Python | 3.11 | `uv` installs it for you |
| uv | latest | `winget install astral-sh.uv` |
| Node.js | 22+ | <https://nodejs.org> |
| Task | 3.x | `go install github.com/go-task/task/v3/cmd/task@latest` |

Later milestones also need [Ollama](https://ollama.com) (M2+) and
[ffmpeg](https://ffmpeg.org/download.html) on PATH (M5+). `task setup` will tell you what is
missing; the dashboard reports it too.

Make sure `%USERPROFILE%\go\bin` is on your PATH — that is where `task` and the proto plugins land.

### 2. Set up

```bash
git clone git@github.com:WildFire49/faceless-auto-video-gen.git
cd faceless-auto-video-gen
task setup
```

This installs the proto toolchain, Go modules, a Python 3.11 virtualenv, and the web packages.

### 3. Run

```bash
task dev
```

Three services start together. Open <http://localhost:3000>.

**You should see a green "AI service healthy" chip.** That chip is fetched
Next.js → Go (Connect/JSON) → Python (gRPC) and back, so when it is green the entire spine works.

To work on the UI without Python running:

```bash
task dev:nopython    # Go serves the fake AI adapter
```

### 4. Verify

The real proof is the end-to-end run. With `task dev` running in another terminal:

```bash
task e2e                    # drives the live stack, writes artifacts/e2e/<run>/report.md
task e2e -- --topic sandals
```

It queues a topic, runs research, independently re-downloads the sources to re-check every
quotation, confirms Gate A stays shut until the fact sheet meets its bar, approves it, and
verifies the decision reached the review log. The artifact it leaves behind holds the full
request/response transcript, the fact sheet and a readable report.

```bash
task test     # isolated tests: Go, Python, TypeScript
task check    # everything CI runs, including the layering linters
```

---

## Commands

| Command | What it does |
|---|---|
| `task setup` | Install every toolchain dependency (run once) |
| `task dev` | Run all three services |
| `task dev:nopython` | Dashboard + Go API with the fake AI worker |
| `task proto` | Regenerate Go, Python and TypeScript stubs |
| `task e2e` | **End-to-end run against the live stack; writes a report artifact** |
| `task test` | Isolated test suites |
| `task check` | Everything CI runs |
| `task --list` | Show all tasks |

Check the API by hand:

```bash
curl -X POST http://127.0.0.1:8080/rewind.v1.RewindService/GetSystemHealth \
  -H "Content-Type: application/json" -d '{"deep":true}'
```

`deep: true` probes Ollama, the GPU and ffmpeg, and tells you exactly what is missing.

---

## Repository layout

```
proto/     the contract — change this FIRST, then run `task proto`
api/       Go: state machine, review gates, job queue, HTTP API, YouTube upload
ai/        Python: research, LLM, voice, images, captions, render
web/       Next.js: the review dashboard (gates A–F)
config/    YAML read by all three services — no hard-coded values anywhere
assets/    your voice sample, music, SFX, fonts
projects/  per-video output (gitignored)
```

Each service is layered, and dependencies only point inward:
`transport → service → domain`, with adapters implementing interfaces the domain declares.
**[SPEC.md §14](SPEC.md#14-code-architecture-modularity--design-patterns)** is the full
contract, including the plug-and-play rule:

> Adding or replacing a provider = **one new file + one registry line + one config value.**
> No existing file may be edited.

Both layering rules are machine-enforced in CI (`depguard` for Go, `import-linter` for Python),
so the architecture cannot erode quietly.

---

## Current status

**M2 — Research & Gate A: complete.** The pipeline does real work: it fetches Wikipedia, asks a
local model to extract dated events, throws away anything it cannot trace back to the source, and
presents what survives for review at Gate A.

```bash
rewind add "iron"                 # queue a topic
rewind queue --needs-review       # what is waiting for you
rewind approve iron A --note "checked every source"
rewind reject iron C --back-to researching --note "the 1882 date is wrong"
rewind log iron                   # the human decision history
```

Gates cannot be skipped, structurally: gate-crossing transitions live in a different table from
automatic ones, so a pipeline step cannot perform one. See `api/internal/domain/state.go`.

### The rule the whole project rests on

**The LLM is never the source of a fact.** It may only point at a sentence in text we fetched.
`ai/rewind_ai/research/verifier.py` then checks that sentence really is in that text, two ways:

- **fuzzy prose match** — tolerates the curly quotes and citation markers a model drops when
  copying, so honest facts are not rejected for cosmetic reasons
- **exact number match** — because fuzzy matching is blind to the attack that matters most:

  ```
  source:   "...dated to approximately 7000 or 8000 BC, found at Fort Rock..."
  evidence: "...dated to approximately 3000 or 4000 BC, found at Fort Rock..."
  ```

  That is a falsified date. It scores **0.99** on prose similarity — four characters out of a
  hundred and eighty — so no prose threshold catches it. Every digit in the evidence must also
  appear in the matching region of the source.

A fact that fails either check is dropped before a human ever sees it. The counts are shown at
Gate A, which makes them a measurement of the *model*: a high rejection rate means that model
invents on this task.

Next up is **M3**: the relevance engine and Gate B — finding modern references that make the
history funny. See [SPEC.md §9](SPEC.md#9-build-milestones-one-claude-code-session-each).

---

## Non-negotiables

These are enforced in code and in review, not just documented:

- Human review gates A–F can never be skipped or auto-approved.
- Uploads are always `privacyStatus: private`. Nothing ever auto-publishes.
- The LLM is never the source of a fact. Every fact comes from a fetched source and must pass the
  evidence verifier.
- No brand logos, product designs or real identifiable people in generated images.
- Free and open-source tools only.
- Voice cloning only from your own recording in `assets/voice/`.
