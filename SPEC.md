# REWIND — Faceless History Shorts Studio
### Technical Specification v2.1 — Go API · Python AI (gRPC) · Next.js + MUI

> **What this is:** A studio for short-form video where **every claim on screen is traceable to a
> source a human approved**. That is the product. The *kind* of video is a **content format**,
> chosen in one line of config — not something baked into the code.
>
> **Shipped formats:** `history_timeline` (the original series concept: an everyday object traced
> from its oldest known version to today, one era every ~5 seconds) and `myth_vs_fact` (widely
> held beliefs paired with the sourced correction). Adding a format is one file
> (SPEC.md §14.2); nothing else in the pipeline changes.
>
> **Golden rule:** The machine does the busywork. A human approves every creative decision.
> Nothing is ever published without passing all review gates.

---

## 0. How to use this document

1. Put this file and `CLAUDE.md` in an empty folder. Open Claude Code in that folder.
2. Tell Claude Code: *"Read SPEC.md and CLAUDE.md. Start Milestone 0."*
3. Claude Code builds **one milestone at a time** (Section 9), then stops for you to review.
4. Each milestone has **acceptance criteria**. Don't move on until they pass.
5. Every section marked **☐ APPROVE** is a design decision for you to confirm or change *before*
   that part is built. Tick them as you go.

---

## 1. Requirements

### 1.1 Functional
| # | Requirement |
|---|---|
| F1 | Take a topic ("sandals") and produce a researched timeline with a source link for every fact |
| F2 | Find modern, trending references relevant to the topic (brands, products, memes, slang) |
| F3 | Write a funny, rhythmic ~45–60s beat script using only approved facts + approved references |
| F4 | Generate narration in the channel's cloned voice with per-beat emotion |
| F5 | Generate era-accurate visuals in one consistent art style |
| F6 | Add word-by-word captions, year stamps, text punchlines, music, and SFX on a 5s beat grid |
| F7 | Render 9:16 (Shorts/Reels/TikTok) — and later 16:9 long-form compilations |
| F8 | Upload to YouTube as **private** with AI disclosure; human publishes manually |
| F9 | Pull retention data after 48h and feed learnings into future scripts |
| F10 | A review dashboard where the human approves/edits/rejects at each gate |

### 1.2 Non-functional
- **Cost:** $0 software. Open-source models, free APIs only.
- **Hardware:** Runs locally. Target: Apple Silicon Mac (M4) with ≥16 GB unified memory, models
  on the GPU through Metal (`mps`). The accelerator is a swap (`compute.accelerator` in
  `config/channel.yaml`): `nvidia_cuda` targets an NVIDIA GPU with ≥8 GB VRAM instead.
  Fallback: CPU (Kokoro voice) + free Kaggle/Colab GPU for image generation.
- **Throughput:** 1–2 finished Shorts/day with ≤20 min human time per video.
- **Accuracy:** Zero unsourced factual claims. Jokes must be clearly jokes.
- **Resumability:** Any step can crash and resume without redoing earlier steps.
- **Policy-safe:** Complies with YouTube inauthentic-content rules, Instagram originality rules,
  and AI-disclosure requirements on all platforms.

### 1.3 Out of scope (v1)
- Auto-publishing (always manual)
- Instagram/TikTok API upload (manual upload in v1)
- Long-form compilations (planned v2)
- Multi-language (planned v2)

**☐ APPROVE Section 1** — requirements & scope

---

## 2. Architecture

### 2.1 Pipeline overview

```
 ┌──────────┐   ┌──────────┐   ┌───────────┐   ┌──────────┐
 │  TOPIC   │──▶│ RESEARCH │──▶│ RELEVANCE │──▶│  SCRIPT  │
 │  QUEUE   │   │ (facts)  │   │ (trends)  │   │ (beats)  │
 └──────────┘   └────┬─────┘   └─────┬─────┘   └────┬─────┘
                  GATE A          GATE B          GATE C
                     │               │               │
 ┌──────────┐   ┌────▼─────┐   ┌─────▼─────┐   ┌────▼─────┐
 │ PUBLISH  │◀──│  RENDER  │◀──│  VISUALS  │◀──│  VOICE   │
 │ (private)│   │ +captions│   │(storyboard│   │ (per-beat│
 └────┬─────┘   │ +music   │   │  images)  │   │  audio)  │
      │         └────┬─────┘   └─────┬─────┘   └────┬─────┘
      │           GATE F          GATE E          GATE D
      ▼
 ┌──────────┐
 │ANALYTICS │──▶ lessons fed back into SCRIPT prompts
 └──────────┘
```

### 2.2 Review gates (human approval points)

| Gate | What you review | Typical time | Can edit in dashboard? |
|---|---|---|---|
| **A — Facts** | Timeline of facts, each with its source link | 3–5 min | Yes: edit/delete facts, add URLs |
| **B — References** | 3–6 proposed modern comparisons + why they're funny | 1–2 min | Yes: pick, reject, write your own |
| **C — Script** | Beat-by-beat script with facts & jokes marked | 5–8 min | Yes: edit any line |
| **D — Voice** | Listen to narration | 1 min | Regenerate single beats |
| **E — Storyboard** | Grid of all images, one row per beat | 1–2 min | Regenerate single images |
| **F — Final video** | Watch the render + loop preview | 1–2 min | Approve / send back to any gate |

### 2.3 Video state machine

Every video is one row in the database with a `status`. Each step only picks up videos in its input
state, so the pipeline is resumable and nothing skips a gate.

```
queued → researching → facts_ready ─[Gate A]→ facts_approved
       → finding_refs → refs_ready ─[Gate B]→ refs_approved
       → scripting → script_ready ─[Gate C]→ script_approved
       → voicing → voice_ready ─[Gate D]→ voice_approved
       → imaging → storyboard_ready ─[Gate E]→ storyboard_approved
       → rendering → render_ready ─[Gate F]→ final_approved
       → uploading → uploaded_private → (human publishes) → published
       → analytics_collected

Any gate can send a video BACK to an earlier state ("rejected_to: <state>") with a note.
Any step failure → status "error" + error message; `rewind retry <id>` resumes.
```

### 2.4 Service architecture (three processes, one repo)

The pipeline above is *what* happens. This is *where* it runs. Three services, one monorepo:

```
   ┌──────────────────────────┐
   │  web/   Next.js + MUI    │   browser, port 3000
   │  Review dashboard A–F    │
   └────────────┬─────────────┘
                │  HTTP/JSON  (Connect protocol — plain POST + JSON,
                │              generated TypeScript client)
                ▼
   ┌──────────────────────────┐
   │  api/   Go               │   port 8080
   │  • owns SQLite           │   THE BRAIN
   │  • video state machine   │   Decides what happens next.
   │  • review gates A–F      │   Never does AI work itself.
   │  • job queue + progress  │
   │  • review_log.json       │
   └────────────┬─────────────┘
                │  gRPC over HTTP/2  (binary, generated stubs both sides)
                ▼
   ┌──────────────────────────┐
   │  ai/    Python 3.11      │   port 50051
   │  • research / LLM        │   THE HANDS
   │  • voice / images        │   Stateless. Does one job when asked.
   │  • captions / render     │   Knows nothing about gates or status.
   └────────────┬─────────────┘
                │ reads/writes
                ▼
        projects/<video_id>/*.json, *.wav, *.png, *.mp4
```

**Why this split**

| Concern | Lives in | Reason |
|---|---|---|
| State, gates, HTTP, concurrency | **Go** | Fast, single static binary, excellent at long-running servers and job queues, strict types catch state-machine bugs at compile time |
| Anything touching a model or media | **Python** | `diffusers`, `faster-whisper`, `chatterbox`, `librosa`, `moviepy` only exist in Python. Not a preference — a hard constraint |
| Human review UI | **Next.js** | Real components, real routing, real audio/video players — things Streamlit can't do well |

**The one rule that keeps this simple:**
**Go owns the database. Python owns no state at all.** Python receives a request, does one job,
writes its output files into `projects/<video_id>/`, returns a result message, and forgets
everything. Only Go writes to SQLite. If you remember one line from this section, that's it.

### 2.5 The gRPC contract (`proto/`)

gRPC is how Go calls Python. You write the function signatures *once*, in a `.proto` file, and a
code generator produces a Go client and a Python server that are guaranteed to match. If you change
the proto and only regenerate one side, that side stops compiling — the contract can't silently
drift.

`proto/rewind/v1/` holds one file per module:

```proto
// proto/rewind/v1/research.proto
syntax = "proto3";
package rewind.v1;

service ResearchService {
  // Server-streaming: Python sends progress events while it works,
  // then one final message with the fact sheet.
  rpc BuildFactSheet(BuildFactSheetRequest) returns (stream BuildFactSheetEvent);
}

message BuildFactSheetRequest {
  string video_id   = 1;   // Go's id; Python uses it only to pick the output folder
  string topic      = 2;
  repeated string extra_urls = 3;
  int32  min_facts  = 4;
}

message BuildFactSheetEvent {
  oneof event {
    Progress progress = 1;   // {stage:"fetching wikipedia", percent:0.3}
    FactSheet result  = 2;   // terminal message
    Failure  failure  = 3;
  }
}

message Fact {
  string id = 1;
  string year_label = 2;    // "~9,000 years ago"
  int32  sort_year  = 3;    // -7000
  string place = 4;
  string claim = 5;
  string evidence = 6;      // exact sentence copied from source
  string source_url = 7;
  string confidence = 8;
  bool   conflict = 9;
}
message FactSheet { string topic = 1; repeated Fact facts = 2; string facts_json_path = 3; }
```

Full service list (one `.proto` each, same shape — a request, a stream of `Progress` then one
terminal `result` or `failure`):

| Service | RPCs |
|---|---|
| `ResearchService` | `BuildFactSheet` |
| `RelevanceService` | `ScanTrends`, `ProposeReferences` |
| `ScriptService` | `WriteScript`, `ValidateScript` |
| `VoiceService` | `SynthesizeNarration`, `RegenerateBeat` |
| `VisualService` | `GenerateStoryboard`, `RegenerateImage` |
| `CaptionService` | `AlignCaptions` |
| `RenderService` | `RenderVideo`, `BuildLoopPreview`, `CheckDeadZones` |
| `HealthService` | `Check` (used by `rewind doctor` — is the GPU there? are models pulled?) |

**Rules**
- Every long RPC is **server-streaming** so the dashboard can show a live progress bar instead of
  a spinner that hangs for four minutes.
- Messages carry **paths, not bytes.** A 40 MB `final.mp4` never travels over gRPC; Python writes
  the file and returns `"projects/iron/final.mp4"`.
- Python **never** decides a status. It returns `result` or `failure`; Go decides that a failure
  means `status = error`.
- `buf` (`buf lint`, `buf breaking`, `buf generate`) manages the protos. Generated code is
  committed so a fresh clone builds without the toolchain.

**Browser → Go is not gRPC.** Browsers can't speak native gRPC. Go uses
[Connect](https://connectrpc.com), which serves gRPC *and* ordinary JSON-over-HTTP from the same
handler — so Python gets real gRPC, and Next.js gets plain JSON `fetch` calls with a generated
TypeScript client. One proto, three languages, zero hand-written API types.

**☐ APPROVE Section 2** — pipeline order, gates, service split & gRPC contract

---

## 3. Tech stack

### 3.1 Backend — `api/` (Go)

| Layer | Choice | Why | Alternative |
|---|---|---|---|
| Language | **Go 1.23+** | Single static binary, great concurrency, compile-time-checked state machine | — |
| HTTP + RPC | `connectrpc.com/connect` + stdlib `net/http` | One handler serves gRPC (to Python) and JSON (to Next.js) | grpc-go + chi for REST |
| gRPC client | `google.golang.org/grpc` | Calls the Python AI service | — |
| Proto tooling | `buf` + `protoc-gen-go` + `protoc-gen-connect-go` | Lint, breaking-change detection, codegen | raw `protoc` |
| Database | SQLite via `modernc.org/sqlite` | **Pure Go — no cgo, no C compiler on Windows** | `mattn/go-sqlite3` (needs gcc) |
| Migrations | `pressly/goose` | Versioned schema | plain SQL file |
| CLI | `spf13/cobra` | `rewind add/queue/run/retry/doctor` | stdlib `flag` |
| Config | `koanf` reading `config/*.yaml` | Same YAML files all three services read | viper |
| Logging | stdlib `log/slog` (JSON) | Structured, no dependency | zerolog |
| Tests | stdlib `testing` + `stretchr/testify` | — | — |

### 3.2 AI worker — `ai/` (Python)

| Layer | Choice | Why | Alternative |
|---|---|---|---|
| Language | Python 3.11 | Every ML/video lib supports it | — |
| RPC server | `grpcio` + `grpcio-tools` | Serves the protos Go calls | — |
| Packaging | `uv` + `pyproject.toml` | Fast, reproducible installs | pip + venv |
| LLM | Ollama + `qwen2.5:14b` (or 7b on smaller GPUs) | Free, local, good at JSON | Llama 3.x |
| Research sources | Wikipedia API, Wikidata, user-supplied URLs, `trafilatura` for article text | Free, citable | Self-hosted SearXNG for web search |
| Trend sources | Google Trends "Trending now" RSS, Wikipedia top-pageviews API, YouTube Data API `mostPopular`, Reddit public JSON (low volume) | Free, official or public | Manual paste box in dashboard |
| Voice | Chatterbox (cloned own voice) | Emotion "exaggeration" control | Kokoro (fast, CPU) |
| Audio FX | `pedalboard`, `pydub`, `pyrubberband` | Polish, ducking, time-stretch | FFmpeg filters |
| Beat detection | `librosa` | Snap cuts to music beats | — |
| Images | FLUX.1-schnell (Apache-2.0) via `diffusers` or ComfyUI API | Free, fast, good quality | SDXL |
| Captions | `faster-whisper` (word timestamps) | Accurate word timing | WhisperX |
| Render | MoviePy 2.x + FFmpeg | Scriptable compositing | Remotion (JS) |
| Lint / tests | `ruff` + `pytest` | — | — |

### 3.3 Frontend — `web/` (Next.js)

| Layer | Choice | Why | Alternative |
|---|---|---|---|
| Framework | **Next.js 15, App Router, TypeScript** | Local-only dashboard, but real routing/components | Vite + React |
| UI kit | **MUI v7** (`@mui/material`, `@mui/x-data-grid`) + Emotion | Batteries-included tables, dialogs, sliders — exactly what gates A–F need. v7 rather than the v6 named earlier: Next 15 ships React 19, which MUI supports cleanly from v7 | — |
| Styling | Emotion via MUI `sx` + a custom `theme.ts` | **No Tailwind anywhere in this repo** | — |
| Design language | Apple-style: SF-ish type scale, 12–20px radii, translucent surfaces, spring motion, restraint | See Section 8.1 | — |
| Motion | `framer-motion` springs (never linear easing) | Interruptible, physical gate transitions | CSS transitions |
| API client | `@connectrpc/connect-web` + `protoc-gen-es` | **API types generated from the same protos** — no hand-written interfaces | `fetch` + zod |
| Data fetching | TanStack Query | Polling job progress, cache invalidation on approve | SWR |
| Tests | Vitest + Playwright (smoke) | — | — |

> **On shadcn/ui:** shadcn is a set of components styled with Tailwind utility classes; it cannot
> be used without Tailwind. Since "no Tailwind" is a hard requirement here, the project uses **MUI
> only**, and the Apple feel comes from the custom MUI theme in §8.1 rather than from shadcn.
> If you later prefer shadcn, that means adopting Tailwind and dropping MUI — §3.3 and §8 are the
> only sections that change.

### 3.4 Shared / cross-cutting

| Layer | Choice | Why |
|---|---|---|
| Contract | Protocol Buffers in `proto/`, managed by `buf` | Single source of truth for Go, Python and TypeScript |
| Upload | YouTube Data API v3 (`videos.insert`) via `google.golang.org/api` — **in Go** | It's a state change, so it belongs with the state owner |
| Analytics | YouTube Analytics API — **in Go**, LLM summarisation of lessons in Python | Same reason |
| Task runner | `Makefile` (`make proto`, `make dev`, `make test`) | One command to start all three services |
| Files | `config/`, `assets/`, `projects/` are shared on disk by all three | Simplest possible interop for a local-only app |

**☐ APPROVE Section 3** — tech stack (Go API · Python AI over gRPC · Next.js + MUI)

---

## 4. Repository layout

> The numbered layers (①②③…) in the trees below are explained in **Section 14 — Code
> Architecture, Modularity & Design Patterns**, which defines the dependency rules and the
> plug-and-play contract. Read §14 alongside this section; the folder names only make sense
> together with it.

```
rewind/
├── CLAUDE.md                  # rules for Claude Code
├── SPEC.md                    # this document
├── README.md
├── Makefile                   # make proto | make dev | make test | make doctor
├── .env.example               # YT_API_KEY, YT_CLIENT_SECRET path, etc. (never commit .env)
│
├── proto/                     # ── THE CONTRACT (source of truth) ──
│   ├── buf.yaml
│   ├── buf.gen.yaml           # generates Go + Python + TypeScript stubs
│   └── rewind/v1/
│       ├── common.proto       # Progress, Failure, VideoRef
│       ├── research.proto     ├ relevance.proto  ├ script.proto
│       ├── voice.proto        ├ visual.proto     ├ caption.proto
│       ├── render.proto       └ health.proto
│
├── api/                       # ── GO: state, gates, HTTP, orchestration ──
│   ├── go.mod
│   ├── cmd/                       # entry points ONLY — wiring, no logic
│   │   ├── rewind-api/main.go     # the server (port 8080)
│   │   └── rewind/main.go         # the CLI (cobra)
│   ├── internal/
│   │   ├── domain/                # ① CORE — pure types + rules, zero dependencies
│   │   │   ├── video.go           #   Video, Status, Gate, Job entities
│   │   │   ├── state.go           #   the state machine (legal transitions)
│   │   │   ├── errors.go          #   sentinel errors: ErrIllegalTransition…
│   │   │   └── ports.go           #   INTERFACES: VideoRepo, AIEngine, Uploader,
│   │   │                          #   Clock, IDGen, ReviewLog  ← the plug points
│   │   ├── service/               # ② USE CASES — depends on domain interfaces only
│   │   │   ├── video_service.go   #   add / list / run / retry
│   │   │   ├── gate_service.go    #   approve / reject / edit, writes review log
│   │   │   ├── pipeline/          #   ③ STRATEGY + REGISTRY
│   │   │   │   ├── step.go        #     Step interface: Name, From, To, Run
│   │   │   │   ├── registry.go    #     name → Step; ordered pipeline lookup
│   │   │   │   └── steps/         #     one file per step, self-registering
│   │   │   │       ├── research.go  relevance.go  script.go  voice.go
│   │   │   │       └── visuals.go   captions.go   render.go   publish.go
│   │   │   └── runner.go          #   executes a Step, streams progress, sets status
│   │   ├── adapter/               # ④ ADAPTERS — implement domain/ports.go
│   │   │   ├── sqlite/            #   VideoRepo, JobRepo, migrations
│   │   │   ├── aigrpc/            #   AIEngine over gRPC  (swap: aifake/)
│   │   │   ├── aifake/            #   AIEngine in-memory  ← tests need no Python
│   │   │   ├── youtube/           #   Uploader           (swap: uploadernoop/)
│   │   │   └── filestore/         #   projects/<id>/ path handling
│   │   ├── transport/             # ⑤ EDGE — translate wire ⇄ domain, nothing else
│   │   │   ├── connectrpc/        #   handlers consumed by web/
│   │   │   ├── middleware/        #   request id, logging, recover, validate
│   │   │   └── cli/               #   cobra command definitions
│   │   └── platform/              # ⑥ CROSS-CUTTING — the "utils" layer, but named
│   │       ├── config/            #   loads ../config/*.yaml into typed structs
│   │       ├── logging/           #   slog setup, trace-id helpers
│   │       ├── retry/             #   backoff + jitter decorator
│   │       ├── validate/          #   id/path guards
│   │       └── clock/             #   real + fake Clock (deterministic tests)
│   ├── gen/rewind/v1/             # generated Go stubs (committed)
│   └── testdata/                  # golden files, fixture DBs
│
├── ai/                        # ── PYTHON: all model + media work ──
│   ├── pyproject.toml
│   ├── rewind_ai/
│   │   ├── server.py              # builds the container, registers handlers, serves
│   │   ├── core/                  # ① CROSS-CUTTING (the "utils" layer, named properly)
│   │   │   ├── config.py          #   typed settings from ../config/*.yaml
│   │   │   ├── registry.py        #   the @register decorator used by every provider
│   │   │   ├── container.py       #   builds providers from config (composition root)
│   │   │   ├── errors.py          #   RewindError hierarchy → gRPC status codes
│   │   │   ├── logging.py         #   structlog + trace id from gRPC metadata
│   │   │   ├── paths.py           #   projects/<id>/ layout — ONE place that knows it
│   │   │   ├── io.py              #   atomic JSON read/write (write temp → rename)
│   │   │   └── progress.py        #   ProgressEmitter → yields proto events
│   │   ├── handlers/              # ② TRANSPORT — thin gRPC servicers, no logic
│   │   │   ├── research.py  relevance.py  script.py  voice.py
│   │   │   └── visual.py    caption.py    render.py  health.py
│   │   ├── llm/                   # ③ SWAPPABLE PROVIDER (template for all of them)
│   │   │   ├── base.py            #   class LLM(Protocol): complete_json(...)
│   │   │   ├── prompts/           #   jinja templates — prompts are DATA, not code
│   │   │   └── providers/
│   │   │       ├── ollama.py      #   @register("llm", "ollama")
│   │   │       └── openai_compat.py
│   │   ├── research/              # Module 2
│   │   │   ├── base.py            #   SourceFetcher protocol
│   │   │   ├── service.py         #   orchestrates fetch → extract → verify
│   │   │   ├── verifier.py        #   evidence checker (pure, heavily tested)
│   │   │   └── sources/           #   wikipedia.py · user_url.py · searxng.py
│   │   ├── relevance/             # Module 3
│   │   │   ├── base.py  service.py
│   │   │   └── sources/           #   google_trends.py · wiki_pageviews.py
│   │   │                          #   youtube_popular.py · reddit.py · manual.py
│   │   ├── script/                # Module 4
│   │   │   ├── writer.py
│   │   │   └── rules/             #   ④ one file per validator rule, self-registering
│   │   │       ├── base.py        #     class Rule(Protocol): check(script) -> []
│   │   │       ├── word_limit.py  beat_count.py  numbers_match_facts.py
│   │   │       └── loop_echo.py   max_refs.py    sfx_limit.py
│   │   ├── voice/                 # Module 5
│   │   │   ├── base.py            #   VoiceEngine protocol
│   │   │   ├── snapping.py  polish.py
│   │   │   └── providers/         #   chatterbox.py · kokoro.py · piper.py
│   │   ├── visuals/               # Module 6
│   │   │   ├── base.py  prompt_builder.py  storyboard.py
│   │   │   └── providers/         #   flux_diffusers.py · comfyui_api.py · sdxl.py
│   │   ├── captions/              # Module 7
│   │   │   ├── base.py  aligner.py
│   │   │   └── providers/         #   faster_whisper.py · whisperx.py
│   │   ├── audio/                 # Module 8  (music selection, ducking, SFX)
│   │   ├── render/                # Module 9
│   │   │   ├── base.py  compositor.py  dead_zone.py  loop_preview.py
│   │   │   ├── presets/           #   caption/motion/transition strategies
│   │   │   └── providers/         #   moviepy.py · ffmpeg_direct.py
│   └── tests/                     # pytest + offline fixtures (mirrors the tree above)
│   └── rewind/v1/                 # generated Python stubs (committed), a TOP-LEVEL
│                                  # package so protoc's absolute `from rewind.v1
│                                  # import ...` resolves with no sys.path hacks
│
├── web/                       # ── NEXT.JS: the review dashboard ──
│   ├── package.json
│   ├── app/
│   │   ├── layout.tsx             # MUI ThemeProvider + AppRouterCacheProvider
│   │   ├── page.tsx               # Home: video table, "needs my review" filter
│   │   └── v/[videoId]/
│   │       ├── facts/page.tsx        # Gate A
│   │       ├── references/page.tsx   # Gate B
│   │       ├── script/page.tsx       # Gate C
│   │       ├── voice/page.tsx        # Gate D
│   │       ├── storyboard/page.tsx   # Gate E
│   │       └── final/page.tsx        # Gate F
│   ├── features/                  # ① FEATURE-FIRST — a gate owns its own folder
│   │   ├── gates/
│   │   │   ├── registry.ts        #   gate letter → GateDefinition (strategy table)
│   │   │   ├── types.ts           #   GateDefinition: component, canApprove, label
│   │   │   ├── GateShell.tsx      #   shared chrome: header, progress dots, actions
│   │   │   ├── facts/             #   FactsGate.tsx + hooks + local types
│   │   │   ├── references/  script/  voice/  storyboard/  final/
│   │   └── videos/                #   list table, status chips, filters
│   ├── components/ui/             # ② PRIMITIVES — themed, dumb, reusable
│   │   ├── Surface.tsx  Stack.tsx  ActionBar.tsx  StatusChip.tsx
│   │   └── ProgressStream.tsx  EmptyState.tsx  ConfirmDialog.tsx
│   ├── lib/                       # ③ CROSS-CUTTING
│   │   ├── api/client.ts          #   one configured Connect client — the only one
│   │   ├── api/queries.ts         #   TanStack query keys + hooks per RPC
│   │   ├── format.ts  guards.ts   #   pure helpers (unit-tested)
│   │   └── gen/rewind/v1/         #   generated TS client (committed)
│   ├── hooks/                     # useJobProgress, useGateNavigation, useReducedMotion
│   └── theme/                     # tokens.ts, theme.ts, motion.ts  (Section 8.1)
│
├── config/                    # shared by all three services
│   ├── channel.yaml           # channel name, voice settings, art style, beat length
│   ├── style_bible.md         # narrator persona + humor rules (Section 6)
│   ├── reference_bank.yaml    # evergreen modern references (Section 5.3)
│   └── presets/               # caption/music/motion style presets (≥5)
├── assets/
│   ├── voice/reference.wav    # your 10–20s voice sample
│   ├── music/                 # royalty-free tracks + bpm.yaml
│   ├── sfx/                   # CC0 sound effects
│   └── fonts/
├── projects/
│   └── <video_id>/            # everything for one video
│       ├── facts.json
│       ├── references.json
│       ├── script.json
│       ├── audio/beat_XX.wav, narration.wav
│       ├── images/beat_XX_a.png, beat_XX_b.png, storyboard.png
│       ├── captions.json
│       ├── final.mp4, loop_preview.mp4
│       └── review_log.json    # who approved what, when, with which edits
└── rewind.db                  # SQLite — written ONLY by api/ (Go)
```

**Where does each language's test live?** With its own service: `api/**/*_test.go`,
`ai/tests/`, `web/**/*.test.ts`. `make test` runs all three.

### 4.1 `config/channel.yaml` (initial values)

```yaml
channel_name: "Rewind"            # ☐ decide final name
beat_seconds: 5.0
target_beats: [9, 12]             # 45–60s videos
aspect: "9:16"
resolution: [1080, 1920]
voice:
  engine: chatterbox              # or kokoro
  reference: assets/voice/reference.wav
  exaggeration: {setup: 0.45, punch: 0.8, fact: 0.5}
  cfg_weight: 0.4
  punch_pause_ms: 250
art_style: >
  painterly historical documentary illustration, warm candlelight palette,
  subtle film grain, cinematic composition, vertical frame
music:
  target_bpm: 96                  # one bar = 2.5s, two bars = one 5s beat
  duck_db: -14
limits:
  max_modern_refs_per_video: 3
  max_sfx_per_beat: 1
  max_words_per_beat: 14
llm_model: "qwen2.5:14b"
```

### 4.2 `config/services.yaml` (ports & paths — no hard-coding anywhere)

```yaml
api:
  http_addr: "127.0.0.1:8080"       # Next.js talks here
  db_path: "rewind.db"
ai:
  grpc_addr: "127.0.0.1:50051"      # Go talks here
  max_message_bytes: 4194304        # 4 MB — we pass paths, not media
  timeouts_seconds:                 # per-RPC deadline; Go cancels and sets status=error
    research: 300
    script: 180
    voice: 900
    visuals: 1800
    render: 1200
web:
  api_base_url: "http://127.0.0.1:8080"
paths:
  projects: "projects"
  assets: "assets"
```

**☐ APPROVE Section 4** — layout & config defaults

---

## 5. Modules

Each module lists: **purpose → input → output → how it works → acceptance criteria.**
All outputs are JSON files in `projects/<video_id>/` so you can inspect them directly.

---

### 5.1 Module 1 — Topic Queue

**Purpose:** Hold the list of episodes to make.

**Commands**
```bash
rewind add "sandals" --priority 2 --notes "compare to Birkenstocks, Crocs"
rewind queue                  # list topics and their status
rewind run <video_id>         # advance one video as far as it can go until the next gate
rewind run --all              # advance every video to its next gate
rewind retry <video_id>       # resume after an error
```

**DB table `videos`:** `id, topic, slug, status, priority, notes, created_at, updated_at,
rejected_to, reject_note, error, yt_video_id, published_at`

**Acceptance:** adding, listing, and state transitions work; illegal transitions (e.g. skipping a
gate) raise an error. Unit-tested.

---

### 5.2 Module 2 — Research (fact sheet)  → GATE A

**Purpose:** Build a timeline of true, sourced facts. **The LLM never invents facts;** it only
extracts them from source text.

**Input:** topic + optional user URLs (from `--notes` or dashboard).

**How it works**
1. Find the Wikipedia article(s): search API → pick best match (e.g. "Sandal", "Flip-flops").
2. Download plain text (Wikipedia action API `prop=extracts&explaintext=1`) + follow the article's
   "History" section. Also fetch any user-supplied URLs with `trafilatura`.
3. Chunk the text; ask the LLM to extract **timeline events** as JSON, each with the exact
   supporting sentence copied from the source.
4. **Verifier pass (code, not LLM):** check that each `evidence` string actually appears in the
   fetched source text (fuzzy match ≥ 90%). Drop any fact that fails → prevents hallucinated dates.
5. Sort chronologically, merge duplicates, flag conflicts between sources (`conflict: true`).

**Output `facts.json`**
```json
{
  "topic": "sandals",
  "facts": [
    {
      "id": "f1",
      "year_label": "~9,000 years ago",
      "sort_year": -7000,
      "place": "Oregon, USA",
      "claim": "Oldest known footwear: sandals woven from sagebrush bark found at Fort Rock Cave.",
      "evidence": "<exact sentence from source>",
      "source_url": "https://en.wikipedia.org/wiki/...",
      "confidence": "high",
      "conflict": false,
      "approved": null
    }
  ]
}
```

**Gate A (dashboard):** table of facts, each with a clickable source. Approve / edit / delete /
add. Need ≥ 8 approved facts spanning ≥ 4 eras to continue.

**Acceptance:** for 3 test topics (iron, mouse, sandals) every fact's `evidence` is found in its
source text; no fact without `source_url`.

**☐ APPROVE 5.2** — sources allowed (Wikipedia + your URLs only in v1? add SearXNG later?)

---

### 5.3 Module 3 — Relevance Engine (modern references)  → GATE B

**Purpose:** Find what's trending *now* and connect it to the episode so the jokes feel current
("Roman soldiers basically wore Birkenstocks with spikes", "the Stanley cup of ancient Egypt").

**Two sources of references**

**(a) Evergreen reference bank — `config/reference_bank.yaml`** (you curate; always safe to use)
```yaml
footwear:   [Birkenstock, Crocs, Nike Air Force 1, Havaianas, Uggs, "socks with sandals"]
drinkware:  [Stanley cup, Hydro Flask, Yeti, "emotional support water bottle"]
tech:       [AirPods, iPhone, "phone at 1% battery", Roomba, smart watch, "charging cable drama"]
home:       [Dyson, air fryer, "Amazon Prime next-day delivery", IKEA flat-pack]
clothing:   [Lululemon, Shein haul, "quiet luxury", "Canadian tuxedo"]
internet:   ["1-star review", "unboxing video", "limited drop", "sold out in 3 minutes",
             "influencer", "life hack", "subscription fee"]
```

**(b) Live trend scan — refreshed daily, cached in `trends_cache.json`**
| Source | What we take | Notes |
|---|---|---|
| Google Trends "Trending now" RSS (per country) | Trending search terms | Free, no key |
| Wikipedia top-pageviews API (yesterday) | Most-read articles (products, events, memes) | Free, official |
| YouTube Data API `videos.list?chart=mostPopular` | Trending video titles | Uses existing key |
| Reddit public JSON (`r/popular`, niche subs), weekly top | Hot products/memes | Low volume, respect API terms |
| Manual paste box in dashboard | Anything you saw on TikTok/IG | TikTok/IG not scraped (ToS) |

**How it works**
1. Categorize the topic (sandals → `footwear`, `summer`, `fashion`).
2. Pull matching evergreen refs + live trends; LLM filters live trends to ones a broad audience
   would recognize **and** that connect to the topic.
3. LLM proposes **3–6 comparisons**, each tied to a specific approved fact.
4. Each proposal is scored and labeled.

**Output `references.json`**
```json
{
  "proposals": [
    {
      "id": "r1",
      "reference": "Birkenstock",
      "kind": "evergreen",
      "fresh_until": null,
      "linked_fact": "f4",
      "comparison": "Roman caligae were basically Birkenstocks with metal spikes on the bottom.",
      "why_funny": "Premium comfort brand vs. brutal army footwear",
      "accuracy_note": "Comparison is about look/shape only; not a claim about Birkenstock history.",
      "approved": null
    },
    {
      "id": "r2",
      "reference": "<live trend term>",
      "kind": "hot",
      "fresh_until": "2026-10-06",
      "source": "google_trends_rss",
      "linked_fact": "f7",
      "comparison": "...",
      "why_funny": "...",
      "approved": null
    }
  ]
}
```

**Rules (enforced by validator)**
- Max **3** modern references per video (config).
- A reference compares **look, feeling, price, hype, or behavior** — never makes a false factual
  claim about the brand/person.
- Brands are **spoken or shown as text only** — never rendered as logos or product designs in
  AI images (trademark/IP safety). No implied sponsorship.
- `hot` references expire: if the video isn't published by `fresh_until`, Gate F warns you.
- No references to tragedies, politics, or real private individuals.

**Gate B (dashboard):** cards with each proposal; tick up to 3, edit wording, or write your own.

**Acceptance:** for "sandals" returns Birkenstock/Crocs/flip-flop-type references; for "water
bottle/cup" returns Stanley/Hydro Flask; live-trend scan completes in < 60s and caches daily.

**☐ APPROVE 5.3** — starting reference bank (edit the YAML), live sources list, max refs/video

---

### 5.4 Module 4 — Script Writer + Validator  → GATE C

**Purpose:** Turn approved facts + approved references into a rhythmic, funny beat script.

**Input:** `facts.json` (approved only), `references.json` (approved only), `style_bible.md`,
`analytics_lessons.md` (Module 11), channel config.

**Beat structure (the "Rewind" formula)**
| Beat | Role | Content |
|---|---|---|
| 1 | **Hook** (0–5s) | Oldest/most surprising version, mid-action + "Let's rewind X years." |
| 2…N-1 | **Era stops** | One era per beat: year stamp + fact (setup) + twist/joke or modern comparison (punch) |
| ~middle | **Rehook** | Open loop: "…and the next one almost set houses on fire." |
| N | **Today + loop** | Modern version → last line echoes the first line so the video loops |

**Output `script.json`**
```json
{
  "title_options": ["Roman Soldiers Wore Spiked Birkenstocks", "..."],
  "description": "…sources listed below…",
  "hashtags": ["#history", "#sandals", "#shorts"],
  "beats": [
    {
      "n": 1,
      "role": "hook",
      "year_stamp": "~7000 BC",
      "voice": "These are the oldest shoes ever found. Nine thousand years old. Let's rewind.",
      "on_screen_text": "9,000 YEARS OLD",
      "visual_prompts": ["woven bark sandals on cave floor, torchlight", "year counter spinning backward"],
      "sfx": "rewind",
      "motion": "slow_push",
      "emphasis_words": ["oldest", "Nine thousand"],
      "fact_ids": ["f1"],
      "ref_ids": [],
      "is_punch": false
    }
  ],
  "sources": ["https://...", "..."]
}
```

**Validator (code) — script is rejected and regenerated (max 3 tries) if:**
- any beat > 14 words, or total beats outside 9–12
- any beat claims a fact not in `fact_ids` (LLM self-check + years/numbers must match approved facts)
- a number or year appears that isn't in an approved fact
- more than 3 modern references, or a reference not in approved `ref_ids`
- last beat doesn't echo beat 1 (keyword overlap check)
- more than 1 SFX per beat; no rehook beat; no year stamp on era beats

**Gate C (dashboard):** beat table; facts highlighted blue, jokes highlighted orange, modern refs
highlighted green; hover a fact to see its source. Edit inline → re-validate → approve.
Also pick the final title.

**Acceptance:** produces valid scripts for iron, mouse, sandals on first or second try; validator
catches injected errors in unit tests (wrong year, 20-word beat, missing loop).

**☐ APPROVE 5.4** — beat formula, word limit, validator rules

---

### 5.5 Module 5 — Voice  → GATE D

**Purpose:** Narration in your own cloned voice, snapped to the 5-second beat grid.

**How it works**
1. Record `assets/voice/reference.wav`: 15–20s of **your own voice**, quiet room, natural tone.
   (Only clone voices you own or have written permission to use.)
2. For each beat: Chatterbox `generate(voice, audio_prompt_path, exaggeration, cfg_weight)`.
   Exaggeration from config by beat type (setup / fact / punch).
3. Insert `punch_pause_ms` of silence before punchlines.
4. **Beat snapping:** if a beat's audio is 4.5–5.5s → time-stretch (`pyrubberband`, max ±10%) to
   exactly fit; if shorter → pad silence at end; if longer than 5.5s → flag for rewrite (Gate C).
5. Polish chain (`pedalboard`): high-pass 80 Hz → compressor (3:1) → +2 dB presence at 4 kHz →
   subtle room reverb (5% wet) → limiter −1 dBTP. Loudness target −14 LUFS.
6. Concatenate → `narration.wav`; write `beat_timings.json` (start/end per beat).

**Gate D:** audio player per beat + full narration; "regenerate this beat" button (new seed or
adjusted exaggeration slider).

**Acceptance:** every beat lands within ±50 ms of its 5s slot; loudness −14 ±1 LUFS; regenerating
one beat doesn't touch others.

**☐ APPROVE 5.5** — Chatterbox vs Kokoro, polish chain, your reference recording

---

### 5.6 Module 6 — Visuals + Storyboard  → GATE E

**Purpose:** Two images per beat (switch every ~2.5s = one music bar), era-accurate, one consistent
art style.

**How it works**
1. Final prompt = `visual_prompt` + era context ("1st century BC Han dynasty China") +
   `art_style` from config + negative prompt (`text, logo, watermark, brand, modern objects,
   deformed hands`).
2. Generate 1080×1920 with FLUX.1-schnell (4 steps). Fixed seed per video for consistency;
   store seed in project so single images can be regenerated.
3. Motion is applied at render time (Ken Burns push/pan, zoom punch on emphasis words).
4. Build `storyboard.png`: grid, one row per beat — [year stamp | image A | image B | voice line].

**Rules:** no brand logos or real product designs; no real identifiable people; no gore.
Modern references appear as **on-screen text**, not generated brand imagery.

**Gate E:** storyboard grid; click any image → regenerate (optionally edit its prompt).

**Acceptance:** 2 images per beat, all same resolution/style; regenerating one image keeps
the rest; storyboard renders.

**☐ APPROVE 5.6** — art style text in `channel.yaml` (run 3 test images first)

---

### 5.7 Module 7 — Captions & Text Overlays

1. Run `faster-whisper` (model `small` or `medium`) on `narration.wav` with `word_timestamps=True`.
2. Align transcript words to script words (so spelling of names/brands matches the script, not the
   ASR guess).
3. Caption style: 2–4 words on screen at a time, centered lower-third safe zone, current word
   highlighted; `emphasis_words` scale up 115% + accent color.
4. **Year stamp:** big animated label top-center on each era beat (slide-in + tick sound).
5. **Punch text:** `on_screen_text` pops in on the punch word.
6. Keep all text inside platform safe zones (avoid bottom ~20% and right-edge UI buttons).

**Acceptance:** captions visible from frame 1; no text in unsafe zones; brand names spelled right.

---

### 5.8 Module 8 — Music & SFX

1. `assets/music/` holds royalty-free tracks (YouTube Audio Library / Pixabay) with `bpm.yaml`.
   Pick a track near 96 BPM (rotate tracks across videos).
2. `librosa.beat.beat_track` → beat times; align the 5s beat grid to the nearest downbeat.
3. Sidechain-duck music under narration (−14 dB). Drop music out for 0.5s on the biggest punch.
4. SFX library (CC0: Freesound, Pixabay): `rewind, whoosh, tick, pop, thud, sizzle,
   record_scratch, ding, crowd_gasp`. Place at word timestamps; max 1 signature SFX per beat;
   soft whoosh on every image cut.
5. Final mix loudness −14 LUFS.

**Acceptance:** cuts land within ±1 frame of music beats; voice always intelligible over music.

---

### 5.9 Module 9 — Render, Dead-Zone Check, Loop Preview  → GATE F

1. Compose with MoviePy: images + motion → text/captions → audio mix. Export H.264, 1080×1920,
   30 fps, AAC 192k.
2. **Style preset** chosen per video from `config/presets/` (caption font/color, transition style,
   motion intensity) — rotate so videos don't look identical (anti-"template" signal).
3. **Dead-zone checker:** scan the timeline; flag any 5s window with no cut, zoom, new text, or SFX.
   Render fails Gate F pre-check if any dead zone exists.
4. **Loop preview:** export `loop_preview.mp4` = last 3s + first 3s back-to-back.
5. Write `metadata.json`: title, description (with source list), hashtags, AI-disclosure = true.

**Gate F:** play `final.mp4` and `loop_preview.mp4`; checklist (facts right? jokes land? loop
smooth? hot references still fresh?). Approve or send back to any gate with a note.

**Acceptance:** renders a 45–60s video in < 5 min on target GPU; dead-zone checker catches an
injected 6s static section in tests.

---

### 5.10 Module 10 — Publish (private only)

1. OAuth once (`client_secret.json` from Google Cloud); token stored locally.
2. `videos.insert` with `privacyStatus: private`, title, description (sources included),
   tags, category "Education", made-for-kids = false, and the API's synthetic/altered-content
   disclosure field set to true *(verify current field name in YouTube Data API docs)*.
3. Save `yt_video_id`; status → `uploaded_private`.
4. **Human** reviews on YouTube and publishes. Instagram/TikTok: dashboard gives a
   "download for Reels/TikTok" button (no watermark) + caption text to copy; toggle AI label
   manually in each app.

**Acceptance:** test upload appears as private with correct metadata; never sets public.

---

### 5.11 Module 11 — Analytics Feedback Loop

1. 48h and 7 days after publish: YouTube Analytics API audience-retention report
   (`elapsedVideoTimeRatio` → `audienceWatchRatio`), plus views, likes, comments, shares.
2. Map retention drops to beat numbers using `beat_timings.json`.
3. Store per-beat stats: role, had_modern_ref, ref_kind, sfx, word_count → retention delta.
4. Weekly: LLM summarizes patterns into `config/analytics_lessons.md` (e.g. "Beats with a modern
   comparison hold +6% vs plain facts"; "hooks starting with a number do best"). **You approve**
   the lessons file before it's used in script prompts.

**Acceptance:** retention curve stored per video; weekly lessons draft generated.

---

## 6. Style Bible & Humor Rules (`config/style_bible.md`)

**Narrator persona:** A dry, slightly unimpressed time-traveler. Loves history, finds the past
ridiculous, speaks like a friend — not a teacher. Deadpan, never shouty.

**Humor toolkit (use 2–4 per video)**
| Device | Example pattern |
|---|---|
| Modern comparison | "Basically [trendy brand], but [brutal historical detail]." |
| Price/hype joke | "Limited drop. Sold out. Because it took a blacksmith three days." |
| 1-star review | "Customer review, 1882: 'Weighs fifteen pounds. No electricity. Two stars.'" |
| Deadpan fragment | "In July. Next to a fire." |
| Rule of three | "No plug. No cord. No mercy." |
| Name reframe | "'Sad' meant solid. Not a mood." |
| Understatement | "Minor design flaw: it leaked gas." |

**Hard rules**
- Facts are always true; jokes are obviously jokes. Never exaggerate a number or date.
- Max 3 modern references; each must connect to a real fact in the same beat.
- Internet slang: max 1 term per video, only if widely understood. Avoid anything that dates
  in weeks unless it's a `hot` reference you'll publish within its fresh window.
- No punching down: no jokes about groups of people, religions, disabilities, tragedies.
- No politics, no real private individuals, no fake quotes from real people.
- Every script ends by echoing its opening line (loop).

**☐ APPROVE Section 6** — persona & humor rules (edit freely; this sets the channel's voice)

---

## 7. Platform Compliance Checklist (auto-checked at Gate F)

- [ ] Every fact has a source; sources listed in the description
- [ ] Human edited/approved script (logged in `review_log.json`)
- [ ] Own cloned voice (not a stock preset)
- [ ] Style preset differs from the previous 2 videos
- [ ] No logos/brand imagery or real people in generated images
- [ ] AI disclosure flag set on YouTube; reminder to toggle AI label on Instagram/TikTok
- [ ] Uploaded as private; publishing cadence ≤ 2/day
- [ ] No sensitive topics (health/finance advice, tragedies, politics)
- [ ] Music is royalty-free and logged in `credits.json`; SFX are CC0

---

## 8. Review Dashboard (`web/`, Next.js 15 + MUI v7)

**Home** (`app/page.tsx`): MUI DataGrid of all videos — topic · status chip · current gate ·
updated. Filter "needs my review". Clicking a row routes to that video's current gate page.

### 8.1 Design language — Apple, expressed through the MUI theme

No Tailwind, no shadcn. Everything below lives in `web/theme/`.

**Tokens** (`theme/tokens.ts`)
```ts
export const tokens = {
  radius:  { sm: 8, md: 12, lg: 20, pill: 999 },
  // Apple's type scale is optical: large text gets tighter tracking, not just bigger size.
  type: {
    display: { size: 34, weight: 700, tracking: '-0.02em', leading: 1.15 },
    title:   { size: 22, weight: 600, tracking: '-0.01em', leading: 1.25 },
    body:    { size: 15, weight: 400, tracking: '0',       leading: 1.5  },
    caption: { size: 13, weight: 400, tracking: '0.01em',  leading: 1.4  },
  },
  // Depth comes from layered translucency, not heavy drop shadows.
  surface: {
    base:  'rgb(250 250 252)',
    card:  'rgba(255,255,255,0.72)',
    blur:  'saturate(180%) blur(20px)',
    hairline: 'rgba(0,0,0,0.08)',
  },
  accent: { fact: '#0A84FF', joke: '#FF9F0A', ref: '#30D158' }, // Gate C highlights
} as const;
```

**Motion** (`theme/motion.ts`) — springs, never linear easing:
```ts
export const spring = {
  press:  { type: 'spring', stiffness: 400, damping: 30 },  // buttons
  sheet:  { type: 'spring', stiffness: 280, damping: 32 },  // gate transitions
  settle: { type: 'spring', stiffness: 180, damping: 26 },  // list reflow after approve
};
```

**Principles applied here**
- **Restraint:** one accent colour per screen. The gate's primary action is the only filled button.
- **Feedback:** every approve/reject animates optimistically, then reconciles with the server.
  Nothing ever just… happens silently.
- **Spatial consistency:** gates A→F always advance right; "send back to gate X" animates left.
  You always know which direction you moved.
- **Materials:** sticky gate header uses `backdrop-filter: ${tokens.surface.blur}` over content,
  with a 1px hairline — not a shadow.
- **Reduced motion:** every `framer-motion` transition is wrapped so `prefers-reduced-motion`
  collapses it to an opacity fade. Non-negotiable.

### 8.2 Pages

One route per gate, all sharing a `<GateShell>` (sticky translucent header with topic, gate letter,
progress dots A–F, and the primary action pinned bottom-right).

| Gate | Layout | MUI pieces | Buttons |
|---|---|---|---|
| A Facts | Table: year · place · claim · source link · confidence | `DataGrid` with inline edit | Approve all / Edit / Delete / Add fact / Add source URL |
| B References | Cards: reference · comparison · why funny · hot/evergreen · expiry | `Card` grid, `Chip` for kind | Select (max 3) / Edit / Write my own / Paste a trend |
| C Script | Beat table, highlights facts blue / jokes orange / refs green + title picker | `Table` + `Tooltip` on facts showing source | Edit inline / Re-validate / Regenerate beat / Approve |
| D Voice | Per-beat audio players + full track | `<audio>` + `Slider` for exaggeration | Regenerate beat (seed / exaggeration) / Approve |
| E Storyboard | Image grid, one row per beat | `ImageList` + `Dialog` for prompt edit | Regenerate image / Edit prompt / Approve |
| F Final | Video player + loop preview + compliance checklist | `Checkbox` list, `Alert` for stale hot refs | Approve / Send back to gate X with note |

### 8.3 How the UI knows a job is running

1. Browser POSTs `RunStep` to Go. Go returns a `job_id` immediately (never blocks the request).
2. Go opens the server-streaming gRPC call to Python and writes each `Progress` event to SQLite.
3. Browser polls `GetJob(job_id)` every 1.5 s via TanStack Query → linear progress bar with the
   stage label ("generating beat 7/12"). Server-Sent Events can replace polling in v2.
4. On the terminal event Go performs the state transition, the poll returns `done`, and the UI
   routes to the next gate with the forward spring transition.

### 8.4 Review log

Every action is written to `projects/<video_id>/review_log.json` **by Go** (timestamp, gate,
action, before/after diff, and — for edits — the exact text you changed). This log is your proof
of human creative involvement. Go appends; nothing else ever writes to it.

**☐ APPROVE Section 8** — dashboard layout, MUI-only decision, Apple theme tokens

---

## 9. Build Milestones (one Claude Code session each)

> Claude Code: build ONLY the current milestone, run its tests, show the demo command, then STOP
> and wait for approval.

Each milestone from M2 onward touches **all three services** — proto → Python implementation →
Go orchestration → Next.js gate page. That vertical slice is deliberate: you finish a milestone
with something you can actually click.

| # | Milestone | Deliverable | Acceptance / what you review |
|---|---|---|---|
| **M0** | Plumbing | Monorepo, `Makefile`, `buf` + `common.proto` + `health.proto`, codegen for all 3 languages, Go server with one Connect endpoint, Python gRPC server with `HealthService`, Next.js app with MUI theme + one page. **Plus the §14 skeleton: every layer folder created with its interface file and one real implementation + one fake**, `core/registry.py`, `core/container.py`, `domain/ports.go`, lint rules wired into CI | `make dev` starts all three. The home page shows a green "AI service healthy" chip fetched Next.js → Go → gRPC → Python. `go test ./...` passes with the AI service **stopped** (fake adapter). **This proves the spine and the seams before any AI exists.** |
| **M1** | State & gates (Go) | SQLite schema + goose migrations, state machine, gate transitions, review log, cobra CLI (`add/queue/run/retry`), Connect API + generated TS client, home DataGrid | `rewind add "iron"` → appears in CLI *and* in the browser table; illegal-transition test passes; `rejected_to` works |
| **M2** | Research + Gate A | `research.proto`, Python: Wikipedia fetch + Ollama extraction + evidence verifier; Go: orchestration + job progress; web: Gate A page | Run "iron": ≥ 8 facts, every evidence string found in source; approve in the browser; `review_log.json` records it |
| **M3** | Relevance + Gate B | reference bank, live trend scan + daily cache, proposal generator, Gate B cards | "sandals" proposes Birkenstock/Crocs-type refs; max-3 rule enforced in Go |
| **M4** | Script + Gate C | beat generator, validator, style bible, Gate C beat table with highlights | Valid script for iron/mouse/sandals; validator unit tests catch injected errors |
| **M5** | Voice + Gate D | Chatterbox per beat, snapping, polish, per-beat players + regen | Beats within ±50 ms of grid; −14 LUFS; single-beat regen |
| **M6** | Visuals + Gate E | FLUX generation, prompt builder, storyboard, image grid + regen | 2 images/beat, consistent style, single-image regen |
| **M7** | Captions + Music + SFX | whisper alignment, caption renderer, beat detection, ducking, SFX placement | Cuts on beat ±1 frame; captions from frame 1 |
| **M8** | Render + Gate F | compositor, presets, dead-zone checker, loop preview, compliance checklist | First full video of "iron" rendered and approved by you |
| **M9** | Publish (Go) | OAuth, private upload with metadata + disclosure, IG/TikTok export button | Private test upload visible in YouTube Studio |
| **M10** | Analytics | retention pull (Go), beat mapping, weekly lessons draft (Python LLM) | Retention stored for a published video |
| **M11** | Hardening | end-to-end run of 3 topics, error handling, README, `rewind doctor` (Go CLI → gRPC health → GPU/models/keys) | Queue 3 topics → all reach Gate F with only your approvals in between |

> **M0 exists because you're new to this.** Getting three languages to talk is the part that
> frustrates people, and it's much easier to debug when the only payload is the word "ok" than
> when a FLUX model is also involved. Do it first, with nothing else in the way.

**Suggested first 3 episodes for testing:** iron (already researched), computer mouse, sandals.

---

## 10. Testing Strategy

**Go (`api/`)** — `go test ./...`
- State machine: every legal transition succeeds, every illegal one returns an error. Table-driven.
- Gate logic: can't approve Gate C before Gate B; `rejected_to` rewinds correctly.
- Orchestrator: a failed RPC sets `status=error` with the message; retry resumes from the same state.
- `aiclient`: tested against an **in-process fake gRPC server**, so Go tests never need Python.

**Python (`ai/`)** — `pytest`
- Evidence verifier, validator rules, beat snapping math, dead-zone checker, reference rules.
- **Fixture topics** with saved Wikipedia text so tests run offline, GPU-free and deterministically.
- **Golden files:** a known-good `script.json` for "iron" to catch validator regressions.
- gRPC handlers tested via `grpc_testing` / a local server on an ephemeral port.

**TypeScript (`web/`)** — `vitest` + one Playwright smoke test
- Gate components render from fixture JSON; approve button disabled until requirements met.

**Contract** — `buf breaking --against '.git#branch=main'` in CI. If a proto change would break a
deployed client, CI fails. This is the safety net that makes three languages tolerable.

**Cross-service smoke** — `make smoke`: starts all three, adds a topic, drives it to Gate A with a
stubbed LLM, asserts the browser API returns the right status.

---

## 11. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| LLM invents dates/facts | Evidence-string verifier; numbers in script must match approved facts; Gate A + C |
| Channel looks templated | Rotating presets, human edits, varied hooks, own voice, review log |
| Jokes feel cringe | Style bible, max 3 refs, Gate B/C human pick, analytics lessons |
| Trend references go stale | `fresh_until` expiry warnings; prefer evergreen bank for long-lived videos |
| Brand/IP issues | Brands as text only; no logos/designs in images; comparisons not claims |
| GPU too small | Kokoro on CPU; 7b LLM; FLUX on Kaggle/Colab; lower image resolution + upscale |
| API quota limits | Cache trends daily; YouTube search used sparingly (100 units/call) |
| Policy changes | Re-check YouTube/Meta policy pages monthly; compliance checklist is config-driven |
| **Three languages overwhelm a first-time builder** | M0 wires the spine with a trivial payload before any AI exists; `make dev` hides the orchestration; Appendix A is the crash course; Go is confined to state/HTTP and never touches ML |
| **Proto drift between Go and Python** | Generated code is committed and CI fails if regeneration changes it; `buf breaking` blocks incompatible edits |
| **Go↔Python process management pain on Windows** | Services run independently, each restartable alone; Go treats "AI service down" as a normal retryable error with a clear dashboard banner, not a crash |
| **Long RPC looks like a hang** | Every slow RPC is server-streaming with `Progress` events; per-RPC deadlines in `config/services.yaml`; timeout ⇒ `status=error`, never a silent stall |
| **MUI theme drifts from the Apple feel** | Tokens live in one file (`web/theme/tokens.ts`); components consume tokens only — no ad-hoc colours, radii or durations in page code |

---

## 12. Decisions for You (fill in before M1)

| Decision | Options | Your choice |
|---|---|---|
| **Backend language** | Go / Python | ☑ **Go** (api/), Python for AI only |
| **Inter-service transport** | gRPC / REST / message queue | ☑ **gRPC** (Go → Python), Connect/JSON (browser → Go) |
| **Frontend** | Next.js / Streamlit | ☑ **Next.js 15 + TypeScript** |
| **UI kit** | MUI / shadcn+Tailwind | ☑ **MUI v7 only** — shadcn requires Tailwind, which is excluded |
| **Design language** | Apple-style via custom MUI theme | ☑ yes (§8.1) |
| **Repo** | `git@github.com:WildFire49/faceless-auto-video-gen.git` | ☑ |
| Channel name | Rewind / Before It Was Easy / your idea | ☐ |
| Voice | Chatterbox (own clone) / Kokoro preset | ☐ |
| Art style | Painterly documentary / vintage print / 3D diorama | ☐ |
| LLM size | qwen2.5:14b / 7b (smaller GPU) | ☑ **qwen2.5:7b-instruct** — "iron" research in 564 s on the M4 |
| Video length | 45s (9 beats) / 60s (12 beats) | ☐ |
| Research sources v1 | Wikipedia + your URLs / + SearXNG web search | ☐ |
| First 3 topics | iron, mouse, sandals / your picks | ☐ |
| Your GPU | model + VRAM | ☑ **Apple M4, 16 GB unified memory, Metal (`mps`)** (measured by the GPU probe) — `compute.accelerator: apple_mps`. Previously an NVIDIA RTX 4060 Laptop (8188 MB VRAM); switching back is `nvidia_cuda`. At M6, check FLUX fits beside the LLM in 16 GB of shared memory |

---

## 13. Production-Grade Engineering Requirements

This is a local-only app, but it is built to production standards so the habits are right and so it
can be deployed later without a rewrite.

### 13.1 Repository & workflow
- **Repo:** `git@github.com:WildFire49/faceless-auto-video-gen.git`
- **Branches:** `main` is always green and deployable. Work on `feat/m<n>-<slug>`; merge via PR.
- **Commits:** Conventional Commits (`feat(api): add gate B transition`). One milestone = one PR.
- **Tags:** `v0.<milestone>.0` at the end of each accepted milestone, so you can always go back.
- **No secrets in git, ever.** `.env`, `client_secret.json`, `token.json`, the reference voice
  recording, `rewind.db`, `projects/` and `assets/music|sfx` are all gitignored.

### 13.2 CI (GitHub Actions, `.github/workflows/`)

| Job | Runs |
|---|---|
| `proto` | `buf lint`, `buf format --diff --exit-code`, `buf breaking`, then `buf generate` and fail if generated code differs from what is committed |
| `go` | `go vet`, `staticcheck`, `golangci-lint` (incl. `gocyclo`, `depguard` enforcing the §14.1 layer rule), `go test -race -cover ./...` |
| `python` | `ruff check` (incl. `C901` complexity), `ruff format --check`, `mypy --strict`, `import-linter` enforcing the §14.1 layer rule, `pytest` (offline fixtures only — no GPU on CI) |
| `web` | `tsc --noEmit`, `eslint`, `vitest run`, `next build` |
| `smoke` | `make smoke` on Linux |

All five must pass before merge. Branch protection on `main`.

### 13.3 Reliability (Go side)
- **Graceful shutdown:** `signal.NotifyContext` → stop accepting HTTP, drain in-flight jobs, close
  the gRPC connection and the DB. A `SIGINT` mid-render must never leave a row stuck in `rendering`.
- **Crash recovery on boot:** any row in an in-progress state (`researching`, `voicing`,
  `rendering`…) at startup was interrupted → set to `error` with
  "interrupted; run `rewind retry <id>`".
- **Context deadlines:** every gRPC call carries the timeout from `config/services.yaml`. On
  deadline, Go cancels the stream and records the error. No unbounded hangs.
- **Retries:** transient failures (connection refused, Ollama busy) retry 3× with exponential
  backoff + jitter. Deterministic failures (validation) never retry.
- **Idempotency:** every step checks for its own completed output first and returns it. Re-running
  `rewind run iron` costs nothing if nothing changed.
- **Single writer:** SQLite in WAL mode, one `*sql.DB` with `SetMaxOpenConns(1)` for writes.
  All state changes go through `internal/state` — no raw status updates anywhere else.
- **Transactions:** a state change and its `review_log` entry commit together or not at all.

### 13.4 Observability
- **Structured logs** (`log/slog`, JSON) with a `video_id` and `job_id` on every line.
- **Request/trace id** generated in Go, passed to Python in gRPC metadata, logged on both sides.
  One grep gives you the full story of any job across both services.
- **gRPC interceptors** (Go client + Python server) log method, duration and status code uniformly.
- **`rewind doctor`** checks: Go build info, Python service reachable, Ollama up and model pulled,
  GPU and VRAM, ffmpeg on PATH, YouTube credentials valid, disk space, assets present.

### 13.5 Security & safety
- Servers bind `127.0.0.1` only — never `0.0.0.0`. This app is not internet-facing.
- gRPC uses insecure credentials **only because both ends are on localhost**; the code says so in
  a comment, and TLS is a one-line change if that ever stops being true.
- Every request is validated at the Go boundary (`protovalidate`) *before* reaching Python.
- Path-traversal guard: `video_id` must match `^[a-z0-9-]{1,64}$` before it is used in a file path.
- Dependabot on; `govulncheck` + `pip-audit` + `npm audit` in CI weekly.

### 13.6 Developer experience
- `task setup` — installs buf and the protoc plugins, Go modules, the Python 3.11 venv, npm packages.
- `task dev` — runs all three services together; `task dev:nopython` runs the dashboard and API
  against the fake AI adapter for UI work.
- `task proto` — regenerates Go, Python and TypeScript stubs in one shot.
- **Task runner is [go-task](https://taskfile.dev), not `make`.** GNU make is not present on
  Windows, which is the target machine, and installing it is a detour. go-task is a single Go
  binary installed with the toolchain already required, and behaves identically on all three
  platforms. `Taskfile.yml` replaces the Makefile named earlier in this section.
- `README.md` gets a real "get it running in 10 minutes on Windows" section, since that is the
  target machine.
- `.editorconfig`, plus pre-commit hooks running `buf format`, `gofmt`, `ruff`, `prettier`.

**☐ APPROVE Section 13** — production standards

---

---

## 14. Code Architecture, Modularity & Design Patterns

> Section 4 says *where files go*. This section says *how the code inside them is allowed to
> depend on each other*, and which patterns to reach for. Claude Code must follow this in every
> milestone. When a new file doesn't obviously belong to a layer below, that's a design smell —
> stop and ask.

### 14.1 The one dependency rule

Every service is layered, and **dependencies only ever point inward**:

```
  transport / handlers / pages      ← knows about the wire & the user
        │
        ▼
  service / use cases               ← knows the workflow
        │
        ▼
  domain / core                     ← knows the rules. Depends on NOTHING.
        ▲
        │ implements interfaces defined in domain
  adapters (sqlite, gRPC, youtube, flux, chatterbox…)
```

Concretely, three rules that are easy to check in review:

1. **`domain/` (Go) and `*/base.py` (Python) import nothing from the project.** Pure types,
   protocols and rules. If it needs a database or a model, it doesn't belong there.
2. **Business logic never imports a driver.** `service/` talks to a `VideoRepo` interface, not to
   SQLite. `research/service.py` talks to an `LLM` protocol, not to Ollama.
3. **Everything is wired in exactly one place** — `cmd/rewind-api/main.go` in Go,
   `core/container.py` in Python, `lib/api/client.ts` in the web app. These are the only files
   allowed to name a concrete implementation. Nothing anywhere else constructs its own dependency.

**Why this matters to you specifically:** it is what makes `go test` run without Python, and
`pytest` run without a GPU or the internet. Tests inject a fake; the code can't tell the difference.

### 14.2 The plug-and-play contract

This is the rule that delivers what you asked for. For **every** swappable piece:

> **Adding or replacing a provider = create one new file + add one registry line + change one
> config value. No existing file may be edited.**

If a swap requires touching a caller, the abstraction is wrong — fix the abstraction, not the
caller. In review, this is a hard gate.

**What is swappable, and by which config key:**

| Piece | Interface | Providers shipped | Config key |
|---|---|---|---|
| LLM | `llm/base.py::LLM` | ollama, openai_compat | `llm.provider` |
| Research source | `research/base.py::SourceFetcher` | wikipedia, user_url, searxng | `research.sources[]` |
| Trend source | `relevance/base.py::TrendSource` | google_trends, wiki_pageviews, youtube_popular, reddit, manual | `relevance.sources[]` |
| Voice engine | `voice/base.py::VoiceEngine` | chatterbox, kokoro, piper | `voice.engine` |
| Image backend | `visuals/base.py::ImageBackend` | flux_diffusers, comfyui_api, sdxl | `visuals.backend` |
| Caption/ASR | `captions/base.py::Aligner` | faster_whisper, whisperx | `captions.engine` |
| Renderer | `render/base.py::Renderer` | moviepy, ffmpeg_direct | `render.backend` |
| Style preset | `render/presets/` | ≥5 presets | `render.preset` (rotated per video) |
| Validator rule | `script/rules/base.py::Rule` | one file per rule | `script.rules[]` |
| Storage | `domain/ports.go::VideoRepo` | sqlite, (postgres later) | `api.db_driver` |
| AI transport | `domain/ports.go::AIEngine` | aigrpc, aifake | injected in `main.go` |
| Uploader | `domain/ports.go::Uploader` | youtube, noop | `publish.target` |

**A worked example — adding Piper as a third voice engine:**

1. Write `ai/rewind_ai/voice/providers/piper.py`:
   ```python
   from rewind_ai.core.registry import register
   from rewind_ai.voice.base import VoiceEngine, BeatAudio

   @register("voice", "piper")                 # ← the one registry line
   class PiperEngine(VoiceEngine):
       def __init__(self, cfg: VoiceConfig) -> None: ...
       def synthesize_beat(self, text: str, emotion: float, seed: int) -> BeatAudio: ...
   ```
2. Set `voice.engine: piper` in `config/channel.yaml`.
3. Done. `snapping.py`, `polish.py`, `handlers/voice.py`, the Go orchestrator and the Gate D page
   are untouched — none of them ever knew which engine was running.

### 14.3 Patterns used, and exactly where

Patterns are used where they pay for themselves — not decoratively. Each one below is load-bearing.

| Pattern | Where | What it buys |
|---|---|---|
| **Strategy** | every row in the §14.2 table | swap an implementation without touching callers |
| **Registry + Factory** | `core/registry.py`, `service/pipeline/registry.go` | providers self-register by name; the factory resolves config → instance. No `if provider == "x"` chains anywhere |
| **Ports & Adapters** | `domain/ports.go` ⇄ `adapter/*` | Go's core has zero knowledge of SQLite, gRPC or YouTube |
| **Repository** | `VideoRepo`, `JobRepo` | all SQL in one package; the rest of the app sees methods, never a query |
| **Dependency Injection (constructor)** | everywhere; wired in `main.go` / `container.py` | no globals, no singletons, no import-time side effects. Tests pass fakes in |
| **Template Method** | `render/base.py`, `pipeline/steps/*.go` | every step is `prepare → run → persist → emit`; a new step fills in the blanks and inherits idempotency, progress and error handling for free |
| **Chain of Responsibility** | `script/rules/` | each validator rule is an independent file returning violations; add or remove one from config with no edits elsewhere |
| **Builder** | `visuals/prompt_builder.py`, script prompt assembly | image prompt = subject + era + art style + negatives, composed step by step and unit-testable without a GPU |
| **Decorator / Middleware** | `platform/retry`, gRPC interceptors, `transport/middleware` | retry, logging, trace-id and validation added without touching business logic |
| **Observer / event stream** | `core/progress.py` → gRPC stream → SQLite → UI | one progress mechanism for every long job |
| **State pattern (table-driven)** | `domain/state.go` | legal transitions are data, not scattered `if` statements |
| **Null Object / Fake** | `adapter/aifake`, `uploadernoop`, `clock.Fake` | complete offline test runs and a safe dry-run mode |
| **Facade** | `service/*_service.go` | the transport layer calls one method per use case, never orchestrates internals |

**Explicitly avoided:** inheritance hierarchies deeper than one level, singletons, service locators,
global mutable state, and "manager"/"helper"/"misc" packages. A `utils` bucket that anything may
import becomes a dependency cycle — hence `platform/` (Go) and `core/` (Python), where every file
has one clear job and a name that says it.

### 14.4 Readability rules (enforced in review)

- **Naming says the job.** `voice/providers/chatterbox.py`, not `voice/impl2.py`. No `utils.py`,
  `helpers.py`, `common.py`, `manager.go`, `misc/`.
- **File size:** aim ≤ 300 lines; > 500 needs a reason. **Function size:** ≤ 50 lines.
- **Cyclomatic complexity ≤ 10** (`golangci-lint` gocyclo, `ruff C901`). CI enforces this.
- **One exported concept per file.** A reader should guess a file's contents from its path.
- **Interfaces are small** — 1–3 methods. A 10-method interface is a layering mistake.
- **Interfaces are declared where they are *used*, not where they are implemented** (Go idiom).
- **No logic in transport.** A gRPC servicer or Connect handler may only: validate, map to a
  domain call, map the result back, emit progress. If there's an `if` about history or beats in a
  handler, it's in the wrong file.
- **Prompts are data.** LLM prompts live in `llm/prompts/*.jinja`, never in Python string literals,
  so you can tune them without touching code.
- **Config over constants.** Any number a human might want to change lives in `config/`.
- **Comments explain *why*.** The code already says what.

### 14.5 How Claude Code must apply this

At the start of each milestone, state which layer each new file belongs to and which interface it
implements. Before adding a second implementation of anything, extract the interface first.
If a milestone seems to require editing a caller in order to add a provider, stop and propose a
spec change rather than working around it.

**☐ APPROVE Section 14** — layering, plug-and-play contract, pattern choices

---

## Appendix A — Crash course: Go and gRPC for a Python developer

*You know Python. This appendix is the minimum you need in order to read the Go and proto code in
this project. It is not a full Go tutorial — it is the delta from what you already know.*

### A.1 The five differences that actually matter

**1. Types are declared, and the compiler is strict.**

```python
def approve(video_id, gate):        # Python: types optional, errors at runtime
    ...
```
```go
func Approve(videoID string, gate Gate) error {   // Go: types required, errors at COMPILE time
    ...
}
```

If you pass an `int` where a `string` goes, the program refuses to build. For a state machine with
seventeen statuses, this is exactly what you want — a whole class of our bugs disappears before
anything runs.

**2. There are no exceptions. Errors are return values.**

This is the single biggest shift from Python.

```python
try:
    facts = build_fact_sheet(topic)
except ResearchError as e:
    log.error(e); raise
```
```go
facts, err := BuildFactSheet(topic)
if err != nil {
    return fmt.Errorf("building fact sheet for %q: %w", topic, err)
}
// from here on, facts is guaranteed valid
```

`if err != nil` appears everywhere. It looks repetitive — that is the point. Every failure is
visible at the call site; nothing propagates invisibly up ten frames. `%w` wraps the error so a
caller can still inspect the original with `errors.Is` / `errors.As`.

**3. `struct` + `interface` instead of classes and inheritance.**

```python
class Video:
    def __init__(self, id, topic): self.id, self.topic = id, topic
    def is_ready(self): return self.status == "facts_ready"
```
```go
type Video struct {
    ID     string
    Topic  string
    Status Status
}
func (v *Video) IsReady() bool { return v.Status == StatusFactsReady }
```

A method is just a function with a *receiver* (`v *Video`) written before the name. There is no
inheritance. An `interface` is satisfied implicitly — if your type has the right methods it
qualifies; you never declare "implements". That is how `aiclient` gets swapped for a fake in tests.

**4. Capitalisation is the access modifier.**

`BuildFactSheet` is exported (public, importable from another package). `buildFactSheet` is private
to its package. There is no `_private` convention and no `public` keyword — the first letter *is*
the rule.

**5. Concurrency is built into the language.**

```go
go processVideo(id)          // run in the background — that is the entire syntax
ch := make(chan Progress)    // a typed queue for passing values between goroutines
```

A goroutine costs about 2 KB, so having thousands is normal. `context.Context` is the standard way
to carry a cancellation signal and a deadline through a call chain — you will see `ctx` as the
first argument of nearly every function in `api/`. When you press Ctrl-C, one cancelled context
unwinds every in-flight job cleanly.

### A.2 A real file from this project, annotated

```go
package state                                   // like a Python module/package

import (
    "context"                                   // cancellation + deadlines
    "fmt"
)

type Status string                              // a named string type, not just an alias

const (                                         // like a Python Enum
    StatusQueued      Status = "queued"
    StatusResearching Status = "researching"
    StatusFactsReady  Status = "facts_ready"
)

// allowed maps each status to the statuses it may move to.
// map[K]V is Python's dict[K, V]; []Status is a list.
var allowed = map[Status][]Status{
    StatusQueued:      {StatusResearching},
    StatusResearching: {StatusFactsReady, StatusError},
}

// Transition is exported. It takes a context and returns only an error.
func Transition(ctx context.Context, v *Video, to Status) error {
    for _, ok := range allowed[v.Status] {      // `for ... range` is Python's `for ... in`
        if ok == to {                           // `_` discards the index we do not need
            v.Status = to
            return nil                          // nil == None, and means "no error"
        }
    }
    return fmt.Errorf("illegal transition %s -> %s", v.Status, to)
}
```

That is most of Go's syntax in thirty lines. There genuinely is not much more.

### A.3 What gRPC is, in terms you already know

**The problem it solves.** You have a Go program that needs to call a Python function in a
different process. Your options:

| Approach | What you write | What goes wrong |
|---|---|---|
| Shell out (`subprocess`) | glue scripts, parse stdout | no types, no streaming, fragile |
| REST + JSON | URL routes plus hand-written types on both sides | the two sides drift; you find out in production |
| **gRPC** | one `.proto` file | the generator writes both sides; they cannot drift |

**The mental model.** A `.proto` file is a **type-checked `.pyi` stub that both languages compile
against.** You write the signature once:

```proto
service ResearchService {
  rpc BuildFactSheet(BuildFactSheetRequest) returns (stream BuildFactSheetEvent);
}
```

Then `buf generate` produces:
- **Python:** an abstract base class `ResearchServiceServicer` with a `BuildFactSheet` method for
  you to fill in. Get the signature wrong and it will not run.
- **Go:** a client where `client.BuildFactSheet(ctx, req)` is an ordinary typed method call. Pass
  the wrong field and it will not compile.

**What you write in Python** — this is the whole of it:

```python
class ResearchService(research_pb2_grpc.ResearchServiceServicer):
    def BuildFactSheet(self, request, context):
        # `request` is a typed object, NOT a dict — request.topic autocompletes
        yield Event(progress=Progress(stage="fetching wikipedia", percent=0.1))
        facts = extract_facts(request.topic)
        yield Event(result=FactSheet(topic=request.topic, facts=facts))
```

`yield` is how a **server-streaming** RPC works — each yield is one message delivered to Go
immediately. That is what drives the live progress bar in the dashboard.

**The four RPC shapes** (we use the first two):

| Shape | Proto | Feels like |
|---|---|---|
| Unary | `rpc X(A) returns (B)` | a normal function call |
| **Server streaming** | `rpc X(A) returns (stream B)` | a Python **generator** |
| Client streaming | `rpc X(stream A) returns (B)` | uploading chunks |
| Bidirectional | `rpc X(stream A) returns (stream B)` | a chat session |

**Why it beats REST here:** binary Protobuf instead of JSON (smaller, faster to parse), HTTP/2
multiplexing (many concurrent calls over one connection), first-class streaming, real deadlines and
cancellation propagated across the process boundary, and — the big one — **the contract is a file
in the repo that CI checks**, not a README someone forgot to update.

**Field numbers matter.** In `string topic = 2;` the `2` is the wire identifier. Names can change
freely; **numbers must never be reused or changed** once shipped, or old and new binaries will
misread each other's data. `buf breaking` in CI enforces this for you.

### A.4 The mental model for this whole project

> **Next.js** is a form. **Go** is the office that keeps the files and decides what happens next.
> **Python** is the specialist you phone up to do one piece of skilled work.
> **The proto file** is the contract the office and the specialist both signed.

When you are lost, ask: *is this about **what state the video is in**?* → Go. *Is this about
**making a thing with a model**?* → Python. *Is this about **what the human sees**?* → Next.js.
Almost every question resolves cleanly.

### A.5 Reading list, in order

1. **A Tour of Go** — `go.dev/tour` (2–3 hours, in-browser, nothing to install). Do "Methods and
   interfaces" and "Concurrency"; skim the rest.
2. **Effective Go** — `go.dev/doc/effective_go`. Skim once, return to it later.
3. **gRPC Go quickstart** — `grpc.io/docs/languages/go/quickstart` (30 min).
4. **Buf tour** — `buf.build/docs/tutorials/getting-started-with-buf-cli` (30 min).

Do #1 before M1 and #3–4 before M0 and you will be fine. Nothing else is needed up front.
